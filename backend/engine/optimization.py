"""Lexicographic CP-SAT dispatch on the existing v0.1 contract.

Departed work is an immutable prefix. Future fixed reservations are mandatory
route nodes, with their original times and integer sequence values preserved.
The model optimizes optional work; fixed residual risks remain diagnostics.
"""
from __future__ import annotations

import copy
from itertools import combinations
from time import monotonic

import ortools
from ortools.sat.python import cp_model

from .context import Context, EngineInputError, issue, minute, stamp
from .metrics import calculate_metrics


class BuildTimeout(Exception):
    pass


class DispatchModel:
    def __init__(self, c: Context, deadline: float):
        # Imported here to avoid a solver/optimization import cycle.
        from .solver import _schedule, _vehicle_state
        self.c, self.deadline = c, deadline
        self.model = m = cp_model.CpModel()
        self.selected, self.departure, self.rank, self.on_vehicle = {}, {}, {}, {}
        self.route_arcs, self.objectives, self.empty = {}, {}, {}
        self.input_issues = []
        self.zero = m.new_bool_var("false")
        m.add(self.zero == 0)
        self.fixed = {jid for jid, j in c.jobs.items() if j["frozen"]}
        self.movable = sorted(set(c.jobs) - self.fixed)
        self.states = {}
        for vid in sorted(c.vehicles):
            self.check_budget()
            state, location, reasons = _vehicle_state(c, vid)
            fixed_route = [a["job_id"] for a in sorted(c.base.values(), key=lambda a: a["sequence"])
                           if a["vehicle_id"] == vid and a["job_id"] in self.fixed]
            if not reasons and _schedule(c, vid, fixed_route) is None:
                reasons = ["고정 예약 사이의 접근·시간·정수 순서 조건을 확인해야 합니다."]
            if reasons:
                self.input_issues.append(issue(None, "INPUT_MISSING", f"차량 {vid}: {'; '.join(reasons)}"))
            else:
                self.states[vid] = (state, location)

        # Bounds are relative to the snapshot, not epoch-sized big-M constants.
        horizon = max([0] + [minute(v["shift_end_at"]) - c.now for v in c.vehicles.values()]
                      + [minute(a["return_at"]) - c.now for a in c.base.values()
                         if a["job_id"] in self.fixed and a["return_at"] is not None])
        max_seq = max([0] + [int(c.base[jid]["sequence"]) for jid in self.fixed]) + len(c.jobs) + 1
        # CP-SAT has finite integer domains; reject instead of coercing overflow.
        numeric = [horizon, max_seq, int(c.buffer), int(c.s["policy"]["time_change_tolerance_minutes"])]
        numeric += [int(x) for x in c.travel.values()]
        numeric += [int(j["service_minutes"]) for j in c.jobs.values() if j["service_minutes"] is not None]
        if any(abs(x) > 10**12 for x in numeric):
            raise EngineInputError([issue(None, "MODEL_INVALID", "최적화 정수 범위를 초과한 입력입니다.")])
        self.duration, self.trip = {}, {}
        for jid in sorted(c.jobs):
            self.check_budget()
            j = c.jobs[jid]
            p = self.selected[jid] = m.new_bool_var(f"selected:{jid}")
            if j["frozen"]:
                a = c.base[jid]
                m.add(p == 1)
                self.departure[jid] = m.new_constant(minute(a["pickup_departure_at"]) - c.now)
                self.rank[jid] = m.new_constant(int(a["sequence"]))
                continue
            d = self.departure[jid] = m.new_int_var(0, horizon, f"departure:{jid}")
            rank = self.rank[jid] = m.new_int_var(0, max_seq, f"sequence:{jid}")
            m.add(rank == 0).only_enforce_if(p.Not())
            m.add(d == 0).only_enforce_if(p.Not())
            m.add(rank >= 1).only_enforce_if(p)
            loaded = c.travel.get((j["origin_id"], j["terminal_id"]))
            returning = c.travel.get((j["terminal_id"], j["return_location_id"]))
            missing = c.missing_job(jid)
            if loaded is None or returning is None:
                missing.append(issue(jid, "INPUT_MISSING", "적재 또는 지정 복귀 이동시간이 미확정입니다.", refs=c.refs(jid)))
            if missing:
                self.input_issues.extend(missing)
                m.add(p == 0)
                continue
            loaded, returning = int(loaded), int(returning)
            self.trip[jid] = loaded + returning
            self.duration[jid] = loaded + int(c.buffer) + int(j["service_minutes"]) + returning
            w = c.window(jid)
            m.add(d >= minute(j["ready_at"]) - c.now).only_enforce_if(p)
            m.add(d + loaded >= minute(w["opens_at"]) - c.now).only_enforce_if(p)
            m.add(d + loaded + int(c.buffer) <= minute(w["closes_at"]) - c.now).only_enforce_if(p)

        travel_terms = []
        for vid, (available, start_location) in self.states.items():
            self.check_budget()
            v = c.vehicles[vid]
            future = sorted(jid for jid in self.fixed if c.base[jid]["vehicle_id"] == vid
                            and c.jobs[jid]["state"] != "departed")
            candidates = [jid for jid in self.movable if jid in self.duration
                          and c.jobs[jid]["equipment_type"] in v["equipment_types"]
                          and c.jobs[jid]["gross_weight_kg"] <= v["capacity_kg"]]
            ids = sorted(future + candidates)
            if not ids:
                continue
            nodes = {jid: idx + 1 for idx, jid in enumerate(ids)}
            arcs, stored = [], {}
            empty = m.new_bool_var(f"empty:{vid}")
            self.empty[vid] = empty
            arcs.append((0, 0, empty))
            last_departed_seq = max([0] + [int(a["sequence"]) for a in c.base.values()
                                         if a["vehicle_id"] == vid and c.jobs[a["job_id"]]["state"] == "departed"])
            for jid in ids:
                x = self.on_vehicle[vid, jid] = m.new_bool_var(f"on:{vid}:{jid}")
                if jid in self.fixed:
                    m.add(x == 1)
                else:
                    m.add(self.departure[jid] + self.duration[jid] <= minute(v["shift_end_at"]) - c.now).only_enforce_if(x)
                arcs.append((nodes[jid], nodes[jid], x.Not()))
                m.add_implication(x, empty.Not())
                end = m.new_bool_var(f"end:{vid}:{jid}")
                arcs.append((nodes[jid], 0, end))
                stored[jid, None] = end
            for previous in [None, *ids]:
                for jid in ids:
                    self.check_budget()
                    if previous == jid:
                        continue
                    origin = start_location if previous is None else c.jobs[previous]["return_location_id"]
                    minutes = c.travel.get((origin, c.jobs[jid]["origin_id"]))
                    if minutes is None:
                        self.input_issues.append(issue(jid, "INPUT_MISSING", f"후보 접근 이동시간 미확정: {origin} → {c.jobs[jid]['origin_id']}", refs=c.refs(jid)))
                        continue
                    arc = m.new_bool_var(f"arc:{vid}:{previous}:{jid}")
                    arcs.append((0 if previous is None else nodes[previous], nodes[jid], arc))
                    stored[previous, jid] = arc
                    if previous is None:
                        end_time, previous_rank = available - c.now, last_departed_seq
                    elif previous in self.fixed:
                        end_time = minute(c.base[previous]["return_at"]) - c.now
                        previous_rank = self.rank[previous]
                    else:
                        end_time = self.departure[previous] + self.duration[previous]
                        previous_rank = self.rank[previous]
                    m.add(self.departure[jid] >= end_time + int(minutes)).only_enforce_if(arc)
                    m.add(self.rank[jid] > previous_rank).only_enforce_if(arc)
                    if jid not in self.fixed:
                        travel_terms.append(int(minutes) * arc)
            m.add_circuit(arcs)
            self.route_arcs[vid] = stored

        for jid in self.movable:
            m.add(sum(x for (vid, key), x in self.on_vehicle.items() if key == jid) == self.selected[jid])
            if jid in self.trip:
                travel_terms.append(self.trip[jid] * self.selected[jid])
        self.objectives["unassigned"] = sum(1 - self.selected[jid] for jid in self.movable)
        self.objectives["travel"] = sum(travel_terms)
        self.build_change_objective()

    def check_budget(self):
        if monotonic() >= self.deadline:
            raise BuildTimeout

    def all_of(self, values, name):
        result = self.model.new_bool_var(name)
        for value in values:
            self.model.add(result <= value)
        self.model.add(result >= sum(values) - len(values) + 1)
        return result

    def any_of(self, values, name):
        if not values:
            return self.zero
        result = self.model.new_bool_var(name)
        for value in values:
            self.model.add(result >= value)
        self.model.add(result <= sum(values))
        return result

    def retained_on_original_vehicle(self, jid):
        if jid in self.fixed:
            return self.selected[jid]
        return self.on_vehicle.get((self.c.base[jid]["vehicle_id"], jid), self.zero)

    def build_change_objective(self):
        m, c = self.model, self.c
        reasons = {jid: [] for jid in c.jobs}
        tolerance = int(c.s["policy"]["time_change_tolerance_minutes"])
        for jid in self.movable:
            self.check_budget()
            p = self.selected[jid]
            if jid not in c.base:
                reasons[jid].append(p)
                continue
            original = self.retained_on_original_vehicle(jid)
            reasons[jid].append(self.all_of([p, original.Not()], f"vehicle-changed:{jid}"))
            before = minute(c.base[jid]["pickup_departure_at"]) - c.now
            early, late = m.new_bool_var(f"early:{jid}"), m.new_bool_var(f"late:{jid}")
            for flag, expression in [(early, self.departure[jid] < before - tolerance),
                                     (late, self.departure[jid] > before + tolerance)]:
                m.add(expression).only_enforce_if(flag)
            m.add(self.departure[jid] >= before - tolerance).only_enforce_if(early.Not())
            m.add(self.departure[jid] <= before + tolerance).only_enforce_if(late.Not())
            outside = self.any_of([early, late], f"outside-tolerance:{jid}")
            reasons[jid].append(self.all_of([p, outside], f"time-changed:{jid}"))
        for left, right in combinations(sorted(c.base), 2):
            self.check_budget()
            a, b = c.base[left], c.base[right]
            if a["vehicle_id"] != b["vehicle_id"]:
                continue
            if a["sequence"] > b["sequence"]:
                left, right = right, left
            reversed_order = m.new_bool_var(f"reversed:{left}:{right}")
            m.add(self.rank[left] > self.rank[right]).only_enforce_if(reversed_order)
            m.add(self.rank[left] <= self.rank[right]).only_enforce_if(reversed_order.Not())
            inversion = self.all_of([self.retained_on_original_vehicle(left),
                                     self.retained_on_original_vehicle(right), reversed_order], f"inversion:{left}:{right}")
            reasons[left].append(inversion)
            reasons[right].append(inversion)
        self.objectives["changed"] = sum(self.any_of(values, f"changed:{jid}") for jid, values in reasons.items())

    def extract(self, solver):
        c = self.c
        assignments = [copy.deepcopy(c.base[jid]) for jid in sorted(self.fixed)]
        for (vid, jid), x in sorted(self.on_vehicle.items()):
            if jid in self.fixed or not solver.value(x):
                continue
            departure = solver.value(self.departure[jid]) + c.now
            loaded = int(c.travel[c.jobs[jid]["origin_id"], c.jobs[jid]["terminal_id"]])
            assignments.append(dict(job_id=jid, vehicle_id=vid, sequence=solver.value(self.rank[jid]),
                                    pickup_departure_at=stamp(departure), gate_arrival_at=stamp(departure + loaded),
                                    return_at=stamp(departure + self.duration[jid])))
        return sorted(assignments, key=lambda a: (a["vehicle_id"], a["sequence"])), sorted(
            jid for jid in self.movable if not solver.value(self.selected[jid]))

    def hint(self, assignments):
        """Both methods get the same bounded B1 construction, within their budget."""
        current = {a["job_id"]: a for a in assignments}
        for jid in self.movable:
            row = current.get(jid)
            self.model.add_hint(self.selected[jid], int(row is not None))
            self.model.add_hint(self.departure[jid], minute(row["pickup_departure_at"]) - self.c.now if row else 0)
            self.model.add_hint(self.rank[jid], int(row["sequence"]) if row else 0)
        for (vid, jid), variable in self.on_vehicle.items():
            self.model.add_hint(variable, int(jid in current and current[jid]["vehicle_id"] == vid))
        for vid, arcs in self.route_arcs.items():
            route = [a["job_id"] for a in sorted(assignments, key=lambda a: a["sequence"])
                     if a["vehicle_id"] == vid and self.c.jobs[a["job_id"]]["state"] != "departed"]
            edges = set(zip([None, *route], [*route, None])) if route else set()
            self.model.add_hint(self.empty[vid], int(not route))
            for edge, variable in arcs.items():
                self.model.add_hint(variable, int(edge in edges))


