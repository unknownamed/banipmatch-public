"""Independent finite enumeration of frozen-work objective boundaries.

Deliberately one compatible vehicle, complete directed travel and minute times;
this supplements, rather than generalizes, the unfrozen tiny-schedule oracle.
Only the public solve entry point is imported from production code.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import combinations, permutations
import json
from pathlib import Path
import unittest

from backend.engine import solve


EPOCH = datetime(2026, 11, 7, tzinfo=timezone.utc)


def at(value):
    return (EPOCH + timedelta(minutes=value)).strftime("%Y-%m-%dT%H:%M:%SZ")


def minute(value):
    return int((datetime.fromisoformat(value.replace("Z", "+00:00")) - EPOCH).total_seconds() // 60)


def row(jid, sequence, departure):
    return dict(job_id=jid, vehicle_id="T1", sequence=sequence,
                pickup_departure_at=at(departure), gate_arrival_at=at(departure + 1),
                return_at=at(departure + 2))


def fixture(sequence=2, departure=5):
    path = Path(__file__).resolve().parents[2] / "docs/development/v0.1/예제 데이터/01_snapshot.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["policy"].update(buffer_minutes=0, time_change_tolerance_minutes=0)
    value["vehicles"] = value["vehicles"][:1]
    value["vehicles"][0].update(start_location_id="O", available_at=at(0), shift_end_at=at(9))
    value["windows"] = value["windows"][:1]
    value["windows"][0].update(opens_at=at(-4), closes_at=at(3))
    movable = deepcopy(value["jobs"][1])
    movable.update(job_id="JM", origin_id="O", return_location_id="O", ready_at=at(0),
                   service_minutes=0, frozen=False, freeze_reason=None, state="planned")
    fixed = deepcopy(movable)
    fixed.update(job_id="JF", origin_id="D", frozen=True, freeze_reason="FIXED_RESERVATION")
    value["jobs"] = [movable, fixed]
    for leg in value["travel_times"]:
        pair = leg["from_location_id"], leg["to_location_id"]
        leg["minutes"] = 0 if pair[0] == pair[1] else 2 if pair == ("O", "D") else 1
    value["baseline_assignments"] = [row("JM", 1 if sequence > 1 else 2, 0),
                                      row("JF", sequence, departure)]
    value["baseline_unassigned_job_ids"] = []
    return value


def changed_ids(assignments, baseline, tolerance):
    """Count a union, including frozen participants of relative-order inversions."""
    changed = set(assignments) - set(baseline)
    for jid in set(assignments) & set(baseline):
        new, old = assignments[jid], baseline[jid]
        if (new[0] != old["vehicle_id"] or
                abs(new[2] - minute(old["pickup_departure_at"])) > tolerance):
            changed.add(jid)
    for left, right in combinations(set(assignments) & set(baseline), 2):
        a, b, old_a, old_b = assignments[left], assignments[right], baseline[left], baseline[right]
        if (a[0] == b[0] == old_a["vehicle_id"] == old_b["vehicle_id"] and
                (a[1] - b[1]) * (old_a["sequence"] - old_b["sequence"]) < 0):
            changed.update((left, right))
    return changed


def exhaustive_objectives(value):
    """Enumerate all subsets, permutations, integer slots and departure minutes.

    Frozen times are records, not newly constrained by changed windows/shifts.
    Departed records stay outside the future route; availability is explicitly
    supplied in these fixtures and the immutable departed sequence is a prefix.
    """
    jobs = {job["job_id"]: job for job in value["jobs"]}
    base = {a["job_id"]: a for a in value["baseline_assignments"]}
    vehicle = value["vehicles"][0]
    travel = {(leg["from_location_id"], leg["to_location_id"]): leg["minutes"]
              for leg in value["travel_times"]}
    departed = {jid for jid, j in jobs.items() if j["state"] == "departed"}
    fixed = {jid for jid, j in jobs.items() if j["frozen"]} - departed
    movable = sorted(set(jobs) - fixed - departed)
    prefix = max([0] + [base[jid]["sequence"] for jid in departed])
    # Larger slots cannot improve an objective: after the final frozen slot,
    # at most len(jobs) consecutive ranks suffice for every future route.
    max_rank = max([prefix] + [base[jid]["sequence"] for jid in fixed]) + len(jobs)
    initial = {jid: ("T1", base[jid]["sequence"], minute(base[jid]["pickup_departure_at"]))
               for jid in departed}
    window = value["windows"][0]
    buffer = value["policy"]["buffer_minutes"]
    best = {"B2": None, "B3": None}

    def schedules(route, ranks, index, cursor, location, assigned, distance):
        if index == len(route):
            yield assigned, distance
            return
        jid = route[index]
        job = jobs[jid]
        approach = travel[location, job["origin_id"]]
        if jid in fixed:
            old = base[jid]
            departure = minute(old["pickup_departure_at"])
            if ranks[index] == old["sequence"] and cursor + approach <= departure:
                yield from schedules(route, ranks, index + 1, minute(old["return_at"]),
                                     job["return_location_id"],
                                     dict(assigned, **{jid: ("T1", ranks[index], departure)}), distance)
            return
        loaded = travel[job["origin_id"], job["terminal_id"]]
        returning = travel[job["terminal_id"], job["return_location_id"]]
        duration = loaded + buffer + job["service_minutes"] + returning
        earliest = max(cursor + approach, minute(job["ready_at"]), minute(window["opens_at"]) - loaded)
        latest = min(minute(window["closes_at"]) - loaded - buffer,
                     minute(vehicle["shift_end_at"]) - duration)
        for departure in range(earliest, latest + 1):
            yield from schedules(route, ranks, index + 1, departure + duration,
                                 job["return_location_id"],
                                 dict(assigned, **{jid: ("T1", ranks[index], departure)}),
                                 distance + approach + loaded + returning)

    for count in range(len(movable) + 1):
        for subset in combinations(movable, count):
            for route in permutations((*sorted(fixed), *subset)):
                for ranks in combinations(range(prefix + 1, max_rank + 1), len(route)):
                    for assigned, distance in schedules(route, ranks, 0, max(0, minute(vehicle["available_at"])),
                                                        vehicle["start_location_id"], initial, 0):
                        changed = len(changed_ids(assigned, base, value["policy"]["time_change_tolerance_minutes"]))
                        values = {"B2": (len(movable) - count, distance),
                                  "B3": (len(movable) - count, changed, distance)}
                        for method, objective in values.items():
                            if best[method] is None or objective < best[method]:
                                best[method] = objective
    return best


def inspect_schedule(value, result):
    """Recalculate this fixture family's schedule, risks and objective from rows.

    Assertions intentionally use no engine diagnostics or reported metrics.
    This is not a general input validator: one compatible vehicle, complete
    matrix and one shared window are explicit bounds of these tiny fixtures.
    """
    jobs = {job["job_id"]: job for job in value["jobs"]}
    base = {a["job_id"]: a for a in value["baseline_assignments"]}
    vehicle = value["vehicles"][0]
    window = value["windows"][0]
    travel = {(leg["from_location_id"], leg["to_location_id"]): leg["minutes"]
              for leg in value["travel_times"]}
    rows = result["assignments"]
    assigned = {a["job_id"]: a for a in rows}
    unassigned = result["unassigned_job_ids"]
    assert len(assigned) == len(rows)
    assert len(set(unassigned)) == len(unassigned)
    assert set(assigned).isdisjoint(unassigned)
    assert set(assigned) | set(unassigned) == set(jobs)
    assert all(not jobs[jid]["frozen"] for jid in unassigned)
    cursor, location = max(0, minute(vehicle["available_at"])), vehicle["start_location_id"]
    prefix = max([0] + [base[jid]["sequence"] for jid, job in jobs.items() if job["state"] == "departed"])
    sequences, risks, distance = set(), set(), 0
    tuples = {}
    for a in sorted(rows, key=lambda a: a["sequence"]):
        jid, sequence = a["job_id"], a["sequence"]
        job = jobs[jid]
        assert a["vehicle_id"] == vehicle["vehicle_id"]
        assert type(sequence) is int and sequence > 0 and sequence not in sequences
        sequences.add(sequence)
        departure, arrival, returned = map(minute, (a["pickup_departure_at"], a["gate_arrival_at"], a["return_at"]))
        tuples[jid] = (a["vehicle_id"], sequence, departure)
        loaded = travel[job["origin_id"], job["terminal_id"]]
        returning = travel[job["terminal_id"], job["return_location_id"]]
        buffer = value["policy"]["buffer_minutes"]
        assert arrival == departure + loaded
        assert returned == arrival + buffer + job["service_minutes"] + returning
        if job["frozen"]:
            assert a == base[jid]
            if arrival + buffer > minute(window["closes_at"]) or returned > minute(vehicle["shift_end_at"]):
                risks.add(jid)
        if job["state"] == "departed":
            assert job["frozen"] and departure <= 0
            assert returned <= minute(vehicle["available_at"])
            continue
        assert sequence > prefix
        approach = travel[location, job["origin_id"]]
        assert departure >= cursor + approach
        assert departure >= minute(job["ready_at"])
        if not job["frozen"]:
            assert arrival >= minute(window["opens_at"])
            assert arrival + buffer <= minute(window["closes_at"])
            assert returned <= minute(vehicle["shift_end_at"])
            distance += approach + loaded + returning
        cursor, location = returned, job["return_location_id"]
    changed = changed_ids(tuples, base, value["policy"]["time_change_tolerance_minutes"])
    return len(unassigned), changed, distance, risks


class FrozenOptimizationOracleTests(unittest.TestCase):
    def check_case(self, value, expected, fixed_risks=1, selected=None):
        original = deepcopy(value)
        self.assertEqual(exhaustive_objectives(value), expected)
        for method in ("B2", "B3"):
            with self.subTest(method=method):
                result = solve(value, method, {"seed": 1, "time_limit_seconds": 3})
                self.assertEqual(result["solution_status"], "OPTIMAL", result["issues"])
                self.assertTrue(result["objective_proven"])
                metrics = result["metrics"]
                unassigned, changed, distance, risks = inspect_schedule(value, result)
                self.assertEqual(metrics["unassigned_count"], unassigned)
                self.assertEqual(metrics["movable_travel_minutes"], distance)
                self.assertEqual(set(metrics["changed_job_ids"]), changed)
                self.assertEqual(metrics["fixed_risk_count"], len(risks))
                objective = (unassigned, distance)
                if method == "B3":
                    objective = (unassigned, len(changed), distance)
                self.assertEqual(objective, expected[method])
                names = ["unassigned", "travel"] if method == "B2" else ["unassigned", "changed", "travel"]
                self.assertEqual([stage["objective"] for stage in result["objective_stages"]], names)
                for stage, optimum in zip(result["objective_stages"], objective):
                    self.assertEqual(stage["status"], "OPTIMAL")
                    self.assertEqual(stage["value"], optimum)
                    self.assertEqual(stage["best_bound"], optimum)
                self.assertEqual(metrics["fixed_risk_count"], fixed_risks)
                self.assertEqual(metrics["movable_violation_count"], 0)
                output = {a["job_id"]: a for a in result["assignments"]}
                if selected is not None:
                    self.assertEqual(set(output), selected[method])
                for job in value["jobs"]:
                    if job["frozen"]:
                        old = next(a for a in value["baseline_assignments"] if a["job_id"] == job["job_id"])
                        self.assertEqual(output[job["job_id"]], old)
                base = {a["job_id"]: a for a in value["baseline_assignments"]}
                assigned = {jid: (a["vehicle_id"], a["sequence"], minute(a["pickup_departure_at"]))
                            for jid, a in output.items()}
                self.assertEqual(set(metrics["changed_job_ids"]), changed_ids(assigned, base, 0))
                self.assertEqual(set(output) | set(result["unassigned_job_ids"]),
                                 {job["job_id"] for job in value["jobs"]})
                self.assertFalse(set(output) & set(result["unassigned_job_ids"]))
        self.assertEqual(value, original)

    def test_future_fixed_integer_slot_exists_or_is_exhausted(self):
        self.check_case(fixture(2), {"B2": (0, 2), "B3": (0, 0, 2)})
        self.check_case(fixture(1), {"B2": (1, 0), "B3": (1, 0, 0)})

    def test_departed_prefix_consumes_slots_without_recharging_travel(self):
        value = fixture(6)
        departed = deepcopy(value["jobs"][0])
        departed.update(job_id="JP", ready_at=at(-4), state="departed", frozen=True,
                        freeze_reason="DEPARTED")
        value["jobs"].append(departed)
        value["baseline_assignments"][0]["sequence"] = 5
        value["baseline_assignments"].insert(0, row("JP", 4, -3))
        self.check_case(value, {"B2": (0, 2), "B3": (0, 0, 2)})
        value["baseline_assignments"][-1]["sequence"] = 5
        value["baseline_assignments"][1]["sequence"] = 6
        self.check_case(value, {"B2": (1, 0), "B3": (1, 0, 0)})

    def test_frozen_cutoff_and_shift_risks_are_not_optional_constraints(self):
        value = fixture()
        value["vehicles"][0]["shift_end_at"] = at(4)
        self.check_case(value, {"B2": (0, 2), "B3": (0, 0, 2)})

    def test_inversion_counts_frozen_participant_and_time_change_only_once(self):
        value = fixture()
        value["baseline_assignments"][0] = row("JM", 3, 8)
        self.check_case(value, {"B2": (0, 2), "B3": (0, 2, 2)})

    def test_two_movable_jobs_compete_for_one_slot_with_different_objectives(self):
        value = fixture()
        ja = value["jobs"][0]
        ja["job_id"] = "JA"
        jb = deepcopy(ja)
        jb.update(job_id="JB", origin_id="D", return_location_id="D")
        value["jobs"].append(jb)
        value["baseline_assignments"][0] = row("JB", 1, 2)
        value["baseline_unassigned_job_ids"] = ["JA"]
        # Only one integer slot exists before JF. B2 chooses the shorter new
        # job, B3 retains JB's original work even though its travel is longer.
        self.check_case(value, {"B2": (1, 2), "B3": (1, 0, 4)}, selected={
            "B2": {"JA", "JF"}, "B3": {"JB", "JF"}})

    def test_approach_to_frozen_node_consumes_time_but_not_travel_objective(self):
        self.check_case(fixture(departure=3), {"B2": (1, 0), "B3": (1, 0, 0)})
        # Removing just that two-minute approach opens the otherwise identical
        # route: this pair separates temporal access from integer-slot limits.
        value = fixture(departure=3)
        next(leg for leg in value["travel_times"] if
             (leg["from_location_id"], leg["to_location_id"]) == ("O", "D"))["minutes"] = 0
        self.check_case(value, {"B2": (0, 2), "B3": (0, 0, 2)})
        # A loose cutoff permits work after the fixed reservation. The real
        # approach still prevents preserving JM's original departure before it;
        # this also avoids relying solely on the redundant workload bound.
        value = fixture(departure=3)
        value["windows"][0]["closes_at"] = at(8)
        # Moving JM after JF reverses both participants; JM's time change is
        # already in that union, so the count is two rather than three.
        self.check_case(value, {"B2": (0, 2), "B3": (0, 2, 2)}, fixed_risks=0)


if __name__ == "__main__":
    unittest.main()
