"""Data/engine regression boundaries for a vehicle's confirmed start state."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from backend.data import validate_snapshot


def after_return(minutes):
    return (datetime.fromisoformat("2026-11-07T01:00:00+00:00")
            + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def returned_vehicle(minutes, start="O"):
    path = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터/01_snapshot.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["jobs"] = snapshot["jobs"][:2]
    snapshot["baseline_assignments"] = snapshot["baseline_assignments"][:2]
    snapshot["vehicles"] = snapshot["vehicles"][:1]
    snapshot["as_of"] = after_return(minutes)
    snapshot["vehicles"][0].update(start_location_id=start, available_at=after_return(minutes))
    snapshot["windows"][0]["closes_at"] = after_return(120)
    return snapshot


class VehicleAvailabilityTests(unittest.TestCase):
    def test_sufficient_reposition_time_accepts_confirmed_start_without_mutation(self):
        for elapsed in (10, 60):
            with self.subTest(elapsed=elapsed):
                snapshot = returned_vehicle(elapsed)
                original = deepcopy(snapshot)
                report = validate_snapshot(snapshot)
                self.assertTrue(report.valid, report.issues)
                self.assertEqual(snapshot, original)
                self.assertEqual(report.snapshot["baseline_assignments"], original["baseline_assignments"])

    def test_later_as_of_does_not_repair_insufficient_available_at(self):
        for elapsed in (0, 5):
            with self.subTest(elapsed=elapsed):
                snapshot = returned_vehicle(20)
                snapshot["vehicles"][0]["available_at"] = after_return(elapsed)
                report = validate_snapshot(snapshot)
                self.assertIsNone(report.snapshot)
                self.assertIn(("FIXED_AVAILABILITY_CONFLICT", "/jobs/0"),
                              {(i.code, i.path) for i in report.issues})

    def test_future_return_cannot_claim_a_different_start_location(self):
        snapshot = returned_vehicle(10)
        snapshot["as_of"] = "2026-11-07T00:00:00Z"
        report = validate_snapshot(snapshot)
        self.assertIn("FIXED_AVAILABILITY_CONFLICT", {i.code for i in report.issues})
        self.assertIsNone(report.snapshot)

    def test_missing_reposition_direction_is_not_replaced_by_reverse_leg(self):
        snapshot = returned_vehicle(10)
        # Only the departed job remains: this tests repositioning itself, not
        # the data module's conservative approach matrix for movable jobs.
        snapshot["jobs"] = snapshot["jobs"][:1]
        snapshot["baseline_assignments"] = snapshot["baseline_assignments"][:1]
        snapshot["travel_times"] = [
            row for row in snapshot["travel_times"]
            if (row["from_location_id"], row["to_location_id"]) != ("D", "O")
        ]
        report = validate_snapshot(snapshot)
        self.assertIn(("TRAVEL_TIME_MISSING", "/jobs/0"),
                      {(i.code, i.path) for i in report.issues})
        self.assertIsNone(report.snapshot)

    def test_same_return_location_remains_valid(self):
        report = validate_snapshot(returned_vehicle(0, start="D"))
        self.assertTrue(report.valid, report.issues)

    def test_final_departed_sequence_defines_start_location_not_each_old_return(self):
        snapshot = returned_vehicle(90, start="D")
        snapshot["jobs"][0]["return_location_id"] = "O"
        snapshot["baseline_assignments"][0]["return_at"] = after_return(20)
        snapshot["jobs"][1].update(state="departed", frozen=True, freeze_reason="ALREADY_DEPARTED")
        snapshot["baseline_assignments"][1].update(
            pickup_departure_at=after_return(20), gate_arrival_at=after_return(50),
            return_at=after_return(90),
        )
        # Sequence is authoritative even when the input arrays arrive reversed.
        snapshot["jobs"].reverse()
        snapshot["baseline_assignments"].reverse()
        report = validate_snapshot(snapshot)
        self.assertTrue(report.valid, report.issues)


if __name__ == "__main__":
    unittest.main()
