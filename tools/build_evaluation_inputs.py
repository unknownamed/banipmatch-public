"""Freeze a new synthetic evaluation set before solving; no operational data.

Baseline routes are constructed under the previous window. The input event then
changes only V1's window. Readiness, service and travel are explicit assumptions.
This generator never calls a solver or selects inputs by outcome.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.data import validate_snapshot

EPOCH = datetime(2026, 11, 8, tzinfo=timezone.utc)
PROFILES = ("cutoff", "opening", "readiness", "fixed")


def at(minutes):
    return (EPOCH + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(profile, seed, count=8, vehicle_count=3):
    rng = random.Random(seed)
    sid = f"eval_{profile}_{count}_{seed}"
    template = json.loads((ROOT / "docs/development/v0.1/예제 데이터/01_snapshot.json").read_text(encoding="utf-8"))
    snapshot = deepcopy(template)
    snapshot.update(scenario_id=sid, plan_id=f"P-{sid}", as_of=at(0))
    evidence = dict(kind="simulated", source_ref=f"synthetic:evaluation-v1:{sid}",
                    observed_at=None, received_at=at(0))
    snapshot["locations"] = [dict(location_id=key, name=f"모의 {key}", kind=kind,
                                 latitude=None, longitude=None, evidence=deepcopy(evidence))
                             for key, kind in (("D", "depot"), ("O1", "origin"),
                                               ("O2", "origin"), ("HJNC", "terminal"))]
    keys = [x["location_id"] for x in snapshot["locations"]]
    travel = {(a, b): 0 if a == b else rng.randint(8, 30) for a in keys for b in keys}
    snapshot["travel_times"] = [dict(from_location_id=a, to_location_id=b, minutes=value,
                                     evidence=deepcopy(evidence)) for (a, b), value in travel.items()]
    buffer = 10
    snapshot["policy"].update(buffer_minutes=buffer, time_change_tolerance_minutes=5,
                               input_valid_until=at(720), external_actions_enabled=False)
    snapshot["vehicles"] = []
    for index in range(vehicle_count):
        vehicle = deepcopy(template["vehicles"][0])
        vehicle.update(vehicle_id=f"T{index+1}", start_location_id="D", available_at=at(0),
                       shift_end_at=at(600), evidence=deepcopy(evidence))
        if index % 3 == 2:
            vehicle.update(equipment_types=["DRY20"], capacity_kg=20000)
        snapshot["vehicles"].append(vehicle)
    snapshot["windows"] = []
    for index in (1, 2):
        window = deepcopy(template["windows"][index-1])
        window.update(opens_at=at(-60), closes_at=at(600), confirmed_at=at(0),
                      confirmed_by="synthetic-dispatcher", evidence=deepcopy(evidence))
        snapshot["windows"].append(window)
    snapshot["change"].update(change_id=f"C-{sid}", previous_opens_at=at(-60),
                               previous_closes_at=at(600), confirmed_at=at(0),
                               confirmed_by="synthetic-dispatcher", evidence=deepcopy(evidence))
    snapshot["jobs"], snapshot["baseline_assignments"] = [], []
    snapshot["baseline_unassigned_job_ids"] = []
    cursors = [0] * vehicle_count
    places = ["D"] * vehicle_count
    for index in range(count):
        v = index % vehicle_count
        ready = rng.randint(0, 60)
        if profile == "readiness" and index == count - 1:
            ready = 350  # Planned readiness is already known before the window event.
        origin = rng.choice(("O1", "O2"))
        returned_to = rng.choice(("D", "O1", "O2"))
        service = rng.choice((5, 10, 15))
        job = deepcopy(template["jobs"][1])
        job.update(job_id=f"J{index:02}", voyage_id="V1" if index % 2 else "V2",
                   origin_id=origin, return_location_id=returned_to, ready_at=at(ready),
                   service_minutes=service, equipment_type="DRY20" if v % 3 == 2 else "DRY40",
                   gross_weight_kg=18000 if v % 3 == 2 else 24000,
                   evidence=deepcopy(evidence))
        departure = max(cursors[v] + travel[places[v], origin], ready) + rng.randint(0, 15)
        if profile == "fixed" and index == 0:
            departure = -10
            job.update(state="departed", frozen=True, freeze_reason="ALREADY_DEPARTED",
                       ready_at=at(-30), voyage_id="V1")
        if profile == "fixed" and index == vehicle_count:
            job.update(frozen=True, freeze_reason="FIXED_RESERVATION", voyage_id="V1")
        arrival = departure + travel[origin, "HJNC"]
        returned = arrival + buffer + service + travel["HJNC", returned_to]
        snapshot["baseline_assignments"].append(dict(job_id=job["job_id"], vehicle_id=f"T{v+1}",
            sequence=10*(index//vehicle_count+1), pickup_departure_at=at(departure),
            gate_arrival_at=at(arrival), return_at=at(returned)))
        snapshot["jobs"].append(job)
        cursors[v], places[v] = returned, returned_to
        if profile == "fixed" and index == 0:
            snapshot["vehicles"][0].update(available_at=at(returned), start_location_id=returned_to)
    if max(cursors) > 600:
        raise ValueError("Generator baseline exceeds the declared shift; do not silently filter the case")
    # Publish the pre-event plan independently so a reader can verify its origin.
    before = deepcopy(snapshot)
    if profile == "opening":
        snapshot["windows"][0].update(opens_at=at(180), closes_at=at(480))
    elif profile == "readiness":
        snapshot["windows"][0].update(closes_at=at(300))
    elif profile == "fixed":
        fixed_row = snapshot["baseline_assignments"][vehicle_count]
        fixed_arrival = int((datetime.fromisoformat(fixed_row["gate_arrival_at"].replace("Z", "+00:00")) - EPOCH).total_seconds() / 60)
        snapshot["windows"][0].update(closes_at=at(fixed_arrival + buffer - 15))
    else:
        snapshot["windows"][0].update(closes_at=at(150))
    for value in (before, snapshot):
        report = validate_snapshot(value, source=f"evaluation:{sid}")
        if not report.valid:
            raise ValueError([asdict(issue) for issue in report.issues])
    return before, snapshot


def main():
    p = argparse.ArgumentParser(description="Freeze ten new synthetic cases without solving")
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    # Explicit protocol, chosen before any optimization outputs are observed.
    specs = [(profile, seed, 8, 3, 3) for profile in PROFILES for seed in (101, 202)]
    specs.extend([("cutoff", 303, 20, 4, 10), ("cutoff", 404, 50, 8, 10)])
    cases = [(spec, *build(*spec[:4])) for spec in specs]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "inputs").mkdir()
    (args.output_dir / "before-event").mkdir()
    manifest = []
    for (profile, seed, count, nv, budget), before, snapshot in cases:
        sid = snapshot["scenario_id"]
        for directory, obj in (("inputs", snapshot), ("before-event", before)):
            path = args.output_dir / directory / f"{sid}.json"
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        path = args.output_dir / "inputs" / f"{sid}.json"
        manifest.append(dict(id=sid, input=f"inputs/{sid}.json", sha256=sha(path),
                             before_event=f"before-event/{sid}.json", before_event_sha256=sha(args.output_dir / "before-event" / f"{sid}.json"),
                             profile=profile, generation_seed=seed, jobs=count, vehicles=nv, budget_seconds=budget))
    protocol = dict(schema_version=1, frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        base_git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        methods=["B0", "B1", "B2", "B3"], solver_seeds=[0, 17], cases=manifest,
        expected_runs=len(cases)*8, data_mode="simulated", worker_count=1,
        selection="All declared cases retained; no solver call during generation; no parameter tuning from this set.",
        interpretation="New synthetic evaluation, not an independently sampled operational holdout or evidence of field savings.",
        assumptions=dict(directed_travel_minutes=[8,30], buffer_minutes=10,
                         readiness_minutes=[0,60], late_readiness_minutes=350, service_minutes=[5,10,15],
                         shift_minutes=600, old_window_minutes=[-60,600], change_tolerance_minutes=5,
                         locations="Artificial complete directed graph; not measured Busan road routes"),
        engine_source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT / "backend/engine").glob("*.py"))},
        generator_sha256=sha(Path(__file__)))
    (args.output_dir / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(dict(cases=len(cases), planned_runs=protocol["expected_runs"], protocol_sha256=sha(args.output_dir / "protocol.json"))))


if __name__ == "__main__":
    main()
