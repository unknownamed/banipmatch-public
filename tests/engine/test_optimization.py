"""Small, independently checkable cases for B2/B3's lexicographic objectives."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from backend.engine import solve


ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "docs/development/v0.1"
CONFIG = {"seed": 1, "time_limit_seconds": 10}
METHODS = ("B2", "B3")


def fixture():
    return json.loads((DRAFT / "예제 데이터/01_snapshot.json").read_text(encoding="utf-8"))


def at(minutes):
    start = datetime(2026, 11, 7, tzinfo=timezone.utc)
    return (start + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def assignment(job_id, vehicle_id, departure, sequence=1):
    """The small cases use 30 loaded + 10 return minutes, no buffer/service."""
    return dict(job_id=job_id, vehicle_id=vehicle_id, sequence=sequence,
                pickup_departure_at=at(departure), gate_arrival_at=at(departure + 30),
                return_at=at(departure + 40))


def assigned(result, job_id):
    return next(row for row in result["assignments"] if row["job_id"] == job_id)


def tradeoff_snapshot():
    """Keeping T1 costs 60 minutes; switching to T2 costs 40 and changes one job."""
    snapshot = fixture()
    snapshot["jobs"] = [copy.deepcopy(snapshot["jobs"][1])]
    snapshot["jobs"][0].update(job_id="J1", ready_at=at(0), service_minutes=0)
    snapshot["policy"].update(buffer_minutes=0, time_change_tolerance_minutes=5)
    snapshot["windows"] = [snapshot["windows"][0]]
    snapshot["windows"][0].update(opens_at=at(0), closes_at=at(120))
    for vehicle in snapshot["vehicles"]:
        vehicle.update(available_at=at(0), shift_end_at=at(180))
    snapshot["vehicles"][0]["start_location_id"] = "D"
    snapshot["vehicles"][1]["start_location_id"] = "O"
    next(leg for leg in snapshot["travel_times"]
         if (leg["from_location_id"], leg["to_location_id"]) == ("D", "O"))["minutes"] = 20
    snapshot["baseline_assignments"] = [assignment("J1", "T1", 20)]
    snapshot["baseline_unassigned_job_ids"] = []
    return snapshot


def preserve_departure_snapshot():
    """Waiting at the pickup can keep a feasible baseline departure unchanged."""
    snapshot = tradeoff_snapshot()
    snapshot["vehicles"] = snapshot["vehicles"][:1]
    snapshot["baseline_assignments"] = [assignment("J1", "T1", 60)]
    return snapshot


def changed_union_snapshot():
    """Both vehicles change J1 once; vehicle+time must not count as two jobs."""
    snapshot = tradeoff_snapshot()
    snapshot["jobs"][0]["ready_at"] = at(60)
    return snapshot


def capacity_competition_snapshot():
    """Serving both requires moving JA off the only DRY40-compatible vehicle."""
    snapshot = tradeoff_snapshot()
    ja = copy.deepcopy(snapshot["jobs"][0])
    ja.update(job_id="JA", equipment_type="DRY20")
    jb = copy.deepcopy(ja)
    jb.update(job_id="JB", equipment_type="DRY40")
    snapshot["jobs"] = [ja, jb]
    snapshot["windows"][0]["closes_at"] = at(30)
    for vehicle in snapshot["vehicles"]:
        vehicle["start_location_id"] = "O"
    snapshot["vehicles"][0]["equipment_types"] = ["DRY20", "DRY40"]
    snapshot["vehicles"][1]["equipment_types"] = ["DRY20"]
    snapshot["baseline_assignments"] = [assignment("JA", "T1", 0)]
    snapshot["baseline_unassigned_job_ids"] = ["JB"]
    return snapshot


def future_fixed_snapshot(sequence=3):
    snapshot = tradeoff_snapshot()
    snapshot["vehicles"] = snapshot["vehicles"][:1]
    snapshot["vehicles"][0]["shift_end_at"] = at(240)
    snapshot["windows"][0]["closes_at"] = at(180)
    fixed = copy.deepcopy(snapshot["jobs"][0])
    fixed.update(job_id="JF", frozen=True, freeze_reason="FIXED_RESERVATION")
    snapshot["jobs"].append(fixed)
    movable_sequence = 1 if sequence > 1 else 2
    snapshot["baseline_assignments"] = [
        assignment("J1", "T1", 20, movable_sequence),
        assignment("JF", "T1", 100, sequence),
    ]
    return snapshot


class OptimizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads((DRAFT / "공통 규격/contracts.schema.json").read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(
            {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/MethodResult"},
            format_checker=FormatChecker(),
        )

    def assert_optimal_contract(self, snapshot, method, result):
        self.validator.validate(result)
        self.assertEqual(result["method"], method)
        self.assertEqual(result["result_origin"], "computed")
        self.assertEqual(result["solution_status"], "OPTIMAL")
        self.assertTrue(result["objective_proven"])
        self.assertEqual(result["validation_status"], "not_run")
        self.assertFalse(result["approval_eligible"])
        metrics = result["metrics"]
        self.assertEqual(metrics["movable_violation_count"], 0)
        objectives = ["unassigned", "travel"] if method == "B2" else ["unassigned", "changed", "travel"]
        expected_values = {"unassigned": metrics["unassigned_count"],
                           "changed": len(metrics["changed_job_ids"]),
                           "travel": metrics["movable_travel_minutes"]}
        self.assertEqual([stage["objective"] for stage in result["objective_stages"]], objectives)
        for stage in result["objective_stages"]:
            self.assertEqual(stage["status"], "OPTIMAL")
            self.assertEqual(stage["value"], expected_values[stage["objective"]])
            if stage["best_bound"] is not None:
                self.assertAlmostEqual(stage["best_bound"], stage["value"])
        assigned_ids = [row["job_id"] for row in result["assignments"]]
        unassigned_ids = result["unassigned_job_ids"]
        self.assertEqual(len(assigned_ids), len(set(assigned_ids)))
        self.assertEqual(len(unassigned_ids), len(set(unassigned_ids)))
        self.assertFalse(set(assigned_ids) & set(unassigned_ids))
        self.assertEqual(set(assigned_ids) | set(unassigned_ids),
                         {job["job_id"] for job in snapshot["jobs"]})
        self.assertEqual(metrics["unassigned_count"], len(unassigned_ids))

    def test_b2_saves_travel_while_b3_preserves_the_baseline_vehicle(self):
        snapshot = tradeoff_snapshot()
        for method, vehicle_id, changed, travel in (("B2", "T2", 1, 40), ("B3", "T1", 0, 60)):
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual(result["unassigned_job_ids"], [])
                self.assertEqual(assigned(result, "J1")["vehicle_id"], vehicle_id)
                self.assertEqual(len(result["metrics"]["changed_job_ids"]), changed)
                self.assertEqual(result["metrics"]["movable_travel_minutes"], travel)

    def test_b3_can_wait_to_keep_a_feasible_baseline_departure(self):
        snapshot = preserve_departure_snapshot()
        result = solve(snapshot, "B3", CONFIG)
        self.assert_optimal_contract(snapshot, "B3", result)
        self.assertEqual(result["metrics"]["changed_job_ids"], [])
        departure = assigned(result, "J1")["pickup_departure_at"]
        self.assertGreaterEqual(departure, at(55))
        self.assertLessEqual(departure, at(65))
        self.assertEqual(result["metrics"]["movable_travel_minutes"], 60)

    def test_b3_counts_vehicle_and_time_change_as_one_job_then_minimizes_travel(self):
        snapshot = changed_union_snapshot()
        for method in METHODS:
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual(assigned(result, "J1")["vehicle_id"], "T2")
                self.assertEqual(result["metrics"]["changed_job_ids"], ["J1"])
                self.assertEqual(result["metrics"]["vehicle_changed_job_ids"], ["J1"])
                self.assertEqual(result["metrics"]["time_changed_job_ids"], ["J1"])
                self.assertEqual(result["metrics"]["movable_travel_minutes"], 40)

    def test_serving_an_extra_job_precedes_changes_and_travel(self):
        snapshot = capacity_competition_snapshot()
        for method in METHODS:
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual(result["unassigned_job_ids"], [])
                self.assertEqual(assigned(result, "JA")["vehicle_id"], "T2")
                self.assertEqual(assigned(result, "JB")["vehicle_id"], "T1")
                self.assertEqual(result["metrics"]["changed_job_ids"], ["JA", "JB"])
                self.assertEqual(result["metrics"]["newly_assigned_job_ids"], ["JB"])
                self.assertEqual(result["metrics"]["movable_travel_minutes"], 80)

    def test_snapshot_and_configuration_are_not_mutated(self):
        for method in METHODS:
            with self.subTest(method=method):
                snapshot = capacity_competition_snapshot()
                config = copy.deepcopy(CONFIG)
                before = copy.deepcopy((snapshot, config))
                result = solve(snapshot, method, config)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual((snapshot, config), before)

    def test_departed_cutoff_risk_is_preserved_without_making_the_model_infeasible(self):
        snapshot = fixture()
        snapshot["windows"][0]["closes_at"] = at(25)
        frozen = next(row for row in snapshot["baseline_assignments"] if row["job_id"] == "J0")
        for method in METHODS:
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual(assigned(result, "J0"), frozen)
                self.assertNotIn("J0", result["unassigned_job_ids"])
                self.assertEqual(result["metrics"]["fixed_risk_count"], 1)
                self.assertTrue(any(issue["job_id"] == "J0" for issue in result["issues"]))

    def test_future_fixed_assignment_keeps_sequence_and_all_times(self):
        snapshot = future_fixed_snapshot(sequence=3)
        fixed = next(row for row in snapshot["baseline_assignments"] if row["job_id"] == "JF")
        for method in METHODS:
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual(result["unassigned_job_ids"], [])
                self.assertEqual(assigned(result, "JF"), fixed)
                movable = assigned(result, "J1")
                self.assertLess(movable["sequence"], fixed["sequence"])
                self.assertLessEqual(movable["return_at"], at(80))  # plus 20-minute approach <= fixed departure
                if method == "B3":
                    self.assertEqual(result["metrics"]["changed_job_ids"], [])

    def test_fixed_sequence_one_does_not_allow_fractional_or_zero_insertion(self):
        snapshot = future_fixed_snapshot(sequence=1)
        fixed = next(row for row in snapshot["baseline_assignments"] if row["job_id"] == "JF")
        for method in METHODS:
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual(result["assignments"], [fixed])
                self.assertEqual(result["unassigned_job_ids"], ["J1"])

    def test_all_optional_jobs_may_be_unassigned_with_a_feasible_model(self):
        snapshot = tradeoff_snapshot()
        snapshot["jobs"][0]["ready_at"] = at(180)
        for method in METHODS:
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual(result["assignments"], [])
                self.assertEqual(result["unassigned_job_ids"], ["J1"])
                self.assertEqual(result["metrics"]["changed_job_ids"], [])
                self.assertEqual(result["metrics"]["movable_travel_minutes"], 0)

    def test_b3_time_change_tolerance_is_inclusive(self):
        for ready, changes in ((25, []), (26, ["J1"])):
            with self.subTest(ready=ready):
                snapshot = tradeoff_snapshot()
                snapshot["vehicles"] = snapshot["vehicles"][:1]
                snapshot["jobs"][0]["ready_at"] = at(ready)
                result = solve(snapshot, "B3", CONFIG)
                self.assert_optimal_contract(snapshot, "B3", result)
                self.assertEqual(result["metrics"]["changed_job_ids"], changes)
                self.assertEqual(result["unassigned_job_ids"], [])

    def test_cutoff_and_shift_end_accept_equality_but_not_a_minute_over(self):
        for cutoff, shift_end, unassigned in ((50, 60, []), (49, 60, ["J1"]), (50, 59, ["J1"])):
            for method in METHODS:
                with self.subTest(method=method, cutoff=cutoff, shift_end=shift_end):
                    snapshot = tradeoff_snapshot()
                    snapshot["vehicles"] = snapshot["vehicles"][:1]
                    snapshot["vehicles"][0]["shift_end_at"] = at(shift_end)
                    snapshot["windows"][0]["closes_at"] = at(cutoff)
                    result = solve(snapshot, method, CONFIG)
                    self.assert_optimal_contract(snapshot, method, result)
                    self.assertEqual(result["unassigned_job_ids"], unassigned)

    def test_required_same_vehicle_reversal_counts_both_jobs(self):
        snapshot = tradeoff_snapshot()
        snapshot["vehicles"] = snapshot["vehicles"][:1]
        ja = copy.deepcopy(snapshot["jobs"][0])
        ja["job_id"] = "JA"
        jb = copy.deepcopy(ja)
        jb.update(job_id="JB", voyage_id="V2")
        snapshot["jobs"] = [ja, jb]
        snapshot["windows"][0].update(opens_at=at(100), closes_at=at(180))
        second_window = copy.deepcopy(snapshot["windows"][0])
        second_window.update(window_id="W2", voyage_id="V2", opens_at=at(0), closes_at=at(50))
        snapshot["windows"].append(second_window)
        snapshot["baseline_assignments"] = [assignment("JA", "T1", 20, 1), assignment("JB", "T1", 80, 2)]
        for method in METHODS:
            with self.subTest(method=method):
                result = solve(snapshot, method, CONFIG)
                self.assert_optimal_contract(snapshot, method, result)
                self.assertEqual(result["unassigned_job_ids"], [])
                self.assertLess(assigned(result, "JB")["sequence"], assigned(result, "JA")["sequence"])
                self.assertEqual(result["metrics"]["order_changed_job_ids"], ["JA", "JB"])
                self.assertEqual(result["metrics"]["changed_job_ids"], ["JA", "JB"])


if __name__ == "__main__":
    unittest.main()
