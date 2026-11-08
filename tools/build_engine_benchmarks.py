"""Build deterministic artificial scenarios; no external or private data."""
import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.data import validate_snapshot


def at(minutes):
    return (datetime(2026, 11, 7, tzinfo=timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(fixed):
    source = ROOT / "docs/experiments/engine-b0-b3/inputs/20_jobs_4_vehicles.json"
    snapshot = json.loads(source.read_text(encoding="utf-8"))
    name = "mixed_fixed_12" if fixed else "mixed_12"
    snapshot["scenario_id"] = name
    snapshot["policy"].update(buffer_minutes=10, input_valid_until=at(360))
    prototype = snapshot["windows"][0]
    snapshot["windows"] = []
    for index, (opens, closes) in enumerate(((0, 150), (30, 210), (120, 300)), 1):
        window = copy.deepcopy(prototype)
        window.update(window_id=f"W{index}", voyage_id=f"V{index}", opens_at=at(opens), closes_at=at(closes))
        snapshot["windows"].append(window)
    snapshot["change"].update(previous_opens_at=at(0), previous_closes_at=at(210))
    for index, vehicle in enumerate(snapshot["vehicles"]):
        vehicle.update(available_at=at(0), shift_end_at=at(330))
        if index == 1:
            vehicle.update(equipment_types=["DRY20"], capacity_kg=20000)
        elif index == 3:
            vehicle.update(capacity_kg=24000)
    snapshot["jobs"] = snapshot["jobs"][:12]
    snapshot["baseline_assignments"] = snapshot["baseline_assignments"][:12]
    for index, (job, assignment) in enumerate(zip(snapshot["jobs"], snapshot["baseline_assignments"])):
        job.update(voyage_id=f"V{index % 3 + 1}", ready_at=at((index * 25) % 190),
                   equipment_type="DRY20" if index % 2 else "DRY40",
                   gross_weight_kg=18000 if index % 2 else (24000 if index % 4 else 28000),
                   service_minutes=(index % 3) * 10)
        departure = 20 + (index // 4) * 85
        assignment.update(pickup_departure_at=at(departure), gate_arrival_at=at(departure + 30),
                          return_at=at(departure + 50 + job["service_minutes"]))
    snapshot["jobs"][-1]["ready_at"] = at(320)  # Independently impossible before its cutoff.
    if fixed:
        departed = snapshot["jobs"][0]
        departed.update(state="departed", frozen=True, freeze_reason="DEPARTED", ready_at=at(-60))
        snapshot["baseline_assignments"][0].update(pickup_departure_at=at(-40), gate_arrival_at=at(-10), return_at=at(10))
        snapshot["vehicles"][0]["available_at"] = at(10)
        reserved = snapshot["jobs"][5]
        reserved.update(frozen=True, freeze_reason="FIXED_RESERVATION", ready_at=at(90), service_minutes=10, voyage_id="V2")
        snapshot["baseline_assignments"][5].update(pickup_departure_at=at(100), gate_arrival_at=at(130), return_at=at(160))
    # Replace inherited provenance rather than presenting clones as new observations.
    def relabel(value):
        if isinstance(value, dict):
            if "evidence" in value:
                value["evidence"].update(kind="simulated", source_ref=f"fixture:benchmark:{name}")
            for nested in value.values():
                relabel(nested)
        elif isinstance(value, list):
            for nested in value:
                relabel(nested)
    relabel(snapshot)
    report = validate_snapshot(snapshot, source=f"benchmark:{name}")
    if not report.valid:
        raise ValueError([asdict(item) for item in report.issues])
    return snapshot


def main():
    parser = argparse.ArgumentParser(description="실자료 없는 혼합 모의 입력 생성")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    inputs = [build(fixed) for fixed in (False, True)]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for snapshot in inputs:
        path = args.output_dir / f"{snapshot['scenario_id']}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
