from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_data_evidence import AUDIT_INPUTS, ROOT, audit_snapshot, build_audit, main
from tools.build_engine_benchmarks import build

COMMON = ROOT / "docs/development/v0.1/예제 데이터/01_snapshot.json"


class EvidenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)

    def test_normal_input_counts_declarations_without_verifying_them(self):
        report = build_audit([COMMON])
        entry = report["snapshots"][0]
        self.assertEqual((report["snapshot_count"], report["valid_snapshot_count"]), (1, 1))
        self.assertEqual(report["external_permissions"], "not_assessed")
        self.assertEqual(report["representativeness"], "not_assessed")
        self.assertEqual(entry["counts"]["jobs"], 4)
        self.assertEqual(entry["counts"]["vehicles"], 2)
        self.assertEqual(sum(entry["declared_evidence_kinds"].values()), entry["fact_bundle_count"])
        self.assertEqual(entry["observed_at_null_count"], entry["fact_bundle_count"])
        self.assertEqual((entry["job_conditions"]["departed_count"], entry["job_conditions"]["frozen_count"]), (1, 1))
        self.assertEqual(entry["job_conditions"]["gross_weight_kg"], {"known": 4, "null": 0, "min": 24000, "max": 24000})

    def test_recorded_report_matches_current_inputs_and_validation_source(self):
        recorded = json.loads((ROOT / "docs/data/input-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(build_audit(list(AUDIT_INPUTS)), recorded)

    def test_input_order_and_duplicate_paths_do_not_change_report(self):
        files = sorted(AUDIT_INPUTS[0].glob("*.json"))
        self.assertEqual(build_audit(files), build_audit(list(reversed(files)) + files))

    def test_invalid_input_is_not_counted_as_a_valid_data_sample(self):
        missing = COMMON.with_name("07_snapshot_입력누락.json")
        report = build_audit([COMMON, missing])
        self.assertEqual(report["valid_snapshot_count"], 1)
        invalid = next(entry for entry in report["snapshots"] if not entry["valid"])
        self.assertIsNone(invalid["input_sha256"])
        self.assertIn("INPUT_MISSING", {issue["code"] for issue in invalid["issues"]})
        self.assertNotIn("counts", invalid)

    def test_outside_path_is_portable_and_original_is_not_modified(self):
        path = self.work / "permitted.json"
        before = COMMON.read_bytes()
        path.write_bytes(before)
        entry = audit_snapshot(path)
        self.assertEqual(entry["path"], "permitted.json")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(entry["input_sha256"], audit_snapshot(COMMON)["input_sha256"])

    def test_hash_changes_with_assumed_buffer_not_formatting(self):
        path = self.work / "input.json"
        snapshot = json.loads(COMMON.read_text(encoding="utf-8"))
        path.write_text(json.dumps(snapshot, indent=4), encoding="utf-8")
        before = audit_snapshot(path)["input_sha256"]
        self.assertEqual(before, audit_snapshot(COMMON)["input_sha256"])
        changed = deepcopy(snapshot)
        changed["policy"]["buffer_minutes"] += 1
        path.write_text(json.dumps(changed), encoding="utf-8")
        self.assertNotEqual(before, audit_snapshot(path)["input_sha256"])

    def test_archived_mixed_inputs_match_existing_generator(self):
        for fixed, name in ((False, "mixed_12.json"), (True, "mixed_fixed_12.json")):
            with self.subTest(name=name):
                archived = json.loads((AUDIT_INPUTS[1] / name).read_text(encoding="utf-8"))
                self.assertEqual(build(fixed), archived)

    def test_cli_never_overwrites_output_and_marks_rejected_inputs(self):
        output = self.work / "report.json"
        self.assertEqual(main(["--inputs", str(COMMON), "--output", str(output)]), 0)
        before = output.read_bytes()
        self.assertEqual(main(["--inputs", str(COMMON), "--output", str(output)]), 1)
        self.assertEqual(output.read_bytes(), before)
        invalid = self.work / "rejected.json"
        self.assertEqual(main(["--inputs", str(COMMON.with_name("08_snapshot_미확인변경.json")), "--output", str(invalid)]), 2)

    def test_empty_input_directory_is_explicit_error(self):
        with self.assertRaises(ValueError):
            build_audit([self.work])
        with self.assertRaises(ValueError):
            build_audit([])
