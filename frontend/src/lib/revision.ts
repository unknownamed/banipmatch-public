// 조건 보완(R4): 담당자가 확인한 준비·가용·근무 시각만 바꿔 새 입력을 만든다.
// 서버가 다시 검사하지만, 화면도 고정 작업·허용 밖 필드를 바꾸지 않는다. 빈 값으로 지우는 것도 하지 않는다.
import type { Evidence, Snapshot } from '../api/types'

export type Confirmation = 'confirmed_simulation' | 'assumed'
/** 편집 키: `job:J1:ready_at`, `vehicle:T1:available_at` 같은 형식. 값은 KST datetime-local 문자열. */
export type Edits = Record<string, string>

const KST_MS = 9 * 60 * 60 * 1000

/** UTC → `<input type="datetime-local">` 값(KST). 미확인(null)은 빈 칸. */
export function toKstInput(utc: string | null): string {
  if (!utc) return ''
  const d = new Date(utc)
  return Number.isNaN(d.getTime()) ? '' : new Date(d.getTime() + KST_MS).toISOString().slice(0, 16)
}

/** KST datetime-local 값 → UTC Z(초 단위). */
export function fromKstInput(value: string): string {
  return new Date(Date.parse(`${value}:00Z`) - KST_MS).toISOString().replace('.000Z', 'Z')
}

export interface FieldChange {
  key: string
  entity: 'job' | 'vehicle'
  id: string
  field: 'ready_at' | 'available_at' | 'shift_end_at'
  before: string | null
  after: string
}

/** 완성된 KST 입력(YYYY-MM-DDTHH:mm, 24시간제)인지. 입력 중인 값은 변경으로 보내지 않는다. */
export const isCompleteInput = (value: string) => /^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d$/.test(value) && !Number.isNaN(Date.parse(`${value}:00Z`))

/** 알려진 고정 사유 코드는 한국어로. 모르는 값은 원문 그대로 보여준다(임의 해석하지 않음). */
const FREEZE_LABEL: Record<string, string> = { ALREADY_DEPARTED: '이미 출발', DEPARTED: '출발', FIXED_RESERVATION: '예약 고정' }
export const freezeLabel = (reason: string | null) => (reason ? (FREEZE_LABEL[reason] ?? reason) : '사유 미기재')

/** 입력과 다른 값만 변경으로 본다. 빈 칸(값 지우기)·입력 중인 값은 변경으로 보내지 않는다. */
export function listChanges(s: Snapshot, edits: Edits): FieldChange[] {
  const out: FieldChange[] = []
  for (const [key, value] of Object.entries(edits)) {
    if (!isCompleteInput(value)) continue
    const [entity, id, field] = key.split(':') as [FieldChange['entity'], string, FieldChange['field']]
    const row = entity === 'job' ? s.jobs.find((j) => j.job_id === id) : s.vehicles?.find((v) => v.vehicle_id === id)
    if (!row || (entity === 'job' && (row as Snapshot['jobs'][number]).frozen)) continue
    const before = (row as unknown as Record<string, string | null>)[field] ?? null
    const after = fromKstInput(value)
    if (before === null ? true : Date.parse(before) !== Date.parse(after)) out.push({ key, entity, id, field, before, after })
  }
  return out.sort((a, b) => a.key.localeCompare(b.key))
}

/**
 * 새 입력 Snapshot. 바뀐 행의 근거는 담당자 수정으로 표시한다.
 * 가정 시험은 kind=assumed라서 서버가 승인·전달을 막는다. 확인된 조건도 모의 배차에서의 확인일 뿐 실제 현장 확인이 아니므로
 * 원래 근거 종류(모의 등)는 유지하고 출처만 바꾼다.
 */
export function revisedSnapshot(s: Snapshot, changes: FieldChange[], confirmation: Confirmation, now: Date): Snapshot {
  const next = structuredClone(s)
  // 입력 시각은 분 단위이고, 기준시각(as_of) 이후 수신한 근거는 쓸 수 없다.
  // 지금 확인한 값이므로 기준시각을 확인 시각으로 옮긴다(되돌리지는 않음). 서버 비교가 '기준시각도 바뀜'을 한계로 표시한다.
  const minute = new Date(Math.floor(now.getTime() / 60000) * 60000)
  const receivedAt = new Date(Math.max(minute.getTime(), Date.parse(s.as_of))).toISOString().replace('.000Z', 'Z')
  next.as_of = receivedAt
  const evidence = (old: Evidence): Evidence => ({
    ...old,
    kind: confirmation === 'assumed' ? 'assumed' : old.kind,
    source_ref: confirmation === 'assumed' ? 'dispatcher:what-if' : 'dispatcher:condition-revision',
    received_at: receivedAt,
  })
  for (const c of changes) {
    const row = (c.entity === 'job' ? next.jobs.find((j) => j.job_id === c.id) : next.vehicles?.find((v) => v.vehicle_id === c.id)) as
      | (Record<string, unknown> & { evidence: Evidence })
      | undefined
    if (!row) continue
    row[c.field] = c.after
    row.evidence = evidence(row.evidence)
  }
  return next
}

/** 준비·가용 조건에 가정이 섞인 입력. 서버도 422 ASSUMPTION_NOT_APPROVABLE로 막는다. */
export const hasAssumedCondition = (s: Snapshot) =>
  s.jobs.some((j) => j.evidence.kind === 'assumed') || !!s.vehicles?.some((v) => v.evidence.kind === 'assumed')
