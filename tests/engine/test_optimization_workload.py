"""The implied workload bound must preserve feasible route-time schedules."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from backend.engine import solve


def at(minutes):
    return (datetime(2026, 11, 7, tzinfo=timezone.utc)
            + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot():
    path = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터/01_snapshot.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["jobs"] = [deepcopy(value["jobs"][1])]
    value["jobs"][0].update(ready_at=at(0), service_minutes=0)
    value["vehicles"] = value["vehicles"][:1]
    value["vehicles"][0].update(available_at=at(0), shift_end_at=at(180))
    value["windows"] = value["windows"][:1]
    value["windows"][0].update(opens_at=at(0), closes_at=at(150))
    value["policy"].update(buffer_minutes=0, time_change_tolerance_minutes=0)
    for leg in value["travel_times"]:
        if (leg["from_location_id"], leg["to_location_id"]) == ("D", "O"):
            leg["minutes"] = 20
    value["baseline_assignments"] = [assignment("J1", 1, 20, 50, 60)]
    value["baseline_unassigned_job_ids"] = []
    return value


def assignment(job_id, sequence, departure, arrival, returned):
    return dict(job_id=job_id, vehicle_id="T1", sequence=sequence,
                pickup_departure_at=at(departure), gate_arrival_at=at(arrival), return_at=at(returned))


class WorkloadBoundTests(unittest.TestCase):
    def check_result(self, value, method, unassigned=()):
        result = solve(value, method, {"seed": 0, "time_limit_seconds": 3})
        self.assertEqual(result["solution_status"], "OPTIMAL", result["issues"])
        self.assertTrue(result["objective_proven"])
        self.assertEqual(result["unassigned_job_ids"], list(unassigned))
        self.assertEqual(result["metrics"]["movable_violation_count"], 0)
        return result

    def test_buffer_cancels_from_latest_return_bound(self):
        value = snapshot()
        value["policy"]["buffer_minutes"] = 10
        value["windows"][0]["closes_at"] = at(60)
        value["vehicles"][0]["shift_end_at"] = at(70)
        value["baseline_assignments"] = [assignment("J1", 1, 20, 50, 70)]
        for method in ("B2", "B3"):
            with self.subTest(method=method):
                result = self.check_result(value, method)
                self.assertEqual(result["assignments"], value["baseline_assignments"])

    def test_zero_duration_and_zero_travel_do_not_require_positive_workload(self):
        value = snapshot()
        value["vehicles"][0]["shift_end_at"] = at(0)
        value["windows"][0]["closes_at"] = at(0)
        for leg in value["travel_times"]:
            leg["minutes"] = 0
        other = deepcopy(value["jobs"][0])
        other["job_id"] = "J2"
        value["jobs"].append(other)
        value["baseline_assignments"] = [assignment("J1", 1, 0, 0, 0), assignment("J2", 2, 0, 0, 0)]
        for method in ("B2", "B3"):
            with self.subTest(method=method):
                result = self.check_result(value, method)
                self.assertEqual(len(result["assignments"]), 2)
                self.assertEqual(result["metrics"]["movable_travel_minutes"], 0)

    def test_nonmetric_matrix_uses_selected_predecessor_not_direct_start(self):
        value = snapshot()
        first = value["jobs"][0]
        first.update(job_id="JA", origin_id="D", return_location_id="O")
        second = deepcopy(first)
        second.update(job_id="JB", origin_id="O", return_location_id="D", ready_at=at(60))
        value["jobs"].append(second)
        for leg in value["travel_times"]:
            if (leg["from_location_id"], leg["to_location_id"]) == ("D", "O"):
                leg["minutes"] = 100
        value["windows"][0]["closes_at"] = at(100)
        value["vehicles"][0]["shift_end_at"] = at(100)
        value["baseline_assignments"] = [assignment("JA", 1, 0, 30, 60), assignment("JB", 2, 60, 90, 100)]
        for method in ("B2", "B3"):
            with self.subTest(method=method):
                result = self.check_result(value, method)
                self.assertEqual([row["job_id"] for row in result["assignments"]], ["JA", "JB"])
                self.assertEqual(result["metrics"]["movable_travel_minutes"], 100)

    def test_fixed_return_after_shift_is_preserved_with_work_before_it(self):
        value = snapshot()
        fixed = deepcopy(value["jobs"][0])
        fixed.update(job_id="JF", frozen=True, freeze_reason="FIXED_RESERVATION")
        value["jobs"].append(fixed)
        frozen = assignment("JF", 3, 100, 130, 140)
        value["baseline_assignments"].append(frozen)
        value["vehicles"][0]["shift_end_at"] = at(90)
        for method in ("B2", "B3"):
            with self.subTest(method=method):
                result = self.check_result(value, method)
                self.assertEqual(next(row for row in result["assignments"] if row["job_id"] == "JF"), frozen)
                self.assertEqual(result["metrics"]["fixed_risk_count"], 1)

    def test_availability_after_every_optional_latest_return_allows_empty_route(self):
        value = snapshot()
        value["vehicles"][0].update(available_at=at(100), shift_end_at=at(120))
        value["windows"][0]["closes_at"] = at(50)
        for method in ("B2", "B3"):
            with self.subTest(method=method):
                result = self.check_result(value, method, unassigned=("J1",))
                self.assertEqual(result["assignments"], [])


if __name__ == "__main__":
    unittest.main()
