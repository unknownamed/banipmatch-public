-- 반입맞춤 SQLite storage draft v0.1.0
-- SQLite >= 3.37 with JSON functions. Every backend connection MUST set BOTH
-- foreign_keys=ON and recursive_triggers=ON (the latter protects against REPLACE).
-- One Python backend owns the DB; clients never open it directly.
-- scenarios.snapshot_json is the authoritative immutable input. Normalized
-- input rows are searchable projections, validated against that JSON by the API.
-- plans.plan_json is the immutable plan-version artifact; assignments is its
-- search projection. Import/approval must insert every projection in ONE transaction.
-- UPDATE/DELETE are blocked on immutable rows. Projection completeness/equality,
-- timestamp RFC3339 validation, hash calculation, baseline assigned/unassigned partition,
-- scheduling/empty repositioning/frozen-job constraints and permissions are API duties.
-- Input revision (scenario_id) and dispatch revision (plan version) are distinct.
-- New scenario: API checks base version AND baseline == current plan, then changes
-- plan_heads.active_scenario_id atomically. Old scenarios and runs remain readable.
-- Approval: BEGIN IMMEDIATE; recheck roles/freshness/confirmed windows/computed result;
-- insert new plan+assignments+approval; CAS plan_heads WHERE current_version=expected
-- AND active_scenario_id=run.scenario_id; require rowcount=1; record idempotent response;
-- COMMIT. Roll back ALL writes on failure. Never send external messages/reservations.
-- Circular initial scenario/base-plan FKs are DEFERRABLE and checked at COMMIT.
PRAGMA foreign_keys = ON;
PRAGMA recursive_triggers = ON;

BEGIN;

CREATE TABLE scenarios (
    scenario_id TEXT NOT NULL PRIMARY KEY CHECK(length(scenario_id) BETWEEN 1 AND 64),
    plan_id TEXT NOT NULL CHECK(length(plan_id) BETWEEN 1 AND 64),
    base_plan_version INTEGER NOT NULL CHECK(base_plan_version >= 1),
    schema_version TEXT NOT NULL CHECK(schema_version = '0.1.0'),
    data_mode TEXT NOT NULL CHECK(data_mode IN ('simulated','observed','mixed')),
    as_of TEXT NOT NULL CHECK(substr(as_of,-1)='Z' AND julianday(as_of) IS NOT NULL),
    input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64 AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json) AND json_type(snapshot_json)='object'),
    created_at TEXT NOT NULL CHECK(substr(created_at,-1)='Z' AND julianday(created_at) IS NOT NULL),
    UNIQUE(scenario_id, plan_id),
    UNIQUE(scenario_id, plan_id, base_plan_version, input_sha256),
    CHECK(json_extract(snapshot_json,'$.scenario_id') IS scenario_id),
    CHECK(json_extract(snapshot_json,'$.plan_id') IS plan_id),
    CHECK(json_extract(snapshot_json,'$.base_plan_version') IS base_plan_version),
    CHECK(json_extract(snapshot_json,'$.schema_version') IS schema_version),
    CHECK(json_extract(snapshot_json,'$.data_mode') IS data_mode),
    CHECK(json_extract(snapshot_json,'$.as_of') IS as_of),
    FOREIGN KEY(plan_id, base_plan_version) REFERENCES plans(plan_id, version)
        DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE locations (
    scenario_id TEXT NOT NULL,
    location_id TEXT NOT NULL CHECK(length(location_id) BETWEEN 1 AND 64),
    name TEXT NOT NULL CHECK(length(name)>0),
    kind TEXT NOT NULL CHECK(kind IN ('depot','origin','terminal')),
    latitude REAL CHECK(latitude IS NULL OR latitude BETWEEN -90 AND 90),
    longitude REAL CHECK(longitude IS NULL OR longitude BETWEEN -180 AND 180),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND json_type(evidence_json)='object'),
    PRIMARY KEY(scenario_id, location_id),
    FOREIGN KEY(scenario_id) REFERENCES scenarios(scenario_id)
) STRICT;

