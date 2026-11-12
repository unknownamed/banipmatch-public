// docs/development/v0.1/공통 규격/contracts.schema.json 의 화면에서 쓰는 부분만 옮긴 타입.
// 필드명·enum을 바꾸지 않는다. 계약이 바뀌면 이 파일도 같은 버전으로 갱신한다.

export type UtcString = string // RFC3339, Z 접미사

export type EvidenceKind = 'observed' | 'simulated' | 'assumed' | 'inferred' | 'manual_verified'

export interface Evidence {
  kind: EvidenceKind
  source_ref: string
  observed_at: UtcString | null
  received_at: UtcString | null
}

export type Verification = 'confirmed' | 'unconfirmed' | 'conflict'

export interface Job {
  job_id: string
  voyage_id: string
  origin_id: string
  terminal_id: string
  return_location_id: string
  ready_at: UtcString | null
  gross_weight_kg: number | null
  equipment_type: string
  service_minutes: number | null
  state: string
  frozen: boolean
  freeze_reason: string | null
  evidence: Evidence
  /** ISO 6346 컨테이너 번호(운송사 TMS·선적지시서). 없으면 화면은 job_id를 쓴다. */
  container_no?: string | null
  booking_no?: string | null
  /** 화주 상호 */
  cargo_owner?: string | null
}

export interface TimeWindow {
  window_id: string
  voyage_id: string
  terminal_id: string
  opens_at: UtcString | null
  closes_at: UtcString | null
  verification: Verification
  confirmed_by: string | null
  confirmed_at: UtcString | null
  evidence: Evidence
}

export interface WindowChange {
  change_id: string
  voyage_id: string
  terminal_id: string
  previous_opens_at: UtcString | null
  previous_closes_at: UtcString | null
  new_window_id: string
  verification: Verification
  confirmed_by: string | null
  confirmed_at: UtcString | null
  evidence: Evidence
}

export interface Assignment {
  job_id: string
  vehicle_id: string
  sequence: number
  pickup_departure_at: UtcString
  gate_arrival_at: UtcString
  return_at: UtcString
}

export interface Snapshot {
  schema_version: string
  scenario_id: string
  plan_id: string
  base_plan_version: number
  data_mode: 'simulated' | 'observed' | 'mixed'
  as_of: UtcString
  jobs: Job[]
  windows: TimeWindow[]
  baseline_assignments: Assignment[]
  baseline_unassigned_job_ids: string[]
  change: WindowChange
  policy: { buffer_minutes: number; external_actions_enabled: boolean; input_valid_until: UtcString | null }
  /** 조건 보완(R4)에서 가용·근무 시각만 쓴다. 나머지 필드는 원본 그대로 보존한다. */
  vehicles?: Vehicle[]
  /** 차량 추가 시 시작 위치를 고르는 데만 쓴다. */
  locations?: { location_id: string; name: string; kind: string; latitude?: number | null; longitude?: number | null }[]
  /** 차량 지도에서 위치 추정(이동 구간)에만 쓴다. */
  travel_times?: { from_location_id: string; to_location_id: string; minutes: number | null }[]
}

export interface Vehicle {
  vehicle_id: string
  start_location_id: string
  capacity_kg: number
  equipment_types: string[]
  available_at: UtcString | null
  shift_end_at: UtcString | null
  evidence: Evidence
  /** 차량 번호판. 없으면 화면은 vehicle_id를 쓴다. */
  plate_no?: string | null
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type Method = 'B0' | 'B1' | 'B2' | 'B3'

export interface ApiError {
  request_id?: string
  code: string
  message: string
  details?: { path: string; reason: string }[]
}

export interface Run {
  run_id: string
  scenario_id: string
  plan_id: string
  base_plan_version: number
  status: RunStatus
  created_at: UtcString
  started_at: UtcString | null
  finished_at: UtcString | null
  methods: Method[]
  config: { time_limit_seconds: number; seed: number }
  error: ApiError | null
}

export type IssueCode =
  | 'INPUT_MISSING'
  | 'OUT_OF_SCOPE'
  | 'WINDOW_UNCONFIRMED'
  | 'EARLY_ARRIVAL'
  | 'CUTOFF_EXCEEDED'
  | 'READY_TOO_LATE'
  | 'VEHICLE_UNAVAILABLE'
  | 'INCOMPATIBLE_EQUIPMENT'
  | 'CAPACITY_EXCEEDED'
  | 'SHIFT_EXCEEDED'
  | 'FIXED_RESIDUAL_RISK'
  | 'SEARCH_LIMIT'
  | 'MODEL_INVALID'

export interface Issue {
  job_id: string | null
  code: IssueCode
  explanation: string
  proof_level: 'input_validation' | 'constraint_check' | 'solver_proven' | 'not_proven'
  evidence_refs: string[]
}

export type SolutionStatus =
  | 'BASELINE'
  | 'HEURISTIC'
  | 'OPTIMAL'
  | 'FEASIBLE'
  | 'INFEASIBLE'
  | 'UNKNOWN'
  | 'MODEL_INVALID'
  | 'INPUT_INCOMPLETE'

export interface Metrics {
  unassigned_count: number
  feasible_movable_count: number
  movable_violation_count: number
  fixed_risk_count: number
  changed_job_ids: string[]
  vehicle_changed_job_ids: string[]
  order_changed_job_ids: string[]
  time_changed_job_ids: string[]
  movable_travel_minutes: number | null
  elapsed_ms: number
  newly_assigned_job_ids: string[]
}

export interface MethodResult {
  method: Method
  result_origin: 'illustrative_fixture' | 'computed'
  solution_status: SolutionStatus
  assignments: Assignment[]
  unassigned_job_ids: string[]
  issues: Issue[]
  metrics: Metrics
  objective_proven: boolean
  approval_eligible: boolean
  engine_version: string
  solver_version: string | null
  objective_stages: { objective: 'unassigned' | 'changed' | 'travel'; status: 'OPTIMAL' | 'FEASIBLE' | 'UNKNOWN' | 'NOT_RUN'; value: number | null; best_bound: number | null }[]
  validation_status: 'passed' | 'failed' | 'not_run'
}

export interface Results {
  run_id: string
  scenario_id: string
  base_plan_version: number
  input_sha256: string
  results: MethodResult[]
}

export interface ApprovalRequest {
  run_id: string
  method: Method
  expected_version: number
  acknowledged_job_ids: string[]
}

export interface Approval {
  approval_id: string
  plan_id: string
  version: number
  run_id: string
  method: Method
  approved_by: string
  approved_at: UtcString
  external_actions_performed: boolean
}

export interface Plan {
  plan_id: string
  version: number
  scenario_id: string
  approval_id: string | null
}

/** GET /v1/runs/{id}/results — 진행 중 202(Run), 종료 후 200(Results). */
export type ResultsResponse = { kind: 'pending'; run: Run } | { kind: 'ready'; results: Results }
