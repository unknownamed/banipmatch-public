from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.audit_evaluation_data import PROTOCOL, ROOT, audit_protocol, main
from tools.build_evaluation_inputs import build


class EvaluationDataAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        self.path = self.work / "protocol.json"
        self.protocol["cases"] = self.protocol["cases"][:1]
        for key in ("input", "before_event"):
            source = PROTOCOL.parent / self.protocol["cases"][0][key]
            destination = self.work / self.protocol["cases"][0][key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        self.write_protocol()

    def write_protocol(self):
        self.path.write_text(json.dumps(self.protocol), encoding="utf-8")

    def change_snapshot(self, key, mutate, update_hash=True):
        path = self.work / self.protocol["cases"][0][key]
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        path.write_bytes(raw)
        if update_hash:
            field = "sha256" if key == "input" else "before_event_sha256"
            self.protocol["cases"][0][field] = hashlib.sha256(raw).hexdigest()
            self.write_protocol()

    def codes(self):
        report = audit_protocol(self.path)
        self.assertFalse(report["valid"])
        return {issue["code"] for case in report["cases"] for issue in case["issues"]}

    def test_recorded_audit_matches_all_frozen_pairs(self):
        report = audit_protocol(PROTOCOL)
        recorded = json.loads((ROOT / "docs/data/evaluation-input-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(report, recorded)
        self.assertTrue(report["valid"])
        self.assertEqual((report["case_count"], report["snapshot_count"]), (10, 20))
        self.assertEqual(report["schedule_validation"], "not_run")
        self.assertTrue(all(case["declared_data_mode"] == "simulated" for case in report["cases"]))

    def test_generator_reproduces_every_before_after_pair(self):
        protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        for spec in protocol["cases"]:
            with self.subTest(case=spec["id"]):
                before, after = build(spec["profile"], spec["generation_seed"], spec["jobs"], spec["vehicles"])
                self.assertEqual(before, json.loads((PROTOCOL.parent / spec["before_event"]).read_text(encoding="utf-8")))
                self.assertEqual(after, json.loads((PROTOCOL.parent / spec["input"]).read_text(encoding="utf-8")))

    def test_before_and_after_raw_hash_mismatch_is_detected(self):
        for key, code in (("input", "INPUT_HASH_MISMATCH"), ("before_event", "BEFORE_HASH_MISMATCH")):
            with self.subTest(key=key):
                path = self.work / self.protocol["cases"][0][key]
                raw = path.read_bytes()
                path.write_bytes(raw + b" ")
                self.assertIn(code, self.codes())
                path.write_bytes(raw)

    def test_modified_readiness_is_not_presented_as_only_a_window_change(self):
        self.change_snapshot("input", lambda s: s["jobs"][0].update(ready_at="2026-11-08T00:01:00Z"))
        self.assertIn("UNRELATED_INPUT_CHANGE", self.codes())

    def test_snapshot_errors_keep_phase_and_field(self):
        self.change_snapshot("before_event", lambda s: s["jobs"][0].update(ready_at=None))
        report = audit_protocol(self.path)
        self.assertFalse(report["valid"])
        issue = next(i for i in report["cases"][0]["issues"] if i.get("phase") == "before")
        self.assertEqual((issue["code"], issue["path"]), ("INPUT_MISSING", "/jobs/0/ready_at"))

    def test_declared_old_window_must_match_original(self):
        def mutate(s):
            s["change"]["previous_closes_at"] = "2026-11-08T09:00:00Z"
        self.change_snapshot("input", mutate)
        self.assertIn("BEFORE_WINDOW_MISMATCH", self.codes())

    def test_case_count_and_id_are_checked(self):
        self.protocol["cases"][0].update(id="different", jobs=100)
        self.write_protocol()
        self.assertTrue({"CASE_ID_MISMATCH", "CASE_COUNT_MISMATCH"} <= self.codes())

    def test_case_paths_cannot_escape_frozen_bundle(self):
        self.protocol["cases"][0]["before_event"] = "../private.json"
        self.write_protocol()
        self.assertEqual(self.codes(), {"CASE_READ"})

    def test_generator_source_change_does_not_pass_a_frozen_protocol(self):
        self.protocol["generator_sha256"] = "0" * 64
        self.write_protocol()
        report = audit_protocol(self.path)
        self.assertFalse(report["generator_hash_matches_protocol"])
        self.assertFalse(report["valid"])

    def test_duplicate_cases_and_malformed_protocol_are_not_success(self):
        self.protocol["cases"].append(deepcopy(self.protocol["cases"][0]))
        self.write_protocol()
        report = audit_protocol(self.path)
        self.assertTrue(report["duplicate_case_ids"])
        self.assertFalse(report["valid"])
        self.path.write_text('{"schema_version":1,"cases":[]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            audit_protocol(self.path)

    def test_cli_preserves_existing_outputs_and_returns_failure_for_changed_pair(self):
        output = self.work / "audit.json"
        self.assertEqual(main(["--protocol", str(self.path), "--output", str(output)]), 0)
        before = output.read_bytes()
        self.assertEqual(main(["--protocol", str(self.path), "--output", str(output)]), 1)
        self.assertEqual(output.read_bytes(), before)
        self.change_snapshot("input", lambda s: s["jobs"][0].update(gross_weight_kg=25000))
        self.assertEqual(main(["--protocol", str(self.path), "--output", str(self.work / "bad.json")]), 2)
