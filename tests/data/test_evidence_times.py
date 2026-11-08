from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from backend.data import load_jobs_csv, validate_snapshot

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터"


class EvidenceTimeTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((EXAMPLES / "01_snapshot.json").read_text(encoding="utf-8"))

    def bundles(self, snapshot):
        for group in ("locations", "vehicles", "jobs", "windows", "travel_times"):
            for index, item in enumerate(snapshot[group]):
                yield f"/{group}/{index}/evidence", item["evidence"]
        yield "/change/evidence", snapshot["change"]["evidence"]

    def test_all_fact_bundles_reject_receipt_after_snapshot_at_exact_path(self):
        for index in range(len(list(self.bundles(self.snapshot)))):
            value = deepcopy(self.snapshot)
            path, evidence = list(self.bundles(value))[index]
            with self.subTest(path=path):
                evidence["received_at"] = "2026-11-07T00:01:00Z"
                before = deepcopy(value)
                report = validate_snapshot(value, source="history.json")
                self.assertIsNone(report.snapshot)
                self.assertEqual([(i.code, i.path, i.source) for i in report.issues], [
                    ("EVIDENCE_AFTER_SNAPSHOT", path + "/received_at", "history.json"),
                ])
                self.assertEqual(value, before)

    def test_receipt_before_or_at_snapshot_and_nullable_observation_are_valid(self):
        for received in ("2026-11-06T23:59:00Z", self.snapshot["as_of"]):
            with self.subTest(received=received):
                for _, evidence in self.bundles(self.snapshot):
                    evidence["received_at"] = received
                    evidence["observed_at"] = None
                report = validate_snapshot(self.snapshot)
                self.assertTrue(report.valid, report.issues)

    def test_observation_cannot_follow_receipt_even_when_both_are_historical(self):
        for index in range(len(list(self.bundles(self.snapshot)))):
            value = deepcopy(self.snapshot)
            path, evidence = list(self.bundles(value))[index]
            with self.subTest(path=path):
                evidence["received_at"] = "2026-11-06T23:58:00Z"
                evidence["observed_at"] = "2026-11-06T23:59:00Z"
                report = validate_snapshot(value)
                self.assertEqual([(i.code, i.path) for i in report.issues], [
                    ("EVIDENCE_TIME_ORDER", path + "/observed_at"),
                ])

    def test_observation_before_or_at_receipt_preserves_kind_and_source(self):
        for kind in ("observed", "simulated", "assumed", "inferred", "manual_verified"):
            for observed in ("2026-11-06T23:59:00Z", self.snapshot["as_of"]):
                with self.subTest(kind=kind, observed=observed):
                    self.snapshot["jobs"][1]["evidence"].update(kind=kind, observed_at=observed)
                    report = validate_snapshot(self.snapshot)
                    self.assertTrue(report.valid, report.issues)
                    self.assertEqual(report.snapshot["jobs"][1]["evidence"], self.snapshot["jobs"][1]["evidence"])

    def test_future_job_ready_time_is_not_a_future_observation(self):
        self.assertGreater(self.snapshot["jobs"][3]["ready_at"], self.snapshot["as_of"])
        self.assertTrue(validate_snapshot(self.snapshot).valid)

    def test_bad_evidence_format_stops_before_time_arithmetic(self):
        self.snapshot["jobs"][1]["evidence"]["received_at"] = "unknown"
        self.assertEqual({i.code for i in validate_snapshot(self.snapshot).issues}, {"SCHEMA_INVALID"})

    def test_shared_csv_evidence_and_context_have_their_own_sources(self):
        evidence = deepcopy(self.snapshot["jobs"][0]["evidence"])
        evidence["received_at"] = "2026-11-07T00:01:00Z"
        self.snapshot["vehicles"][0]["available_at"] = None
        report = load_jobs_csv(
            EXAMPLES / "jobs_template.csv", context=self.snapshot, evidence=evidence,
            context_source="context.json", evidence_source="evidence.json",
        )
        receipts = [i for i in report.issues if i.code == "EVIDENCE_AFTER_SNAPSHOT"]
        self.assertEqual(len(receipts), 4)
        self.assertTrue(all(i.source == "evidence.json" and i.row is None for i in receipts))
        issue = next(i for i in report.issues if i.path == "/vehicles/0/available_at")
        self.assertEqual((issue.source, issue.row), ("context.json", None))

    def test_csv_default_source_mapping_remains_compatible(self):
        evidence = deepcopy(self.snapshot["jobs"][0]["evidence"])
        evidence["received_at"] = "2026-11-07T00:01:00Z"
        report = load_jobs_csv(EXAMPLES / "jobs_template.csv", context=self.snapshot, evidence=evidence)
        self.assertEqual([i.row for i in report.issues], [2, 3, 4, 5])

    def test_empty_csv_job_list_error_belongs_to_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "empty-jobs.csv"
            header = (EXAMPLES / "jobs_template.csv").read_text(encoding="utf-8-sig").splitlines()[0]
            csv_path.write_text(header + "\n", encoding="utf-8")
            report = load_jobs_csv(csv_path, context=self.snapshot,
                                   evidence=self.snapshot["jobs"][0]["evidence"], context_source="context.json")
            self.assertEqual([(i.path, i.source, i.row) for i in report.issues], [
                ("/jobs", "empty-jobs.csv", None),
            ])