def _run_stage(model, objective, remaining, seed):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    model.minimize(objective)
    return solver, solver.solve(model)


def solve_optimized(snapshot, method, config, started, engine_version):
    from .solver import _diagnose, _insert, _unassigned_issue, _vehicle_state
    c = Context(snapshot, config)
    order = ["unassigned", "travel"] if method == "B2" else ["unassigned", "changed", "travel"]
    stages = [dict(objective=name, status="NOT_RUN", value=None, best_bound=None) for name in order]
    assignments = [copy.deepcopy(a) for a in c.base.values() if c.jobs[a["job_id"]]["frozen"]]
    unassigned = sorted(jid for jid, job in c.jobs.items() if not job["frozen"])
    status, input_issues, timed_out = "UNKNOWN", [], False
    effective_seed = config["seed"] % (2**31 - 1)
    deadline = started + config["time_limit_seconds"]
    last_values = None
    # Seed construction is charged to the same deadline, not extra solver time.
    warm_assignments, warm_unassigned, warm_issues, _ = _insert(c, min(deadline, monotonic() + 1))
    warm_metrics = calculate_metrics(snapshot, warm_assignments, warm_unassigned, warm_issues, 0)
    has_incumbent = (warm_metrics["movable_violation_count"] == 0
                     and not any(i["code"] == "INPUT_MISSING" for i in warm_issues)
                     and not any(_vehicle_state(c, vid)[2] for vid in c.vehicles))
    if has_incumbent:
        assignments, unassigned = warm_assignments, warm_unassigned
        status = "FEASIBLE"
        last_values = dict(unassigned=warm_metrics["unassigned_count"],
                           changed=len(warm_metrics["changed_job_ids"]),
                           travel=warm_metrics["movable_travel_minutes"])
    try:
        dispatch = DispatchModel(c, deadline)
        input_issues = dispatch.input_issues
        if has_incumbent:
            dispatch.hint(assignments)
            dispatch.model.add(dispatch.objectives["unassigned"] <= last_values["unassigned"])
        validation = dispatch.model.validate()
        if validation:
            raise EngineInputError([issue(None, "MODEL_INVALID", "최적화 모형의 정수 범위·제약 검증에 실패했습니다.")])
        for stage in stages:
            remaining = deadline - monotonic()
            if remaining <= 0:
                timed_out = True
                break
            expression = dispatch.objectives[stage["objective"]]
            solver, outcome = _run_stage(dispatch.model, expression, remaining, effective_seed)
            if outcome in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                candidate_values = {name: int(solver.value(expr)) for name, expr in dispatch.objectives.items()}
                if last_values is None or tuple(candidate_values[name] for name in order) <= tuple(last_values[name] for name in order):
                    assignments, unassigned = dispatch.extract(solver)
                    last_values = candidate_values
                stage.update(status="OPTIMAL" if outcome == cp_model.OPTIMAL else "FEASIBLE",
                             value=last_values[stage["objective"]], best_bound=solver.best_objective_bound)
                status = "FEASIBLE"
                if outcome != cp_model.OPTIMAL:
                    timed_out = True
                    break
                dispatch.model.add(expression == stage["value"])
                dispatch.model.clear_hints()
                dispatch.hint(assignments)
            elif outcome == cp_model.MODEL_INVALID:
                raise EngineInputError([issue(None, "MODEL_INVALID", "최적화 솔버가 모형을 거절했습니다.")])
            else:
                stage["status"] = "UNKNOWN"
                timed_out = outcome == cp_model.UNKNOWN
                if outcome == cp_model.INFEASIBLE:
                    status = "INFEASIBLE"
                break
    except BuildTimeout:
        timed_out = True

    proven = all(stage["status"] == "OPTIMAL" for stage in stages) and not input_issues
    if proven:
        status = "OPTIMAL"
    issues = _diagnose(c, assignments) + input_issues
    for jid in unassigned:
        for detail in _unassigned_issue(c, jid, timed_out, set()):
            if detail["code"] == "SEARCH_LIMIT":
                detail["explanation"] = ("최적화 결과에서 미처리로 남았습니다. 전체 미처리 목적의 증명과 이 작업 단독의 불가능은 다릅니다. 차량 경쟁·고정 예약·시간·근무·정수 순서 제약을 추가 확인해야 합니다."
                                         if proven else "제한 시간 또는 현재 확인된 입력 범위에서 배정을 확정하지 못했습니다. 이 작업의 불가능을 증명한 것은 아닙니다.")
            issues.append(detail)
    if status == "INFEASIBLE":
        issues.append(issue(None, "MODEL_INVALID", "전체 최적화 모형이 불능으로 판정됐습니다. 고정 기록·모형 제약을 확인해야 하며 각 미처리 작업의 불가능을 뜻하지 않습니다.", "solver_proven"))
    if any(i["code"] == "INPUT_MISSING" for i in issues):
        status, proven = "INPUT_INCOMPLETE", False
    metrics = calculate_metrics(snapshot, assignments, unassigned, issues, int((monotonic() - started) * 1000))
    if last_values is not None and last_values != {"unassigned": metrics["unassigned_count"],
                                                 "changed": len(metrics["changed_job_ids"]),
                                                 "travel": metrics["movable_travel_minutes"]}:
        raise EngineInputError([issue(None, "MODEL_INVALID", "솔버 목적값과 반환 일정의 지표가 일치하지 않습니다.")])
    return dict(method=method, result_origin="computed", solution_status=status, assignments=assignments,
                unassigned_job_ids=unassigned, issues=issues, metrics=metrics, objective_proven=proven,
                approval_eligible=False, engine_version=engine_version, solver_version=f"OR-Tools {ortools.__version__}",
                objective_stages=stages, validation_status="not_run", execution_metadata=dict(
                    solver_settings=dict(algorithm="cp-sat-lexicographic", seed=config["seed"], effective_seed=effective_seed,
                                         seed_used=True, time_limit_seconds=config["time_limit_seconds"],
                                         time_limit_reached=timed_out, budget_scope="input/model/all objective stages",
                                         proof_scope="known-input v0.1 integer sequence model", external_warm_start=False,
                                         warm_start_budget_seconds=1, warm_start_valid=has_incumbent),
                    initial_solution_ref="internal:B1-same-input-within-total-budget", worker_count=1))
