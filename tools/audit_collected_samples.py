"""로컬 HJNC 응답과 광양항 CSV를 재집계한다. 네트워크·식별자 출력·입력 변환은 없다."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re


GATE_COLUMNS = ("차량번호", "진입게이트", "진입일시", "진출게이트", "진출일시", "작업시간")
HJNC_FIELDS = ("VOY_NO", "YARD_OPEN", "YARD_CLOSE", "ETB")


def source_info(raw: bytes) -> dict:
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def audit_hjnc(raw: bytes) -> dict:
    envelope = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(envelope, dict) or not isinstance(envelope.get("stringContent"), str):
        raise ValueError("HJNC 응답에 stringContent 문자열이 필요합니다.")
    rows = json.loads(envelope["stringContent"])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("HJNC stringContent는 객체 배열이어야 합니다.")
    ids = [row.get("VOY_NO") for row in rows if isinstance(row.get("VOY_NO"), str) and row["VOY_NO"].strip()]
    counts = {key: sum(not isinstance(row.get(key), str) or not row[key].strip()
                       for row in rows) for key in HJNC_FIELDS}
    ranges = {}
    for key in HJNC_FIELDS[1:]:
        values = [row[key] for row in rows if isinstance(row.get(key), str) and row[key].strip()]
        try:
            for value in values:
                datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError(f"HJNC {key}의 날짜 형식이 예상과 다릅니다.") from None
        ranges[key] = [min(values), max(values)] if values else None
    total = envelope.get("totalElements")
    has_next = envelope.get("hasNext")
    if total is not None and type(total) is not int:
        raise ValueError("HJNC totalElements는 정수여야 합니다.")
    if has_next is not None and type(has_next) is not bool:
        raise ValueError("HJNC hasNext는 불리언이어야 합니다.")
    return {**source_info(raw), "row_count": len(rows), "unique_nonempty_voyage_ids": len(set(ids)),
            "duplicate_nonempty_voyage_ids": len(ids) - len(set(ids)), "missing_or_nontext": counts,
            "naive_time_ranges": ranges, "reported_total": total,
            "reported_has_next": has_next,
            "reported_total_matches_rows": type(total) is int and total == len(rows),
            "time_zone": "unconfirmed", "change_history": "not_established",
            "coverage_and_permissions": "not_established"}


def audit_gate(raw: bytes) -> dict:
    rows = csv.reader(io.StringIO(raw.decode("cp949"), newline=""), strict=True)
    if next(rows, None) != list(GATE_COLUMNS):
        raise ValueError("광양항 CSV의 열/순서가 예상과 다릅니다.")
    counts = Counter()
    missing = Counter({key: 0 for key in GATE_COLUMNS})
    elapsed = []
    differences = Counter()
    for row in rows:
        counts["physical_data_rows"] += 1
        if len(row) != len(GATE_COLUMNS):
            raise ValueError(f"CSV 레코드 {counts['physical_data_rows']}의 열 수가 맞지 않습니다.")
        if not any(value.strip() for value in row):
            counts["all_fields_empty_rows"] += 1
            continue
        counts["nonempty_rows"] += 1
        entry = dict(zip(GATE_COLUMNS, row))
        for key, value in entry.items():
            missing[key] += not value.strip()
        counts["masked_plate_rows"] += "*" in entry["차량번호"]
        try:
            start = datetime.strptime(entry["진입일시"], "%Y-%m-%d %H:%M")
            end = datetime.strptime(entry["진출일시"], "%Y-%m-%d %H:%M")
        except ValueError:
            counts["invalid_time_rows"] += 1
            continue
        minutes = int((end - start).total_seconds() // 60)
        if minutes < 0:
            counts["negative_elapsed_rows"] += 1
            continue
        elapsed.append(minutes)
        match = re.fullmatch(r"([0-9]+):([0-5][0-9])", entry["작업시간"])
        if match is None:
            counts["invalid_work_time_rows"] += 1
            continue
        work_minutes = int(match[1]) * 60 + int(match[2])
        differences[minutes - work_minutes] += 1
    elapsed.sort()
    statistics = None
    if elapsed:
        statistics = {"count": len(elapsed), "min": elapsed[0], "max": elapsed[-1],
                      **{name: elapsed[math.ceil(len(elapsed) * p) - 1]
                         for name, p in (("p50", .5), ("p90", .9), ("p95", .95))}}
    keys = ("physical_data_rows", "all_fields_empty_rows", "nonempty_rows", "masked_plate_rows",
            "invalid_time_rows", "negative_elapsed_rows", "invalid_work_time_rows")
    return {**source_info(raw), "encoding": "cp949", **{key: counts[key] for key in keys},
            "missing_by_column_nonempty": dict(missing),
            "elapsed_vs_work_time_comparable_rows": sum(differences.values()),
            "elapsed_vs_work_time_mismatch_rows": sum(n for delta, n in differences.items() if delta),
            "elapsed_minus_work_minutes_histogram": {str(k): differences[k] for k in sorted(differences)},
            "elapsed_minutes_nearest_rank": statistics,
            "meaning": "terminal_entry_to_exit_only; not HJNC queue/service or road travel",
            "calibration_status": "not_used"}


def build_audit(hjnc: bytes, gate: bytes) -> dict:
    return {"report_version": 1, "external_permissions": "not_assessed",
            "hjnc": audit_hjnc(hjnc), "gwangyang_gate": audit_gate(gate)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hjnc", type=Path, required=True)
    parser.add_argument("--gate-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.resolve() in (args.hjnc.resolve(), args.gate_csv.resolve()):
            raise ValueError("출력은 입력과 다른 경로여야 합니다.")
        report = build_audit(args.hjnc.read_bytes(), args.gate_csv.read_bytes())
    except (OSError, ValueError, csv.Error):
        print("자료를 읽거나 해석하지 못했습니다. 파일·인코딩·열·날짜 형식을 확인하세요.")
        return 2
    try:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except OSError:
        print("보고서 저장 실패: 상위 폴더와 권한을 확인하고 새 출력 경로를 사용하세요.")
        return 1
    print("집계 완료. 자료 진위·사용 권한·현장 대표성·엔진 입력 적합성 판정은 별도입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
