// 원안(B0)과 추천안을 같은 작업 ID로 맞춰 보는 순수 함수.
// 변경 여부·원인은 API 응답(metrics, issues)에 있는 것만 쓴다. 화면에서 새로 계산하지 않는다.
import type { Assignment, Issue, Job, MethodResult, Snapshot, TimeWindow } from '../api/types'

export type ChangeKind = 'vehicle' | 'order' | 'time'

export interface JobRow {
  job: Job
  window: TimeWindow | undefined
  locked: boolean
  baseline: Assignment | undefined
  candidate: Assignment | undefined
  candidateUnassigned: boolean
  /** 추천안 결과에 이 작업이 아예 없음(배정·미처리 어디에도 없음) → 계약 위반 표시용 */
  candidateMissing: boolean
  changes: ChangeKind[]
  baselineIssues: Issue[]
  candidateIssues: Issue[]
}

export function isLocked(job: Job): boolean {
  return job.frozen || job.state === 'departed'
}

export function buildRows(snapshot: Snapshot, baseline: MethodResult | undefined, candidate: MethodResult | undefined): JobRow[] {
  const byJob = (list: Assignment[] | undefined) => new Map((list ?? []).map((a) => [a.job_id, a]))
  // 원안은 B0 결과가 있으면 그것을, 없으면 입력의 baseline_assignments 를 쓴다.
  const base = byJob(baseline?.assignments ?? snapshot.baseline_assignments)
  const cand = byJob(candidate?.assignments)
  const unassigned = new Set(candidate?.unassigned_job_ids ?? [])
  const m = candidate?.metrics

  return snapshot.jobs.map((job) => {
    const changes: ChangeKind[] = []
    if (m?.vehicle_changed_job_ids.includes(job.job_id)) changes.push('vehicle')
    if (m?.order_changed_job_ids.includes(job.job_id)) changes.push('order')
    if (m?.time_changed_job_ids.includes(job.job_id)) changes.push('time')
    const inCand = cand.has(job.job_id)
    return {
      job,
      window: snapshot.windows.find((w) => w.voyage_id === job.voyage_id && w.terminal_id === job.terminal_id),
      locked: isLocked(job),
      baseline: base.get(job.job_id),
      candidate: cand.get(job.job_id),
      candidateUnassigned: unassigned.has(job.job_id),
      candidateMissing: candidate !== undefined && !inCand && !unassigned.has(job.job_id),
      changes,
      baselineIssues: (baseline?.issues ?? []).filter((i) => i.job_id === job.job_id),
      candidateIssues: (candidate?.issues ?? []).filter((i) => i.job_id === job.job_id),
    }
  })
}

const ASSIGNMENT_FIELDS = ['vehicle_id', 'sequence', 'pickup_departure_at', 'gate_arrival_at', 'return_at'] as const

/**
 * 고정 작업이 조정안에서 원안 배정을 그대로 보존했는지. 조정안이 없으면(계산 전) 판단하지 않고 true.
 * 공통 규칙: 고정 작업은 차량·순서·시각 전체를 보존한다.
 */
export function lockedPreserved(r: JobRow, hasCandidate: boolean): boolean {
  if (!r.locked || !r.baseline || !hasCandidate) return true
  const c = r.candidate
  return !!c && ASSIGNMENT_FIELDS.every((f) => c[f] === r.baseline![f])
}

/** 고정 작업이 조정안에서 사라졌거나 배정 필드가 하나라도 바뀐 작업 ID. */
export function lockedViolations(rows: JobRow[]): string[] {
  const hasCandidate = rows.some((r) => r.candidate || r.candidateUnassigned || r.candidateMissing)
  return rows.filter((r) => !lockedPreserved(r, hasCandidate)).map((r) => r.job.job_id)
}

export const ISSUE_LABEL: Record<string, string> = {
  INPUT_MISSING: '입력 누락',
  OUT_OF_SCOPE: '범위 밖',
  WINDOW_UNCONFIRMED: '반입시간 미확인',
  EARLY_ARRIVAL: '반입 시작 전 도착',
  CUTOFF_EXCEEDED: '마감 초과',
  READY_TOO_LATE: '준비 지연',
  VEHICLE_UNAVAILABLE: '차량 불가',
  INCOMPATIBLE_EQUIPMENT: '장비 불일치',
  CAPACITY_EXCEEDED: '중량 초과',
  SHIFT_EXCEEDED: '근무시간 초과',
  FIXED_RESIDUAL_RISK: '고정 작업 잔여 위험',
  SEARCH_LIMIT: '맡을 차량 못 찾음',
  MODEL_INVALID: '모델 오류',
}

export const PROOF_LABEL: Record<Issue['proof_level'], string> = {
  input_validation: '입력 검사',
  constraint_check: '제약 검사',
  solver_proven: '솔버 증명',
  not_proven: '증명 안 됨',
}
