"""Reproduce B0-B3 comparisons from explicitly simulated JSON snapshots."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.engine import solve
from backend.engine import optimization  # Load the dependency before timing any method.


def main():
    parser = argparse.ArgumentParser(description="모의 입력 B0~B3 비교, 외부 API 호출 없음")
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--time-limit-seconds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    config = {"seed": args.seed, "time_limit_seconds": args.time_limit_seconds}
    records, summary = [], []
    for path in sorted(args.inputs.glob("*.json")):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if snapshot["data_mode"] != "simulated":
            raise ValueError("This comparison tool accepts simulated data only")
        canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        results = [solve(snapshot, method, config) for method in ("B0", "B1", "B2", "B3")]
        records.append({"input_file": path.name, "input_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                        "scenario_id": snapshot["scenario_id"], "job_count": len(snapshot["jobs"]),
                        "vehicle_count": len(snapshot["vehicles"]), "results": results})
        for result in results:
            m = result["metrics"]
            row = {"scenario": path.stem, "method": result["method"], "status": result["solution_status"],
                   "unassigned": m["unassigned_count"], "changed": len(m["changed_job_ids"]),
                   "travel_minutes": m["movable_travel_minutes"], "movable_violations": m["movable_violation_count"],
                   "fixed_risks": m["fixed_risk_count"], "elapsed_ms": m["elapsed_ms"],
                   "objective_proven": result["objective_proven"]}
            summary.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    if not records:
        raise ValueError("No input JSON files")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve earlier experiments; choose a new output name for another run.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"data_mode": "simulated", "config_per_method": config,
                   "python": platform.python_version(), "platform": platform.platform(),
                   "external_warm_start": False, "records": records}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    with args.output.with_suffix(".csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)


if __name__ == "__main__":
    main()