CREATE TABLE vehicles (
    scenario_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL CHECK(length(vehicle_id) BETWEEN 1 AND 64),
    start_location_id TEXT NOT NULL,
    available_at TEXT CHECK(available_at IS NULL OR (substr(available_at,-1)='Z' AND julianday(available_at) IS NOT NULL)),
    shift_end_at TEXT NOT NULL CHECK(substr(shift_end_at,-1)='Z' AND julianday(shift_end_at) IS NOT NULL),
    capacity_kg INTEGER NOT NULL CHECK(capacity_kg>0),
    equipment_types_json TEXT NOT NULL CHECK(json_valid(equipment_types_json)
        AND json_type(equipment_types_json)='array' AND json_array_length(equipment_types_json)>0),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND json_type(evidence_json)='object'),
    plate_no TEXT CHECK(plate_no IS NULL OR length(plate_no) BETWEEN 1 AND 20),
    PRIMARY KEY(scenario_id, vehicle_id),
    FOREIGN KEY(scenario_id) REFERENCES scenarios(scenario_id),
    FOREIGN KEY(scenario_id, start_location_id) REFERENCES locations(scenario_id, location_id)
) STRICT;

CREATE TABLE windows (
    scenario_id TEXT NOT NULL,
    window_id TEXT NOT NULL CHECK(length(window_id) BETWEEN 1 AND 64),
    voyage_id TEXT NOT NULL CHECK(length(voyage_id) BETWEEN 1 AND 64),
    terminal_id TEXT NOT NULL,
    opens_at TEXT NOT NULL CHECK(substr(opens_at,-1)='Z' AND julianday(opens_at) IS NOT NULL),
    closes_at TEXT NOT NULL CHECK(substr(closes_at,-1)='Z' AND julianday(closes_at) IS NOT NULL),
    verification TEXT NOT NULL CHECK(verification IN ('confirmed','unconfirmed','conflict')),
    confirmed_by TEXT,
    confirmed_at TEXT CHECK(confirmed_at IS NULL OR (substr(confirmed_at,-1)='Z' AND julianday(confirmed_at) IS NOT NULL)),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND json_type(evidence_json)='object'),
    PRIMARY KEY(scenario_id, window_id),
    UNIQUE(scenario_id, voyage_id, terminal_id),
    UNIQUE(scenario_id, window_id, voyage_id, terminal_id),
    CHECK(julianday(opens_at)<=julianday(closes_at)),
    CHECK(verification<>'confirmed' OR (confirmed_by IS NOT NULL AND length(trim(confirmed_by))>0 AND confirmed_at IS NOT NULL)),
    FOREIGN KEY(scenario_id) REFERENCES scenarios(scenario_id),
    FOREIGN KEY(scenario_id, terminal_id) REFERENCES locations(scenario_id, location_id)
) STRICT;

CREATE TABLE jobs (
    scenario_id TEXT NOT NULL,
    job_id TEXT NOT NULL CHECK(length(job_id) BETWEEN 1 AND 64),
    voyage_id TEXT NOT NULL,
    origin_id TEXT NOT NULL,
    terminal_id TEXT NOT NULL,
    return_location_id TEXT NOT NULL,
    ready_at TEXT CHECK(ready_at IS NULL OR (substr(ready_at,-1)='Z' AND julianday(ready_at) IS NOT NULL)),
    gross_weight_kg INTEGER CHECK(gross_weight_kg IS NULL OR gross_weight_kg>0),
    equipment_type TEXT NOT NULL CHECK(equipment_type IN ('DRY20','DRY40')),
    service_minutes INTEGER CHECK(service_minutes IS NULL OR service_minutes>=0),
    state TEXT NOT NULL CHECK(state IN ('planned','departed')),
    frozen INTEGER NOT NULL CHECK(frozen IN (0,1)),
    freeze_reason TEXT,
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND json_type(evidence_json)='object'),
    container_no TEXT CHECK(container_no IS NULL OR length(container_no)=11),
    booking_no TEXT CHECK(booking_no IS NULL OR length(booking_no) BETWEEN 1 AND 35),
    cargo_owner TEXT CHECK(cargo_owner IS NULL OR length(cargo_owner) BETWEEN 1 AND 60),
    PRIMARY KEY(scenario_id, job_id),
    CHECK(state<>'departed' OR frozen=1),
    CHECK(frozen=0 OR (freeze_reason IS NOT NULL AND length(trim(freeze_reason))>0)),
    FOREIGN KEY(scenario_id) REFERENCES scenarios(scenario_id),
    FOREIGN KEY(scenario_id, origin_id) REFERENCES locations(scenario_id, location_id),
    FOREIGN KEY(scenario_id, terminal_id) REFERENCES locations(scenario_id, location_id),
    FOREIGN KEY(scenario_id, return_location_id) REFERENCES locations(scenario_id, location_id),
    FOREIGN KEY(scenario_id, voyage_id, terminal_id) REFERENCES windows(scenario_id, voyage_id, terminal_id)
) STRICT;

