from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs/development/v0.1/예제 데이터"


class PreparationCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.snapshot = json.loads((EXAMPLES / "01_snapshot.json").read_text(encoding="utf-8"))
        self.context = self.work / "context.json"
        self.evidence = self.work / "evidence.json"
        self.context.write_text(json.dumps(self.snapshot), encoding="utf-8")
        self.evidence.write_text(json.dumps(self.snapshot["jobs"][0]["evidence"]), encoding="utf-8")
        self.output = self.work / "prepared.json"
        self.report = self.work / "report.json"

    def run_cli(self, *arguments):
        result = subprocess.run(
            [sys.executable, "-m", "backend.data", *map(str, arguments)],
            cwd=ROOT, capture_output=True, encoding="utf-8", timeout=20,
        )
        self.assertFalse(result.stderr, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def csv_arguments(self):
        return ["import-jobs", EXAMPLES / "jobs_template.csv",
                "--context", self.context, "--evidence", self.evidence]

    def test_json_validation_saves_snapshot_and_deterministic_report(self):
        code, report = self.run_cli("validate-json", self.context, "--output", self.output, "--report", self.report)
        self.assertEqual(code, 0)
        self.assertTrue(report["valid"])
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), self.snapshot)
        self.assertEqual(json.loads(self.report.read_text(encoding="utf-8")), report)
        canonical = json.dumps(self.snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(report["input_sha256"], hashlib.sha256(canonical).hexdigest())
        _, second = self.run_cli("validate-json", self.context)
        self.assertEqual(report, second)

    def test_csv_import_matches_normal_snapshot(self):
        code, report = self.run_cli(*self.csv_arguments(), "--output", self.output)
        self.assertEqual(code, 0, report)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), self.snapshot)

    def test_published_invalid_examples_save_report_but_no_snapshot(self):
        for filename, expected in (("07_snapshot_입력누락.json", "INPUT_MISSING"),
                                   ("08_snapshot_미확인변경.json", "WINDOW_UNCONFIRMED")):
            with self.subTest(filename=filename):
                code, report = self.run_cli("validate-json", EXAMPLES / filename, "--output", self.output)
                self.assertEqual(code, 2)
                self.assertFalse(report["valid"])
                self.assertIsNone(report["input_sha256"])
                self.assertIn(expected, {i["code"] for i in report["issues"]})
                self.assertFalse(self.output.exists())

    def test_invalid_json_writes_diagnostic_report(self):
        self.context.write_text("{", encoding="utf-8")
        code, report = self.run_cli("validate-json", self.context, "--report", self.report)
        self.assertEqual(code, 2)
        self.assertEqual(report, json.loads(self.report.read_text(encoding="utf-8")))
        self.assertEqual(report["issues"][0]["code"], "JSON_INVALID")

    def test_csv_context_jobs_can_be_replaced_even_if_old_jobs_are_invalid(self):
        self.snapshot["jobs"][1]["ready_at"] = None
        self.context.write_text(json.dumps(self.snapshot), encoding="utf-8")
        code, report = self.run_cli(*self.csv_arguments())
        self.assertEqual(code, 0, report)

    def test_csv_context_and_evidence_parse_errors_preserve_source(self):
        self.context.write_text('{"jobs":[],"jobs":[]}', encoding="utf-8")
        self.evidence.write_bytes(b"\xff")
        code, report = self.run_cli(*self.csv_arguments())
        self.assertEqual(code, 2)
        self.assertEqual({(i["code"], i["source"]) for i in report["issues"]}, {
            ("JSON_DUPLICATE_KEY", "context.json"), ("FILE_READ", "evidence.json"),
        })

    def test_missing_inputs_are_reported_without_tracebacks(self):
        code, report = self.run_cli("validate-json", self.work / "missing.json")
        self.assertEqual(code, 2)
        self.assertEqual(report["issues"][0]["code"], "FILE_READ")

    def test_existing_output_and_report_are_never_overwritten(self):
        for flag in ("--output", "--report"):
            with self.subTest(flag=flag):
                self.output.write_text("keep", encoding="utf-8")
                code, report = self.run_cli("validate-json", self.context, flag, self.output)
                self.assertEqual(code, 1)
                self.assertEqual(report["issues"][0]["code"], "OUTPUT_PATH")
                self.assertEqual(self.output.read_text(encoding="utf-8"), "keep")

    def test_output_aliases_are_rejected_before_writing(self):
        before = self.context.read_bytes()
        for arguments in (("--output", self.context), ("--report", self.context),
                          ("--output", self.output, "--report", self.output)):
            with self.subTest(arguments=arguments):
                code, report = self.run_cli("validate-json", self.context, *arguments)
                self.assertEqual(code, 1)
                self.assertEqual(report["issues"][0]["code"], "OUTPUT_PATH")
                self.assertEqual(self.context.read_bytes(), before)
                self.assertFalse(self.output.exists())

    def test_failed_write_is_distinct_from_invalid_input(self):
        parent = self.work / "not-a-directory"
        parent.write_text("keep", encoding="utf-8")
        code, report = self.run_cli("validate-json", self.context, "--output", parent / "out.json")
        self.assertEqual(code, 1)
        self.assertEqual(report["issues"][0]["code"], "OUTPUT_WRITE")
        self.assertEqual(parent.read_text(encoding="utf-8"), "keep")

    def test_evidence_time_error_points_to_evidence_file(self):
        value = deepcopy(self.snapshot["jobs"][0]["evidence"])
        value["received_at"] = "2026-11-07T00:01:00Z"
        self.evidence.write_text(json.dumps(value), encoding="utf-8")
        code, report = self.run_cli(*self.csv_arguments(), "--output", self.output)
        self.assertEqual(code, 2)
        self.assertFalse(self.output.exists())
        self.assertEqual(len(report["issues"]), 4)
        self.assertTrue(all(i["source"] == "evidence.json" and i["row"] is None for i in report["issues"]))
