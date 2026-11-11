import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tools.provider_fixture_bundle import DEFAULT, build_bundle, check_bundle


def test_archived_fixtures_are_deterministic_and_pass_existing_auditors():
    files = build_bundle()
    assert files == build_bundle()
    for name, raw in files.items():
        assert (DEFAULT / name).read_bytes() == raw
    report = check_bundle()
    assert report["valid"] and report["case_count"] == 21


def test_provenance_is_synthetic_and_clock_does_not_claim_real_receipt():
    manifest = json.loads(build_bundle()["manifest.json"])
    assert manifest["data_kind"] == "simulated"
    assert manifest["real_responses_or_keys_copied"] is False
    for case in manifest["cases"]:
        assert case["data_kind"] == "simulated" and case["engine_eligible"] is False
        assert "simulated_received_at" in case and "received_at" not in case


def test_failures_missing_and_preliminary_times_are_not_normalized_into_success():
    cases = {x["id"]: x for x in check_bundle()["cases"]}
    assert cases["hjnc-missing-window"]["status"] == "partial"
    assert cases["hjnc-http-error"]["status"] == "http_error"
    assert cases["kma-application-required"]["status"] == "application_required"
    assert cases["kma-truncated"]["status"] == "format_error"
    for name, value in [("kma-sea-missing", ""), ("kma-sea-unknown-negative", "-99.0")]:
        observation = cases[name]["audit"]["observations"][0]
        assert observation["ws_m_s_original"] == value
        assert observation["missing_or_invalid_nonnegative_fields"] == ["WS"]
    assert cases["kma-warning-preliminary"]["audit"]["selected_records"][0]["effective_at_utc"] is None
    assert cases["kma-sea-future"]["audit"]["future_observation_rows"] == 1
    assert cases["kma-sea-wrong-station"]["audit"]["station_mismatch_rows"] == 1
    assert cases["hjnc-stale"]["freshness"] == cases["kma-sea-stale"]["freshness"] == "stale"


def copy_bundle(tmp_path):
    folder = tmp_path / "bundle"
    shutil.copytree(DEFAULT, folder)
    return folder


def test_changed_wire_bytes_are_rejected_before_parsing(tmp_path):
    folder = copy_bundle(tmp_path)
    file = folder / "wire/kma-sea-normal.txt"
    file.write_bytes(file.read_bytes().replace(b"4.0", b"5.0"))
    with pytest.raises(ValueError, match="해시"):
        check_bundle(folder)


@pytest.mark.parametrize("mutation", ["outside", "duplicate", "real_kind"])
def test_invalid_manifest_cannot_read_outside_or_claim_observed(tmp_path, mutation):
    folder = copy_bundle(tmp_path)
    path = folder / "manifest.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "outside":
        m["cases"][0]["wire"] = "../../not-a-fixture.txt"
    elif mutation == "duplicate":
        m["cases"].append(m["cases"][0])
    else:
        m["cases"][0]["data_kind"] = "observed"
    path.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError):
        check_bundle(folder)


def test_cli_checks_and_refuses_to_overwrite_existing_bundle(tmp_path):
    script = Path(__file__).resolve().parents[2] / "tools/provider_fixture_bundle.py"
    target = tmp_path / "new"
    command = [sys.executable, str(script), "--directory", str(target)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    before = (target / "manifest.json").read_bytes()
    assert subprocess.run(command, capture_output=True).returncode == 1
    assert (target / "manifest.json").read_bytes() == before
    assert subprocess.run(command + ["--check"], capture_output=True).returncode == 0
    bad = subprocess.run(command + ["--unknown", "private-test-value"], capture_output=True)
    assert bad.returncode == 2
    assert b"private-test-value" not in bad.stdout + bad.stderr