CREATE TABLE travel_times (
    scenario_id TEXT NOT NULL,
    from_location_id TEXT NOT NULL,
    to_location_id TEXT NOT NULL,
    minutes INTEGER NOT NULL CHECK(minutes>=0),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND json_type(evidence_json)='object'),
    PRIMARY KEY(scenario_id, from_location_id, to_location_id),
    FOREIGN KEY(scenario_id) REFERENCES scenarios(scenario_id),
    FOREIGN KEY(scenario_id, from_location_id) REFERENCES locations(scenario_id, location_id),
    FOREIGN KEY(scenario_id, to_location_id) REFERENCES locations(scenario_id, location_id)
) STRICT;

CREATE TABLE changes (
    scenario_id TEXT NOT NULL PRIMARY KEY,
    change_id TEXT NOT NULL CHECK(length(change_id) BETWEEN 1 AND 64),
    voyage_id TEXT NOT NULL,
    terminal_id TEXT NOT NULL,
    previous_opens_at TEXT NOT NULL CHECK(substr(previous_opens_at,-1)='Z' AND julianday(previous_opens_at) IS NOT NULL),
    previous_closes_at TEXT NOT NULL CHECK(substr(previous_closes_at,-1)='Z' AND julianday(previous_closes_at) IS NOT NULL),
    new_window_id TEXT NOT NULL,
    verification TEXT NOT NULL CHECK(verification IN ('confirmed','unconfirmed','conflict')),
    confirmed_by TEXT,
    confirmed_at TEXT CHECK(confirmed_at IS NULL OR (substr(confirmed_at,-1)='Z' AND julianday(confirmed_at) IS NOT NULL)),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND json_type(evidence_json)='object'),
    CHECK(julianday(previous_opens_at)<=julianday(previous_closes_at)),
    CHECK(verification<>'confirmed' OR (confirmed_by IS NOT NULL AND length(trim(confirmed_by))>0 AND confirmed_at IS NOT NULL)),
    FOREIGN KEY(scenario_id) REFERENCES scenarios(scenario_id),
    FOREIGN KEY(scenario_id, new_window_id, voyage_id, terminal_id)
        REFERENCES windows(scenario_id, window_id, voyage_id, terminal_id)
) STRICT;

-- Baseline of EACH input revision; a new scenario can refer to an existing plan version.
CREATE TABLE baseline_assignments (
    scenario_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence>=1),
    pickup_departure_at TEXT NOT NULL CHECK(substr(pickup_departure_at,-1)='Z' AND julianday(pickup_departure_at) IS NOT NULL),
    gate_arrival_at TEXT CHECK(gate_arrival_at IS NULL OR (substr(gate_arrival_at,-1)='Z' AND julianday(gate_arrival_at) IS NOT NULL)),
    return_at TEXT CHECK(return_at IS NULL OR (substr(return_at,-1)='Z' AND julianday(return_at) IS NOT NULL)),
    PRIMARY KEY(scenario_id, job_id),
    UNIQUE(scenario_id, vehicle_id, sequence),
    FOREIGN KEY(scenario_id, job_id) REFERENCES jobs(scenario_id, job_id),
    FOREIGN KEY(scenario_id, vehicle_id) REFERENCES vehicles(scenario_id, vehicle_id)
) STRICT;

