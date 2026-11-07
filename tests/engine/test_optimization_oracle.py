"""Exhaustive tiny schedules, independent of the solver/model/metric helpers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import combinations, permutations, product
import json
from pathlib import Path
import random
import unittest

from backend.engine import solve


EPOCH = datetime(2026, 11, 7, tzinfo=timezone.utc)


def at(value):
    return (EPOCH + timedelta(minutes=value)).strftime("%Y-%m-%dT%H:%M:%SZ")


def minute(value):
    return int((datetime.fromisoformat(value.replace("Z", "+00:00")) - EPOCH).total_seconds() // 60)


def tiny_snapshot(rng):
    path = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터/01_snapshot.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["policy"].update(buffer_minutes=0, time_change_tolerance_minutes=rng.randrange(2))
    for leg in snapshot["travel_times"]:
        leg["minutes"] = (0 if leg["from_location_id"] == leg["to_location_id"]
                          else rng.randint(1, 2))
    travel = {(leg["from_location_id"], leg["to_location_id"]): leg["minutes"]
              for leg in snapshot["travel_times"]}
    snapshot["windows"] = snapshot["windows"][:1]
    snapshot["windows"][0].update(opens_at=at(rng.randrange(3)), closes_at=at(rng.randint(6, 9)))
    for vehicle in snapshot["vehicles"]:
        vehicle.update(start_location_id=rng.choice(("O", "D")),
                       available_at=at(0), shift_end_at=at(10))
    prototype = snapshot["jobs"][1]
    snapshot["jobs"], snapshot["baseline_assignments"], snapshot["baseline_unassigned_job_ids"] = [], [], []
    for index in range(3):
        job = deepcopy(prototype)
        job.update(job_id=f"J{index}", origin_id=rng.choice(("O", "D")),
                   return_location_id=rng.choice(("O", "D")), ready_at=at(rng.randrange(4)),
                   service_minutes=rng.randrange(2))
        snapshot["jobs"].append(job)
        if rng.randrange(4) == 0:
            snapshot["baseline_unassigned_job_ids"].append(job["job_id"])
        else:
            vehicle, departure = rng.choice(("T1", "T2")), rng.randrange(8)
            arrival = departure + travel[job["origin_id"], "HJNC"]
            returned = arrival + job["service_minutes"] + travel["HJNC", job["return_location_id"]]
            snapshot["baseline_assignments"].append(dict(
                job_id=job["job_id"], vehicle_id=vehicle, sequence=index + 1,
                pickup_departure_at=at(departure), gate_arrival_at=at(arrival), return_at=at(returned)))
    return snapshot


def exhaustive_objectives(snapshot):
    """Enumerate every placement, route permutation, and integer departure.

    These deliberately tiny cases contain no frozen work. All jobs have a
    compatible vehicle and complete directed travel data; the separate fixed
    reservation tests cover the integer slots and immutable prefix boundaries.
    """
    jobs = {job["job_id"]: job for job in snapshot["jobs"]}
    vehicles = {vehicle["vehicle_id"]: vehicle for vehicle in snapshot["vehicles"]}
    travel = {(leg["from_location_id"], leg["to_location_id"]): leg["minutes"]
              for leg in snapshot["travel_times"]}
    window = snapshot["windows"][0]
    baseline = {row["job_id"]: row for row in snapshot["baseline_assignments"]}
    tolerance = snapshot["policy"]["time_change_tolerance_minutes"]
    vehicle_ids, job_ids = tuple(sorted(vehicles)), tuple(sorted(jobs))

    def route_schedules(vehicle_id, route, index=0, cursor=0, location=None, rows=(), distance=0):
        if index == len(route):
            yield dict(rows), distance
            return
        location = vehicles[vehicle_id]["start_location_id"] if location is None else location
        job = jobs[route[index]]
        approach = travel[location, job["origin_id"]]
        loaded = travel[job["origin_id"], job["terminal_id"]]
        returning = travel[job["terminal_id"], job["return_location_id"]]
        duration = loaded + job["service_minutes"] + returning
        earliest = max(cursor + approach, minute(job["ready_at"]), minute(window["opens_at"]) - loaded)
        latest = min(minute(window["closes_at"]) - loaded,
                     minute(vehicles[vehicle_id]["shift_end_at"]) - duration)
        for departure in range(earliest, latest + 1):
            row = (job["job_id"], (vehicle_id, index + 1, departure))
            yield from route_schedules(vehicle_id, route, index + 1, departure + duration,
                                       job["return_location_id"], (*rows, row),
                                       distance + approach + loaded + returning)

    def changed_count(assignments):
        changed = set(assignments) - set(baseline)
        for job_id in set(assignments) & set(baseline):
            vehicle, _, departure = assignments[job_id]
            old = baseline[job_id]
            if (vehicle != old["vehicle_id"]
                    or abs(departure - minute(old["pickup_departure_at"])) > tolerance):
                changed.add(job_id)
        for left, right in combinations(set(assignments) & set(baseline), 2):
            a, b = assignments[left], assignments[right]
            old_a, old_b = baseline[left], baseline[right]
            if (a[0] == old_a["vehicle_id"] == b[0] == old_b["vehicle_id"]
                    and (a[1] - b[1]) * (old_a["sequence"] - old_b["sequence"]) < 0):
                changed.update((left, right))
        return len(changed)

    best = {"B2": None, "B3": None}
    for placement in product((None, *vehicle_ids), repeat=len(job_ids)):
        unassigned = placement.count(None)
        routes = [tuple(job_id for job_id, chosen in zip(job_ids, placement) if chosen == vehicle_id)
                  for vehicle_id in vehicle_ids]
        for ordered_routes in product(*(permutations(route) for route in routes)):
            options = [tuple(route_schedules(vehicle_id, route))
                       for vehicle_id, route in zip(vehicle_ids, ordered_routes)]
            for chosen_routes in product(*options):
                assignments, distance = {}, 0
                for rows, route_distance in chosen_routes:
                    assignments.update(rows)
                    distance += route_distance
                values = {"B2": (unassigned, distance),
                          "B3": (unassigned, changed_count(assignments), distance)}
                for method, value in values.items():
                    if best[method] is None or value < best[method]:
                        best[method] = value
    return best


class ExhaustiveOptimizationTests(unittest.TestCase):
    def test_small_deterministic_cases_match_all_assignments_orders_and_start_times(self):
        rng = random.Random(471)
        for case in range(5):
            snapshot = tiny_snapshot(rng)
            expected = exhaustive_objectives(snapshot)
            for method in ("B2", "B3"):
                with self.subTest(case=case, method=method):
                    result = solve(snapshot, method, {"seed": 1, "time_limit_seconds": 5})
                    metrics = result["metrics"]
                    actual = (metrics["unassigned_count"], metrics["movable_travel_minutes"])
                    if method == "B3":
                        actual = (actual[0], len(metrics["changed_job_ids"]), actual[1])
                    self.assertEqual(result["solution_status"], "OPTIMAL")
                    self.assertTrue(result["objective_proven"])
                    self.assertEqual(actual, expected[method])
                    self.assertEqual(metrics["movable_violation_count"], 0)


if __name__ == "__main__":
    unittest.main()
