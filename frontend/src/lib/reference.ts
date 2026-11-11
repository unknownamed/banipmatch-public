// 실제·참고 자료 읽기 상태 표시(#32). 형식은 PR #42 backend.references의 내부 미리보기 모델(reference-read-preview-1)이며
// 아직 합의된 공개 API가 아니다. 화면은 상태를 해석해 바꾸지 않고 그대로 구분해 보여준다.

export type ReadStatus = 'received' | 'empty' | 'partial' | 'failed'
export type Freshness = 'fresh' | 'stale'

export interface ReferenceItem {
  values: Record<string, string>
  provenance: { kind: 'reference' | 'simulated'; source_ref: string; received_at: string; observed_at: string | null }
}

export interface ReferenceSample {
  status: Exclude<ReadStatus, 'failed'>
  items: ReferenceItem[]
  row_count: number
  reported_count: number | null
  excluded_rows: number
  blockers: string[]
  received_at: string
  freshness: Freshness
}

export interface ReferenceView {
  model_version: string
  source: string
  source_ref: string
  kind: 'reference' | 'simulated'
  checked_at: string
  last_attempt: { at: string; status: ReadStatus; error_code: string | null; attempts: number } | null
  last_success: { received_at: string; status: string; row_count: number; item_count: number } | null
  current: ReferenceSample | null
  cached: ReferenceSample | null
  engine_conversion: 'blocked' | string
  approval_eligible: boolean
  automatic_mock_fallback: boolean
}

export const STATUS_LABEL: Record<ReadStatus, string> = {
  received: '수신',
  empty: '정상 응답 · 0건',
  partial: '부분 응답',
  failed: '조회 실패',
}

export const KIND_LABEL = { reference: '실제 자료(참고)', simulated: '모의(합성)' } as const

export const BLOCKER_LABEL: Record<string, string> = {
  reference_only_not_engine_input: '참고용 · 배차 계산 입력 아님',
  source_timezone_unconfirmed: '원문 시간대 미확인(UTC로 바꾸지 않음)',
  coverage_not_established: '전체 조회 범위 미확인',
  window_change_not_confirmed: '확정된 반입시간 변경 아님',
}

export const ERROR_LABEL: Record<string, string> = {
  http_error: 'HTTP 오류',
  timeout: '시간 초과',
  connection: '연결 실패',
  provider_error: '제공자 오류 응답',
  parse_error: '응답 해석 실패',
}

export interface Display {
  /** 화면 맨 위 한 줄 상태. 최근 실패는 이전 표본이 있어도 먼저 보여준다. */
  headline: string
  tone: 'ok' | 'warn' | 'danger'
  /** 표에 보여줄 표본과 그 표본이 지금 조회 결과인지, 이전 표본인지. */
  sample: ReferenceSample | null
  sampleIsPrevious: boolean
}

/**
 * 표시 규칙: 실패를 이전 표본의 정상 표시로 덮지 않는다. 0건은 실패와 다르다. 이전 표본은 '이전 수신'으로만 보인다.
 * 실패해도 모의 자료로 자동 전환하지 않는다(모의는 사용자가 따로 고른다).
 */
export function display(v: ReferenceView): Display {
  const failed = v.last_attempt?.status === 'failed'
  const sample = v.current ?? v.cached
  const sampleIsPrevious = !v.current && !!v.cached
  if (failed) {
    const why = ERROR_LABEL[v.last_attempt!.error_code ?? ''] ?? v.last_attempt!.error_code ?? '원인 미상'
    return { headline: `${STATUS_LABEL.failed} (${why})${v.cached ? ' · 아래는 이전 수신 표본' : ' · 보여줄 자료 없음'}`, tone: 'danger', sample, sampleIsPrevious }
  }
  if (!sample) return { headline: '아직 조회하지 않음', tone: 'warn', sample: null, sampleIsPrevious: false }
  const parts = [STATUS_LABEL[sample.status]]
  if (sample.freshness === 'stale') parts.push('오래됨')
  if (sampleIsPrevious) parts.push('새 조회 없음 · 이전 수신 표본')
  return { headline: parts.join(' · '), tone: sample.status === 'received' && sample.freshness === 'fresh' && !sampleIsPrevious ? 'ok' : 'warn', sample, sampleIsPrevious }
}