CREATE TABLE plans (
    plan_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version>=1),
    scenario_id TEXT NOT NULL,
    approval_id TEXT,
    plan_json TEXT NOT NULL CHECK(json_valid(plan_json) AND json_type(plan_json)='object'),
    created_at TEXT NOT NULL CHECK(substr(created_at,-1)='Z' AND julianday(created_at) IS NOT NULL),
    PRIMARY KEY(plan_id, version),
    UNIQUE(plan_id, version, scenario_id),
    CHECK(json_extract(plan_json,'$.plan_id') IS plan_id),
    CHECK(json_extract(plan_json,'$.version') IS version),
    CHECK(json_extract(plan_json,'$.scenario_id') IS scenario_id),
    CHECK(json_extract(plan_json,'$.approval_id') IS approval_id),
    FOREIGN KEY(scenario_id, plan_id) REFERENCES scenarios(scenario_id, plan_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(approval_id, plan_id, version, scenario_id)
        REFERENCES approvals(approval_id, plan_id, version, scenario_id)
        DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE baseline_unassigned (
    scenario_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    PRIMARY KEY(scenario_id, job_id),
    FOREIGN KEY(scenario_id, job_id) REFERENCES jobs(scenario_id, job_id)
) STRICT;

CREATE TRIGGER baseline_unassigned_disjoint
BEFORE INSERT ON baseline_unassigned
WHEN EXISTS (SELECT 1 FROM baseline_assignments a WHERE a.scenario_id=NEW.scenario_id AND a.job_id=NEW.job_id)
  OR EXISTS (SELECT 1 FROM jobs j WHERE j.scenario_id=NEW.scenario_id AND j.job_id=NEW.job_id AND j.frozen=1)
BEGIN SELECT RAISE(ABORT,'baseline unassigned job must be movable and not assigned'); END;

CREATE TRIGGER baseline_assignments_disjoint
BEFORE INSERT ON baseline_assignments
WHEN EXISTS (SELECT 1 FROM baseline_unassigned u WHERE u.scenario_id=NEW.scenario_id AND u.job_id=NEW.job_id)
BEGIN SELECT RAISE(ABORT,'baseline job is already marked unassigned'); END;

CREATE TRIGGER baseline_unassigned_no_update BEFORE UPDATE ON baseline_unassigned
BEGIN SELECT RAISE(ABORT,'baseline_unassigned rows are immutable; insert a new revision'); END;
CREATE TRIGGER baseline_unassigned_no_delete BEFORE DELETE ON baseline_unassigned
BEGIN SELECT RAISE(ABORT,'baseline_unassigned rows are immutable audit records'); END;

CREATE TABLE plan_heads (
    plan_id TEXT NOT NULL PRIMARY KEY,
    current_version INTEGER NOT NULL CHECK(current_version>=1),
    active_scenario_id TEXT NOT NULL,
    updated_at TEXT NOT NULL CHECK(substr(updated_at,-1)='Z' AND julianday(updated_at) IS NOT NULL),
    FOREIGN KEY(plan_id, current_version) REFERENCES plans(plan_id, version),
    FOREIGN KEY(active_scenario_id, plan_id) REFERENCES scenarios(scenario_id, plan_id)
) STRICT;

CREATE TABLE assignments (
    plan_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version>=1),
    scenario_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence>=1),
    pickup_departure_at TEXT NOT NULL CHECK(substr(pickup_departure_at,-1)='Z' AND julianday(pickup_departure_at) IS NOT NULL),
    gate_arrival_at TEXT CHECK(gate_arrival_at IS NULL OR (substr(gate_arrival_at,-1)='Z' AND julianday(gate_arrival_at) IS NOT NULL)),
    return_at TEXT CHECK(return_at IS NULL OR (substr(return_at,-1)='Z' AND julianday(return_at) IS NOT NULL)),
    PRIMARY KEY(plan_id, version, job_id),
    UNIQUE(plan_id, version, vehicle_id, sequence),
    FOREIGN KEY(plan_id, version, scenario_id) REFERENCES plans(plan_id, version, scenario_id),
    FOREIGN KEY(scenario_id, job_id) REFERENCES jobs(scenario_id, job_id),
    FOREIGN KEY(scenario_id, vehicle_id) REFERENCES vehicles(scenario_id, vehicle_id)
) STRICT;

