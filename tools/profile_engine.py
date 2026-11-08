"""Measure one simulated solve without rerunning an entire benchmark sweep.

Diagnostic parameter overrides are local experiments, not engine defaults.
Logging adds overhead; use benchmark_engine.py for final timing comparisons.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import solve, optimization as opt, solver as engine_solver
from tools.benchmark_engine import digest


def main():
    p = argparse.ArgumentParser(description="Bounded CP-SAT phase diagnosis")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--method", choices=["B2", "B3"], default="B3")
    p.add_argument("--budget", type=int, default=10)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--presolve-off", action="store_true")
    p.add_argument("--probing-level", type=int, choices=[0, 1, 2])
    p.add_argument("--symmetry-level", type=int, choices=[0, 1, 2, 3])
    a = p.parse_args()
    snapshot = json.loads(a.input.read_text(encoding="utf-8"))
    if snapshot.get("data_mode") != "simulated" or not 1 <= a.budget <= 120 or a.seed < 0:
        p.error("Use a simulated input, 1..120 second budget and non-negative seed")
    a.output_dir.mkdir(parents=True, exist_ok=False)
    source = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted((ROOT / "backend/engine").glob("*.py"))}
    source["tools/profile_engine.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = dict(input=a.input.name, input_sha256=digest(snapshot), method=a.method,
                  budget=a.budget, seed=a.seed, python=platform.python_version(),
                  solver_version=opt.ortools.__version__, worker_count=1,
                  git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  source_sha256=source, diagnostic_overrides={}, phases=[], stages=[], completed=False)
    if a.presolve_off:
        report["diagnostic_overrides"]["cp_model_presolve"] = False
    if a.probing_level is not None:
        report["diagnostic_overrides"]["cp_model_probing_level"] = a.probing_level
    if a.symmetry_level is not None:
        report["diagnostic_overrides"]["symmetry_level"] = a.symmetry_level
    target = a.output_dir / "profile.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    original_build, original_stage, original_insert = opt.DispatchModel, opt._run_stage, engine_solver._insert
    original_solver = opt.cp_model.CpSolver

    def insert(*args):
        start = perf_counter()
        result = original_insert(*args)
        report["phases"].append(dict(name="warm_start", seconds=perf_counter() - start))
        return result

    def build(*args):
        start = perf_counter()
        result = original_build(*args)
        report["phases"].append(dict(name="model_build", seconds=perf_counter() - start))
        proto = result.model.proto
        report["model"] = dict(variables=len(proto.variables), constraints=len(proto.constraints),
                               route_arcs=sum(len(arcs) for arcs in result.route_arcs.values()),
                               on_vehicle=len(result.on_vehicle))
        (a.output_dir / "model_stats.txt").write_text(result.model.model_stats(), encoding="utf-8")
        return result

    def stage(model, objective, remaining, seed):
        index = len(report["stages"]) + 1
        messages = []
        class DiagnosticSolver(original_solver):
            def solve(self, current_model, *args, **kwargs):
                # Apply after the engine's defaults, so an explicit diagnostic
                # override is never silently overwritten by production setup.
                self.parameters.log_search_progress = True
                self.parameters.log_to_stdout = False
                for key, value in report["diagnostic_overrides"].items():
                    setattr(self.parameters, key, value)
                self.log_callback = messages.append
                return super().solve(current_model, *args, **kwargs)
        start = perf_counter()
        with patch.object(opt.cp_model, "CpSolver", DiagnosticSolver):
            solver, status = original_stage(model, objective, remaining, seed)
        text = "\n".join(messages)
        (a.output_dir / f"stage_{index}_solver.txt").write_text(text, encoding="utf-8")
        summary = dict(index=index, budget_seconds=remaining, seconds=perf_counter() - start,
                       status=solver.status_name(status), branches=solver.num_branches,
                       conflicts=solver.num_conflicts,
                       hinted_variables=len(model.proto.solution_hint.vars),
                       model_variables=len(model.proto.variables),
                       stopped_after_presolve="Stopped after presolve" in text,
                       parameters=str(solver.parameters), response_stats=solver.response_stats())
        report["stages"].append(summary)
        return solver, status

    start = perf_counter()
    try:
        with patch.object(engine_solver, "_insert", side_effect=insert), patch.object(opt, "DispatchModel", side_effect=build), patch.object(opt, "_run_stage", side_effect=stage):
            result = solve(snapshot, a.method, dict(seed=a.seed, time_limit_seconds=a.budget))
        assert digest(snapshot) == report["input_sha256"], "Input mutated"
        report.update(completed=True, wall_seconds=perf_counter() - start, result=result)
    finally:
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ["phases", "model", "stages", "wall_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
