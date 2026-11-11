"""공급자 형식을 따르는 별도 합성 예제 생성·감사. 네트워크·개인 원본·키는 읽지 않는다."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.audit_collected_samples import audit_hjnc
from tools.audit_kma_response import audit_response

DEFAULT = ROOT / "docs/data/provider-fixtures-2026-11-10"
SIMULATED_NOW = "2026-11-10T03:00:00Z"
STATION = "99999"
REGION = "S9999900"


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def framed(*lines) -> bytes:
    return ("#START7777\n# SYNTHETIC fixture, not a provider response\n" + "\n".join(lines) + "\n#7777END\n").encode("cp949")


def sea(*, wind="4.0", station=STATION, time="202611101159") -> bytes:
    return framed(f"B,{time},{station},합성해양지점,128.0000,35.0000,0.8,180,{wind},6.0,18.0,16.0,1015.0,60.0, ,=")


def warning(*, preliminary=False) -> bytes:
    level, effective = ("예비", "202611102358") if preliminary else ("주의", "202611101200")
    return framed(f"S9999000,합성상위구역,{REGION},합성앞바다,202611101100,{effective},풍랑,{level},발표, ,=")


def build_bundle() -> dict[str, bytes]:
    cases, files = [], {}

    def add(identifier, source, raw, expected, *, kind=None, status=200, receipt=SIMULATED_NOW):
        suffix = "json" if source == "hjnc" or status != 200 else "txt"
        name = f"wire/{identifier}.{suffix}"
        files[name] = raw
        entry = {"id": identifier, "source": source, "data_kind": "simulated", "wire": name,
                 "encoding": "utf-8" if suffix == "json" else "cp949", "http_status": status,
                 "simulated_received_at": receipt, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                 "engine_eligible": False, "expected": expected}
        if kind:
            entry["kind"] = kind
            entry.update({"regions": [REGION]} if kind == "warning" else {"station": STATION})
        cases.append(entry)

    row = {"VOY_NO": "SYNTHETIC-VOYAGE-01", "VSL_NM": "SYNTHETIC VESSEL",
           "YARD_OPEN": "2026-11-10 09:00", "YARD_CLOSE": "2026-11-10 18:00", "ETB": "2026-11-11 02:00"}

    def hjnc(rows, total=None, next_page=False):
        return json_bytes({"content": [], "stringContent": json.dumps(rows, ensure_ascii=False),
                           "totalElements": len(rows) if total is None else total, "hasNext": next_page})

    add("hjnc-normal", "hjnc", hjnc([row]), {"status": "received", "audit": {"row_count": 1}})
    add("hjnc-empty", "hjnc", hjnc([]), {"status": "empty", "audit": {"row_count": 0}})
    add("hjnc-partial-page", "hjnc", hjnc([row], 3), {"status": "partial", "audit": {"reported_total_matches_rows": False}})
    missing = dict(row, YARD_CLOSE=None)
    add("hjnc-missing-window", "hjnc", hjnc([missing]), {"status": "partial", "audit": {"missing_or_nontext": {"YARD_CLOSE": 1}}})
    add("hjnc-stale", "hjnc", hjnc([row]), {"status": "received", "freshness": "stale"}, receipt="2026-11-10T02:00:00Z")
    add("hjnc-format-changed", "hjnc", hjnc([dict(row, ETB="not-a-time")]), {"status": "format_error"})
    add("hjnc-http-error", "hjnc", json_bytes({"error": "SYNTHETIC service failure"}), {"status": "http_error"}, status=503)
    add("kma-station-normal", "kma", framed(f"{STATION} 128.0000 35.0000 24000000 0.0 999 합성지점 SyntheticStation SYNTHETIC"),
        {"status": "sample_received", "audit": {"row_count": 1, "station_mismatch_rows": 0}}, kind="station")
    add("kma-sea-normal", "kma", sea(), {"status": "sample_received", "audit": {"row_count": 1, "future_observation_rows": 0}}, kind="sea")
    add("kma-sea-empty", "kma", framed(), {"status": "empty_framed_response", "audit": {"row_count": 0}}, kind="sea")
    add("kma-sea-missing", "kma", sea(wind=""), {"status": "sample_received", "audit": {"observations": [{"ws_m_s_original": "", "missing_or_invalid_nonnegative_fields": ["WS"]}]}}, kind="sea")
    add("kma-sea-unknown-negative", "kma", sea(wind="-99.0"), {"status": "sample_received", "audit": {"observations": [{"ws_m_s_original": "-99.0", "missing_or_invalid_nonnegative_fields": ["WS"]}]}}, kind="sea")
    add("kma-sea-future", "kma", sea(time="202611101201"), {"status": "sample_received", "audit": {"future_observation_rows": 1}}, kind="sea")
    add("kma-sea-wrong-station", "kma", sea(station="99998"), {"status": "sample_received", "audit": {"station_mismatch_rows": 1}}, kind="sea")
    add("kma-sea-stale", "kma", sea(time="202611101059"), {"status": "sample_received", "freshness": "stale"}, kind="sea", receipt="2026-11-10T02:00:00Z")
    error = json_bytes({"result": {"status": 403, "message": "활용신청이 필요한 API 입니다."}})
    add("kma-application-required", "kma", error, {"status": "application_required"}, kind="sea", status=403)
    add("kma-rate-limited", "kma", json_bytes({"result": {"status": 429, "message": "SYNTHETIC rate limit"}}), {"status": "http_error"}, kind="sea", status=429)
    add("kma-warning-normal", "kma", warning(), {"status": "sample_received", "audit": {"selected_row_count": 1, "selected_records": [{"effective_at_utc": "2026-11-10T03:00:00Z"}]}}, kind="warning")
    add("kma-warning-preliminary", "kma", warning(preliminary=True), {"status": "sample_received", "audit": {"selected_records": [{"effective_at_utc": None, "effective_representation": "preliminary_period_code"}]}}, kind="warning")
    add("kma-warning-empty", "kma", framed(), {"status": "empty_framed_response", "audit": {"selected_row_count": 0}}, kind="warning")
    add("kma-truncated", "kma", b"#START7777\n", {"status": "format_error"}, kind="sea")
    manifest = {"bundle_version": 1, "data_kind": "simulated", "simulated_now_utc": SIMULATED_NOW,
                "freshness_seconds": 300, "freshness_policy": "fixture display test only, not provider update guarantee",
                "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "real_responses_or_keys_copied": False, "cases": cases}
    files["manifest.json"] = json_bytes(manifest)
    return files


def assert_subset(actual, expected):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError("예상 객체와 다릅니다.")
        for key, value in expected.items():
            if key not in actual:
                raise ValueError("예상 필드가 없습니다.")
            assert_subset(actual[key], value)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError("예상 배열 길이와 다릅니다.")
        for a, e in zip(actual, expected):
            assert_subset(a, e)
    elif actual != expected:
        raise ValueError("예상 검사 결과와 다릅니다.")


def check_bundle(directory: Path = DEFAULT) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("bundle_version") != 1 or manifest.get("data_kind") != "simulated":
        raise ValueError("합성 예제 버전/종류가 다릅니다.")
    seen, results = set(), []
    now = datetime.fromisoformat(manifest["simulated_now_utc"].replace("Z", "+00:00"))
    for case in manifest["cases"]:
        if case["id"] in seen or case["data_kind"] != "simulated" or case["engine_eligible"] is not False:
            raise ValueError("중복 예제 또는 모의/계산 경계가 잘못됐습니다.")
        if case["source"] not in ("hjnc", "kma"):
            raise ValueError("알 수 없는 공급자입니다.")
        seen.add(case["id"])
        path = (directory / case["wire"]).resolve()
        if Path(case["wire"]).is_absolute() or not path.is_relative_to(directory.resolve()):
            raise ValueError("예제 폴더 밖 파일은 읽지 않습니다.")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != case["raw_sha256"]:
            raise ValueError("합성 원문 해시가 다릅니다.")
        receipt = datetime.fromisoformat(case["simulated_received_at"].replace("Z", "+00:00"))
        if receipt.utcoffset() != timedelta(0) or receipt > now:
            raise ValueError("합성 수신시각의 UTC/순서가 잘못됐습니다.")
        result = {"freshness": "fresh" if (now - receipt).total_seconds() < manifest["freshness_seconds"] else "stale"}
        try:
            if case["source"] == "hjnc":
                if case["http_status"] != 200:
                    result["status"] = "http_error"
                else:
                    audit = audit_hjnc(raw)
                    partial = (any(audit["missing_or_nontext"].values()) or not audit["reported_total_matches_rows"]
                               or audit["reported_has_next"] is not False)
                    result.update(audit=audit, status="partial" if partial else "received" if audit["row_count"] else "empty")
            elif case["source"] == "kma":
                audit = audit_response(raw, case["kind"], case["http_status"], case["simulated_received_at"],
                                       case.get("station"), tuple(case.get("regions", [])))
                result.update(audit=audit, status=audit["status"])
        except ValueError:
            result["status"] = "format_error"
        assert_subset(result, case["expected"])
        results.append({"id": case["id"], "data_kind": "simulated", "engine_eligible": False, **result})
    return {"valid": True, "case_count": len(results), "cases": results}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "인수 오류: --help의 형식을 확인하세요.\n")


def main() -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--directory", type=Path, default=DEFAULT)
    args = parser.parse_args()
    try:
        expected = build_bundle()
        if args.check:
            for name, content in expected.items():
                if (args.directory / name).read_bytes() != content:
                    raise ValueError("보관 예제가 생성 규칙과 다릅니다.")
            report = check_bundle(args.directory)
        else:
            args.directory.mkdir(parents=True, exist_ok=False)
            for name, content in expected.items():
                path = args.directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(content)
            report = check_bundle(args.directory)
    except (OSError, ValueError, KeyError, TypeError):
        print("예제 생성/검사 실패. 새 출력 폴더·해시·형식을 확인하세요. 원문은 출력하지 않습니다.")
        return 1
    print(json.dumps({"valid": report["valid"], "case_count": report["case_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