CREATE TABLE runs (
    run_id TEXT NOT NULL PRIMARY KEY CHECK(length(run_id) BETWEEN 1 AND 64),
    scenario_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    base_plan_version INTEGER NOT NULL CHECK(base_plan_version>=1),
    input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64 AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled')),
    created_at TEXT NOT NULL CHECK(substr(created_at,-1)='Z' AND julianday(created_at) IS NOT NULL),
    started_at TEXT CHECK(started_at IS NULL OR (substr(started_at,-1)='Z' AND julianday(started_at) IS NOT NULL)),
    finished_at TEXT CHECK(finished_at IS NULL OR (substr(finished_at,-1)='Z' AND julianday(finished_at) IS NOT NULL)),
    methods_json TEXT NOT NULL CHECK(json_valid(methods_json) AND json_type(methods_json)='array'
        AND json_array_length(methods_json)>0),
    time_limit_seconds INTEGER NOT NULL CHECK(time_limit_seconds BETWEEN 1 AND 120),
    seed INTEGER NOT NULL CHECK(seed>=0),
    error_json TEXT CHECK(error_json IS NULL OR (json_valid(error_json) AND json_type(error_json)='object')),
    UNIQUE(run_id, scenario_id, plan_id, base_plan_version),
    FOREIGN KEY(scenario_id, plan_id, base_plan_version, input_sha256)
        REFERENCES scenarios(scenario_id, plan_id, base_plan_version, input_sha256),
    FOREIGN KEY(plan_id, base_plan_version) REFERENCES plans(plan_id, version)
) STRICT;

CREATE TABLE method_results (
    run_id TEXT NOT NULL,
    method TEXT NOT NULL CHECK(method IN ('B0','B1','B2','B3')),
    scenario_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    base_plan_version INTEGER NOT NULL CHECK(base_plan_version>=1),
    result_origin TEXT NOT NULL CHECK(result_origin IN ('illustrative_fixture','computed')),
    solution_status TEXT NOT NULL CHECK(solution_status IN
        ('BASELINE','HEURISTIC','OPTIMAL','FEASIBLE','INFEASIBLE','UNKNOWN','MODEL_INVALID','INPUT_INCOMPLETE')),
    objective_proven INTEGER NOT NULL CHECK(objective_proven IN (0,1)),
    approval_eligible INTEGER NOT NULL CHECK(approval_eligible IN (0,1)),
    result_json TEXT NOT NULL CHECK(json_valid(result_json) AND json_type(result_json)='object'),
    PRIMARY KEY(run_id, method),
    UNIQUE(run_id, method, scenario_id, plan_id, base_plan_version),
    CHECK(json_extract(result_json,'$.method') IS method),
    CHECK(json_extract(result_json,'$.result_origin') IS result_origin),
    CHECK(json_extract(result_json,'$.solution_status') IS solution_status),
    CHECK(json_extract(result_json,'$.objective_proven') IS objective_proven),
    CHECK(json_extract(result_json,'$.approval_eligible') IS approval_eligible),
    CHECK(result_origin<>'illustrative_fixture' OR approval_eligible=0),
    FOREIGN KEY(run_id, scenario_id, plan_id, base_plan_version)
        REFERENCES runs(run_id, scenario_id, plan_id, base_plan_version)
) STRICT;

CREATE TABLE approvals (
    approval_id TEXT NOT NULL PRIMARY KEY CHECK(length(approval_id) BETWEEN 1 AND 64),
    plan_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version>=1),
    scenario_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    method TEXT NOT NULL CHECK(method IN ('B1','B2','B3')),
    expected_version INTEGER NOT NULL CHECK(expected_version>=1),
    approved_by TEXT NOT NULL CHECK(length(trim(approved_by))>0),
    approved_at TEXT NOT NULL CHECK(substr(approved_at,-1)='Z' AND julianday(approved_at) IS NOT NULL),
    acknowledged_job_ids_json TEXT NOT NULL CHECK(json_valid(acknowledged_job_ids_json)
        AND json_type(acknowledged_job_ids_json)='array'),
    external_actions_performed INTEGER NOT NULL DEFAULT 0 CHECK(external_actions_performed=0),
    UNIQUE(plan_id, version),
    UNIQUE(run_id, method),
    UNIQUE(approval_id, plan_id, version, scenario_id),
    CHECK(version=expected_version+1),
    FOREIGN KEY(plan_id, version, scenario_id) REFERENCES plans(plan_id, version, scenario_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(run_id, method, scenario_id, plan_id, expected_version)
        REFERENCES method_results(run_id, method, scenario_id, plan_id, base_plan_version)
) STRICT;

