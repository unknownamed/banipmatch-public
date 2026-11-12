"""Offline dispatcher-response preview from verified calculation results.

No contacts, external sends, plan writes or inferred operational promises.
Use: python -m tools.dispatch_response --snapshot INPUT --result RESULT --output NEW_FILE
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from backend.api.contracts import digest, validate
from backend.api.input_preflight import check_input
from backend.api.result_integrity import verify_schedule


CHECKS = {
    "INPUT_MISSING": ("입력 자료 담당", "오류 경로의 누락값과 출처를 확인한 뒤 새 입력으로 다시 계산하세요."),
    "OUT_OF_SCOPE": ("배차 담당자", "현재 모델이 다루지 못하는 작업 조건을 확인하고 별도 대응을 검토하세요."),
    "WINDOW_UNCONFIRMED": ("터미널 정보 확인 담당", "해당 항차의 공식 반입 시작·마감과 확인 시각을 확인하세요. ETA로 대신하지 마세요."),
    "EARLY_ARRIVAL": ("배차 담당자", "반입 시작 이후 도착하는 조정안을 비교하세요. 대기 장소·대기 허용은 별도로 확인하세요."),
    "CUTOFF_EXCEEDED": ("배차 담당자", "기존 차량의 순서·시각 조정 가능성을 비교하세요. 예외 반입은 허가 전까지 가능하다고 가정하지 마세요."),
    "READY_TOO_LATE": ("화주·상차지 확인 담당", "상차 준비 완료 시각을 확인하세요. 앞당길 수 있다고 확인된 경우에만 새 ready_at으로 다시 계산하세요."),
    "VEHICLE_UNAVAILABLE": ("운송사 차량 담당", "차량의 실제 가용·복귀 시각을 확인하세요. 추가 차량은 확보된 조건을 새 입력에 넣은 뒤 비교하세요."),
    "INCOMPATIBLE_EQUIPMENT": ("운송사 차량 담당", "작업에 맞는 장비를 갖춘 가용 차량이 있는지 확인하세요."),
    "CAPACITY_EXCEEDED": ("운송사 차량 담당", "화물 중량과 해당 차량의 적재한도를 확인하세요. 제한을 임의로 늘리지 마세요."),
    "SHIFT_EXCEEDED": ("운송사 차량 담당", "차량의 작업 가능 시간을 확인하세요. 연장 가능 여부를 가정하지 마세요."),
    "FIXED_RESIDUAL_RISK": ("배차 담당자·해당 기사", "출발·고정 작업은 유지하고 실제 진행 상황과 대응 가능 여부를 확인하세요. 자동 취소·재배정하지 마세요."),
    "SEARCH_LIMIT": ("배차 담당자", "계산 시간 안에 배정을 찾지 못한 결과입니다. 입력과 계산 예산을 검토하세요. 현장 불가능으로 단정하지 마세요."),
    "MODEL_INVALID": ("개발·입력 담당", "입력 또는 모델 오류를 확인하세요. 이 결과로 운송 지시를 만들지 마세요."),
}


def assignment_index(rows: list[dict]) -> dict[str, dict]:
    indexed = {row["job_id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("동일 작업의 중복 배정")
    return indexed


def ranked(rows: list[dict]) -> dict[str, dict]:
    """차량별 작업 순서를 1부터 다시 매긴다. 엔진의 sequence는 빈 번호가 있을 수 있어,
    순서와 시각이 그대로인 작업이 번호만 달라 '변경'으로 기사에게 전달되지 않게 한다."""
    indexed = assignment_index(rows)
    out: dict[str, dict] = {}
    by_vehicle: dict[str, list[dict]] = {}
    for row in indexed.values():
        by_vehicle.setdefault(row["vehicle_id"], []).append(row)
    for route in by_vehicle.values():
        for rank, row in enumerate(sorted(route, key=lambda r: r["sequence"]), 1):
            out[row["job_id"]] = {**row, "sequence": rank}
    return out


def job_display(snapshot: dict, job_id: str) -> dict:
    """기사·담당자 화면용 현장 식별 정보(입력에 있을 때만). 내부 job_id는 연결 키로 남는다."""
    job = next(j for j in snapshot["jobs"] if j["job_id"] == job_id)
    place = {loc["location_id"]: loc["name"] for loc in snapshot.get("locations", [])}
    size = {"DRY40": "40ft", "DRY20": "20ft"}.get(job["equipment_type"], job["equipment_type"])
    return {"container_no": job.get("container_no"), "booking_no": job.get("booking_no"), "cargo_owner": job.get("cargo_owner"),
            "origin_name": place.get(job["origin_id"], job["origin_id"]), "terminal_id": job["terminal_id"],
            "voyage_id": job["voyage_id"], "size": size}


def build_response_preview(snapshot: dict, result: dict) -> dict:
    """Recheck a computed candidate, preserving issues and exact schedule differences.

    This is a review artifact, not current DB authority or an approval/dispatch API.
    Unlike optimizer KPI tolerance, communication diffs include any changed time.
    """
    validate("Snapshot", snapshot)
    validate("MethodResult", result)
    check_input(snapshot)
    if (result["result_origin"] != "computed" or result["method"] == "B0"
            or not result["approval_eligible"] or result["validation_status"] != "passed"):
        raise ValueError("독립 검사 통과 상태의 실계산 조정 결과가 필요함")
    if not verify_schedule(snapshot, result):
        raise ValueError("일정 재검사 실패")
    before = ranked(snapshot["baseline_assignments"])
    after = ranked(result["assignments"])
    changed = []
    by_vehicle: dict[str, list[dict]] = {}
    for job_id in sorted(before.keys() | after.keys()):
        old, new = before.get(job_id), after.get(job_id)
        if old == new:
            continue
        kind = "removed_from_plan" if new is None else "newly_assigned" if old is None else "reassigned" if old["vehicle_id"] != new["vehicle_id"] else "schedule_changed"
        fields = sorted(k for k in set(old or {}) | set(new or {}) if k != "job_id" and (old or {}).get(k) != (new or {}).get(k))
        change = {"job_id": job_id, "kind": kind, "changed_fields": fields,
                  "before": deepcopy(old), "after": deepcopy(new), "display": job_display(snapshot, job_id),
                  "instruction": "담당자 확인 전에는 운송 지시가 아닙니다."}
        if new is None:
            change["instruction"] = "조정안에서 미처리로 남았습니다. 담당자 확인이 필요하며 실제 운송 취소를 뜻하지 않습니다."
        changed.append(change)
        # Reassigned jobs must reach both old and new vehicle owners, never only the new one.
        for vehicle_id in sorted({a["vehicle_id"] for a in (old, new) if a is not None}):
            by_vehicle.setdefault(vehicle_id, []).append(deepcopy(change))
    plates = {v["vehicle_id"]: v.get("plate_no") for v in snapshot["vehicles"]}
    followups = []
    for issue in result["issues"]:
        owner, check = CHECKS[issue["code"]]
        followups.append({**deepcopy(issue), "contact_role": owner, "check_next": check,
                          "action_kind": "manual_check", "automatic_resolution": False})
    covered = {i["job_id"] for i in followups}
    for job_id in sorted(set(result["unassigned_job_ids"]) - covered):
        followups.append({"job_id": job_id, "code": "REASON_NOT_PROVIDED", "explanation": "계산 결과에 구체적 미처리 사유가 없습니다.",
                          "proof_level": "not_proven", "evidence_refs": [], "contact_role": "배차·개발 담당자",
                          "check_next": "입력과 계산 결과를 확인하세요. 사유를 임의로 추정하지 마세요.",
                          "action_kind": "manual_check", "automatic_resolution": False})
    return {
        "artifact_version": "response-preview-0.1", "stage": "review_before_approval",
        "plan_id": snapshot["plan_id"], "scenario_id": snapshot["scenario_id"],
        "base_plan_version": snapshot["base_plan_version"], "input_sha256": digest(snapshot),
        "method": result["method"], "result_sha256": digest(result), "data_mode": snapshot["data_mode"],
        "delivery_authorized": False, "external_actions_performed": False,
        "change_reference": {"change_id": snapshot["change"]["change_id"],
                             "verification": snapshot["change"]["verification"],
                             "evidence": deepcopy(snapshot["change"]["evidence"])},
        "changes": changed,
        "vehicle_changes": [{"vehicle_id": vid, "plate_no": plates.get(vid), "changes": rows} for vid, rows in sorted(by_vehicle.items())],
        "followups": followups,
        "unassigned_job_ids": sorted(result["unassigned_job_ids"]),
        "limits": ["자료 파일의 검수 결과이며 현재 서버 계획·권한·유효기간의 확인을 대신하지 않습니다.",
                   "확인할 사항은 담당자 판단을 돕는 안내이며 현장의 원인·해결 가능성·연락 결과를 증명하지 않습니다.",
                   "차량별 변경은 수신자 명단이 아닙니다. 기사 배정·동의·연락 경로는 별도 확인해야 합니다."],
    }


def bind_archived_approval(snapshot: dict, results: dict, plan: dict, approval: dict) -> dict:
    """Validate related saved responses, without granting live send authority."""
    for name, value in (("Results", results), ("Plan", plan), ("Approval", approval)):
        validate(name, value)
    if not (snapshot["plan_id"] == plan["plan_id"] == approval["plan_id"]
            and snapshot["scenario_id"] == plan["scenario_id"] == results["scenario_id"]
            and snapshot["base_plan_version"] == results["base_plan_version"]
            and plan["version"] == approval["version"] == snapshot["base_plan_version"] + 1
            and plan["approval_id"] == approval["approval_id"]
            and results["run_id"] == approval["run_id"] and results["input_sha256"] == digest(snapshot)):
        raise ValueError("저장된 입력·실행·승인·계획 식별/버전 불일치")
    candidates = [r for r in results["results"] if r["method"] == approval["method"]]
    if len(candidates) != 1:
        raise ValueError("승인한 방법의 결과는 하나여야 함")
    result = candidates[0]
    if (assignment_index(plan["assignments"]) != assignment_index(result["assignments"])
            or set(plan["unassigned_job_ids"]) != set(result["unassigned_job_ids"])):
        raise ValueError("승인 계획과 계산 결과 불일치")
    artifact = build_response_preview(snapshot, result)
    artifact.update(stage="archived_approval_review", approval_id=approval["approval_id"],
                    approved_version=approval["version"], run_id=approval["run_id"])
    return artifact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True, help="MethodResult JSON; 설명용 응답은 거절")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    preview = build_response_preview(json.loads(args.snapshot.read_text(encoding="utf-8-sig")),
                                     json.loads(args.result.read_text(encoding="utf-8-sig")))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(preview, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("대응 검토 자료 생성 완료. 승인·외부 발송 없음.")


if __name__ == "__main__":
    main()
