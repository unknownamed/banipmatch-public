"""Snapshot time relationships use replay time, never the server clock."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from backend.data import load_jobs_csv, validate_snapshot
from backend.engine.context import EngineInputError, validate_shape

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터"


class SnapshotTimeTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((EXAMPLES / "01_snapshot.json").read_text(encoding="utf-8"))

    def offset(self, minutes):
        value = datetime.fromisoformat(self.snapshot["as_of"].replace("Z", "+00:00"))
        return (value + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_confirmation_after_snapshot_is_rejected_at_exact_path(self):
        for path in ["/change", *[f"/windows/{i}" for i in range(len(self.snapshot["windows"]))]]:
            with self.subTest(path=path):
                value = deepcopy(self.snapshot)
                item = value["change"] if path == "/change" else value["windows"][int(path.split("/")[-1])]
                item["confirmed_at"] = self.offset(1)
                before = deepcopy(value)
                report = validate_snapshot(value, source="replay.json")
                self.assertIsNone(report.snapshot)
                self.assertEqual([(e.code, e.path, e.source, e.row) for e in report.issues],
                                 [("CONFIRMATION_AFTER_SNAPSHOT", path + "/confirmed_at", "replay.json", None)])
                self.assertEqual(value, before)

    def test_confirmation_before_or_at_snapshot_is_valid(self):
        for minutes in (-1, 0):
            with self.subTest(minutes=minutes):
                value = deepcopy(self.snapshot)
                for item in [value["change"], *value["windows"]]:
                    item["confirmed_at"] = self.offset(minutes)
                report = validate_snapshot(value)
                self.assertTrue(report.valid, report.issues)

    def test_expired_validity_is_rejected_without_changing_input(self):
        self.snapshot["policy"]["input_valid_until"] = self.offset(-1)
        before = deepcopy(self.snapshot)
        report = validate_snapshot(self.snapshot, source="replay.json")
        self.assertIsNone(report.snapshot)
        self.assertEqual([(e.code, e.path) for e in report.issues],
                         [("INPUT_EXPIRED_AT_SNAPSHOT", "/policy/input_valid_until")])
        self.assertEqual(self.snapshot, before)

    def test_validity_at_or_after_snapshot_is_valid(self):
        for minutes in (0, 1):
            with self.subTest(minutes=minutes):
                self.snapshot["policy"]["input_valid_until"] = self.offset(minutes)
                report = validate_snapshot(self.snapshot)
                self.assertTrue(report.valid, report.issues)

    def test_coherent_historical_replay_is_not_compared_with_wall_clock(self):
        def shift(node):
            if isinstance(node, dict):
                return {key: shift(value) for key, value in node.items()}
            if isinstance(node, list):
                return [shift(value) for value in node]
            if isinstance(node, str) and node.startswith("2026-") and node.endswith("Z"):
                return "2020" + node[4:]
            return node
        report = validate_snapshot(shift(self.snapshot))
        self.assertTrue(report.valid, report.issues)

    def test_bad_time_stops_at_schema_check(self):
        for item, key in ((self.snapshot["change"], "confirmed_at"),
                          (self.snapshot["policy"], "input_valid_until")):
            original = item[key]
            item[key] = "invalid-time"
            report = validate_snapshot(self.snapshot)
            self.assertFalse(report.valid)
            self.assertEqual({e.code for e in report.issues}, {"SCHEMA_INVALID"})
            item[key] = original

    def test_csv_context_time_errors_have_no_fake_csv_row(self):
        self.snapshot["change"]["confirmed_at"] = self.offset(1)
        self.snapshot["policy"]["input_valid_until"] = self.offset(-1)
        report = load_jobs_csv(EXAMPLES / "jobs_template.csv", context=self.snapshot,
                               evidence=self.snapshot["jobs"][0]["evidence"])
        self.assertIsNone(report.snapshot)
        self.assertEqual({e.path for e in report.issues},
                         {"/change/confirmed_at", "/policy/input_valid_until"})
        self.assertTrue(all(e.row is None and e.source is None for e in report.issues))

    def test_metadata_precision_is_consistent_with_engine(self):
        for field in ("confirmed_at", "observed_at", "received_at"):
            for suffix in ("30Z", "00.000000001Z"):
                with self.subTest(field=field, suffix=suffix):
                    value = deepcopy(self.snapshot)
                    item = value["change"] if field == "confirmed_at" else value["change"]["evidence"]
                    item[field] = "2026-11-06T23:59:" + suffix
                    path = "/change/" + ("" if field == "confirmed_at" else "evidence/") + field
                    report = validate_snapshot(value)
                    self.assertIn(("TIME_PRECISION", path), [(e.code, e.path) for e in report.issues])
                    with self.assertRaises(EngineInputError):
                        validate_shape(value, {"seed": 0, "time_limit_seconds": 5})

    def test_zero_fraction_and_null_observation_remain_valid(self):
        self.snapshot["change"]["confirmed_at"] = self.snapshot["as_of"][:-1] + ".000000000Z"
        self.snapshot["change"]["evidence"]["observed_at"] = None
        report = validate_snapshot(self.snapshot)
        self.assertTrue(report.valid, report.issues)
        validate_shape(self.snapshot, {"seed": 0, "time_limit_seconds": 5})
