"""저장한 KMA 표본만 검사한다. 키·네트워크·엔진 입력 변환은 사용하지 않는다."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re


KST = timezone(timedelta(hours=9))
SEA_COLUMNS = ("TP", "TM", "STN_ID", "STN_KO", "LON", "LAT", "WH", "WD", "WS",
               "WS_GST", "TW", "TA", "PA", "HM")
WARNING_COLUMNS = ("REG_UP", "REG_UP_KO", "REG_ID", "REG_KO", "TM_FC", "TM_EF",
                   "WRN", "LVL", "CMD", "ED_TM")


def kst_to_utc(value: str) -> str:
    if not re.fullmatch(r"[0-9]{12}", value):
        raise ValueError("KMA 원본 시각은12자리 KST여야 합니다.")
    return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=KST).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def framed_lines(raw: bytes, kind: str) -> list[str]:
    text = raw.decode("cp949")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "#START7777":
        raise ValueError("정상 KMA 시작 표지가 없습니다.")
    if lines.count("#START7777") != 1 or lines.count("#7777END") > 1:
        raise ValueError("중복 KMA 자료 프레임입니다.")
    has_end = lines[-1] == "#7777END"
    if not has_end and not (kind == "warning" and any(line.startswith("# REG_UP ") for line in lines)):
        raise ValueError("종료 표지 또는 관측한 특보 헤더가 없습니다.")
    if "#7777END" in lines and not has_end:
        raise ValueError("종료 표지 뒤에 추가 자료가 있습니다.")
    if any(re.match(r"#\s*(?:error|오류)", line, re.IGNORECASE) for line in lines):
        raise ValueError("오류 표지를 정상 빈 자료로 처리할 수 없습니다.")
    body = lines[1:-1] if has_end else lines[1:]
    return [line for line in body if not line.startswith("#")]


def comma_rows(lines: list[str], columns: tuple[str, ...], trailer: tuple[str, ...]) -> list[dict]:
    records = []
    for line in lines:
        fields = [field.strip() for field in next(csv.reader(io.StringIO(line), strict=True))]
        if len(fields) != len(columns) + len(trailer) or tuple(fields[-len(trailer):]) != trailer:
            raise ValueError("관측한 KMA 열 수/행 종료 형식과 다릅니다.")
        records.append(dict(zip(columns, fields[:-len(trailer)])))
    return records


def audit_response(raw: bytes, kind: str, http_status: int, received_at: str,
                   station: str | None = None, regions: tuple[str, ...] = ()) -> dict:
    receipt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
    if receipt.utcoffset() != timedelta(0):
        raise ValueError("수신시각은 UTC 오프셋이 필요합니다.")
    result = {"raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw),
              "kind": kind, "http_status": http_status, "received_at": received_at,
              "engine_conversion": "not_performed", "causal_attribution": "not_established"}
    if kind not in ("station", "sea", "warning"):
        raise ValueError("지원하지 않는 KMA 표본 종류입니다.")
    if http_status != 200:
        result["status"] = "http_error"
        if http_status == 403:
            try:
                message = json.loads(raw.decode("utf-8"))["result"]["message"]
                if isinstance(message, str) and "활용신청" in message:
                    result["status"] = "application_required"
            except (UnicodeError, ValueError, KeyError, TypeError):
                result["error_body_format"] = "unrecognized"
        return result
    lines = framed_lines(raw, kind)
    if kind == "station":
        records = []
        for line in lines:
            values = line.split()
            if len(values) != 9:
                raise ValueError("관측한 단일 지점정보 형식과 다릅니다.")
            records.append(dict(zip(("STN_ID", "LON", "LAT", "STN_SP", "HT", "AD", "STN_KO", "STN_EN", "FCT_ID"), values)))
    else:
        records = comma_rows(lines, SEA_COLUMNS if kind == "sea" else WARNING_COLUMNS,
                             ("", "=") if kind == "sea" else ("=",))
    result.update(status="sample_received" if records else "empty_framed_response",
                  row_count=len(records), units_source="response_help_and_official_documentation")
    if kind in ("station", "sea"):
        if not station:
            raise ValueError("예상 지점 ID가 필요합니다.")
        result["expected_station"] = station
        result["station_mismatch_rows"] = sum(row["STN_ID"] != station for row in records)
    if kind == "station":
        result["stations"] = [{key: row[key] for key in ("STN_ID", "STN_KO", "LON", "LAT", "FCT_ID")} for row in records]
    elif kind == "sea":
        observations = []
        for row in records:
            observed = kst_to_utc(row["TM"])
            unverified = []
            for key in ("WH", "WS", "WS_GST"):
                try:
                    value = Decimal(row[key])
                    if not value.is_finite() or value < 0:
                        unverified.append(key)
                except InvalidOperation:
                    unverified.append(key)
            observations.append({"station_id": row["STN_ID"], "observed_at_utc": observed,
                                 "original_time_kst": row["TM"],
                                 "received_minus_observed_seconds": int((receipt - datetime.fromisoformat(observed.replace("Z", "+00:00"))).total_seconds()),
                                 "wh_m_original": row["WH"], "ws_m_s_original": row["WS"],
                                 "gust_m_s_original": row["WS_GST"],
                                 "missing_or_invalid_nonnegative_fields": unverified})
        result["observations"] = observations
        result["future_observation_rows"] = sum(datetime.fromisoformat(row["observed_at_utc"].replace("Z", "+00:00")) > receipt
                                                for row in observations)
        result["missing_sentinel_policy"] = "not_confirmed; negative_or_invalid_values_not_zero_filled"
    else:
        if not regions:
            raise ValueError("대상 특보구역 코드가 필요합니다.")
        selected = []
        for row in records:
            if row["REG_ID"] not in regions:
                continue
            published = kst_to_utc(row["TM_FC"])
            effective = kst_to_utc(row["TM_EF"])
            if row["LVL"] not in ("예비", "주의", "경보"):
                raise ValueError("확인하지 않은 특보 수준입니다.")
            preliminary = row["LVL"] == "예비"
            selected.append({"region_id": row["REG_ID"], "region_name": row["REG_KO"],
                             "published_at_utc": published, "effective_at_utc": None if preliminary else effective,
                             "effective_time_original_kst": row["TM_EF"],
                             "effective_representation": "preliminary_period_code" if preliminary else "instant_kst_converted",
                             "kind": row["WRN"], "level": row["LVL"], "command": row["CMD"],
                             "release_notice_original": row["ED_TM"]})
        result.update(target_regions=list(regions), selected_row_count=len(selected), selected_records=selected,
                      coverage="not_established; warning_response_may_have_no_end_marker",
                      absence_interpretation="no_selected_row_is_not_proof_of_no_warning")
    return result


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "인수 오류: --help의 형식을 확인하세요.\n")


def main() -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--kind", choices=("station", "sea", "warning"), required=True)
    parser.add_argument("--http-status", type=int, required=True)
    parser.add_argument("--received-at", required=True)
    parser.add_argument("--station")
    parser.add_argument("--regions", nargs="+", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_response(args.input.read_bytes(), args.kind, args.http_status, args.received_at,
                                args.station, tuple(args.regions))
    except (OSError, ValueError, csv.Error):
        print("감사 실패: 원본 형식·시각·지점/구역 조건을 확인하세요. 원문은 출력하지 않습니다.")
        return 2
    try:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        print("저장 실패: 기존 입력/출력을 보존합니다. 새 경로를 사용하세요.")
        return 1
    print("KMA 표본 감사 저장 완료. 공급자 허가·원인·승인 판정은 별도입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
