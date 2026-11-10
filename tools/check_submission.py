"""Verify an extracted submission bundle without a Git checkout or network."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_submission import MANIFEST, EVALUATION, SOURCE_COMMIT, safe_path


def verify_files(root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1" or manifest.get("stage") != "review_draft":
        raise ValueError("Unsupported submission manifest")
    names = set()
    for row in manifest["files"]:
        name = safe_path(row["path"])
        path = root / name
        if name in names or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Duplicate or escaping entry: {name}")
        names.add(name)
        data = path.read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"File hash/size mismatch: {name}")
    # Run before installing dependencies or starting the app: extra files are not silently trusted.
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
              and "__pycache__" not in p.parts}
    if actual != names | {MANIFEST}:
        raise ValueError(f"Unexpected/missing files: {sorted(actual ^ (names | {MANIFEST}))[:5]}")
    report = json.loads((root / "report/report-build.json").read_text(encoding="utf-8"))
    pdf = root / "report/반입맞춤_문제해결_보고서_검토본.pdf"
    if (report["source_commit"] != manifest["source_commit"]
            or report["pdf_sha256"] != hashlib.sha256(pdf.read_bytes()).hexdigest()
            or not 1 <= report["page_count"] <= 20):
        raise ValueError("Report/source binding mismatch")
    for name, expected in report.get("inputs", {}).items():
        if name not in names or hashlib.sha256((root / safe_path(name)).read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected:
            raise ValueError(f"Report input mismatch: {name}")
    return manifest


def verify_frozen(root: Path) -> dict:
    from tools import build_showcase_evidence as frozen
    from tools.evaluate_engine import make_pairs
    from backend.api.contracts import validate
    directory = root / EVALUATION
    for name, expected in frozen.FROZEN_HASHES.items():
        if frozen.sha256(directory / name) != expected:
            raise ValueError(f"Frozen record changed: {name}")
    protocol = frozen.read_json(directory / "protocol.json")
    metadata = frozen.read_json(directory / "results/metadata.json")
    if (metadata["git_head"] != SOURCE_COMMIT or not metadata["completed"] or metadata["dirty_tracked"]
            or metadata["base_git_head"] != protocol["base_git_head"]
            or metadata["protocol_sha256"] != frozen.sha256(directory / "protocol.json")
            or metadata["completed_runs"] != 80 or metadata["expected_runs"] != 80
            or metadata["failures"] != 0 or metadata["worker_count"] != 1
            or frozen.sha256(directory / "results/tracked.diff") != metadata["tracked_diff_sha256"]):
        raise ValueError("Historical run metadata mismatch")
    for name, expected in metadata["source_sha256"].items():
        path = root / "submission-evidence/historical" / SOURCE_COMMIT / safe_path(name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Historical source changed: {name}")
    snapshots = {}
    for case in protocol["cases"]:
        before = frozen.checked_path(directory, case["before_event"])
        if frozen.sha256(before) != case["before_event_sha256"]:
            raise ValueError("Before-event input changed")
        path = frozen.checked_path(directory, case["input"])
        if frozen.sha256(path) != case["sha256"]:
            raise ValueError("Frozen input changed")
        snapshot = frozen.read_json(path)
        validate("Snapshot", snapshot)
        if snapshot["data_mode"] != "simulated":
            raise ValueError("Frozen evaluation must remain simulated")
        snapshots[case["id"]] = snapshot
    records = [json.loads(x) for x in (directory / "results/results.jsonl").read_text(encoding="utf-8").splitlines()]
    frozen.validate_records(protocol, snapshots, records)
    pairs = make_pairs(records)
    summary = frozen.read_json(directory / "results/summary.json")
    if len(records) != summary["runs"] or len(pairs) != summary["pairs"]:
        raise ValueError("Frozen summary mismatch")
    return {"runs": len(records), "pairs": len(pairs), "historical_source_files": len(metadata["source_sha256"]),
            "same_work_pairs": sum(p["identical_assigned_set"] and p["equal_count_comparable"] for p in pairs),
            "solver_rerun": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--files-only", action="store_true", help="stdlib integrity check only")
    args = parser.parse_args()
    manifest = verify_files(args.root)
    result = {"files": len(manifest["files"]), "source_commit": manifest["source_commit"],
              "stage": manifest["stage"], "verified": True}
    if not args.files_only:
        result["frozen_evaluation"] = verify_frozen(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
