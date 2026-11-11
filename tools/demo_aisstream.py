"""Explicit, offline synthetic AIS replay. No API keys or live-data fallback."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

from tools.probe_aisstream import BUSAN_TRIAL_BOX


SOURCE = "https://aisstream.io/documentation"
MODEL_SOURCE = "https://github.com/aisstream/ais-message-models/blob/master/type-definition.yaml"
BASE = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
SCENARIOS = ("normal", "stale", "missing-static", "invalid", "empty")
IDS = (999000001, 999000002)  # Illustrative placeholders, not a reserved MMSI allocation.


def utc(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def position(mmsi: int, seconds: int) -> dict:
    index = IDS.index(mmsi)
    # Constant-speed straight lines for a diagram, not navigable port routes.
    origin_lat, origin_lon = 35.035 + index * .018, 128.745 + index * .025
    metres = (5.0 + index) * 1852 / 3600 * seconds
    lat = round(origin_lat + math.cos(math.radians(55)) * metres / 111320, 6)
    lon = round(origin_lon + math.sin(math.radians(55)) * metres / (111320 * math.cos(math.radians(origin_lat))), 6)
    return {"MessageType": "PositionReport",
            "MetaData": {"MMSI": mmsi, "ShipName": f"SIM-BUSAN-{index + 1:02d}",
                         "Latitude": lat, "Longitude": lon, "time_utc": utc(BASE + timedelta(seconds=seconds))},
            "Message": {"PositionReport": {
                "MessageID": 1, "RepeatIndicator": 0, "UserID": mmsi, "Valid": True,
                "NavigationalStatus": 0, "RateOfTurn": 0, "Sog": 5.0 + index,
                "PositionAccuracy": True, "Longitude": lon, "Latitude": lat,
                "Cog": 55.0, "TrueHeading": 55, "Timestamp": seconds % 60,
                "SpecialManoeuvreIndicator": 0, "Spare": 0, "Raim": False,
                "CommunicationState": 0}}}


def static_event(mmsi: int, *, part: str = "ship") -> dict:
    index = IDS.index(mmsi)
    dimensions = {"A": 20, "B": 10, "C": 5, "D": 5}
    common = {"MessageID": 5 if part == "ship" else 24, "RepeatIndicator": 0,
              "UserID": mmsi, "Valid": True}
    if part == "ship":
        kind = "ShipStaticData"
        body = {**common, "AisVersion": 0, "ImoNumber": 0, "CallSign": "SIM0001",
                "Name": f"SIM-BUSAN-{index + 1:02d}", "Type": 70, "Dimension": dimensions,
                "FixType": 1, "Eta": {"Month": 0, "Day": 0, "Hour": 24, "Minute": 60},
                "MaximumStaticDraught": 0.0, "Destination": "SIMULATED ONLY",
                "Dte": False, "Spare": False}
    else:
        kind = "StaticDataReport"
        body = {**common, "Reserved": 0, "PartNumber": part == "b",
                "ReportA": {"Valid": part == "a", "Name": f"SIM-BUSAN-{index + 1:02d}" if part == "a" else ""},
                "ReportB": {"Valid": part == "b", "ShipType": 70, "VendorIDName": "SIM",
                            "VenderIDModel": 0, "VenderIDSerial": 0, "CallSign": "SIM0002",
                            "Dimension": dimensions, "FixType": 1, "Spare": 0}}
    # Deliberately conflicting last-known metadata coordinates: a static message
    # must never create or refresh the moving position.
    return {"MessageType": kind, "MetaData": {"MMSI": mmsi, "ShipName": body.get("Name", ""),
            "Latitude": 0, "Longitude": 0, "time_utc": utc(BASE)}, "Message": {kind: body}}


def scenario(name: str) -> dict:
    if name not in SCENARIOS:
        raise ValueError("unknown synthetic scenario")
    entries = []
    def add(seconds, event):
        entries.append({"offset_seconds": seconds, "received_at": utc(BASE + timedelta(seconds=seconds)),
                        "event": event})
    add(0, {"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}})
    if name != "empty":
        add(1, static_event(IDS[0]))
        if name != "missing-static":
            add(2, static_event(IDS[1], part="a"))
            add(3, static_event(IDS[1], part="b"))
        for seconds in range(5, 181, 15):
            for mmsi in IDS:
                if name == "stale" and mmsi == IDS[1] and seconds > 35:
                    continue
                event = position(mmsi, seconds)
                if name == "missing-static" and mmsi == IDS[1]:
                    event["MetaData"]["ShipName"] = ""
                add(seconds, event)
        if name == "stale":
            # A later static update does not rescue stale positional data.
            add(160, static_event(IDS[1], part="a"))
        if name == "invalid":
            bad = position(IDS[0], 60)
            bad["Message"]["PositionReport"]["Latitude"] = 91
            add(60, bad)
            mismatch = position(IDS[1], 90)
            mismatch["Message"]["PositionReport"]["UserID"] = IDS[0]
            add(90, mismatch)
    entries.sort(key=lambda row: row["offset_seconds"])
    return {"kind": "simulated", "scenario": name, "base_time": utc(BASE),
            "duration_seconds": 180, "fresh_for_seconds": 90, "events": entries}


class Replay:
    """Local presentation state only. Not an engine input or production AIS parser."""
    def __init__(self, *, fresh_for_seconds=90):
        if type(fresh_for_seconds) is not int or fresh_for_seconds <= 0:
            raise ValueError("positive display threshold required")
        self.fresh_for_seconds = fresh_for_seconds
        self.ships, self.rejected, self.accepted = {}, [], 0
        self.confirmed = False

    def consume(self, event: dict, received_at: str):
        try:
            received = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
            if not received_at.endswith("Z") or received.tzinfo is None:
                raise ValueError
            if event.get("MessageType") == "SubscriptionConfirmation":
                self.confirmed = True
                return
            kind = event["MessageType"]
            if kind not in ("PositionReport", "ShipStaticData", "StaticDataReport"):
                raise ValueError
            meta, body = event["MetaData"], event["Message"][kind]
            mmsi = meta["MMSI"]
            if (type(mmsi) is not int or not 100000000 <= mmsi <= 999999999
                    or type(body["UserID"]) is not int or body["UserID"] != mmsi
                    or body.get("Valid") is not True):
                raise ValueError
            if kind == "PositionReport":
                lat, lon, sog, cog = (body[k] for k in ("Latitude", "Longitude", "Sog", "Cog"))
                if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon, sog, cog))
                        or not -90 <= lat <= 90 or not -180 <= lon <= 180
                        or not 0 <= sog < 102.3 or not 0 <= cog < 360):
                    raise ValueError
                old = self.ships.get(mmsi, {}).get("position")
                if old and received <= datetime.fromisoformat(old["received_at"].replace("Z", "+00:00")):
                    raise ValueError
                ship = self.ships.setdefault(mmsi, {"mmsi": mmsi, "name": None, "position": None, "track": []})
                ship["position"] = {"latitude": lat, "longitude": lon, "sog_knots": sog,
                                    "cog_degrees": cog, "received_at": received_at}
                ship["track"].append([lat, lon])
            else:
                # A split class-B ReportB is not a name and cannot clear ReportA.
                if kind == "ShipStaticData":
                    name = body.get("Name")
                else:
                    report = body.get("ReportA", {})
                    name = report.get("Name") if report.get("Valid") is True and body.get("PartNumber") is False else None
                ship = self.ships.setdefault(mmsi, {"mmsi": mmsi, "name": None, "position": None, "track": []})
                if isinstance(name, str) and name.strip():
                    ship["name"] = name.strip()
            self.accepted += 1
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            self.rejected.append({"received_at": received_at, "reason": "invalid_or_out_of_order_message"})

    def view(self, at: datetime) -> dict:
        ships = deepcopy(list(self.ships.values()))
        for ship in ships:
            position = ship["position"]
            ship["static_status"] = "joined" if ship["name"] else "missing"
            if position is None:
                ship.update(position_status="missing", age_seconds=None)
            else:
                age = (at - datetime.fromisoformat(position["received_at"].replace("Z", "+00:00"))).total_seconds()
                if age < 0:
                    raise ValueError("replay clock precedes received position")
                ship.update(position_status="stale" if age >= self.fresh_for_seconds else "fresh",
                            age_seconds=age)
        return {"kind": "simulated", "at": utc(at), "subscription_confirmed": self.confirmed,
                "accepted": self.accepted, "rejected": len(self.rejected), "ships": ships,
                "approval_eligible": False, "voyage_link_verified": False,
                "window_change_confirmed": False}


def bundle() -> dict:
    result = {"kind": "simulated", "format_source": SOURCE, "model_source": MODEL_SOURCE,
              "bbox": list(BUSAN_TRIAL_BOX), "scenarios": {}}
    for name in SCENARIOS:
        generated = scenario(name)
        state = Replay(fresh_for_seconds=generated["fresh_for_seconds"])
        events = iter(generated["events"])
        pending = next(events, None)
        frames = []
        for second in range(generated["duration_seconds"] + 1):
            while pending is not None and pending["offset_seconds"] <= second:
                state.consume(pending["event"], pending["received_at"])
                pending = next(events, None)
            frames.append(state.view(BASE + timedelta(seconds=second)))
        result["scenarios"][name] = {**generated, "frames": frames}
    return result


def write_demo(output: Path) -> Path:
    # A new directory is the unit of output; existing material is never replaced.
    output.mkdir(parents=True, exist_ok=False)
    data = bundle()
    template = (Path(__file__).parent / "templates" / "aisstream-demo.html").read_text(encoding="utf-8")
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    page = output / "index.html"
    page.write_text(template.replace("__AIS_DEMO_DATA__", encoded), encoding="utf-8")
    manifest = {k: v for k, v in data.items() if k != "scenarios"}
    manifest["scenarios"] = {}
    for name, item in data["scenarios"].items():
        wire_name = f"{name}.jsonl"
        receipt_name = f"{name}.receipts.json"
        (output / wire_name).write_text("".join(json.dumps(row["event"], ensure_ascii=False, allow_nan=False)
                                                  + "\n" for row in item["events"]), encoding="utf-8")
        receipts = [{k: v for k, v in row.items() if k != "event"} for row in item["events"]]
        (output / receipt_name).write_text(json.dumps(receipts, indent=2), encoding="utf-8")
        manifest["scenarios"][name] = {"kind": "simulated", "wire_file": wire_name,
                                       "receipt_file": receipt_name, "event_count": len(receipts)}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return page


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("simulated",), required=True)
    parser.add_argument("--output", type=Path, required=True, help="새 출력 디렉터리")
    args = parser.parse_args(argv)
    try:
        page = write_demo(args.output)
    except (OSError, ValueError):
        print("생성 실패: 기존 출력은 보존함. 새 디렉터리 경로를 사용하세요.")
        return 2
    print(f"모의 AIS 시연 생성: {page.resolve()}")
    print("외부 호출 0회. 모든 선박·식별자·좌표는 합성. 실제 부산 관측/확정 변경이 아님.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
