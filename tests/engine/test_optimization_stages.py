"""Stable timeout and incomplete-input checks; do not race the real clock."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from backend.engine import EngineInputError, solve
from backend.engine import optimization as opt


def fixture():
    path = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터/01_snapshot.json"
    return json.loads(path.read_text(encoding="utf-8"))


class OptimizationStagesTests(unittest.TestCase):
    def test_unproved_upper_objective_stops_lower_stages(self):
        original = opt._run_stage
        def feasible(*args):
            solver, _ = original(*args)
            return solver, cp_model.FEASIBLE
        with patch.object(opt, "_run_stage", side_effect=feasible) as runner:
            result = solve(fixture(), "B3")
        self.assertEqual(runner.call_count, 1)
        self.assertEqual([s["status"] for s in result["objective_stages"]], ["FEASIBLE", "NOT_RUN", "NOT_RUN"])
        self.assertEqual(result["solution_status"], "FEASIBLE")
        self.assertFalse(result["objective_proven"])

    def test_later_unknown_retains_last_candidate_and_not_global_optimality(self):
        original = opt._run_stage
        calls = []
        def run(*args):
            calls.append(args)
            return original(*args) if len(calls) == 1 else (None, cp_model.UNKNOWN)
        with patch.object(opt, "_run_stage", side_effect=run):
            result = solve(fixture(), "B3")
        self.assertEqual(result["metrics"]["unassigned_count"], 1)
        self.assertEqual([s["status"] for s in result["objective_stages"]], ["OPTIMAL", "UNKNOWN", "NOT_RUN"])
        self.assertIsNone(result["objective_stages"][1]["best_bound"])
        self.assertFalse(result["objective_proven"])
        self.assertEqual(result["solution_status"], "FEASIBLE")

    def test_no_solver_solution_keeps_valid_warm_start_without_claiming_optimality(self):
        with patch.object(opt, "_run_stage", return_value=(None, cp_model.UNKNOWN)):
            result = solve(fixture(), "B2")
        self.assertEqual(result["solution_status"], "FEASIBLE")
        self.assertEqual({a["job_id"] for a in result["assignments"]}, {"J0", "J1", "J2"})
        self.assertEqual(result["unassigned_job_ids"], ["J3"])
        self.assertEqual(result["objective_stages"][0]["status"], "UNKNOWN")
        self.assertFalse(result["objective_proven"])

    def test_each_stage_consumes_the_same_total_budget(self):
        original = opt._run_stage
        clock, budgets = [0.0], []
        def run(model, expression, remaining, seed):
            budgets.append(remaining)
            answer = original(model, expression, remaining, seed)
            clock[0] += 4
            return answer
        with patch.object(opt, "monotonic", side_effect=lambda: clock[0]), patch.object(opt, "_run_stage", side_effect=run):
            result = opt.solve_optimized(fixture(), "B3", {"seed": 0, "time_limit_seconds": 10}, 0, "test")
        self.assertEqual(budgets, [10, 6, 2])
        self.assertTrue(result["objective_proven"])

    def test_budget_exhausted_between_stages_preserves_last_candidate(self):
        original = opt._run_stage
        clock = [0.0]
        def run(*args):
            answer = original(*args)
            clock[0] = 10
            return answer
        with patch.object(opt, "monotonic", side_effect=lambda: clock[0]), patch.object(opt, "_run_stage", side_effect=run) as runner:
            result = opt.solve_optimized(fixture(), "B3", {"seed": 0, "time_limit_seconds": 10}, 0, "test")
        self.assertEqual(runner.call_count, 1)
        self.assertEqual([s["status"] for s in result["objective_stages"]], ["OPTIMAL", "NOT_RUN", "NOT_RUN"])
        self.assertEqual(result["solution_status"], "FEASIBLE")
        self.assertTrue(result["execution_metadata"]["solver_settings"]["time_limit_reached"])

    def test_model_build_timeout_keeps_warm_start_and_fixed_work(self):
        with patch.object(opt, "DispatchModel", side_effect=opt.BuildTimeout):
            result = solve(fixture(), "B3")
        self.assertEqual(result["solution_status"], "FEASIBLE")
        self.assertEqual(result["assignments"][0], fixture()["baseline_assignments"][0])
        self.assertTrue(all(s["status"] == "NOT_RUN" for s in result["objective_stages"]))
        self.assertFalse(result["objective_proven"])

    def test_timeout_never_returns_a_worse_objective_than_its_warm_start(self):
        original = opt._run_stage
        def feasible(*args):
            solver, _ = original(*args)
            return solver, cp_model.FEASIBLE
        baseline = solve(fixture(), "B1")
        with patch.object(opt, "_run_stage", side_effect=feasible):
            result = solve(fixture(), "B3")
        key = lambda r: (r["metrics"]["unassigned_count"], len(r["metrics"]["changed_job_ids"]), r["metrics"]["movable_travel_minutes"])
        self.assertLessEqual(key(result), key(baseline))

    def assert_incomplete_timeout(self, snapshot, result, reason):
        self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
        self.assertTrue(any(i["code"] == "INPUT_MISSING" and reason in i["explanation"]
                            for i in result["issues"]))
        self.assertTrue(result["execution_metadata"]["solver_settings"]["time_limit_reached"])
        self.assertTrue(all(s["status"] == "NOT_RUN" for s in result["objective_stages"]))
        self.assertFalse(result["objective_proven"])
        self.assertFalse(result["approval_eligible"])
        self.assertEqual(next(a for a in result["assignments"] if a["job_id"] == "J0"),
                         snapshot["baseline_assignments"][0])

    def test_build_timeout_retains_missing_vehicle_availability(self):
        snapshot = fixture()
        snapshot["vehicles"][0]["available_at"] = None
        for method in ("B2", "B3"):
            with self.subTest(method=method), patch.object(opt, "DispatchModel", side_effect=opt.BuildTimeout):
                result = solve(snapshot, method)
            self.assert_incomplete_timeout(snapshot, result, "available_at")

    def test_build_timeout_retains_missing_approach_found_by_warm_start(self):
        snapshot = fixture()
        snapshot["travel_times"] = [p for p in snapshot["travel_times"]
                                    if (p["from_location_id"], p["to_location_id"]) != ("D", "O")]
        for method in ("B2", "B3"):
            with self.subTest(method=method), patch.object(opt, "DispatchModel", side_effect=opt.BuildTimeout):
                result = solve(snapshot, method)
            self.assert_incomplete_timeout(snapshot, result, "D → O")

    def test_timeout_inside_construction_retains_discovered_input_issues(self):
        snapshot = fixture()
        snapshot["vehicles"][0]["available_at"] = None
        original = opt.DispatchModel.check_budget
        discovered = []
        def expire_after_diagnosis(model):
            if model.input_issues:
                discovered.extend(model.input_issues)
                model.deadline = -1
            original(model)
        with patch.object(opt.DispatchModel, "check_budget", expire_after_diagnosis):
            result = solve(snapshot, "B3")
        self.assertTrue(discovered)
        self.assert_incomplete_timeout(snapshot, result, "available_at")
        self.assertTrue(all(detail in result["issues"] for detail in discovered))

    def test_missing_ready_vehicle_and_routes_are_never_optimal(self):
        for missing in ("ready", "vehicle", "route"):
            with self.subTest(missing=missing):
                snapshot = fixture()
                if missing == "ready":
                    snapshot["jobs"][1]["ready_at"] = None
                elif missing == "vehicle":
                    snapshot["vehicles"][0]["available_at"] = None
                else:
                    snapshot["travel_times"] = [t for t in snapshot["travel_times"]
                                                if (t["from_location_id"], t["to_location_id"]) != ("D", "O")]
                result = solve(snapshot, "B3")
                self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
                self.assertFalse(result["objective_proven"])
                self.assertEqual(next(a for a in result["assignments"] if a["job_id"] == "J0"), snapshot["baseline_assignments"][0])

    def test_large_seed_is_explicitly_normalized_without_mutating_config(self):
        config = {"seed": 2**50, "time_limit_seconds": 10}
        result = solve(fixture(), "B2", config)
        settings = result["execution_metadata"]["solver_settings"]
        self.assertEqual(settings["seed"], config["seed"])
        self.assertEqual(settings["effective_seed"], config["seed"] % (2**31 - 1))

    def test_solver_invalid_model_is_not_reported_as_success(self):
        with patch.object(opt, "_run_stage", return_value=(None, cp_model.MODEL_INVALID)):
            with self.assertRaises(EngineInputError):
                solve(fixture(), "B2")
