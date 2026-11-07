from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from backend.data import load_jobs_csv, load_snapshot_json, validate_snapshot

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터"


class DataInputTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((EXAMPLES / "01_snapshot.json").read_text(encoding="utf-8"))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.csv_path = Path(self.directory.name) / "jobs.csv"
        self.evidence = deepcopy(self.snapshot["jobs"][0]["evidence"])

    def codes(self, report):
        return {issue.code for issue in report.issues}

    def write_csv(self, mutate=None):
        with (EXAMPLES / "jobs_template.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        if mutate:
            mutate(rows)
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerows(rows)

    def test_normal_snapshot_is_independent_and_not_a_feasibility_check(self):
        before = deepcopy(self.snapshot)
        report = validate_snapshot(self.snapshot)
        self.assertTrue(report.valid, report.issues)
        self.assertEqual(self.snapshot, before)
        report.snapshot["jobs"][0]["state"] = "planned"
        self.assertEqual(self.snapshot, before)
        # J3의 준비 지연과 원안 마감 위반은 엔진이 다룰 정상 입력이다.
        self.assertTrue(load_snapshot_json(EXAMPLES / "01_snapshot.json").valid)

    def test_published_incomplete_and_unconfirmed_examples_block_input(self):
        for filename, code in (("07_snapshot_입력누락.json", "INPUT_MISSING"),
                               ("08_snapshot_미확인변경.json", "WINDOW_UNCONFIRMED")):
            with self.subTest(filename=filename):
                report = load_snapshot_json(EXAMPLES / filename)
                self.assertIn(code, self.codes(report))
                self.assertIsNone(report.snapshot)

    def test_structurally_bad_inputs_return_issues_instead_of_crashing(self):
        for value in (None, [], {}, {"jobs": [None]}):
            with self.subTest(value=value):
                self.assertEqual(self.codes(validate_snapshot(value)), {"SCHEMA_INVALID"})

    def test_schema_rejects_bad_units_types_extra_fields_and_timezones(self):
        changes = (("gross_weight_kg", -1), ("service_minutes", -1),
                   ("service_minutes", 1.5), ("frozen", "False"),
                   ("ready_at", "2026-11-07T09:00:00+09:00"),
                   ("ready_at", "not-a-time"), ("unexpected", "ignored?"))
        for field, value in changes:
            with self.subTest(field=field, value=value):
                snapshot = deepcopy(self.snapshot)
                snapshot["jobs"][1][field] = value
                self.assertIn("SCHEMA_INVALID", self.codes(validate_snapshot(snapshot)))

    def test_non_minute_time_is_not_rounded(self):
        for value in ("2026-11-07T00:00:01Z", "2026-11-07T00:00:00.000000001Z"):
            with self.subTest(value=value):
                self.snapshot["jobs"][1]["ready_at"] = value
                self.assertIn("TIME_PRECISION", self.codes(validate_snapshot(self.snapshot)))

    def test_duplicate_job_reports_second_occurrence(self):
        self.snapshot["jobs"][1]["job_id"] = "J0"
        issue = next(i for i in validate_snapshot(self.snapshot).issues if i.code == "DUPLICATE_ID")
        self.assertEqual(issue.path, "/jobs/1/job_id")

    def test_reference_errors_are_reported_without_lookup_exceptions(self):
        self.snapshot["jobs"][1]["origin_id"] = "MISSING"
        self.snapshot["baseline_assignments"][1]["vehicle_id"] = "MISSING"
        self.snapshot["change"]["new_window_id"] = "MISSING"
        codes = self.codes(validate_snapshot(self.snapshot))
        self.assertTrue({"UNKNOWN_LOCATION", "UNKNOWN_VEHICLE", "CHANGE_TARGET"} <= codes)

    def test_window_order_duplicate_and_confirmation(self):
        mutations = (
            (lambda s: s["windows"][0].update(opens_at="2026-11-08T00:00:00Z"), "WINDOW_ORDER"),
            (lambda s: s["windows"].append(deepcopy(s["windows"][0])), "DUPLICATE_WINDOW"),
            (lambda s: s["change"].update(confirmed_by=" "), "CONFIRMATION_MISSING"),
            (lambda s: s["windows"][0].update(confirmed_at=None), "CONFIRMATION_MISSING"),
            (lambda s: s["jobs"][1].update(voyage_id="MISSING"), "UNKNOWN_WINDOW"),
        )
        for mutate, code in mutations:
            with self.subTest(code=code):
                snapshot = deepcopy(self.snapshot)
                mutate(snapshot)
                self.assertIn(code, self.codes(validate_snapshot(snapshot)))

    def test_baseline_partition_and_sequences(self):
        self.snapshot["baseline_unassigned_job_ids"] = ["J1"]
        self.snapshot["baseline_assignments"][1]["sequence"] = 1
        codes = self.codes(validate_snapshot(self.snapshot))
        self.assertTrue({"BASELINE_COVERAGE", "DUPLICATE_SEQUENCE"} <= codes)

    def test_departed_job_cannot_be_made_movable(self):
        self.snapshot["jobs"][0]["frozen"] = False
        self.assertIn("DEPARTED_MUST_FREEZE", self.codes(validate_snapshot(self.snapshot)))

    def test_fixed_job_requires_reason_and_assignment(self):
        self.snapshot["jobs"][0]["freeze_reason"] = None
        self.snapshot["baseline_assignments"].pop(0)
        self.snapshot["baseline_unassigned_job_ids"] = ["J0"]
        codes = self.codes(validate_snapshot(self.snapshot))
        self.assertTrue({"FREEZE_REASON_MISSING", "FROZEN_UNASSIGNED"} <= codes)

    def test_fixed_return_and_vehicle_availability_are_not_invented(self):
        for mutate, code in (
            (lambda s: s["baseline_assignments"][0].update(return_at=None), "INPUT_MISSING"),
            (lambda s: s["vehicles"][0].update(available_at=None), "INPUT_MISSING"),
            (lambda s: s["vehicles"][0].update(available_at=s["as_of"]), "FIXED_AVAILABILITY_CONFLICT"),
        ):
            with self.subTest(code=code):
                snapshot = deepcopy(self.snapshot)
                mutate(snapshot)
                report = validate_snapshot(snapshot)
                self.assertIn(code, self.codes(report))
                self.assertIsNone(report.snapshot)

    def test_directional_missing_route_is_not_zero_or_reverse(self):
        self.snapshot["travel_times"] = [
            route for route in self.snapshot["travel_times"]
            if (route["from_location_id"], route["to_location_id"]) != ("O", "HJNC")
        ]
        self.assertIn("TRAVEL_TIME_MISSING", self.codes(validate_snapshot(self.snapshot)))

    def test_duplicate_route_is_rejected(self):
        self.snapshot["travel_times"].append(deepcopy(self.snapshot["travel_times"][0]))
        self.assertIn("DUPLICATE_ROUTE", self.codes(validate_snapshot(self.snapshot)))

    def test_csv_template_round_trip_preserves_context_and_evidence(self):
        self.assertTrue(load_jobs_csv(
            EXAMPLES / "jobs_template.csv", context=self.snapshot, evidence=self.evidence,
        ).valid)
        self.write_csv()
        before = deepcopy(self.snapshot)
        report = load_jobs_csv(self.csv_path, context=self.snapshot, evidence=self.evidence)
        self.assertTrue(report.valid, report.issues)
        self.assertEqual(report.snapshot, before)
        self.assertEqual(self.snapshot, before)
        self.assertEqual(report.snapshot["jobs"][1]["frozen"], False)
        self.assertIsNone(report.snapshot["jobs"][1]["freeze_reason"])

    def test_csv_missing_values_preserve_null_and_report_row(self):
        self.write_csv(lambda rows: rows[2].__setitem__(5, ""))
        report = load_jobs_csv(self.csv_path, context=self.snapshot, evidence=self.evidence)
        issue = next(i for i in report.issues if i.code == "INPUT_MISSING")
        self.assertEqual((issue.row, issue.source, issue.path), (3, "jobs.csv", "/jobs/1/ready_at"))
        self.assertIsNone(report.snapshot)

    def test_csv_bad_bool_and_integer_report_both_rows(self):
        def mutate(rows):
            rows[2][10] = "yes"
            rows[3][6] = "24.5"
        self.write_csv(mutate)
        report = load_jobs_csv(self.csv_path, context=self.snapshot, evidence=self.evidence)
        self.assertEqual({(i.code, i.row) for i in report.issues}, {("CSV_BOOLEAN", 3), ("CSV_INTEGER", 4)})

    def test_csv_rejects_duplicate_missing_and_extra_columns(self):
        for mutate in (
            lambda rows: rows[0].__setitem__(0, "voyage_id"),
            lambda rows: rows[0].pop(),
            lambda rows: rows[0].append("extra"),
            lambda rows: rows[1].append("extra"),
        ):
            with self.subTest(mutate=mutate):
                self.write_csv(mutate)
                report = load_jobs_csv(self.csv_path, context=self.snapshot, evidence=self.evidence)
                self.assertFalse(report.valid)
                self.assertTrue(self.codes(report) & {"CSV_HEADER", "CSV_COLUMNS"})

    def test_csv_context_errors_are_not_attributed_to_csv(self):
        self.write_csv()
        self.snapshot["vehicles"][0]["available_at"] = None
        report = load_jobs_csv(self.csv_path, context=self.snapshot, evidence=self.evidence)
        issue = next(i for i in report.issues if i.path == "/vehicles/0/available_at")
        self.assertIsNone(issue.source)
        self.assertIsNone(issue.row)

    def test_csv_requires_explicit_evidence(self):
        self.write_csv()
        report = load_jobs_csv(self.csv_path, context=self.snapshot, evidence={})
        self.assertEqual(self.codes(report), {"EVIDENCE_INVALID"})

    def test_csv_schema_error_maps_to_source_row(self):
        self.write_csv(lambda rows: rows[2].__setitem__(8, "-1"))
        report = load_jobs_csv(self.csv_path, context=self.snapshot, evidence=self.evidence)
        self.assertEqual(report.issues[0].row, 3)
        self.assertEqual(self.codes(report), {"SCHEMA_INVALID"})

    def test_csv_empty_and_malformed_files_are_rejected(self):
        self.csv_path.write_text("", encoding="utf-8")
        self.assertEqual(self.codes(load_jobs_csv(
            self.csv_path, context=self.snapshot, evidence=self.evidence,
        )), {"CSV_HEADER"})
        self.write_csv()
        with self.csv_path.open("a", encoding="utf-8") as stream:
            stream.write('"unterminated')
        self.assertEqual(self.codes(load_jobs_csv(
            self.csv_path, context=self.snapshot, evidence=self.evidence,
        )), {"CSV_INVALID"})

    def test_json_syntax_duplicate_keys_and_unreadable_files(self):
        path = Path(self.directory.name) / "snapshot.json"
        for text, code in (("{", "JSON_INVALID"), ('{"jobs":[],"jobs":[]}', "JSON_DUPLICATE_KEY")):
            with self.subTest(code=code):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(self.codes(load_snapshot_json(path)), {code})
        path.write_bytes(b"\xff")
        self.assertEqual(self.codes(load_snapshot_json(path)), {"FILE_READ"})
        path.write_text('{"value":' + '9' * 5000 + '}', encoding="utf-8")
        self.assertEqual(self.codes(load_snapshot_json(path)), {"JSON_INVALID"})
        self.assertEqual(self.codes(load_snapshot_json(path.with_name("missing.json"))), {"FILE_READ"})

    def test_non_finite_json_numbers_are_rejected(self):
        self.snapshot["locations"][0]["latitude"] = float("nan")
        self.assertIn("JSON_NUMBER_INVALID", self.codes(validate_snapshot(self.snapshot)))
        path = Path(self.directory.name) / "snapshot.json"
        path.write_text(json.dumps(self.snapshot), encoding="utf-8")
        self.assertIn("JSON_NUMBER_INVALID", self.codes(load_snapshot_json(path)))

    def test_csv_oversized_integer_returns_issue(self):
        self.write_csv(lambda rows: rows[2].__setitem__(6, "9" * 5000))
        self.assertIn("CSV_INTEGER", self.codes(load_jobs_csv(
            self.csv_path, context=self.snapshot, evidence=self.evidence,
        )))


if __name__ == "__main__":
    unittest.main()
