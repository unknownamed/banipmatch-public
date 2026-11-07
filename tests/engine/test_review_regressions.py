"""Regression cases from PR #1's dispatch feasibility review."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from backend.engine import solve


def fixture():
    path = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터/01_snapshot.json"
    return json.loads(path.read_text(encoding="utf-8"))


def after_return(minutes):
    return (datetime.fromisoformat("2026-11-07T01:00:00+00:00")
            + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def returned_vehicle(minutes, start="O"):
    snapshot = fixture()
    snapshot["jobs"] = snapshot["jobs"][:2]
    snapshot["baseline_assignments"] = snapshot["baseline_assignments"][:2]
    snapshot["vehicles"] = snapshot["vehicles"][:1]
    snapshot["as_of"] = after_return(minutes)
    snapshot["vehicles"][0].update(start_location_id=start, available_at=after_return(minutes))
    snapshot["windows"][0]["closes_at"] = after_return(45)
    return snapshot


def alternative_vehicle():
    snapshot = fixture()
    snapshot["jobs"] = snapshot["jobs"][1:2]
    snapshot["baseline_assignments"] = snapshot["baseline_assignments"][1:2]
    snapshot["vehicles"][0]["available_at"] = "2026-11-07T03:00:00Z"
    snapshot["vehicles"][1]["start_location_id"] = "X"
    extra = copy.deepcopy(snapshot["locations"][0])
    extra.update(location_id="X", name="모의 대체 차고지")
    snapshot["locations"].append(extra)
    return snapshot


def add_alternative_path(snapshot):
    leg = copy.deepcopy(snapshot["travel_times"][0])
    leg["from_location_id"] = "X"
    snapshot["travel_times"].append(leg)


class ReviewRegressionTests(unittest.TestCase):
    def test_return_boundary_cannot_teleport_to_pickup(self):
        for elapsed in (0, 5):
            for method in ("B0", "B1"):
                with self.subTest(elapsed=elapsed, method=method):
                    snapshot = returned_vehicle(elapsed)
                    result = solve(snapshot, method)
                    self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
                    self.assertTrue(any(i["code"] == "INPUT_MISSING" for i in result["issues"]))
                    self.assertEqual(result["assignments"][0], snapshot["baseline_assignments"][0])
                    if method == "B1":
                        self.assertEqual(result["unassigned_job_ids"], ["J1"])
                        self.assertEqual(result["metrics"]["feasible_movable_count"], 0)
                    else:
                        self.assertEqual(result["assignments"], snapshot["baseline_assignments"])

    def test_confirmed_start_after_sufficient_reposition_is_usable(self):
        for elapsed in (10, 60):
            with self.subTest(elapsed=elapsed):
                snapshot = returned_vehicle(elapsed)
                snapshot["windows"][0]["closes_at"] = after_return(120)
                result = solve(snapshot, "B1")
                self.assertEqual(result["solution_status"], "HEURISTIC")
                self.assertEqual(result["unassigned_job_ids"], [])
                self.assertEqual(result["assignments"][1]["pickup_departure_at"], after_return(elapsed))
                self.assertEqual(result["metrics"]["movable_travel_minutes"], 40)
                self.assertEqual(result["metrics"]["feasible_movable_count"], 1)

    def test_later_snapshot_does_not_repair_impossible_available_timestamp(self):
        snapshot = returned_vehicle(20)
        snapshot["vehicles"][0]["available_at"] = after_return(0)
        result = solve(snapshot, "B1")
        self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
        self.assertEqual(result["unassigned_job_ids"], ["J1"])

    def test_unknown_reposition_time_blocks_new_work(self):
        snapshot = returned_vehicle(10)
        # O -> D remains present; it cannot substitute for missing D -> O.
        snapshot["travel_times"] = snapshot["travel_times"][1:]
        result = solve(snapshot, "B1")
        self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
        self.assertEqual(result["unassigned_job_ids"], ["J1"])

    def test_start_at_return_location_charges_approach_and_checks_cutoff(self):
        snapshot = returned_vehicle(0, start="D")
        late = solve(snapshot, "B1")
        self.assertEqual(late["unassigned_job_ids"], ["J1"])
        self.assertEqual(late["solution_status"], "HEURISTIC")
        snapshot["windows"][0]["closes_at"] = after_return(50)
        on_time = solve(snapshot, "B1")
        self.assertEqual(on_time["unassigned_job_ids"], [])
        self.assertEqual(on_time["assignments"][1]["pickup_departure_at"], after_return(10))
        self.assertEqual(on_time["metrics"]["movable_travel_minutes"], 50)

    def check_irrelevant_path(self, field, value):
        snapshot = alternative_vehicle()
        snapshot["vehicles"][1][field] = value
        without_path = solve(snapshot, "B1")
        add_alternative_path(snapshot)
        with_path = solve(snapshot, "B1")
        for result in (without_path, with_path):
            self.assertEqual(result["solution_status"], "HEURISTIC")
            self.assertEqual(result["assignments"], [])
            self.assertEqual(result["unassigned_job_ids"], ["J1"])
            self.assertEqual([i["code"] for i in result["issues"]], ["SEARCH_LIMIT"])
        self.assertEqual(without_path["issues"], with_path["issues"])

    def test_incompatible_vehicle_does_not_require_approach_path(self):
        self.check_irrelevant_path("equipment_types", ["DRY20"])

    def test_under_capacity_vehicle_does_not_require_approach_path(self):
        self.check_irrelevant_path("capacity_kg", 10000)

    def test_compatible_vehicle_still_requires_approach_path(self):
        snapshot = alternative_vehicle()
        result = solve(snapshot, "B1")
        self.assertEqual(result["solution_status"], "INPUT_INCOMPLETE")
        self.assertEqual([i["code"] for i in result["issues"]], ["INPUT_MISSING"])
        add_alternative_path(snapshot)
        complete = solve(snapshot, "B1")
        self.assertEqual(complete["solution_status"], "HEURISTIC")
        self.assertEqual(complete["unassigned_job_ids"], [])


if __name__ == "__main__":
    unittest.main()
