from datetime import timedelta
import json
import subprocess
import sys

import pytest

from tools.demo_aisstream import BASE, IDS, Replay, bundle, position, scenario, static_event, utc, write_demo
from tools.probe_aisstream import Audit, BUSAN_TRIAL_BOX


def test_generated_wire_is_accepted_by_existing_probe_parser_without_a_key():
    audit = Audit(BUSAN_TRIAL_BOX)
    sample = scenario("normal")
    for row in sample["events"]:
        assert set(row["event"]) <= {"MessageType", "MetaData", "Message"}
        assert audit.consume(row["event"], BASE + timedelta(seconds=row["offset_seconds"]))
    result = audit.summary()
    assert result["message_counts"] == {"ShipStaticData": 1, "StaticDataReport": 2, "PositionReport": 24}
    assert result["position_static_join_count"] == 2
    assert result["valid_position_events"] == 24
    assert result["outside_trial_box_events"] == result["invalid_position_events"] == 0


@pytest.fixture(scope="module")
def generated():
    return bundle()


def test_replay_scenarios_are_explicit_and_never_share_last_positions(generated):
    normal = generated["scenarios"]["normal"]["frames"][-1]
    empty = generated["scenarios"]["empty"]["frames"][-1]
    assert normal["kind"] == empty["kind"] == "simulated"
    assert len(normal["ships"]) == 2
    assert all(s["static_status"] == "joined" and s["position_status"] == "fresh" for s in normal["ships"])
    assert empty["subscription_confirmed"] is True
    assert empty["ships"] == [] and empty["accepted"] == 0
    for case in generated["scenarios"].values():
        for frame in case["frames"]:
            assert frame["approval_eligible"] is False
            assert frame["voyage_link_verified"] is frame["window_change_confirmed"] is False


def test_stale_position_keeps_coordinates_and_original_age_despite_later_static(generated):
    frames = generated["scenarios"]["stale"]["frames"]
    before, boundary, after = (next(s for s in frames[t]["ships"] if s["mmsi"] == IDS[1])
                               for t in (124, 125, 180))
    assert before["position_status"] == "fresh"
    assert boundary["position_status"] == after["position_status"] == "stale"
    assert before["position"] == after["position"]
    assert after["age_seconds"] == 145
    assert len(after["track"]) == 3


def test_missing_static_is_not_invented_from_a_position_or_other_vessel(generated):
    ships = generated["scenarios"]["missing-static"]["frames"][-1]["ships"]
    missing = next(s for s in ships if s["mmsi"] == IDS[1])
    assert missing["name"] is None and missing["static_status"] == "missing"
    assert missing["position_status"] == "fresh"


def test_invalid_events_are_rejected_without_changing_position_or_age(generated):
    frames = generated["scenarios"]["invalid"]["frames"]
    for second, mmsi, rejected in ((60, IDS[0], 1), (90, IDS[1], 2)):
        before = next(s for s in frames[second - 1]["ships"] if s["mmsi"] == mmsi)
        after = next(s for s in frames[second]["ships"] if s["mmsi"] == mmsi)
        assert before["position"] == after["position"]
        assert after["age_seconds"] == before["age_seconds"] + 1
        assert frames[second]["rejected"] == rejected


def test_class_b_parts_can_arrive_out_of_order_and_do_not_create_position():
    state = Replay()
    state.consume(static_event(IDS[1], part="b"), utc(BASE))
    assert state.view(BASE)["ships"][0]["name"] is None
    state.consume(static_event(IDS[1], part="a"), utc(BASE + timedelta(seconds=1)))
    state.consume(static_event(IDS[1], part="b"), utc(BASE + timedelta(seconds=2)))
    ship = state.view(BASE + timedelta(seconds=2))["ships"][0]
    assert ship["name"] == "SIM-BUSAN-02"
    assert ship["position"] is None and ship["position_status"] == "missing"


@pytest.mark.parametrize("field,value", [("Latitude", 91), ("Longitude", 181),
    ("Latitude", float("nan")), ("Sog", 102.3), ("Cog", 360), ("Sog", True), ("Valid", False)])
def test_invalid_ais_or_sentinel_values_never_appear_as_valid_motion(field, value):
    state = Replay()
    first = position(IDS[0], 5)
    state.consume(first, utc(BASE + timedelta(seconds=5)))
    bad = position(IDS[0], 10)
    bad["Message"]["PositionReport"][field] = value
    state.consume(bad, utc(BASE + timedelta(seconds=10)))
    frame = state.view(BASE + timedelta(seconds=10))
    assert frame["rejected"] == 1
    assert frame["ships"][0]["age_seconds"] == 5


def test_unknown_or_duplicate_receipts_do_not_make_a_new_position():
    state = Replay()
    state.consume(position(IDS[0], 20), utc(BASE + timedelta(seconds=20)))
    state.consume(position(IDS[0], 5), utc(BASE + timedelta(seconds=5)))
    state.consume(position(IDS[0], 20), utc(BASE + timedelta(seconds=20)))
    state.consume({"MessageType": "UnknownMessage"}, utc(BASE + timedelta(seconds=25)))
    frame = state.view(BASE + timedelta(seconds=30))
    assert frame["rejected"] == 3 and frame["accepted"] == 1
    assert frame["ships"][0]["age_seconds"] == 10


def test_provider_timestamp_and_static_metadata_never_refresh_position_age():
    state = Replay()
    event = position(IDS[0], 5)
    event["MetaData"]["time_utc"] = "2099-01-01T00:00:00Z"
    state.consume(event, utc(BASE + timedelta(seconds=5)))
    state.consume(static_event(IDS[0]), utc(BASE + timedelta(seconds=100)))
    ship = state.view(BASE + timedelta(seconds=100))["ships"][0]
    assert ship["position_status"] == "stale" and ship["age_seconds"] == 95
    assert ship["position"]["latitude"] != 0


def test_returned_track_cannot_corrupt_a_later_frame():
    state = Replay()
    state.consume(position(IDS[0], 5), utc(BASE + timedelta(seconds=5)))
    view = state.view(BASE + timedelta(seconds=5))
    view["ships"][0]["track"][0][0] = 91
    assert state.view(BASE + timedelta(seconds=5))["ships"][0]["track"][0][0] != 91


def test_generated_bundle_contains_wire_files_receipts_and_explicit_simulation_manifest(tmp_path):
    output = tmp_path / "new-demo"
    page = write_demo(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "simulated"
    html = page.read_text(encoding="utf-8")
    assert "모의 데이터 100%" in html and "__AIS_DEMO_DATA__" not in html
    assert "new WebSocket(" not in html and "fetch(" not in html
    for case in manifest["scenarios"].values():
        wire = (output / case["wire_file"]).read_text(encoding="utf-8").splitlines()
        receipts = json.loads((output / case["receipt_file"]).read_text(encoding="utf-8"))
        assert len(wire) == len(receipts) == case["event_count"]
        assert all("kind" not in json.loads(line) and "received_at" not in json.loads(line) for line in wire)
    original = page.read_bytes()
    with pytest.raises(FileExistsError):
        write_demo(output)
    assert page.read_bytes() == original


def test_cli_requires_explicit_simulation_and_never_accepts_a_live_mode(tmp_path):
    path = tmp_path / "must-not-exist"
    for mode in ([], ["--mode", "live"]):
        run = subprocess.run([sys.executable, "-m", "tools.demo_aisstream", "--output", str(path), *mode],
                             capture_output=True)
        assert run.returncode == 2
        assert not path.exists()
