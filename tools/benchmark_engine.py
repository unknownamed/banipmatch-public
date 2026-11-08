"""Bounded, reproducible sweeps of explicitly simulated engine inputs.

Every method receives a fresh copy of the same scenario variant and total budget.
Completed runs are flushed to JSONL so interrupted experiments remain inspectable.
"""
import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.engine import solve
from backend.engine import optimization  # Exclude library loading from method timing.


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="모의 입력 규모·예산·여유시간 비교")
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--budgets", type=int, nargs="+", default=[1, 3, 10])
    parser.add_argument("--buffers", type=int, nargs="+")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--methods", choices=["B0", "B1", "B2", "B3"], nargs="+", default=["B0", "B1", "B2", "B3"])
    args = parser.parse_args()
    if args.repeats < 1 or any(v < 1 for v in args.budgets) or any(v < 0 for v in args.buffers or []) or any(v < 0 for v in args.seeds):
        parser.error("양수 예산/반복 수와 음수가 아닌 여유시간/시드를 사용하세요.")
    if len(set(p.resolve() for p in args.inputs)) != len(args.inputs):
        parser.error("같은 입력을 중복 지정하지 마세요.")
    inputs = [(p, json.loads(p.read_text(encoding="utf-8"))) for p in args.inputs]
    if any(s.get("data_mode") != "simulated" for _, s in inputs):
        parser.error("모의 입력만 사용합니다.")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted((ROOT / "backend/engine").glob("*.py"))}
    source_hashes["tools/benchmark_engine.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    metadata = dict(data_mode="simulated", python=platform.python_version(), platform=platform.platform(),
                    git_head=head, source_sha256=source_hashes, worker_count=1, external_warm_start=False,
                    budgets=args.budgets, buffers=args.buffers, seeds=args.seeds, repeats=args.repeats,
                    methods=args.methods, inputs=[dict(file=p.name, sha256=digest(s)) for p, s in inputs],
                    baseline_policy="Preserve original assignment records, including frozen times.",
                    completed=False)
    meta_path = args.output_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = []
    with (args.output_dir / "results.jsonl").open("x", encoding="utf-8") as log:
        for path, original in inputs:
            for buffer in args.buffers if args.buffers is not None else [original["policy"]["buffer_minutes"]]:
                variant = copy.deepcopy(original)
                variant["policy"]["buffer_minutes"] = buffer
                input_hash = digest(variant)
                for budget in args.budgets:
                    for seed in args.seeds:
                        for repetition in range(1, args.repeats + 1):
                            for method in args.methods:
                                snapshot = copy.deepcopy(variant)
                                config = dict(seed=seed, time_limit_seconds=budget)
                                started = perf_counter()
                                result = solve(snapshot, method, config)
                                wall_ms = round((perf_counter() - started) * 1000, 3)
                                if digest(snapshot) != input_hash:
                                    raise AssertionError("Engine mutated experiment input")
                                key = dict(input=path.name, buffer=buffer, budget=budget, seed=seed,
                                           repetition=repetition, method=method)
                                log.write(json.dumps(dict(**key, input_sha256=input_hash, wall_ms=wall_ms,
                                                          result=result), ensure_ascii=False) + "\n")
                                log.flush()
                                m = result["metrics"]
                                row = dict(**key, status=result["solution_status"], unassigned=m["unassigned_count"],
                                           changed=len(m["changed_job_ids"]), travel_minutes=m["movable_travel_minutes"],
                                           movable_violations=m["movable_violation_count"], fixed_risks=m["fixed_risk_count"],
                                           objective_proven=result["objective_proven"], elapsed_ms=m["elapsed_ms"], wall_ms=wall_ms,
                                           stages="/".join(s["status"] for s in result.get("objective_stages", [])))
                                rows.append(row)
                                print(json.dumps(row, ensure_ascii=False), flush=True)
    with (args.output_dir / "runs.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    grouped = {}
    for row in rows:
        key = tuple(row[name] for name in ("input", "buffer", "budget", "method"))
        grouped.setdefault(key, []).append(row)
    aggregate = []
    for key, group in grouped.items():
        item = dict(zip(("input", "buffer", "budget", "method"), key))
        item.update(runs=len(group), proven_runs=sum(r["objective_proven"] for r in group),
                    statuses=sorted(set(r["status"] for r in group)),
                    objective_tuples=sorted(set((r["unassigned"], r["changed"], r["travel_minutes"]) for r in group)),
                    max_movable_violations=max(r["movable_violations"] for r in group),
                    max_fixed_risks=max(r["fixed_risks"] for r in group),
                    wall_ms_min=min(r["wall_ms"] for r in group),
                    wall_ms_median=statistics.median(r["wall_ms"] for r in group),
                    wall_ms_max=max(r["wall_ms"] for r in group))
        aggregate.append(item)
    (args.output_dir / "aggregate.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata.update(completed=True, completed_runs=len(rows))
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
