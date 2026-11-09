"""고정 평가의 변경 전후 입력을 감사한다. 솔버·결과·현장 효과를 검증하지 않는다."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.data import validate_snapshot
from backend.data.inputs import _unique_object

PROTOCOL = ROOT / "docs/experiments/engine-evaluation-2026-11-08/protocol.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: dict) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _local_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("평가 묶음 밖의 파일은 읽지 않습니다.")
    return path


def _read_snapshot(path: Path) -> tuple[bytes, dict]:
    raw = path.read_bytes()
    return raw, json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)


def _diff(before, after, path="") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        differences = []
        for key in sorted(before.keys() | after.keys()):
            child = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before or key not in after:
                differences.append(child)
            else:
                differences.extend(_diff(before[key], after[key], child))
        return differences
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [p for index, (a, b) in enumerate(zip(before, after))
                for p in _diff(a, b, path + f"/{index}")]
    return [] if before == after else [path]


def audit_case(root: Path, spec: dict) -> dict:
    required = {"id", "input", "sha256", "before_event", "before_event_sha256", "jobs", "vehicles"}
    if (not isinstance(spec, dict) or not required <= spec.keys()
            or any(not isinstance(spec[key], str) for key in ("id", "input", "sha256", "before_event", "before_event_sha256"))
            or any(type(spec[key]) is not int for key in ("jobs", "vehicles"))):
        raise ValueError("평가 사례 명세가 불완전합니다.")
    entry = {"case_id": spec["id"], "input": spec["input"], "before_event": spec["before_event"],
             "profile": spec.get("profile"), "generation_seed": spec.get("generation_seed"),
             "valid": False, "issues": []}
    try:
        after_raw, after = _read_snapshot(_local_path(root, spec["input"]))
        before_raw, before = _read_snapshot(_local_path(root, spec["before_event"]))
    except (OSError, UnicodeError, ValueError, TypeError):
        entry["issues"].append({"code": "CASE_READ", "path": "", "message": "묶음 내부 UTF-8 JSON과 경로를 확인하세요."})
        return entry

    def issue(code, path, message):
        entry["issues"].append({"code": code, "path": path, "message": message})

    hashes = {"input_raw_sha256": _sha(after_raw), "before_raw_sha256": _sha(before_raw)}
    entry.update(hashes)
    if hashes["input_raw_sha256"] != spec["sha256"]:
        issue("INPUT_HASH_MISMATCH", "/input", "고정한 입력 원본 해시와 다릅니다.")
    if hashes["before_raw_sha256"] != spec["before_event_sha256"]:
        issue("BEFORE_HASH_MISMATCH", "/before_event", "고정한 변경 전 원본 해시와 다릅니다.")
    for label, value in (("before", before), ("after", after)):
        report = validate_snapshot(value)
        if not report.valid:
            entry["issues"].extend({"phase": label, **asdict(item)}
                                   for item in report.issues)
    if any("phase" in item for item in entry["issues"]):
        return entry
    entry.update({"before_input_sha256": _canonical(before), "input_sha256": _canonical(after),
                  "jobs": len(after["jobs"]), "vehicles": len(after["vehicles"]),
                  "declared_data_mode": after["data_mode"],
                  "changed_fields": _diff(before, after)})
    if before["scenario_id"] != spec["id"] or after["scenario_id"] != spec["id"]:
        issue("CASE_ID_MISMATCH", "/scenario_id", "고정 사례 ID가 다릅니다.")
    if len(after["jobs"]) != spec["jobs"] or len(after["vehicles"]) != spec["vehicles"]:
        issue("CASE_COUNT_MISMATCH", "/jobs", "명세에 고정한 작업·차량 수와 다릅니다.")
    if before["data_mode"] != "simulated" or after["data_mode"] != "simulated":
        issue("CASE_MODE_MISMATCH", "/data_mode", "합성 평가 묶음의 선언이 모의와 다릅니다.")

    target_id = after["change"]["new_window_id"]
    target_index = next(i for i, window in enumerate(after["windows"]) if window["window_id"] == target_id)
    old = next((w for w in before["windows"] if w["window_id"] == target_id), None)
    allowed = {f"/windows/{target_index}/opens_at", f"/windows/{target_index}/closes_at"}
    if not entry["changed_fields"] or not set(entry["changed_fields"]) <= allowed:
        issue("UNRELATED_INPUT_CHANGE", "", "확인된 변경은 대상 반입 창의 시작·마감에만 있어야 합니다.")
    if old is None or (after["change"]["previous_opens_at"], after["change"]["previous_closes_at"]) != (old["opens_at"], old["closes_at"]):
        issue("BEFORE_WINDOW_MISMATCH", "/change", "변경 이전 값이 보관한 이전 창과 다릅니다.")
    entry["valid"] = not entry["issues"]
    return entry


def audit_protocol(path: Path) -> dict:
    raw = path.read_bytes()
    protocol = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(protocol, dict) or protocol.get("schema_version") != 1 or not isinstance(protocol.get("cases"), list) or not protocol["cases"]:
        raise ValueError("고정 프로토콜 형식을 확인하세요.")
    cases = [audit_case(path.parent, spec) for spec in protocol["cases"]]
    ids = [entry["case_id"] for entry in cases]
    duplicate_ids = len(ids) != len(set(ids))
    generator_sha = _sha((ROOT / "tools/build_evaluation_inputs.py").read_bytes())
    generator_matches = generator_sha == protocol.get("generator_sha256")
    return {"report_version": "1", "scope": "frozen_synthetic_input_pairs_only",
            "protocol_raw_sha256": _sha(raw), "case_count": len(cases),
            "snapshot_count": 2 * len(cases), "valid_case_count": sum(c["valid"] for c in cases),
            "duplicate_case_ids": duplicate_ids,
            "generator_raw_sha256": generator_sha, "generator_hash_matches_protocol": generator_matches,
            "valid": all(c["valid"] for c in cases) and not duplicate_ids and generator_matches,
            "schedule_validation": "not_run", "solver_execution": "not_run",
            "external_permissions": "not_assessed", "field_representativeness": "not_assessed",
            "source_sha256_lf": {name: _sha((ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
                for name in ("tools/audit_evaluation_data.py", "backend/data/validation.py", "backend/data/inputs.py")},
            "cases": cases}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="고정 평가 입력의 변경 전후 관계·원본 해시 감사")
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit_protocol(args.protocol)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (OSError, UnicodeError, ValueError):
        print("프로토콜과 새 출력 경로를 확인하세요. 기존 파일은 보존했습니다.", file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in ("valid", "case_count", "snapshot_count", "valid_case_count")}))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
