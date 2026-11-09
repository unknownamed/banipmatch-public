"""Build a read-only showcase of frozen evaluation records; never call the solver.

Run from the repository root, or use --check in CI. Only showcase.json/showcase.md
are written; all inputs and original engine/audit flags remain unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.evaluate_engine import audit_result, make_pairs
from backend.api.contracts import validate

EVALUATION = ROOT / "docs/experiments/engine-evaluation-2026-11-08"
SOURCE_COMMIT = "0d2640bec9886fe344166809123bc9a2cc19bb92"
# These identify the published evidence, rather than accepting a self-consistent
# rewrite of a protocol, its inputs, and its results as the original experiment.
# Hash UTF-8 bytes after CRLF -> LF only, matching the committed Git blobs.
FROZEN_HASHES = {
    "protocol.json": "1e08d7e97e155f651aed79b039998b4ef94ac3bc35a29bfd1369297fec0e4e4e",
    "results/results.jsonl": "c2c01698fbc8dfe78c32b5ec3d017aa0004a5e4d204e31cad5b1cdfcbf684821",
    "results/metadata.json": "5451005ba1ce5e60d19c9d27a378091cea4c3ca227451d9570c41d4cb6e8a8fd",
    "results/summary.json": "b521fc530ca55ebb5c1d9c4f3263f10354b5d1ad86a8c4c31379d757a1f325dd",
}
LABELS = {"cutoff": "마감 단축", "opening": "시작 지연", "readiness": "준비 지연", "fixed": "고정 작업 위험"}
ORIGINAL_RESULTS_BYTE_SHA256 = "435bb9fc0d09195f80a29a51eac03c7951777d1615d67f2f8b233eb059ee23af"


def normalized_bytes(value):
    """Ignore checkout CRLF conversion only; preserve spaces, BOM and lone CR."""
    return value.replace(b"\r\n", b"\n")


def sha256(path):
    return hashlib.sha256(normalized_bytes(path.read_bytes())).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def checked_path(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Evidence path escapes evaluation directory")
    return path


def check_source_metadata(protocol, metadata, directory):
    if (metadata["git_head"] != SOURCE_COMMIT or metadata["base_git_head"] != protocol["base_git_head"]
            or metadata["protocol_sha256"] != sha256(directory / "protocol.json")
            or not metadata["completed"] or metadata["dirty_tracked"]
            or metadata["expected_runs"] != 80 or metadata["completed_runs"] != 80
            or metadata["failures"] != 0 or metadata["worker_count"] != 1):
        raise ValueError("Invalid frozen source metadata")
    if sha256(directory / "results/tracked.diff") != metadata["tracked_diff_sha256"]:
        raise ValueError("Source tracked diff hash mismatch")
    for name, digest in metadata["source_sha256"].items():
        # Verify historical source, not today's engine. This publishes prior
        # calculations and must never reinterpret them as a current server run.
        blob = subprocess.check_output(["git", "show", f"{SOURCE_COMMIT}:{name}"], cwd=ROOT)
        if hashlib.sha256(blob).hexdigest() != digest:
            raise ValueError(f"Historical source hash mismatch: {name}")
    for name, digest in protocol["engine_source_sha256"].items():
        if metadata["source_sha256"].get(name) != digest:
            raise ValueError("Protocol/source engine hash mismatch")


def validate_records(protocol, snapshots, records):
    """Reject incomplete grids and independently recheck every raw record."""
    methods, seeds = protocol["methods"], protocol["solver_seeds"]
    if methods != ["B0", "B1", "B2", "B3"] or seeds != [0, 17] or len(protocol["cases"]) != 10:
        raise ValueError("Unexpected frozen method/seed/case selection")
    cases = {case["id"]: case for case in protocol["cases"]}
    if len(cases) != 10:
        raise ValueError("Duplicate case")
    expected = {(case_id, seed, method) for case_id in cases for seed in seeds for method in methods}
    seen = set()
    for row in records:
        key = (row["case_id"], row["seed"], row["method"])
        if key not in expected or key in seen:
            raise ValueError("Unexpected or duplicate case/seed/method record")
        seen.add(key)
        case = cases[row["case_id"]]
        result = row["result"]
        if ("error" in row or row["input_sha256"] != case["sha256"]
                or row["budget_seconds"] != case["budget_seconds"] or result["method"] != row["method"]):
            raise ValueError("Raw record provenance/method mismatch")
        settings = result["execution_metadata"]["solver_settings"]
        if settings["seed"] != row["seed"] or settings["time_limit_seconds"] != case["budget_seconds"]:
            raise ValueError("Raw result solver seed/budget mismatch")
        actual_audit = audit_result(snapshots[row["case_id"]], result)
        if actual_audit != row["audit"] or actual_audit["failed"]:
            raise ValueError("Independent audit mismatch or failure")
    if seen != expected:
        raise ValueError("Missing frozen records")


def comparison(b2, b3):
    a, b = b2["result"], b3["result"]
    ids_a = sorted(row["job_id"] for row in a["assignments"])
    ids_b = sorted(row["job_id"] for row in b["assignments"])
    ma, mb = a["metrics"], b["metrics"]
    return dict(same_served_job_set=ids_a == ids_b, b2_served_job_ids=ids_a, b3_served_job_ids=ids_b,
                equal_unassigned_count=ma["unassigned_count"] == mb["unassigned_count"],
                equal_fixed_risk_count=ma["fixed_risk_count"] == mb["fixed_risk_count"],
                delta_changed_jobs=len(mb["changed_job_ids"]) - len(ma["changed_job_ids"]),
                delta_travel_minutes=mb["movable_travel_minutes"] - ma["movable_travel_minutes"])


def build_bundle(directory=EVALUATION):
    directory = Path(directory)
    for name, digest in FROZEN_HASHES.items():
        if sha256(directory / name) != digest:
            raise ValueError(f"Frozen evidence hash mismatch: {name}")
    protocol, metadata = read_json(directory / "protocol.json"), read_json(directory / "results/metadata.json")
    check_source_metadata(protocol, metadata, directory)
    snapshots = {}
    for case in protocol["cases"]:
        for field, hash_field in (("input", "sha256"), ("before_event", "before_event_sha256")):
            path = checked_path(directory, case[field])
            if sha256(path) != case[hash_field]:
                raise ValueError(f"Input hash mismatch: {case['id']}")
        snapshot = read_json(checked_path(directory, case["input"]))
        validate("Snapshot", snapshot)
        if snapshot["data_mode"] != "simulated":
            raise ValueError("Showcase requires synthetic input")
        snapshots[case["id"]] = snapshot
    records = [json.loads(line) for line in (directory / "results/results.jsonl").read_text(encoding="utf-8").splitlines()]
    validate_records(protocol, snapshots, records)
    pairs = make_pairs(records)
    summary = read_json(directory / "results/summary.json")
    if (len(records) != summary["runs"] or len(pairs) != summary["pairs"]
            or sum(p["identical_assigned_set"] and p["equal_count_comparable"] for p in pairs)
            != summary["identical_workload_comparable"]):
        raise ValueError("Summary/pair mismatch")
    lookup = {(r["case_id"], r["seed"], r["method"]): dict(r, source_jsonl_line=i)
              for i, r in enumerate(records, 1)}
    cases = []
    for case in protocol["cases"]:
        methods = {method: lookup[(case["id"], 0, method)] for method in protocol["methods"]}
        cases.append(dict(case_id=case["id"], label=f"{LABELS[case['profile']]} · {case['jobs']}건 · 생성 시드{case['generation_seed']}",
                          profile=case["profile"], job_count=case["jobs"], vehicle_count=case["vehicles"],
                          generation_seed=case["generation_seed"], budget_seconds=case["budget_seconds"],
                          snapshot=snapshots[case["id"]], methods=methods,
                          comparison=comparison(methods["B2"], methods["B3"])))
    return dict(schema_version="1.0", evidence_kind="frozen_synthetic_evaluation",
                provenance=dict(source_commit=SOURCE_COMMIT, protocol_sha256=FROZEN_HASHES["protocol.json"],
                                hash_convention="UTF-8 bytes with CRLF normalized to LF only; no other whitespace normalization",
                                original_results_byte_sha256=ORIGINAL_RESULTS_BYTE_SHA256,
                                metadata_sha256=FROZEN_HASHES["results/metadata.json"],
                                results_sha256=FROZEN_HASHES["results/results.jsonl"],
                                summary_sha256=FROZEN_HASHES["results/summary.json"],
                                source_sha256=metadata["source_sha256"],
                                input_sha256_by_case={c["id"]: c["sha256"] for c in protocol["cases"]}),
                selection=dict(solver_seed=0, methods=protocol["methods"], case_count=10, record_count=40),
                context=dict(total_records=80, total_pairs=20, summary=summary, pairs=pairs), cases=cases)


def markdown(bundle):
    lines = ["# 공개 시연용 고정 모의 평가 근거", "",
             "기존 80회 결과를 다시 계산하지 않고 읽기 전용으로 묶었다. 모든 10개 입력의 솔버 시드0 B0~B3 40개 원시 결과와 전체80회·20쌍 맥락을 제공한다. 유리한 사례를 선택하지 않았다.", "",
             "원시 `validation_status=not_run`, `approval_eligible=false`를 보존했다. `audit`은 별도 일정 검사 기록이며 API 실행·내부 승인·외부 예약 변경이 아니다. B0는 원안 위험 진단이며 일정 승인 대상이 아니다.", "",
             "변경 감소의 현장 시간·비용·탄소 효과는 미확인이다. 같은 미처리 수라도 처리 작업 ID가 다르면 동일 업무 효율 개선으로 합치지 않는다. 고정 위험과 솔버의 단계별 증명 상태는 원시 결과에 함께 있다.", "",
             "전체80회: 별도 일정 검사60/60, B0 보존20/20, B2/B3 같은 처리 작업 집합14/20쌍, B2/B3 전체 최적성 증명35/40회. 50건 사례에서는 B3 이점·전체 최적성을 확인하지 못했다.", "",
             "| 사례(솔버 시드0) | 미처리 B2→B3 | 변경 B2→B3 | 이동 분 B2→B3 | 고정 위험 B2→B3 | 처리 집합 | 전체 증명 B2→B3 |", "|---|---:|---:|---:|---:|---|---|"]
    for case in bundle["cases"]:
        a, b = (case["methods"][m]["result"] for m in ("B2", "B3"))
        ma, mb = a["metrics"], b["metrics"]
        lines.append(f"| {case['label']} | {ma['unassigned_count']}→{mb['unassigned_count']} | {len(ma['changed_job_ids'])}→{len(mb['changed_job_ids'])} | {ma['movable_travel_minutes']}→{mb['movable_travel_minutes']} | {ma['fixed_risk_count']}→{mb['fixed_risk_count']} | {'같음' if case['comparison']['same_served_job_set'] else '다름'} | {a['objective_proven']}→{b['objective_proven']} |")
    lines.extend(["", "## 재현·추적", "", "`python tools/build_showcase_evidence.py --check`는 원시 파일·입력·출처 커밋 소스 해시, 80개 방법/시드 조합, 독립 일정 검사를 확인하고 산출물을 대조한다. 솔버를 호출하지 않는다. 새 시각 정보를 생성하지 않는다.", "", "파일 해시와 산출물 대조는 Git의 운영체제별 줄바꿈 변환을 허용하기 위해 UTF-8 바이트의 CRLF만 LF로 정규화한다. 공백·내용·BOM·단독 CR은 변경하지 않으며, 공백 한 글자 변경도 실패한다. `provenance.hash_convention`이 이 규칙을 명시한다. `results_sha256`은 저장소 LF 기준이고, 원래 Windows 실행의 CRLF 원본 바이트 해시는 `original_results_byte_sha256`에 별도로 보존했다. 입력·프로토콜·메타데이터에 남은 기존 실행 해시는 바꾸지 않았다.", "", "[JSON](showcase.json)의 `provenance`에 SHA-256과 출처 커밋을, 각 방법의 `source_jsonl_line`에 [results.jsonl](results/results.jsonl)의 1부터 시작하는 행 번호를 기록했다. 각 `methods` 항목은 행 번호 외 원시 기록을 그대로 보존한다. 실행 가능한 해와 최적성 증명은 서로 다르며 `solution_status`, `objective_proven`, `objective_stages`를 확인한다.", "", f"출처 커밋: `{SOURCE_COMMIT}`", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        bundle = build_bundle(EVALUATION)
        outputs = {"showcase.json": json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", "showcase.md": markdown(bundle)}
        for name, content in outputs.items():
            path = EVALUATION / name
            if args.check:
                if not path.exists() or normalized_bytes(path.read_bytes()) != content.encode("utf-8"):
                    raise ValueError(f"Showcase differs; regenerate: {name}")
            else:
                path.write_bytes(content.encode("utf-8"))
        print("Showcase verified: 10 cases, 40 selected records, full 80-record/20-pair context; no solver run.")
        return 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Showcase validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
