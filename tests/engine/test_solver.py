"""Black-box checks for the B0/B1 engine and its published MethodResult shape."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from backend.engine import EngineInputError, solve


ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "docs/development/v0.1"
CONFIG = {"seed": 1, "time_limit_seconds": 10}


def fixture():
    return json.loads((DRAFT / "예제 데이터/01_snapshot.json").read_text(encoding="utf-8"))


def job(snapshot, job_id):
    return next(row for row in snapshot["jobs"] if row["job_id"] == job_id)


def assignment(rows, job_id):
    return next(row for row in rows if row["job_id"] == job_id)


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def plus(text, minutes):
    return (utc(text) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def without_approach_leg(snapshot):
    snapshot["travel_times"] = [row for row in snapshot["travel_times"]
                                if (row["from_location_id"], row["to_location_id"]) != ("D", "O")]
    return snapshot


class SolverTests(unittest.TestCase):
    def test_b0_retains_all_baseline_assignments_and_reports_risk(self):
        snapshot = fixture()
        result = solve(snapshot, "B0", CONFIG)
        self.assertEqual(result["assignments"], snapshot["baseline_assignments"])
        self.assertEqual(result["unassigned_job_ids"], snapshot["baseline_unassigned_job_ids"])
        self.assertEqual(result["solution_status"], "BASELINE")
        self.assertEqual(result["metrics"]["changed_job_ids"], [])
        self.assertEqual(result["metrics"]["movable_violation_count"], 2)
        self.assertEqual(result["metrics"]["fixed_risk_count"], 0)
        self.assertTrue({"J1", "J3"}.issubset({issue["job_id"] for issue in result["issues"]}))

    def test_b1_preserves_departed_job_and_finds_feasible_movable_jobs(self):
        snapshot = fixture()
        result = solve(snapshot, "B1", CONFIG)
        self.assertEqual(assignment(result["assignments"], "J0"),
                         assignment(snapshot["baseline_assignments"], "J0"))
        self.assertEqual({row["job_id"] for row in result["assignments"]}, {"J0", "J1", "J2"})
        self.assertEqual(result["unassigned_job_ids"], ["J3"])
        self.assertEqual(result["solution_status"], "HEURISTIC")
        self.assertEqual(result["metrics"]["movable_violation_count"], 0)
        self.assertEqual(result["metrics"]["feasible_movable_count"], 2)
        self.assertTrue(any(issue["job_id"] == "J3" and issue["code"] == "READY_TOO_LATE"
                            for issue in result["issues"]))

    def test_results_obey_schema_and_do_not_claim_independent_approval(self):
        schema = json.loads((DRAFT / "공통 규격/contracts.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(
            {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/MethodResult"},
            format_checker=FormatChecker(),
        )
        for method in ["B0", "B1"]:
            with self.subTest(method=method):
                result = solve(fixture(), method, CONFIG)
                validator.validate(result)
                self.assertEqual(result["method"], method)
                self.assertEqual(result["result_origin"], "computed")
                self.assertEqual(result["validation_status"], "not_run")
                self.assertFalse(result["approval_eligible"])
                self.assertFalse(result["objective_proven"])

    def test_snapshot_and_config_are_not_mutated(self):
        snapshot = fixture()
        config = copy.deepcopy(CONFIG)
        original = copy.deepcopy((snapshot, config))
        solve(snapshot, "B0", config)
        solve(snapshot, "B1", config)
        self.assertEqual((snapshot, config), original)

    def test_duplicate_ids_are_rejected_with_structured_issues(self):
        snapshot = fixture()
        snapshot["jobs"].append(copy.deepcopy(snapshot["jobs"][0]))
        with self.assertRaises(EngineInputError) as raised:
            solve(snapshot, "B1", CONFIG)
        self.assertIsInstance(raised.exception, ValueError)
        self.assertEqual(raised.exception.category, "invalid")
        self.assertTrue(raised.exception.issues)

    def test_unknown_reference_is_rejected(self):
        snapshot = fixture()
        job(snapshot, "J1")["origin_id"] = "NONEXISTENT"
        with self.assertRaises(EngineInputError) as raised:
            solve(snapshot, "B1", CONFIG)
        self.assertEqual(raised.exception.category, "invalid")

    def test_non_minute_plan_timestamp_is_rejected(self):
        snapshot = fixture()
        assignment(snapshot["baseline_assignments"], "J1")["pickup_departure_at"] = "2026-11-07T01:10:01Z"
        with self.assertRaises(EngineInputError) as raised:
            solve(snapshot, "B0", CONFIG)
        self.assertEqual(raised.exception.category, "invalid")

    def test_departed_unfrozen_job_is_not_silently_rescheduled(self):
        snapshot = fixture()
        job(snapshot, "J0")["frozen"] = False
        with self.assertRaises(EngineInputError):
            solve(snapshot, "B1", CONFIG)

    def test_unimplemented_methods_are_explicit(self):
        for method in ["B2", "B3"]:
            with self.subTest(method=method):
                with self.assertRaises(NotImplementedError):
                    solve(fixture(), method, CONFIG)

    def test_b0_missing_travel_is_input_error_not_invented_zero(self):
        snapshot = without_approach_leg(fixture())
        with self.assertRaises(EngineInputError) as raised:
            solve(snapshot, "B0", CONFIG)
        self.assertEqual(raised.exception.category, "incomplete")
        self.assertTrue(raised.exception.issues)

    def test_b1_missing_approach_prevents_new_assignments(self):
        result = solve(without_approach_leg(fixture()), "B1", CONFIG)
        self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
        self.assertEqual({row["job_id"] for row in result["assignments"]}, {"J0"})
        self.assertEqual(set(result["unassigned_job_ids"]), {"J1", "J2", "J3"})
        self.assertEqual(result["metrics"]["movable_travel_minutes"], 0)
        self.assertFalse(result["approval_eligible"])

    def test_missing_job_values_are_excluded_and_marked_incomplete(self):
        for field in ["ready_at", "gross_weight_kg", "service_minutes"]:
            with self.subTest(field=field):
                snapshot = fixture()
                job(snapshot, "J1")[field] = None
                result = solve(snapshot, "B1", CONFIG)
                self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
                self.assertIn("J1", result["unassigned_job_ids"])
                self.assertTrue(any(issue["job_id"] == "J1" and issue["code"] == "INPUT_MISSING"
                                    for issue in result["issues"]))

    def test_unknown_vehicle_availability_blocks_its_new_assignments(self):
        snapshot = fixture()
        next(row for row in snapshot["vehicles"] if row["vehicle_id"] == "T2")["available_at"] = None
        result = solve(snapshot, "B1", CONFIG)
        self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
        self.assertFalse(any(row["vehicle_id"] == "T2" for row in result["assignments"]))
        self.assertEqual(assignment(result["assignments"], "J0"),
                         assignment(snapshot["baseline_assignments"], "J0"))

    def test_fixed_cutoff_risk_is_kept_instead_of_dropped(self):
        snapshot = fixture()
        next(row for row in snapshot["windows"] if row["window_id"] == "W1")["closes_at"] = "2026-11-07T00:25:00Z"
        for method in ["B0", "B1"]:
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assertEqual(assignment(result["assignments"], "J0"),
                                 assignment(snapshot["baseline_assignments"], "J0"))
                self.assertNotIn("J0", result["unassigned_job_ids"])
                self.assertEqual(result["metrics"]["fixed_risk_count"], 1)

    def test_future_fixed_reservation_is_an_immutable_time_anchor(self):
        for departure, j1_fits in [("2026-11-07T00:20:00Z", False),
                                   ("2026-11-07T01:40:00Z", True)]:
            with self.subTest(departure=departure):
                snapshot = fixture()
                fixed_job = job(snapshot, "J2")
                fixed_job["frozen"] = True
                fixed_job["freeze_reason"] = "FIXED_RESERVATION"
                fixed = assignment(snapshot["baseline_assignments"], "J2")
                fixed.update(sequence=3, pickup_departure_at=departure,
                             gate_arrival_at=plus(departure, 30), return_at=plus(departure, 70))
                assignment(snapshot["baseline_assignments"], "J3")["sequence"] = 4
                result = solve(snapshot, "B1", CONFIG)
                self.assertEqual(assignment(result["assignments"], "J2"), fixed)
                assigned_ids = {row["job_id"] for row in result["assignments"]}
                self.assertEqual("J1" in assigned_ids, j1_fits)
                if j1_fits:
                    j1 = assignment(result["assignments"], "J1")
                    self.assertEqual(j1["vehicle_id"], "T2")
                    self.assertLess(j1["sequence"], fixed["sequence"])
                    self.assertLessEqual(utc(j1["return_at"]) + timedelta(minutes=10), utc(departure))

    def test_previously_unassigned_feasible_job_is_newly_assigned(self):
        snapshot = fixture()
        snapshot["baseline_assignments"] = [row for row in snapshot["baseline_assignments"]
                                             if row["job_id"] != "J1"]
        snapshot["baseline_unassigned_job_ids"] = ["J1"]
        result = solve(snapshot, "B1", CONFIG)
        self.assertIn("J1", result["metrics"]["newly_assigned_job_ids"])
        self.assertIn("J1", result["metrics"]["changed_job_ids"])
        self.assertNotIn("J1", result["unassigned_job_ids"])

    def test_input_array_order_does_not_change_heuristic_ties(self):
        original = fixture()
        shuffled = copy.deepcopy(original)
        for key in ["jobs", "vehicles", "windows", "travel_times", "baseline_assignments"]:
            shuffled[key].reverse()
        left = solve(original, "B1", CONFIG)
        right = solve(shuffled, "B1", CONFIG)
        self.assertEqual({row["job_id"]: row for row in left["assignments"]},
                         {row["job_id"]: row for row in right["assignments"]})
        self.assertEqual(sorted(left["unassigned_job_ids"]), sorted(right["unassigned_job_ids"]))
        self.assertEqual({key: value for key, value in left["metrics"].items() if key != "elapsed_ms"},
                         {key: value for key, value in right["metrics"].items() if key != "elapsed_ms"})

    def test_negative_calculation_budget_is_rejected(self):
        with self.assertRaises(ValueError):
            solve(fixture(), "B1", {"seed": 1, "time_limit_seconds": -1})

    def test_overlapping_departed_jobs_block_new_work_on_the_vehicle(self):
        snapshot = fixture()
        job(snapshot, "J2").update(state="departed", frozen=True,
                                    freeze_reason="ALREADY_DEPARTED",
                                    ready_at="2026-11-06T23:30:00Z")
        assignment(snapshot["baseline_assignments"], "J2").update(
            vehicle_id="T1", sequence=2,
            pickup_departure_at="2026-11-06T23:50:00Z",
            gate_arrival_at="2026-11-07T00:20:00Z",
            return_at="2026-11-07T01:00:00Z")
        assignment(snapshot["baseline_assignments"], "J1")["sequence"] = 3
        next(w for w in snapshot["windows"] if w["window_id"] == "W1")["closes_at"] = "2026-11-07T05:00:00Z"
        for method in ("B0", "B1"):
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
                self.assertGreaterEqual(result["metrics"]["fixed_risk_count"], 1)
                for jid in ("J0", "J2"):
                    self.assertEqual(assignment(result["assignments"], jid),
                                     assignment(snapshot["baseline_assignments"], jid))
                if method == "B0":
                    self.assertEqual(result["assignments"], snapshot["baseline_assignments"])
                else:
                    self.assertFalse(any(a["vehicle_id"] == "T1" and a["job_id"] not in ("J0", "J2")
                                         for a in result["assignments"]))

    def test_departed_job_after_planned_work_is_an_invalid_vehicle_state(self):
        snapshot = fixture()
        assignment(snapshot["baseline_assignments"], "J0")["sequence"] = 2
        assignment(snapshot["baseline_assignments"], "J1")["sequence"] = 1
        next(w for w in snapshot["windows"] if w["window_id"] == "W1")["closes_at"] = "2026-11-07T05:00:00Z"
        for method in ("B0", "B1"):
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
                self.assertGreaterEqual(result["metrics"]["fixed_risk_count"], 1)
                self.assertEqual(assignment(result["assignments"], "J0"),
                                 assignment(snapshot["baseline_assignments"], "J0"))
                if method == "B0":
                    self.assertEqual(result["assignments"], snapshot["baseline_assignments"])
                else:
                    self.assertFalse(any(a["vehicle_id"] == "T1" and a["job_id"] != "J0"
                                         for a in result["assignments"]))


if __name__ == "__main__":
    unittest.main()
