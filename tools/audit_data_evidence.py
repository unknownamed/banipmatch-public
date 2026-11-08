"""허용된 Snapshot의 선언된 출처와 모의 조건을 집계한다. 외부 진위·권한 검증 아님."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.data import load_snapshot_json

FACT_GROUPS = ("locations", "vehicles", "jobs", "windows", "travel_times")
AUDIT_INPUTS = (
    ROOT / "docs/experiments/engine-b0-b3/inputs",
    ROOT / "docs/experiments/engine-sensitivity-2026-11-08/inputs",
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _label(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _range(values: list) -> dict:
    known = [value for value in values if value is not None]
    return {"known": len(known), "null": len(values) - len(known),
            "min": min(known) if known else None, "max": max(known) if known else None}


def audit_snapshot(path: Path) -> dict:
    report = load_snapshot_json(path)
    entry = {"path": _label(path), "valid": report.valid,
             "input_sha256": None, "issues": [asdict(issue) for issue in report.issues]}
    if not report.valid:
        return entry
    snapshot = report.snapshot
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    facts = [item["evidence"] for group in FACT_GROUPS for item in snapshot[group]]
    facts.append(snapshot["change"]["evidence"])
    kinds = Counter(item["kind"] for item in facts)
    references = Counter(item["source_ref"] for item in facts)
    window_minutes = [
        int((datetime.fromisoformat(w["closes_at"].replace("Z", "+00:00"))
             - datetime.fromisoformat(w["opens_at"].replace("Z", "+00:00"))).total_seconds() / 60)
        for w in snapshot["windows"]
    ]
    entry.update({
        "input_sha256": _sha(canonical), "schema_version": snapshot["schema_version"],
        "scenario_id": snapshot["scenario_id"], "declared_data_mode": snapshot["data_mode"],
        "as_of_utc": snapshot["as_of"],
        "counts": {group: len(snapshot[group]) for group in FACT_GROUPS},
        "declared_evidence_kinds": dict(sorted(kinds.items())),
        "declared_source_refs": dict(sorted(references.items())),
        "observed_at_null_count": sum(item["observed_at"] is None for item in facts),
        "fact_bundle_count": len(facts),
        "job_conditions": {
            "frozen_count": sum(item["frozen"] for item in snapshot["jobs"]),
            "departed_count": sum(item["state"] == "departed" for item in snapshot["jobs"]),
            "equipment_types": dict(sorted(Counter(item["equipment_type"] for item in snapshot["jobs"]).items())),
            "gross_weight_kg": _range([item["gross_weight_kg"] for item in snapshot["jobs"]]),
            "service_minutes": _range([item["service_minutes"] for item in snapshot["jobs"]]),
        },
        "vehicle_capacity_kg": _range([item["capacity_kg"] for item in snapshot["vehicles"]]),
        "travel_minutes": _range([item["minutes"] for item in snapshot["travel_times"]]),
        "window_duration_minutes": _range(window_minutes),
        "policy": snapshot["policy"],
    })
    return entry


def build_audit(paths: list[Path]) -> dict:
    files = set()
    for path in paths:
        if path.is_dir():
            children = list(path.glob("*.json"))
            if not children:
                raise ValueError("입력 폴더에 Snapshot JSON이 없습니다.")
            files.update(child.resolve() for child in children)
        else:
            files.add(path.resolve())
    if not files:
        raise ValueError("Snapshot 입력을 하나 이상 지정해야 합니다.")
    entries = [audit_snapshot(path) for path in sorted(files, key=lambda p: (_label(p), str(p)))]
    return {
        "report_version": "1",
        "scope": "declared_snapshot_metadata_only",
        "external_permissions": "not_assessed",
        "representativeness": "not_assessed",
        "counts_are_fact_bundles_not_independent_observations": True,
        "source_sha256_lf": {
            name: _sha((ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("tools/audit_data_evidence.py", "backend/data/validation.py", "backend/data/inputs.py")
        },
        "snapshot_count": len(entries),
        "valid_snapshot_count": sum(entry["valid"] for entry in entries),
        "snapshots": entries,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot의 선언된 출처와 입력 조건 집계")
    parser.add_argument("--inputs", nargs="+", type=Path, default=list(AUDIT_INPUTS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_audit(args.inputs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError):
        print("입력·출력 경로를 확인하세요. 기존 파일은 덮어쓰지 않습니다.", file=sys.stderr)
        return 1
    print(json.dumps({"snapshot_count": report["snapshot_count"],
                      "valid_snapshot_count": report["valid_snapshot_count"]}))
    return 0 if report["snapshot_count"] == report["valid_snapshot_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
