"""Compare one or two saved HJNC observations locally; never call a provider.

The report describes observed field differences, not confirmed operational
changes, provider event times, complete pagination or engine-ready input.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

if __package__:
    from tools.audit_collected_samples import HJNC_FIELDS, audit_hjnc
else:
    from audit_collected_samples import HJNC_FIELDS, audit_hjnc


EXPECTED_SOURCE_REF = "https://www.hjnc.co.kr/esvc/vessel/berthScheduleT"
UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")


def received_time(value: str) -> datetime:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("관측 수신시각은 UTC Z 형식이어야 합니다.")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def observation(raw: bytes, received_at: str) -> tuple[dict, dict]:
    received_time(received_at)
    audit = audit_hjnc(raw)
    if audit["duplicate_nonempty_voyage_ids"] or any(audit["missing_or_nontext"].values()):
        raise ValueError("필수 항목 누락 또는 항차 중복이 있습니다.")
    rows = json.loads(json.loads(raw.decode("utf-8-sig"))["stringContent"])
    # No trimming or invented identifier: ambiguous whitespace must be fixed at
    # the source rather than silently merging two captured rows.
    if any(row["VOY_NO"] != row["VOY_NO"].strip() for row in rows):
        raise ValueError("항차 식별자 앞뒤 공백을 확인해야 합니다.")
    indexed = {row["VOY_NO"]: {key: row[key] for key in HJNC_FIELDS[1:]} for row in rows}
    metadata = {"expected_source_ref": EXPECTED_SOURCE_REF, "received_at": received_at,
                "capture_provenance": "caller_supplied_unverified_capture_and_receipt",
                "bytes": audit["bytes"], "sha256": audit["sha256"],
                "row_count": audit["row_count"], "reported_total": audit["reported_total"],
                "reported_has_next": audit["reported_has_next"],
                "reported_total_matches_rows": audit["reported_total_matches_rows"],
                "page_coverage": "not_established", "source_time_zone": "unconfirmed",
                "source_time_representation": "naive strings preserved"}
    return metadata, indexed


def voyage_key(identifier: str) -> str:
    # Local output links records without copying raw identifiers. This is a
    # deterministic digest, not a promise of anonymization or permission.
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()


def compare_observations(current: bytes, current_received_at: str,
                         previous: bytes | None = None,
                         previous_received_at: str | None = None) -> dict:
    if (previous is None) != (previous_received_at is None):
        raise ValueError("이전 관측 파일과 수신시각은 함께 필요합니다.")
    current_meta, current_rows = observation(current, current_received_at)
    report = {"report_version": 1, "current": current_meta, "previous": None,
              "report_scope": "local_preparation_tool_not_shared_product_contract",
              "comparison_status": "not_comparable_single_observation",
              "provider_change_occurred_at": None,
              "interpretation": "observed_differences_only_not_confirmed_window_changes_or_approval",
              "engine_conversion": "not_performed", "permissions": "not_assessed",
              "voyage_key_scheme": "sha256_of_exact_VOY_NO_not_anonymization",
              "window_observation_differences": [], "etb_observation_differences": [],
              "added_observations": [], "not_observed_in_current": [],
              "common_voyage_count": None, "unchanged_window_count": None,
              "same_raw_sha256": None}
    if previous is None:
        return report
    previous_meta, previous_rows = observation(previous, previous_received_at)
    if received_time(previous_received_at) >= received_time(current_received_at):
        raise ValueError("이전 수신시각은 현재 수신시각보다 앞서야 합니다.")
    common = sorted(set(current_rows) & set(previous_rows))
    report.update(previous=previous_meta, common_voyage_count=len(common),
                  same_raw_sha256=previous_meta["sha256"] == current_meta["sha256"])
    for identifier in common:
        before, after = previous_rows[identifier], current_rows[identifier]
        changes = {key: {"previous_naive": before[key], "current_naive": after[key]}
                   for key in ("YARD_OPEN", "YARD_CLOSE") if before[key] != after[key]}
        if changes:
            report["window_observation_differences"].append({
                "voyage_key_sha256": voyage_key(identifier), "fields": changes,
                "provider_change_occurred_at": None})
        if before["ETB"] != after["ETB"]:
            report["etb_observation_differences"].append({
                "voyage_key_sha256": voyage_key(identifier),
                "previous_naive": before["ETB"], "current_naive": after["ETB"],
                "classification": "etb_observation_difference_only_not_window_change",
                "provider_change_occurred_at": None})
    for key, identifiers in (("added_observations", set(current_rows) - set(previous_rows)),
                              ("not_observed_in_current", set(previous_rows) - set(current_rows))):
        report[key] = [{"voyage_key_sha256": voyage_key(identifier),
                        "classification": "newly_observed" if key == "added_observations"
                        else "not_observed_not_evidence_of_cancellation",
                        "provider_change_occurred_at": None} for identifier in sorted(identifiers)]
    report["unchanged_window_count"] = len(common) - len(report["window_observation_differences"])
    report["comparison_status"] = ("not_comparable_no_common_voyage" if not common else
                                   "window_observation_differences_found"
                                   if report["window_observation_differences"] else
                                   "no_window_difference_observed")
    return report


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unexpected input, which may include secrets.
        self.exit(2, "인수 오류: --help의 필수 인수와 형식을 확인하세요.\n")


def main() -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--current-received-at", required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--previous-received-at")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if (args.previous is None) != (args.previous_received_at is None):
            raise ValueError("이전 관측 인수는 함께 필요합니다.")
        inputs = [args.current] + ([args.previous] if args.previous is not None else [])
        if args.output.resolve() in [path.resolve() for path in inputs]:
            raise ValueError("입력과 출력 경로가 같습니다.")
        if args.output.exists():
            print("기존 출력은 보존합니다. 새 출력 경로를 사용하세요.")
            return 1
        report = compare_observations(args.current.read_bytes(), args.current_received_at,
                                      args.previous.read_bytes() if args.previous is not None else None,
                                      args.previous_received_at)
    except (OSError, ValueError, TypeError, RecursionError):
        print("관측 비교 실패: 입력 형식·필수 항목·UTC 수신시각·순서를 확인하세요.")
        return 2
    try:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except OSError:
        print("보고서 저장 실패: 새 출력 경로와 폴더 권한을 확인하세요.")
        return 1
    print("관측 보고서 저장 완료. 관측 차이는 확정 반입 변경·변경 발생시각·승인이 아닙니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
