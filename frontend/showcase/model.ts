import type { Method, MethodResult, Snapshot } from '../src/api/types'

export const methods: Method[] = ['B0', 'B1', 'B2', 'B3']
export interface RecordEntry {
  result: MethodResult
  audit: { integrity: string; schedule: string; failed: boolean }
  source_jsonl_line: number
  wall_ms: number
  seed: number
}
export interface Case {
  case_id: string
  label: string
  profile: string
  job_count: number
  vehicle_count: number
  generation_seed: number
  budget_seconds: number
  snapshot: Snapshot
  methods: Record<Method, RecordEntry>
  comparison: {
    same_served_job_set: boolean
    b2_served_job_ids: string[]
    b3_served_job_ids: string[]
    delta_changed_jobs: number
    delta_travel_minutes: number | null
    equal_unassigned_count: boolean
    equal_fixed_risk_count: boolean
  }
}
export interface Archive {
  schema_version: string
  evidence_kind: string
  provenance: { source_commit: string; protocol_sha256: string; results_sha256: string }
  selection: { solver_seed: number; case_count: number; record_count: number }
  context: { total_records: number; total_pairs: number; summary: {
    independently_validated: number; baseline_integrity_passed: number
    identical_workload_comparable: number; equal_count_comparable: number
    objective_proven: number; failures: number
  }; pairs: unknown[] }
  cases: Case[]
}
export function filterCases(cases: Case[], query: string) {
  const needle = query.trim().toLocaleLowerCase()
  return cases.filter(c => `${c.case_id} ${c.label} ${c.profile} ${c.job_count}건`.toLocaleLowerCase().includes(needle))
}
export const signed = (n: number | null) => n === null ? '미제공' : `${n > 0 ? '+' : ''}${n}`
export function clock(value: string | null) {
  return value ? new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)) : '미확인'
}