-- Complete response is persisted in the SAME transaction as the mutation.
-- actor_id comes from authentication; route includes HTTP verb and resolved path.
-- Same key/different request_sha256 -> API 409; same body -> replay stored response.
CREATE TABLE idempotency_records (
    actor_id TEXT NOT NULL CHECK(length(actor_id)>0),
    route TEXT NOT NULL CHECK(length(route)>0),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)>0),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64 AND request_sha256 NOT GLOB '*[^0-9a-f]*'),
    response_status INTEGER NOT NULL CHECK(response_status BETWEEN 100 AND 599),
    response_json TEXT NOT NULL CHECK(json_valid(response_json)),
    created_at TEXT NOT NULL CHECK(substr(created_at,-1)='Z' AND julianday(created_at) IS NOT NULL),
    PRIMARY KEY(actor_id, route, idempotency_key)
) STRICT;

CREATE INDEX scenarios_by_plan ON scenarios(plan_id, base_plan_version, created_at);
CREATE INDEX jobs_by_voyage ON jobs(scenario_id, terminal_id, voyage_id);
CREATE INDEX runs_by_plan ON runs(plan_id, base_plan_version, created_at);

CREATE TRIGGER approvals_require_computed_result
BEFORE INSERT ON approvals
WHEN NOT EXISTS (
    SELECT 1 FROM method_results m
    WHERE m.run_id=NEW.run_id AND m.method=NEW.method
      AND m.scenario_id=NEW.scenario_id AND m.plan_id=NEW.plan_id
      AND m.base_plan_version=NEW.expected_version
      AND m.result_origin='computed' AND m.approval_eligible=1
)
BEGIN SELECT RAISE(ABORT,'approval requires an eligible computed result'); END;

CREATE TRIGGER runs_keep_input_identity
BEFORE UPDATE ON runs
WHEN NEW.run_id IS NOT OLD.run_id OR NEW.scenario_id IS NOT OLD.scenario_id
  OR NEW.plan_id IS NOT OLD.plan_id OR NEW.base_plan_version IS NOT OLD.base_plan_version
  OR NEW.input_sha256 IS NOT OLD.input_sha256 OR NEW.created_at IS NOT OLD.created_at
  OR NEW.methods_json IS NOT OLD.methods_json OR NEW.time_limit_seconds IS NOT OLD.time_limit_seconds
  OR NEW.seed IS NOT OLD.seed
BEGIN SELECT RAISE(ABORT,'run input identity is immutable'); END;

CREATE TRIGGER runs_no_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT,'runs are audit records'); END;

CREATE TRIGGER plan_heads_keep_plan_id
BEFORE UPDATE OF plan_id ON plan_heads WHEN NEW.plan_id IS NOT OLD.plan_id
BEGIN SELECT RAISE(ABORT,'plan head identity is immutable'); END;

CREATE TRIGGER scenarios_no_update BEFORE UPDATE ON scenarios
BEGIN SELECT RAISE(ABORT,'scenarios rows are immutable; insert a new revision'); END;
CREATE TRIGGER scenarios_no_delete BEFORE DELETE ON scenarios
BEGIN SELECT RAISE(ABORT,'scenarios rows are immutable audit records'); END;

CREATE TRIGGER locations_no_update BEFORE UPDATE ON locations
BEGIN SELECT RAISE(ABORT,'locations rows are immutable; insert a new revision'); END;
CREATE TRIGGER locations_no_delete BEFORE DELETE ON locations
BEGIN SELECT RAISE(ABORT,'locations rows are immutable audit records'); END;

