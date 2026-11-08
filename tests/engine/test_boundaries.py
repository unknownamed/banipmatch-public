"""Constraint and local CLI boundary cases, separate from the happy-path fixture."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from backend.engine import solve
from backend.engine.__main__ import main

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "docs/development/v0.1"
INPUT = DRAFT / "예제 데이터/01_snapshot.json"


def fixture():
    return json.loads(INPUT.read_text(encoding="utf-8"))


class BoundaryTests(unittest.TestCase):
    def test_unused_unassigned_return_location_is_not_required_approach(self):
        snapshot = fixture()
        for vehicle in snapshot["vehicles"]:
            vehicle["available_at"] = "2026-11-07T03:00:00Z"
        extra = copy.deepcopy(snapshot["locations"][0])
        extra.update(location_id="X", name="미처리 작업의 모의 복귀지")
        snapshot["locations"].append(extra)
        snapshot["jobs"][3]["return_location_id"] = "X"
        leg = copy.deepcopy(snapshot["travel_times"][2])
        leg["to_location_id"] = "X"
        snapshot["travel_times"].append(leg)
        result = solve(snapshot, "B1")
        self.assertEqual(result["solution_status"], "HEURISTIC")
        self.assertFalse(any(i["code"] == "INPUT_MISSING" for i in result["issues"]))
        self.assertEqual(set(result["unassigned_job_ids"]), {"J1", "J2", "J3"})

    def test_equipment_and_capacity_prevent_assignment_with_specific_reason(self):
        for field, value, code in [("equipment_types", ["DRY20"], "INCOMPATIBLE_EQUIPMENT"),
                                   ("capacity_kg", 10000, "CAPACITY_EXCEEDED")]:
            with self.subTest(field=field):
                snapshot = fixture()
                for v in snapshot["vehicles"]:
                    v[field] = value
                result = solve(snapshot, "B1")
                self.assertEqual([a["job_id"] for a in result["assignments"]], ["J0"])
                self.assertTrue(any(i["job_id"] == "J1" and i["code"] == code for i in result["issues"]))
                self.assertGreater(result["metrics"]["fixed_risk_count"], 0)

    def test_opening_time_delays_departure_instead_of_waiting_at_gate(self):
        snapshot = fixture()
        snapshot["windows"][0]["opens_at"] = "2026-11-07T01:00:00Z"
        result = solve(snapshot, "B1")
        adjusted = next(a for a in result["assignments"] if a["job_id"] == "J1")
        self.assertEqual(adjusted["gate_arrival_at"], "2026-11-07T01:00:00Z")
        self.assertEqual(adjusted["pickup_departure_at"], "2026-11-07T00:30:00Z")
        self.assertEqual(result["metrics"]["movable_violation_count"], 0)

    def test_shift_end_blocks_new_work_without_claiming_global_infeasibility(self):
        snapshot = fixture()
        for v in snapshot["vehicles"]:
            v["shift_end_at"] = "2026-11-07T00:50:00Z"
        result = solve(snapshot, "B1")
        self.assertEqual([a["job_id"] for a in result["assignments"]], ["J0"])
        j1 = next(i for i in result["issues"] if i["job_id"] == "J1")
        self.assertEqual(j1["code"], "SEARCH_LIMIT")
        self.assertEqual(j1["proof_level"], "not_proven")
        self.assertFalse(result["objective_proven"])

    def test_cooperative_timeout_retains_fixed_work_and_reports_limit(self):
        with patch("backend.engine.solver.monotonic", side_effect=[0, 2, 2]):
            result = solve(fixture(), "B1", {"seed": 0, "time_limit_seconds": 1})
        self.assertEqual([a["job_id"] for a in result["assignments"]], ["J0"])
        self.assertTrue(result["execution_metadata"]["solver_settings"]["time_limit_reached"])
        self.assertEqual(set(result["unassigned_job_ids"]), {"J1", "J2", "J3"})
        self.assertTrue(any(i["code"] == "SEARCH_LIMIT" for i in result["issues"]))
        self.assertFalse(result["approval_eligible"])

    def test_local_cli_serializes_results_against_common_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "results.json"
            with patch("sys.argv", ["engine", "--snapshot", str(INPUT), "--output", str(output)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
        schema = json.loads((DRAFT / "공통 규격/contracts.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/Results"},
                                          format_checker=FormatChecker())
        self.assertEqual(list(validator.iter_errors(result)), [])
        self.assertEqual([r["method"] for r in result["results"]], ["B0", "B1", "B2", "B3"])
        self.assertTrue(all(r["result_origin"] == "computed" for r in result["results"]))

    def test_cli_input_rejection_does_not_write_a_result_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = fixture()
            snapshot["change"]["verification"] = "unconfirmed"
            input_path, output = Path(temporary) / "input.json", Path(temporary) / "results.json"
            input_path.write_text(json.dumps(snapshot), encoding="utf-8")
            error = io.StringIO()
            with patch("sys.argv", ["engine", "--snapshot", str(input_path), "--output", str(output)]):
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(), 2)
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(error.getvalue())["category"], "incomplete")


if __name__ == "__main__":
    unittest.main()
