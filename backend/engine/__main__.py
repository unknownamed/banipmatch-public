"""Local reproducible calculation only; does not register or approve a plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from . import EngineInputError, solve


def main() -> int:
    parser = argparse.ArgumentParser(description="반입맞춤 B0~B3 로컬 계산")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--methods", nargs="+", choices=("B0", "B1", "B2", "B3"), default=["B0", "B1", "B2", "B3"])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--time-limit-seconds", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if len(set(args.methods)) != len(args.methods):
        parser.error("methods must be unique")
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
        config = dict(seed=args.seed, time_limit_seconds=args.time_limit_seconds)
        results = [solve(snapshot, method, config) for method in args.methods]
    except EngineInputError as exc:
        print(json.dumps(dict(error="ENGINE_INPUT_REJECTED", category=exc.category,
                              issues=exc.issues), ensure_ascii=False), file=sys.stderr)
        return 2
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    output = dict(run_id="local-" + digest[:16], scenario_id=snapshot["scenario_id"],
                  base_plan_version=snapshot["base_plan_version"], input_sha256=digest, results=results)
    text = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(json.dumps({"output": str(args.output), "results": [
            {"method": r["method"], "status": r["solution_status"], "metrics": r["metrics"]}
            for r in results]}, ensure_ascii=False))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