CREATE TRIGGER vehicles_no_update BEFORE UPDATE ON vehicles
BEGIN SELECT RAISE(ABORT,'vehicles rows are immutable; insert a new revision'); END;
CREATE TRIGGER vehicles_no_delete BEFORE DELETE ON vehicles
BEGIN SELECT RAISE(ABORT,'vehicles rows are immutable audit records'); END;

CREATE TRIGGER windows_no_update BEFORE UPDATE ON windows
BEGIN SELECT RAISE(ABORT,'windows rows are immutable; insert a new revision'); END;
CREATE TRIGGER windows_no_delete BEFORE DELETE ON windows
BEGIN SELECT RAISE(ABORT,'windows rows are immutable audit records'); END;

CREATE TRIGGER jobs_no_update BEFORE UPDATE ON jobs
BEGIN SELECT RAISE(ABORT,'jobs rows are immutable; insert a new revision'); END;
CREATE TRIGGER jobs_no_delete BEFORE DELETE ON jobs
BEGIN SELECT RAISE(ABORT,'jobs rows are immutable audit records'); END;

CREATE TRIGGER travel_times_no_update BEFORE UPDATE ON travel_times
BEGIN SELECT RAISE(ABORT,'travel_times rows are immutable; insert a new revision'); END;
CREATE TRIGGER travel_times_no_delete BEFORE DELETE ON travel_times
BEGIN SELECT RAISE(ABORT,'travel_times rows are immutable audit records'); END;

CREATE TRIGGER changes_no_update BEFORE UPDATE ON changes
BEGIN SELECT RAISE(ABORT,'changes rows are immutable; insert a new revision'); END;
CREATE TRIGGER changes_no_delete BEFORE DELETE ON changes
BEGIN SELECT RAISE(ABORT,'changes rows are immutable audit records'); END;

CREATE TRIGGER baseline_assignments_no_update BEFORE UPDATE ON baseline_assignments
BEGIN SELECT RAISE(ABORT,'baseline_assignments rows are immutable; insert a new revision'); END;
CREATE TRIGGER baseline_assignments_no_delete BEFORE DELETE ON baseline_assignments
BEGIN SELECT RAISE(ABORT,'baseline_assignments rows are immutable audit records'); END;

CREATE TRIGGER plans_no_update BEFORE UPDATE ON plans
BEGIN SELECT RAISE(ABORT,'plans rows are immutable; insert a new revision'); END;
CREATE TRIGGER plans_no_delete BEFORE DELETE ON plans
BEGIN SELECT RAISE(ABORT,'plans rows are immutable audit records'); END;

CREATE TRIGGER assignments_no_update BEFORE UPDATE ON assignments
BEGIN SELECT RAISE(ABORT,'assignments rows are immutable; insert a new revision'); END;
CREATE TRIGGER assignments_no_delete BEFORE DELETE ON assignments
BEGIN SELECT RAISE(ABORT,'assignments rows are immutable audit records'); END;

CREATE TRIGGER method_results_no_update BEFORE UPDATE ON method_results
BEGIN SELECT RAISE(ABORT,'method_results rows are immutable; insert a new revision'); END;
CREATE TRIGGER method_results_no_delete BEFORE DELETE ON method_results
BEGIN SELECT RAISE(ABORT,'method_results rows are immutable audit records'); END;

CREATE TRIGGER approvals_no_update BEFORE UPDATE ON approvals
BEGIN SELECT RAISE(ABORT,'approvals rows are immutable; insert a new revision'); END;
CREATE TRIGGER approvals_no_delete BEFORE DELETE ON approvals
BEGIN SELECT RAISE(ABORT,'approvals rows are immutable audit records'); END;

CREATE TRIGGER idempotency_records_no_update BEFORE UPDATE ON idempotency_records
BEGIN SELECT RAISE(ABORT,'idempotency_records rows are immutable; insert a new revision'); END;
CREATE TRIGGER idempotency_records_no_delete BEFORE DELETE ON idempotency_records
BEGIN SELECT RAISE(ABORT,'idempotency_records rows are immutable audit records'); END;

PRAGMA user_version = 1;
COMMIT;
