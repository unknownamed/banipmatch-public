"""Freeze and exercise synthetic data-gap cases without provider calls or approvals.

This is an integration acceptance pack, not a performance benchmark. No live
value is copied into a synthetic record. The existing frozen 80-run set is read
neither as input nor as a tuning target.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter

from backend.api.contracts import ApiError, DRAFT, ROOT, validate
from backend.api.input_preflight import check_input
from backend.engine import solve
from tools.evaluate_engine import audit_result, make_pairs

METHODS = ("B0", "B1", "B2", "B3")
SPECS = (
    ("cutoff", "확인된 마감 단축", None, "원안·조정안의 처리 수준과 변경 부담을 비교한다."),
    ("opening", "반입 시작 지연", None, "조기 도착을 자동 대기 허용으로 해결하지 않는다."),
    ("fixed_risk", "출발 작업의 마감 위험", None, "출발 작업을 보존하고 남은 위험을 따로 표시한다."),
    ("ready_missing", "화물 준비시각 없음", "INPUT_INCOMPLETE", "운송사 확인이 필요하며 0시/현재시각으로 채우지 않는다."),
    ("ready_recovered", "준비시각을 확인한 모의 비교", None, "추가 확인을 가정한 별도 입력이다. 실제 현장 개선량이 아니다."),
    ("route_missing", "방향별 이동시간 없음", "INPUT_INCOMPLETE", "반대 방향 값이나 0분으로 대체하지 않는다."),
    ("return_unknown", "고정 작업 복귀 미확인", "INPUT_INCOMPLETE", "차량을 즉시 가용으로 만들지 않는다."),
    ("window_unconfirmed", "반입시간 변경 미확인", "WINDOW_UNCONFIRMED", "선박 ETA·기상만으로 반입시간을 확정하지 않는다."),
    ("future_evidence", "기준시각 이후 자료", "INPUT_INVALID", "나중에 받은 근거를 당시 알았던 자료로 계산하지 않는다."),
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def at(value):
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not value.endswith("Z") or moment.utcoffset() != timedelta(0) or moment.second or moment.microsecond:
        raise ValueError("UTC minute boundary required")
    return moment


def make_cases(anchor="2026-11-10T00:00:00Z"):
    source = json.loads((DRAFT / "예제 데이터/01_snapshot.json").read_text(encoding="utf-8"))
    delta = at(anchor) - at(source["as_of"])

    def shifted(node):
        if isinstance(node, dict):
            return {key: (datetime.fromisoformat(value.replace("Z", "+00:00")) + delta).isoformat().replace("+00:00", "Z")
                    if isinstance(value, str) and (key.endswith("_at") or key in {"as_of", "input_valid_until"})
                    else shifted(value) for key, value in node.items()}
        return [shifted(v) for v in node] if isinstance(node, list) else node

    def stamp(minutes):
        return (at(anchor) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

    cases = []
    for name, title, expected, explanation in SPECS:
        snapshot = shifted(deepcopy(source))
        snapshot.update(scenario_id=f"data_demo_{name}", plan_id=f"data_demo_plan_{name}")
        snapshot["change"]["change_id"] = f"data_demo_change_{name}"
        # Original fixture timings are shifted together; values remain invented.
        for rows in (snapshot["locations"], snapshot["vehicles"], snapshot["jobs"], snapshot["windows"],
                     snapshot["travel_times"], [snapshot["change"]]):
            for row in rows:
                row["evidence"]["source_ref"] = f"synthetic:data-demo-acceptance:{name}"
        if name == "opening":
            snapshot["windows"][0].update(opens_at=stamp(60), closes_at=stamp(180))
        elif name == "fixed_risk":
            snapshot["windows"][0]["closes_at"] = stamp(10)
        elif name == "ready_missing":
            snapshot["jobs"][3]["ready_at"] = None
        elif name == "ready_recovered":
            snapshot["jobs"][3]["ready_at"] = stamp(30)
        elif name == "route_missing":
            snapshot["travel_times"] = [row for row in snapshot["travel_times"] if
                 (row["from_location_id"], row["to_location_id"]) != ("O", "HJNC")]
        elif name == "return_unknown":
            snapshot["baseline_assignments"][0]["return_at"] = None
            snapshot["vehicles"][0]["available_at"] = None
        elif name == "window_unconfirmed":
            for row in (snapshot["change"], snapshot["windows"][0]):
                row.update(verification="unconfirmed", confirmed_by=None, confirmed_at=None)
        elif name == "future_evidence":
            snapshot["jobs"][1]["evidence"]["received_at"] = stamp(1)
        validate("Snapshot", snapshot)
        cases.append({"id": name, "title": title, "expected_preflight": expected,
                      "explanation": explanation, "snapshot": snapshot})
    return cases


def source_hashes():
    paths = [*sorted((ROOT / "backend/engine").glob("*.py")),
             *sorted((ROOT / "backend/data").rglob("*.py")),
             ROOT / "backend/api/input_preflight.py", ROOT / "backend/api/result_integrity.py",
             ROOT / "tools/evaluate_engine.py", Path(__file__).resolve()]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def build(output, anchor):
    cases = make_cases(anchor)  # Declare all cases before any solve call.
    output.mkdir(parents=True, exist_ok=False)
    (output / "inputs").mkdir()
    manifest = []
    for case in cases:
        snapshot = case["snapshot"]
        filename = f"inputs/{case['id']}.json"
        write_new(output / filename, snapshot)
        manifest.append({k: v for k, v in case.items() if k != "snapshot"} |
                        {"input": filename, "canonical_sha256": digest(snapshot)})
    protocol = {"version": 1, "kind": "simulated", "purpose": "data_gap_acceptance_not_field_evaluation",
                "anchor": anchor, "methods": list(METHODS), "seed": 42, "time_limit_seconds": 3,
                "external_actions_enabled": False, "source_hashes": source_hashes(), "cases": manifest}
    write_new(output / "protocol.json", protocol)
    return protocol


def run(protocol_path, output, solver=solve):
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if (protocol["version"] != 1 or protocol["kind"] != "simulated" or protocol["methods"] != list(METHODS)
            or protocol["source_hashes"] != source_hashes()):
        raise ValueError("Protocol or source mismatch; freeze a separate new pack")
    cases = []
    seen = set()
    for case in protocol["cases"]:
        path = (protocol_path.parent / case["input"]).resolve()
        if not path.is_relative_to(protocol_path.parent.resolve()) or case["id"] in seen:
            raise ValueError("Invalid case path or duplicate case")
        seen.add(case["id"])
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        validate("Snapshot", snapshot)
        if snapshot["data_mode"] != "simulated" or digest(snapshot) != case["canonical_sha256"]:
            raise ValueError("Input mode or hash mismatch")
        cases.append((case, snapshot))
    if len(cases) != len(SPECS):
        raise ValueError("Missing acceptance cases")
    output.mkdir(parents=True, exist_ok=False)
    records, outcomes = [], []
    with (output / "results.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for case, original in cases:
            code = None
            try:
                check_input(original)
            except ApiError as error:
                code = error.code
            outcome = {"case_id": case["id"], "preflight": code, "expected": case["expected_preflight"],
                       "passed": code == case["expected_preflight"], "solver_calls": 0}
            # Failed preflight must not be replaced by a calculation with zero-filled inputs.
            if code is None and outcome["passed"]:
                fixed_ids = {job["job_id"] for job in original["jobs"] if job["frozen"]}
                fixed = {row["job_id"]: row for row in original["baseline_assignments"] if row["job_id"] in fixed_ids}
                for method in METHODS:
                    snapshot = deepcopy(original)
                    record = {"case_id": case["id"], "method": method, "input_sha256": digest(original),
                              "budget_seconds": protocol["time_limit_seconds"], "seed": protocol["seed"]}
                    started = perf_counter()
                    try:
                        result = solver(snapshot, method, {"time_limit_seconds": protocol["time_limit_seconds"],
                                                          "seed": protocol["seed"]})
                        record["result"] = result
                        if digest(snapshot) != digest(original) or result["method"] != method:
                            raise ValueError("Input mutation or wrong method")
                        record["audit"] = audit_result(original, result)
                        preserved = {row["job_id"]: row for row in result["assignments"] if row["job_id"] in fixed_ids} == fixed
                        if not preserved or record["audit"]["failed"]:
                            raise ValueError("Fixed record or independent schedule check failed")
                        if method != "B0" and record["audit"]["schedule"] != "passed":
                            raise ValueError("Complete-input demo did not produce a validated schedule")
                        if case["id"] == "fixed_risk" and result["metrics"]["fixed_risk_count"] == 0:
                            raise ValueError("Fixed work risk disappeared")
                        record["fixed_preserved"] = True
                    except Exception as error:
                        # Preserve failed runs, no outcome-based regeneration. No provider data here.
                        record["error_type"] = type(error).__name__
                        record["audit"] = {"schedule": "error", "failed": True}
                        outcome["passed"] = False
                    outcome["solver_calls"] += 1
                    record["wall_ms"] = round((perf_counter() - started) * 1000, 3)
                    records.append(record)
                    stream.write(canonical(record) + "\n")
                    stream.flush()
            outcomes.append(outcome)
    summary = {"kind": "simulated", "purpose": protocol["purpose"], "protocol_sha256": digest(protocol),
               "cases": outcomes, "passed": all(row["passed"] for row in outcomes),
               "solver_calls": len(records), "pairs": make_pairs(records),
               "limitations": ["not_live_api_or_browser_test", "not_field_effect", "no_approval_or_external_action",
                               "reference_panels_are_separate_from_engine_snapshot"]}
    write_new(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("build")
    freeze.add_argument("--output", required=True, type=Path)
    freeze.add_argument("--as-of", default="2026-11-10T00:00:00Z")
    execute = commands.add_parser("run")
    execute.add_argument("--protocol", required=True, type=Path)
    execute.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "build":
        value = build(args.output, args.as_of)
        print(json.dumps({"cases": len(value["cases"]), "kind": value["kind"]}))
        return 0
    value = run(args.protocol, args.output)
    print(json.dumps({"passed": value["passed"], "cases": len(value["cases"]), "solver_calls": value["solver_calls"]}))
    return 0 if value["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
