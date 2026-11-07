"""Regression checks for job-based change counts and directed travel totals."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from backend.engine.metrics import MissingTravelTimeError, calculate_metrics


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs/development/v0.1/예제 데이터"


def fixture():
    return json.loads((EXAMPLES / "01_snapshot.json").read_text(encoding="utf-8"))


def issue(job_id):
    return {"job_id": job_id, "code": "CUTOFF_EXCEEDED"}


class MetricsTests(unittest.TestCase):
    def test_published_baseline_and_explanation_match_known_metrics(self):
        snapshot = fixture()
        document = json.loads(
            (EXAMPLES / "04_results_설명용.json").read_text(encoding="utf-8")
        )
        for result in document["results"]:
            with self.subTest(method=result["method"]):
                actual = calculate_metrics(snapshot, result["assignments"],
                                           result["unassigned_job_ids"], result["issues"], 0)
                self.assertEqual(actual, result["metrics"])

    def test_removed_job_and_renumbering_do_not_count_as_reordering(self):
        snapshot = fixture()
        assignments = copy.deepcopy(snapshot["baseline_assignments"])
        assignments = [row for row in assignments if row["job_id"] != "J2"]
        next(row for row in assignments if row["job_id"] == "J3")["sequence"] = 1
        result = calculate_metrics(snapshot, assignments, ["J2"], [], 12)
        self.assertEqual(result["changed_job_ids"], [])
        self.assertEqual(result["order_changed_job_ids"], [])
        self.assertEqual(result["unassigned_count"], 1)
        self.assertEqual(result["elapsed_ms"], 12)

    def test_same_vehicle_inversion_marks_both_jobs(self):
        snapshot = fixture()
        assignments = copy.deepcopy(snapshot["baseline_assignments"])
        for row in assignments:
            if row["job_id"] == "J2": row["sequence"] = 2
            if row["job_id"] == "J3": row["sequence"] = 1
        result = calculate_metrics(snapshot, assignments, [], [], 0)
        self.assertEqual(result["order_changed_job_ids"], ["J2", "J3"])
        self.assertEqual(result["changed_job_ids"], ["J2", "J3"])

    def test_vehicle_change_is_not_also_order_change(self):
        snapshot = fixture()
        assignments = copy.deepcopy(snapshot["baseline_assignments"])
        for row in assignments:
            if row["job_id"] == "J2":
                row["vehicle_id"] = "T1"
                row["sequence"] = 3
            elif row["job_id"] == "J3":
                row["sequence"] = 1
        result = calculate_metrics(snapshot, assignments, [], [], 0)
        self.assertEqual(result["vehicle_changed_job_ids"], ["J2"])
        self.assertEqual(result["order_changed_job_ids"], [])

    def test_time_tolerance_uses_strictly_greater_threshold(self):
        snapshot = fixture()
        snapshot["policy"]["time_change_tolerance_minutes"] = 5
        assignments = copy.deepcopy(snapshot["baseline_assignments"])
        j1 = next(row for row in assignments if row["job_id"] == "J1")
        j1["pickup_departure_at"] = "2026-11-07T01:15:00Z"
        self.assertEqual(calculate_metrics(snapshot, assignments, [], [], 0)["time_changed_job_ids"], [])
        j1["pickup_departure_at"] = "2026-11-07T01:16:00Z"
        self.assertEqual(calculate_metrics(snapshot, assignments, [], [], 0)["time_changed_job_ids"], ["J1"])

    def test_new_assignment_is_changed_and_separately_reported(self):
        snapshot = fixture()
        assignments = copy.deepcopy(snapshot["baseline_assignments"])
        snapshot["baseline_assignments"] = [
            row for row in snapshot["baseline_assignments"] if row["job_id"] != "J3"
        ]
        snapshot["baseline_unassigned_job_ids"] = ["J3"]
        result = calculate_metrics(snapshot, assignments, [], [], 0)
        self.assertEqual(result["newly_assigned_job_ids"], ["J3"])
        self.assertEqual(result["changed_job_ids"], ["J3"])
        self.assertEqual(result["time_changed_job_ids"], [])

    def test_multiple_issues_count_each_assigned_job_once(self):
        snapshot = fixture()
        assignments = [row for row in snapshot["baseline_assignments"] if row["job_id"] != "J3"]
        result = calculate_metrics(snapshot, assignments, ["J3"],
                                   [issue("J0"), issue("J0"), issue("J1"),
                                    issue("J1"), issue("J3"), issue(None)], 0)
        self.assertEqual(result["fixed_risk_count"], 1)
        self.assertEqual(result["movable_violation_count"], 1)
        self.assertEqual(result["feasible_movable_count"], 1)

    def test_fixed_only_schedule_has_zero_movable_travel(self):
        snapshot = fixture()
        assignments = [row for row in snapshot["baseline_assignments"] if row["job_id"] == "J0"]
        snapshot["travel_times"] = []
        result = calculate_metrics(snapshot, assignments, ["J1", "J2", "J3"], [], 0)
        self.assertEqual(result["movable_travel_minutes"], 0)

    def test_missing_directed_leg_is_not_replaced_by_reverse_leg(self):
        snapshot = fixture()
        snapshot["travel_times"] = [row for row in snapshot["travel_times"]
                                    if (row["from_location_id"], row["to_location_id"]) != ("D", "O")]
        with self.assertRaises(MissingTravelTimeError) as raised:
            calculate_metrics(snapshot, snapshot["baseline_assignments"], [], [], 0)
        self.assertEqual(raised.exception.origin_id, "D")
        self.assertEqual(raised.exception.destination_id, "O")

    def test_explicit_zero_leg_is_valid_and_null_is_missing(self):
        snapshot = fixture()
        leg = next(row for row in snapshot["travel_times"]
                   if (row["from_location_id"], row["to_location_id"]) == ("D", "O"))
        leg["minutes"] = 0
        self.assertEqual(calculate_metrics(snapshot, snapshot["baseline_assignments"], [], [], 0)["movable_travel_minutes"], 120)
        leg["minutes"] = None
        with self.assertRaises(MissingTravelTimeError):
            calculate_metrics(snapshot, snapshot["baseline_assignments"], [], [], 0)

    def test_departed_prefix_keeps_vehicle_start_location(self):
        snapshot = fixture()
        j0 = next(job for job in snapshot["jobs"] if job["job_id"] == "J0")
        j0["return_location_id"] = "UNKNOWN_RETURN"
        # Current post-departure state remains D; no leg from UNKNOWN_RETURN is needed.
        result = calculate_metrics(snapshot, snapshot["baseline_assignments"], [], [], 0)
        self.assertEqual(result["movable_travel_minutes"], 150)

    def test_future_fixed_reservation_sets_next_approach_origin(self):
        snapshot = fixture()
        j0 = next(job for job in snapshot["jobs"] if job["job_id"] == "J0")
        j0["state"] = "planned"
        j0["return_location_id"] = "HJNC"
        result = calculate_metrics(snapshot, snapshot["baseline_assignments"], [], [], 0)
        # T1's J1 approaches O from HJNC (30), not from D (10).
        self.assertEqual(result["movable_travel_minutes"], 170)

    def test_does_not_mutate_any_inputs(self):
        snapshot = fixture()
        assignments = copy.deepcopy(snapshot["baseline_assignments"])
        issues = [issue("J1")]
        before = copy.deepcopy((snapshot, assignments, issues))
        calculate_metrics(snapshot, assignments, [], issues, 9)
        self.assertEqual((snapshot, assignments, issues), before)

    def test_invalid_partition_or_duplicate_sequence_is_rejected(self):
        snapshot = fixture()
        with self.assertRaises(ValueError):
            calculate_metrics(snapshot, snapshot["baseline_assignments"], ["J3"], [], 0)
        assignments = copy.deepcopy(snapshot["baseline_assignments"])
        assignments[1]["sequence"] = assignments[0]["sequence"]
        with self.assertRaises(ValueError):
            calculate_metrics(snapshot, assignments, [], [], 0)

    def test_integral_json_numbers_preserve_metrics_without_mutating_inputs(self):
        snapshot = fixture()
        expected = calculate_metrics(snapshot, snapshot["baseline_assignments"], [], [], 12)
        for row in snapshot["travel_times"]:
            row["minutes"] = float(row["minutes"])
        for row in snapshot["baseline_assignments"]:
            row["sequence"] = float(row["sequence"])
        snapshot["policy"]["time_change_tolerance_minutes"] = 5.0
        before = copy.deepcopy(snapshot)
        actual = calculate_metrics(snapshot, snapshot["baseline_assignments"], [], [], 12.0)
        self.assertEqual(actual, expected)
        self.assertIs(type(actual["movable_travel_minutes"]), int)
        self.assertIs(type(actual["elapsed_ms"]), int)
        self.assertEqual(snapshot, before)

    def test_boolean_fractional_and_nonfinite_values_are_not_integers(self):
        for field in ("travel", "sequence", "tolerance", "elapsed"):
            for value in (True, False, 1.5, -1, float("inf"), float("nan")):
                with self.subTest(field=field, value=value):
                    snapshot = fixture()
                    elapsed = 0
                    if field == "travel":
                        next(row for row in snapshot["travel_times"]
                             if (row["from_location_id"], row["to_location_id"]) == ("D", "O"))["minutes"] = value
                    elif field == "sequence":
                        snapshot["baseline_assignments"][0]["sequence"] = value
                    elif field == "tolerance":
                        snapshot["policy"]["time_change_tolerance_minutes"] = value
                    else:
                        elapsed = value
                    with self.assertRaises(ValueError):
                        calculate_metrics(snapshot, snapshot["baseline_assignments"], [], [], elapsed)


if __name__ == "__main__":
    unittest.main()
