"""저장한 도로공사 realUnitTrtm 응답을 감사한다. 수집·단위 추정·엔진 변환은 하지 않는다."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re


def number(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def audit_response(raw: bytes, start: str | None, end: str | None, http_status: int) -> dict:
    result = {"raw_sha256": hashlib.sha256(raw).hexdigest(), "http_status": http_status,
              "requested_start": start, "requested_end": end, "status": "http_error",
              "unit": "unconfirmed", "source_time_zone": "unconfirmed",
              "aggregation_code_meaning": "unconfirmed", "engine_conversion": "blocked",
              "coverage": "not_established"}
    if http_status != 200:
        return result
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("도로 응답은 객체여야 합니다.")
    if payload.get("code") != "SUCCESS":
        result["status"] = "provider_error"
        return result
    rows = payload.get("realUnitTrtmVO")
    count = payload.get("count")
    if not isinstance(rows, list) or type(count) is not int or count < len(rows):
        raise ValueError("도로 응답의 행/건수 형식이 맞지 않습니다.")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("도로 응답의 행은 객체여야 합니다.")
    issues = Counter()
    forms = Counter()
    missing = Counter({k: 0 for k in ("startUnitCode", "endUnitCode", "stdDate", "stdTime",
                                     "timeAvg", "timeMin", "timeMax", "sumTmUnitTypeCode",
                                     "startEndStdTypeCode", "tcsCarTypeCode", "tcsCarTypeDivCode")})
    for row in rows:
        for key in missing:
            missing[key] += not isinstance(row.get(key), str) or not row[key].strip()
        for key, expected in (("startUnitCode", start), ("endUnitCode", end)):
            value = row.get(key)
            if expected is not None and (not isinstance(value, str) or value.strip() != expected):
                issues["requested_direction_mismatch"] += 1
            if isinstance(value, str) and value != value.strip():
                issues["padded_unit_code_fields"] += 1
        avg, low, high = (number(row.get(key)) for key in ("timeAvg", "timeMin", "timeMax"))
        if any(value is None for value in (avg, low, high)):
            issues["missing_or_invalid_time_value_rows"] += 1
        elif not low <= avg <= high:
            issues["min_mean_max_inconsistent_rows"] += 1
        date = row.get("stdDate")
        try:
            if not isinstance(date, str) or not re.fullmatch(r"[0-9]{8}", date):
                raise ValueError
            datetime.strptime(date, "%Y%m%d")
        except ValueError:
            issues["invalid_date_rows"] += 1
        time = row.get("stdTime")
        if isinstance(time, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", time):
            forms["hh_mm"] += 1
        elif isinstance(time, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3])\s*", time):
            forms["hour_only_unresolved_bucket"] += 1
        else:
            forms["missing_or_unrecognized"] += 1
    result.update(status="sample_received" if rows else "empty",
                  reported_count=count, row_count=len(rows), reported_page=payload.get("pageNo"),
                  reported_rows_per_page=payload.get("numOfRows"),
                  missing_or_nontext=dict(missing), issues=dict(sorted(issues.items())),
                  time_forms=dict(sorted(forms.items())))
    return result


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "인수 오류: --help의 필수 인수와 형식을 확인하세요.\n")


def main() -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--http-status", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_response(args.input.read_bytes(), args.start, args.end, args.http_status)
    except (OSError, ValueError):
        print("감사 실패: 입력 파일·JSON 구조를 확인하세요. 원문은 출력하지 않습니다.")
        return 2
    try:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except OSError:
        print("저장 실패: 기존 출력·입력은 보존합니다. 새 경로와 폴더 권한을 확인하세요.")
        return 1
    print("참고 표본 감사 완료. 엔진 변환은 보류 상태입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
