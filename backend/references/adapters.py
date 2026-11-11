"""Allowlisted sample projections. No provider calls, credentials or unit guesses."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

from tools.audit_collected_samples import HJNC_FIELDS, audit_hjnc
from tools.audit_road_response import audit_response


SOURCE_REFS = {
    "hjnc": "https://www.hjnc.co.kr/esvc/vessel/berthScheduleT",
    "road": "https://data.ex.co.kr/openapi/trtm/realUnitTrtm",
}
MAX_BYTES = 1_000_000


class SampleError(ValueError):
    """Only fixed codes escape the adapter; provider error text is discarded."""


@dataclass(frozen=True)
class Projection:
    status: str
    items: tuple[dict, ...]
    row_count: int
    reported_count: int | None
    excluded_rows: int
    blockers: tuple[str, ...]


def project(source: str, raw: bytes, received_at: str, kind: str,
            direction: tuple[str, str] | None) -> Projection:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise SampleError("invalid_sample")
    provenance = {"kind": kind, "source_ref": SOURCE_REFS[source],
                  "received_at": received_at, "observed_at": None}
    try:
        if source == "hjnc":
            audit = audit_hjnc(raw)
            if audit["duplicate_nonempty_voyage_ids"]:
                raise SampleError("duplicate_voyage")
            rows = json.loads(json.loads(raw.decode("utf-8-sig"))["stringContent"])
            total = audit["reported_total"]
            if total is not None and total < len(rows):
                raise SampleError("invalid_count")
            items = []
            for row in rows:
                if any(not isinstance(row.get(k), str) or not row[k].strip() for k in HJNC_FIELDS):
                    continue
                if row["VOY_NO"] != row["VOY_NO"].strip():
                    continue
                if datetime.strptime(row["YARD_OPEN"], "%Y-%m-%d %H:%M") > datetime.strptime(
                        row["YARD_CLOSE"], "%Y-%m-%d %H:%M"):
                    continue
                items.append({"values": {k: row[k] for k in HJNC_FIELDS},
                              "provenance": dict(provenance)})
            partial = (len(items) != len(rows) or total is None or total != len(rows)
                       or audit["reported_has_next"] is not False)
            blockers = ("source_timezone_unconfirmed", "coverage_not_established",
                        "window_change_not_confirmed")
        else:
            audit = audit_response(raw, *direction, 200)
            if audit["status"] == "provider_error":
                raise SampleError("provider_error")
            payload = json.loads(raw.decode("utf-8-sig"))
            rows, total = payload["realUnitTrtmVO"], audit["reported_count"]
            items = []
            for row in rows:
                # Reuse the data team's audit for each row, including direction,
                # numeric ordering and unresolved aggregation/time fields.
                single = json.dumps({"code": "SUCCESS", "count": 1,
                                     "realUnitTrtmVO": [row]}).encode()
                check = audit_response(single, *direction, 200)
                bad = any(check["missing_or_nontext"].values()) or any(
                    n for k, n in check["issues"].items() if k != "padded_unit_code_fields")
                if bad or check["time_forms"].get("hh_mm", 0) != 1:
                    continue
                fields = tuple(check["missing_or_nontext"])
                items.append({"values": {k: row[k] for k in fields},
                              "provenance": dict(provenance)})
            partial = len(items) != len(rows) or total != len(rows)
            blockers = ("source_timezone_unconfirmed", "duration_unit_unconfirmed",
                        "aggregation_meaning_unconfirmed", "truck_route_not_verified",
                        "coverage_not_established")
        status = "partial" if partial else "received" if rows else "empty"
        return Projection(status, tuple(items), len(rows), total, len(rows) - len(items),
                          ("reference_only_not_engine_input",) + blockers)
    except SampleError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise SampleError("invalid_sample") from None
