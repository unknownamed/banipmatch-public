"""Synthetic observations only; no captured provider response is imported."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.compare_hjnc_observations import compare_observations


PREVIOUS = "2026-11-09T01:00:00Z"
CURRENT = "2026-11-09T02:00:00Z"


def row(identifier="SYNTHETIC-VOYAGE"):
    return {"VOY_NO": identifier, "YARD_OPEN": "2026-11-10 00:00",
            "YARD_CLOSE": "2026-11-13 01:00", "ETB": "2026-11-13 11:00"}


def raw(rows=None, **extra):
    return json.dumps({"stringContent": json.dumps([row()] if rows is None else rows),
                       "totalElements": 999, "hasNext": False, **extra}).encode()


def test_identical_raw_with_later_receipt_is_an_unchanged_new_observation():
    source = raw()
    report = compare_observations(source, CURRENT, source, PREVIOUS)
    assert report["report_version"] == 1
    assert report["same_raw_sha256"] is True
    assert report["comparison_status"] == "no_window_difference_observed"
    assert report["unchanged_window_count"] == report["common_voyage_count"] == 1
    assert report["current"]["received_at"] == CURRENT
    assert report["previous"]["received_at"] == PREVIOUS
    assert report["current"]["sha256"] == hashlib.sha256(source).hexdigest()
    assert report["current"]["source_time_zone"] == "unconfirmed"
    assert report["current"]["expected_source_ref"] == "https://www.hjnc.co.kr/esvc/vessel/berthScheduleT"
    assert report["current"]["capture_provenance"] == "caller_supplied_unverified_capture_and_receipt"
    assert report["current"]["page_coverage"] == "not_established"
    assert report["current"]["reported_total_matches_rows"] is False
    assert report["provider_change_occurred_at"] is None


def test_single_response_is_explicitly_not_comparable():
    report = compare_observations(raw(), CURRENT)
    assert report["comparison_status"] == "not_comparable_single_observation"
    assert report["previous"] is None
    assert report["common_voyage_count"] is None
    assert report["unchanged_window_count"] is None
    assert report["window_observation_differences"] == []


@pytest.mark.parametrize("earlier", [CURRENT, "2026-11-09T03:00:00Z"])
def test_receipt_order_must_be_strict(earlier):
    with pytest.raises(ValueError):
        compare_observations(raw(), CURRENT, raw(), earlier)


@pytest.mark.parametrize("timestamp", ["2026-11-09 02:00:00", "2026-11-09T02:00:00+00:00",
                                       "2026-11-09T02:00:00+09:00", "2026-02-30T00:00:00Z"])
def test_explicit_valid_utc_receipt_required(timestamp):
    with pytest.raises(ValueError):
        compare_observations(raw(), timestamp)


def test_previous_file_and_receipt_are_a_pair():
    with pytest.raises(ValueError):
        compare_observations(raw(), CURRENT, raw())
    with pytest.raises(ValueError):
        compare_observations(raw(), CURRENT, previous_received_at=PREVIOUS)


@pytest.mark.parametrize("field", ["VOY_NO", "YARD_OPEN", "YARD_CLOSE", "ETB"])
@pytest.mark.parametrize("value", [None, "", " "])
def test_missing_or_blank_required_fields_rejected(field, value):
    item = row()
    if value is None:
        del item[field]
    else:
        item[field] = value
    with pytest.raises(ValueError):
        compare_observations(raw([item]), CURRENT)


def test_duplicate_identifiers_and_bad_source_dates_rejected():
    with pytest.raises(ValueError):
        compare_observations(raw([row(), row()]), CURRENT)
    for field in ("YARD_OPEN", "YARD_CLOSE", "ETB"):
        item = row()
        item[field] = "2026-02-30 10:00"
        with pytest.raises(ValueError):
            compare_observations(raw([item]), CURRENT)


@pytest.mark.parametrize("identifier", [" SYNTHETIC-VOYAGE", "SYNTHETIC-VOYAGE "])
def test_identifier_whitespace_is_rejected_instead_of_silently_normalized(identifier):
    with pytest.raises(ValueError):
        compare_observations(raw([row(identifier)]), CURRENT)


def test_etb_only_change_never_becomes_a_window_change():
    after = row()
    after["ETB"] = "2026-11-13 15:00"
    report = compare_observations(raw([after]), CURRENT, raw(), PREVIOUS)
    assert report["comparison_status"] == "no_window_difference_observed"
    assert report["window_observation_differences"] == []
    assert len(report["etb_observation_differences"]) == 1
    assert report["etb_observation_differences"][0]["classification"].endswith("not_window_change")


def test_both_window_fields_are_preserved_as_naive_observation_differences():
    after = row()
    after.update(YARD_OPEN="2026-11-11 00:00", YARD_CLOSE="2026-11-14 01:00")
    report = compare_observations(raw([after]), CURRENT, raw(), PREVIOUS)
    assert report["comparison_status"] == "window_observation_differences_found"
    change, = report["window_observation_differences"]
    assert change["fields"] == {field: {"previous_naive": row()[field], "current_naive": after[field]}
                                for field in ("YARD_OPEN", "YARD_CLOSE")}
    assert change["voyage_key_sha256"] == hashlib.sha256(row()["VOY_NO"].encode()).hexdigest()
    assert change["provider_change_occurred_at"] is None
    assert report["etb_observation_differences"] == []


def test_added_missing_and_empty_pages_do_not_claim_cancellation_or_coverage():
    report = compare_observations(raw([row("NEW")]), CURRENT, raw([row("OLD")]), PREVIOUS)
    assert report["common_voyage_count"] == 0
    assert report["comparison_status"] == "not_comparable_no_common_voyage"
    assert len(report["added_observations"]) == len(report["not_observed_in_current"]) == 1
    assert report["not_observed_in_current"][0]["classification"] == "not_observed_not_evidence_of_cancellation"
    empty = compare_observations(raw([]), CURRENT, raw(), PREVIOUS)
    assert len(empty["not_observed_in_current"]) == 1
    assert empty["comparison_status"] == "not_comparable_no_common_voyage"
    assert empty["current"]["page_coverage"] == "not_established"
    for current, previous in ((raw(), raw([])), (raw([]), raw([]))):
        report = compare_observations(current, CURRENT, previous, PREVIOUS)
        assert report["comparison_status"] == "not_comparable_no_common_voyage"
        assert report["common_voyage_count"] == 0


def test_report_excludes_raw_identifiers_secrets_and_unrelated_fields():
    item = row()
    item["secret"] = "ROW-SECRET"
    after = deepcopy(item)
    after["YARD_CLOSE"] = "2026-11-14 01:00"
    report = compare_observations(raw([after], token="ENVELOPE-SECRET"), CURRENT,
                                  raw([item]), PREVIOUS)
    text = json.dumps(report)
    for value in ("SYNTHETIC-VOYAGE", "ROW-SECRET", "ENVELOPE-SECRET"):
        assert value not in text


def test_cli_does_not_overwrite_inputs_or_outputs_or_print_raw_identifiers(tmp_path):
    current, previous, output = [tmp_path / name for name in ("current.json", "previous.json", "report.json")]
    current.write_bytes(raw(token="ENVELOPE-SECRET"))
    previous.write_bytes(raw())
    script = Path(__file__).resolve().parents[2] / "tools/compare_hjnc_observations.py"
    command = [sys.executable, str(script), "--current", str(current), "--current-received-at", CURRENT,
               "--previous", str(previous), "--previous-received-at", PREVIOUS, "--output"]
    result = subprocess.run(command + [str(output)], capture_output=True)
    assert result.returncode == 0
    saved = output.read_bytes()
    again = subprocess.run(command + [str(output)], capture_output=True)
    assert again.returncode == 1
    assert output.read_bytes() == saved
    for target in (current, previous):
        before = target.read_bytes()
        same = subprocess.run(command + [str(target)], capture_output=True)
        assert same.returncode == 2
        assert target.read_bytes() == before
        assert b"SYNTHETIC-VOYAGE" not in same.stdout + same.stderr
    for token in (b"SYNTHETIC-VOYAGE", b"ENVELOPE-SECRET"):
        assert token not in result.stdout + result.stderr + again.stdout + again.stderr
    current.write_bytes(b'{"stringContent":"SECRET-BAD-JSON"}')
    bad_output = tmp_path / "bad-report.json"
    bad = subprocess.run(command + [str(bad_output)], capture_output=True)
    assert bad.returncode == 2
    assert b"SECRET-BAD-JSON" not in bad.stdout + bad.stderr
    assert not bad_output.exists()


def test_cli_single_capture_pair_errors_and_parser_do_not_echo_input(tmp_path):
    current = tmp_path / "current.json"
    current.write_bytes(raw())
    script = Path(__file__).resolve().parents[2] / "tools/compare_hjnc_observations.py"
    command = [sys.executable, str(script), "--current", str(current), "--current-received-at", CURRENT]
    single = tmp_path / "single.json"
    result = subprocess.run(command + ["--output", str(single)], capture_output=True)
    assert result.returncode == 0
    assert json.loads(single.read_text(encoding="utf-8"))["comparison_status"] == "not_comparable_single_observation"
    for extra in (["--previous", str(current)], ["--previous-received-at", PREVIOUS],
                  ["--UNRECOGNIZED-SECRET"]):
        target = tmp_path / "rejected.json"
        result = subprocess.run(command + extra + ["--output", str(target)], capture_output=True)
        assert result.returncode == 2
        assert b"UNRECOGNIZED-SECRET" not in result.stdout + result.stderr
        assert not target.exists()
