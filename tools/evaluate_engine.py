"""Run a frozen synthetic protocol; preserve raw results and separate audits."""
import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import solve
from backend.engine import optimization  # Load dependency before timing.
from backend.api.contracts import validate
from backend.api.result_integrity import check_result_integrity, verify_schedule


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_protocol(path):
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("schema_version") != 1 or protocol["methods"] != ["B0", "B1", "B2", "B3"]:
        raise ValueError("Unsupported protocol or methods")
    seeds = protocol["solver_seeds"]
    if not seeds or len(set(seeds)) != len(seeds) or any(type(s) is not int or s < 0 for s in seeds):
        raise ValueError("Invalid solver seeds")
    actual = {p.relative_to(ROOT).as_posix(): sha256(p) for p in sorted((ROOT / "backend/engine").glob("*.py"))}
    if actual != protocol["engine_source_sha256"]:
        raise ValueError("Engine source hash mismatch")
    cases, seen = [], set()
    for case in protocol["cases"]:
        if case["id"] in seen or type(case["budget_seconds"]) is not int or case["budget_seconds"] <= 0:
            raise ValueError("Duplicate case or invalid budget")
        seen.add(case["id"])
        source = (path.parent / case["input"]).resolve()
        if not source.is_relative_to(path.parent.resolve()) or sha256(source) != case["sha256"]:
            raise ValueError("Input path or hash mismatch")
        snapshot = json.loads(source.read_text(encoding="utf-8"))
        validate("Snapshot", snapshot)
        if snapshot["data_mode"] != "simulated":
            raise ValueError("Synthetic inputs required")
        cases.append((case, snapshot))
    if not cases:
        raise ValueError("Empty protocol")
    return protocol, cases


def audit_result(snapshot, result):
    validate("MethodResult", result)
    if result["validation_status"] != "not_run" or result["approval_eligible"] or result["result_origin"] != "computed":
        raise ValueError("Unexpected raw engine validation/origin")
    check_result_integrity(snapshot, result)
    if result["method"] == "B0":
        return {"integrity": "passed", "schedule": "baseline_not_applicable", "failed": False}
    passed = verify_schedule(snapshot, result)
    eligible = result["solution_status"] in {"HEURISTIC", "FEASIBLE", "OPTIMAL"}
    return {"integrity": "passed", "schedule": "passed" if passed else ("failed" if eligible else "not_eligible"),
            "failed": eligible and not passed}


