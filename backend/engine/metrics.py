"""Pure result metrics for the published v0.1 dispatch contract.

Inputs are expected to have passed structural and semantic input checks. This
module does not certify that a schedule is feasible; the caller supplies the
job-level diagnostic issues. Unknown travel is an error, never zero travel.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from itertools import combinations
from math import isfinite
from typing import Any, Mapping, Sequence


class MissingTravelTimeError(ValueError):
    """An assigned movable job has a missing directed travel segment."""

    def __init__(self, job_id: str, origin_id: str, destination_id: str):
        self.job_id = job_id
        self.origin_id = origin_id
        self.destination_id = destination_id
        super().__init__(
            f"Missing travel time for {job_id}: {origin_id} -> {destination_id}"
        )


def _json_integer(value: Any, label: str, minimum: int = 0) -> int:
    """Accept JSON Schema integer values such as 10.0, but never booleans."""
    if type(value) is int:
        integer = value
    elif type(value) is float and isfinite(value) and value.is_integer():
        integer = int(value)
    else:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    if integer < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    return integer


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Metrics require normalized UTC timestamps ending in Z")
    result = datetime.fromisoformat(value[:-1] + "+00:00")
    if result.second or result.microsecond:
        raise ValueError("Metrics require timestamps on minute boundaries")
    return result


def _by_id(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    result = {}
    for row in rows:
        identifier = row[field]
        if identifier in result:
            raise ValueError(f"Duplicate {field}: {identifier}")
        result[identifier] = row
    return result


def _check_sequences(assignments: Sequence[Mapping[str, Any]]) -> None:
    seen = set()
    for assignment in assignments:
        sequence = _json_integer(assignment["sequence"], "Assignment sequence", 1)
        key = (assignment["vehicle_id"], sequence)
        if key in seen:
            raise ValueError(f"Duplicate vehicle sequence: {key}")
        seen.add(key)


def _travel_minutes(
    snapshot: Mapping[str, Any],
    assignments: Sequence[Mapping[str, Any]],
    jobs: Mapping[str, Any],
    vehicles: Mapping[str, Any],
) -> int:
    matrix = {}
    for leg in snapshot["travel_times"]:
        key = (leg["from_location_id"], leg["to_location_id"])
        if key in matrix:
            raise ValueError(f"Duplicate directed travel segment: {key}")
        matrix[key] = leg["minutes"]

    def minutes(job_id: str, origin: str, destination: str) -> int:
        value = matrix.get((origin, destination))
        if value is None:
            raise MissingTravelTimeError(job_id, origin, destination)
        return _json_integer(value, f"Travel time: {origin} -> {destination}")

    routes: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for assignment in assignments:
        routes[assignment["vehicle_id"]].append(assignment)

    total = 0
    for vehicle_id, route in routes.items():
        location = vehicles[vehicle_id]["start_location_id"]
        for assignment in sorted(route, key=lambda row: row["sequence"]):
            job = jobs[assignment["job_id"]]
            if job["frozen"]:
                # The vehicle's start location/availability already describes
                # its state after the departed fixed prefix. Future fixed
                # reservations instead determine the location of the next job.
                if job["state"] != "departed":
                    location = job["return_location_id"]
                continue
            job_id = job["job_id"]
            total += minutes(job_id, location, job["origin_id"])
            total += minutes(job_id, job["origin_id"], job["terminal_id"])
            total += minutes(job_id, job["terminal_id"], job["return_location_id"])
            location = job["return_location_id"]
    return total


def calculate_metrics(
    snapshot: Mapping[str, Any],
    assignments: Sequence[Mapping[str, Any]],
    unassigned_job_ids: Sequence[str],
    issues: Sequence[Mapping[str, Any]],
    elapsed_ms: int,
) -> dict[str, Any]:
    """Return exactly the published ``Metrics`` fields without mutating input.

    Change counts use job IDs and retained pairs, not row renumbering. Missing
    travel for an assigned movable job raises ``MissingTravelTimeError`` because
    the current contract has no nullable or unknown travel-total representation.
    Unassigned jobs do not contribute travel. Global and unassigned-job issues
    do not count as violations of assigned jobs. Any issue attached to an
    assigned job marks that job once; multiple issues do not inflate counts.
    """
    elapsed_ms = _json_integer(elapsed_ms, "elapsed_ms")
    tolerance = _json_integer(snapshot["policy"]["time_change_tolerance_minutes"],
                              "Time-change tolerance")

    jobs = _by_id(snapshot["jobs"], "job_id")
    vehicles = _by_id(snapshot["vehicles"], "vehicle_id")
    baseline = _by_id(snapshot["baseline_assignments"], "job_id")
    current = _by_id(assignments, "job_id")
    _check_sequences(snapshot["baseline_assignments"])
    _check_sequences(assignments)

    assigned = set(current)
    unassigned = set(unassigned_job_ids)
    baseline_unassigned = set(snapshot["baseline_unassigned_job_ids"])
    if len(unassigned) != len(unassigned_job_ids):
        raise ValueError("Duplicate unassigned job ID")
    if assigned & unassigned or assigned | unassigned != set(jobs):
        raise ValueError("Assigned and unassigned jobs must partition the input")
    if set(baseline) & baseline_unassigned or set(baseline) | baseline_unassigned != set(jobs):
        raise ValueError("Baseline assignment lists must partition the input")
    if any(row["vehicle_id"] not in vehicles for row in assignments):
        raise ValueError("Assignment references an unknown vehicle")

    retained = assigned & set(baseline)
    vehicle_changed = {
        job_id for job_id in retained
        if current[job_id]["vehicle_id"] != baseline[job_id]["vehicle_id"]
    }
    time_changed = {
        job_id for job_id in retained
        if abs((
            _timestamp(current[job_id]["pickup_departure_at"])
            - _timestamp(baseline[job_id]["pickup_departure_at"])
        ).total_seconds()) > tolerance * 60
    }
    same_vehicle: dict[str, list[str]] = defaultdict(list)
    for job_id in retained - vehicle_changed:
        same_vehicle[current[job_id]["vehicle_id"]].append(job_id)
    order_changed = set()
    for job_ids in same_vehicle.values():
        for left, right in combinations(job_ids, 2):
            old_delta = baseline[left]["sequence"] - baseline[right]["sequence"]
            new_delta = current[left]["sequence"] - current[right]["sequence"]
            if old_delta * new_delta < 0:
                order_changed.update((left, right))
    newly_assigned = assigned & baseline_unassigned
    changed = vehicle_changed | time_changed | order_changed | newly_assigned

    risky = {issue["job_id"] for issue in issues if issue.get("job_id") in assigned}
    movable = {job_id for job_id in assigned if not jobs[job_id]["frozen"]}
    fixed = assigned - movable
    return {
        "unassigned_count": len(unassigned),
        "feasible_movable_count": len(movable - risky),
        "movable_violation_count": len(movable & risky),
        "fixed_risk_count": len(fixed & risky),
        "changed_job_ids": sorted(changed),
        "vehicle_changed_job_ids": sorted(vehicle_changed),
        "order_changed_job_ids": sorted(order_changed),
        "time_changed_job_ids": sorted(time_changed),
        "movable_travel_minutes": _travel_minutes(snapshot, assignments, jobs, vehicles),
        "elapsed_ms": elapsed_ms,
        "newly_assigned_job_ids": sorted(newly_assigned),
    }