def make_pairs(records):
    groups = {}
    for row in records:
        if row["method"] in {"B2", "B3"}:
            key = (row["case_id"], row["input_sha256"], row["budget_seconds"], row["seed"])
            group = groups.setdefault(key, {})
            if row["method"] in group:
                raise ValueError("Duplicate paired run")
            group[row["method"]] = row
    pairs = []
    for (case_id, digest, budget, seed), group in groups.items():
        pair = dict(case_id=case_id, input_sha256=digest, budget_seconds=budget, seed=seed)
        reasons, values = [], {}
        for method in ("B2", "B3"):
            row = group.get(method)
            if row is None or row.get("error") or row.get("audit", {}).get("schedule") != "passed":
                reasons.append(f"{method}_not_validated")
            if row and row.get("result"):
                values[method] = row["result"]
                if row["result"]["metrics"]["movable_violation_count"] != 0:
                    reasons.append(f"{method}_movable_violations")
        if len(values) == 2:
            a, b = values["B2"]["metrics"], values["B3"]["metrics"]
            if a["unassigned_count"] != b["unassigned_count"]:
                reasons.append("different_unassigned_count")
            if a["fixed_risk_count"] != b["fixed_risk_count"]:
                reasons.append("different_fixed_risk_count")
            pair.update(B2_unassigned=a["unassigned_count"], B3_unassigned=b["unassigned_count"],
                        identical_assigned_set={x["job_id"] for x in values["B2"]["assignments"]} ==
                        {x["job_id"] for x in values["B3"]["assignments"]},
                        changed_delta=len(b["changed_job_ids"]) - len(a["changed_job_ids"]),
                        travel_minutes_delta=b["movable_travel_minutes"] - a["movable_travel_minutes"],
                        wall_ms_delta=group["B3"]["wall_ms"] - group["B2"]["wall_ms"])
        pair.update(equal_count_comparable=not reasons, exclusion_reason=";".join(reasons))
        pairs.append(pair)
    return pairs


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(protocol_path, output_dir):
    protocol, cases = load_protocol(protocol_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    git = lambda *args: subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8")
    tracked_diff = git("diff", "HEAD", "--binary")
    (output_dir / "tracked.diff").write_text(tracked_diff, encoding="utf-8")
    sources = [*sorted((ROOT / "backend/engine").glob("*.py")),
               *sorted((ROOT / "backend/data").rglob("*.py")),
               *sorted((ROOT / "backend/api").glob("*.py")), Path(__file__).resolve()]
    metadata = dict(protocol_sha256=sha256(protocol_path), base_git_head=protocol["base_git_head"],
                    git_head=git("rev-parse", "HEAD").strip(), tracked_diff_sha256=sha256(output_dir / "tracked.diff"),
                    dirty_tracked=bool(tracked_diff), git_status=git("status", "--short"),
                    source_sha256={p.relative_to(ROOT).as_posix(): sha256(p) for p in sources},
                    python=platform.python_version(), platform=platform.platform(),
                    solver=f"OR-Tools {optimization.ortools.__version__}", worker_count=1,
                    completed=False, expected_runs=len(cases)*len(protocol["solver_seeds"])*len(protocol["methods"]))
    meta_path = output_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    records, rows = [], []
    with (output_dir / "results.jsonl").open("x", encoding="utf-8") as log:
        for case, original in cases:
            for seed in protocol["solver_seeds"]:
                for method in protocol["methods"]:
                    snapshot = copy.deepcopy(original)
                    record = dict(case_id=case["id"], input_sha256=case["sha256"],
                                  budget_seconds=case["budget_seconds"], seed=seed, method=method)
                    started = perf_counter()
                    try:
                        result = solve(snapshot, method, {"seed": seed, "time_limit_seconds": case["budget_seconds"]})
                        record.update(wall_ms=round((perf_counter()-started)*1000, 3), result=result)
                        if canonical(snapshot) != canonical(original):
                            raise ValueError("Engine mutated input")
                        if result["method"] != method:
                            raise ValueError("Engine returned wrong method")
                        record["audit"] = audit_result(original, result)
                    except Exception as exc:
                        record.setdefault("wall_ms", round((perf_counter()-started)*1000, 3))
                        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
                        record["audit"] = {"integrity": "error", "schedule": "error", "failed": True}
                    log.write(json.dumps(record, ensure_ascii=False) + "\n")
                    log.flush()
                    records.append(record)
                    row = {k: v for k, v in record.items() if k not in {"result", "audit", "error"}}
                    result = record.get("result", {})
                    metrics = result.get("metrics", {})
                    row.update(status=result.get("solution_status"), objective_proven=result.get("objective_proven"),
                               stages=canonical(result.get("objective_stages", [])),
                               audit_schedule=record["audit"]["schedule"], error=canonical(record.get("error")),
                               unassigned=metrics.get("unassigned_count"),
                               changed=len(metrics["changed_job_ids"]) if "changed_job_ids" in metrics else None,
                               travel_minutes=metrics.get("movable_travel_minutes"), elapsed_ms=metrics.get("elapsed_ms"),
                               movable_violations=metrics.get("movable_violation_count"), fixed_risks=metrics.get("fixed_risk_count"))
                    rows.append(row)
                    print(canonical(row), flush=True)
    pairs = make_pairs(records)
    write_csv(output_dir / "runs.csv", rows)
    write_csv(output_dir / "pairs.csv", pairs)
    failures = sum(r["audit"]["failed"] for r in records)
    summary = dict(runs=len(records), expected_runs=metadata["expected_runs"], failures=failures,
                   exceptions=sum("error" in r for r in records),
                   independently_validated=sum(r["audit"]["schedule"] == "passed" for r in records),
                   baseline_integrity_passed=sum(r["audit"]["schedule"] == "baseline_not_applicable" for r in records),
                   not_eligible=sum(r["audit"]["schedule"] == "not_eligible" for r in records),
                   objective_proven=sum(bool(r.get("result", {}).get("objective_proven")) for r in records),
                   pairs=len(pairs), equal_count_comparable=sum(p["equal_count_comparable"] for p in pairs),
                   identical_workload_comparable=sum(p["equal_count_comparable"] and p.get("identical_assigned_set", False) for p in pairs),
                   delta_convention="B3 minus B2; equal count does not imply identical served jobs")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata.update(completed=True, completed_runs=len(records), failures=failures)
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(bool(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    return run(args.protocol.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    sys.exit(main())
