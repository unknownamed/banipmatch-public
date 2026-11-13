// 점검 결과 맨 위 요약에 쓰는 값. 계산 결과만 다시 세고 새 판단은 만들지 않는다.
// 원래 배차에서 마감을 넘기는 작업뿐 아니라 아예 배정되지 않은 작업(예: 확정본에서 배정 보류한 작업)도 문제로 센다.
import type { MethodResult } from '../api/types'

export type Summary = {
  late: string[]
  unassigned: string[]
  total: number
  risk: number
  fixed: number
  unresolved: string[]
  changed: number
}

export function summarize(base: MethodResult, cand: MethodResult | undefined): Summary | null {
  const late = [...new Set(base.issues.filter(i => i.job_id && (i.code === 'CUTOFF_EXCEEDED' || i.code === 'READY_TOO_LATE')).map(i => i.job_id!))]
  const unassigned = [...new Set(base.unassigned_job_ids)].filter(id => !late.includes(id))
  const risk = base.metrics.fixed_risk_count
  const total = late.length + unassigned.length
  if (total === 0 && risk === 0) return null
  const unresolved = cand ? cand.unassigned_job_ids : []
  const fixed = cand ? [...late, ...unassigned].filter(id => !unresolved.includes(id)).length : 0
  const changed = cand ? cand.metrics.changed_job_ids.length : 0
  return { late, unassigned, total, risk, fixed, unresolved, changed }
}

/** 첫 칸 이름: 무엇을 세었는지 그대로 쓴다. */
export function problemLabel(s: Summary): string {
  if (s.unassigned.length && !s.late.length) return '원래 배차에서 미배정'
  if (s.unassigned.length) return '마감 넘김·미배정'
  return '원래 배차로 마감 넘김'
}

export function headline(s: Summary, name: string | null): string {
  const L = s.late.length, U = s.unassigned.length
  if (s.total === 0) return `이미 출발한 작업 ${s.risk}건에 마감 위험이 있습니다. 담당자 확인이 필요합니다.`
  if (!name) {
    if (!U) return `원래 배차대로 가면 컨테이너 ${L}건이 새 마감을 넘깁니다.`
    if (!L) return `원래 배차에 아직 배정되지 않은 컨테이너가 ${U}건 있습니다.`
    return `원래 배차대로 가면 컨테이너 ${L}건이 마감을 넘기고, ${U}건은 배정되지 않았습니다.`
  }
  const noun = !U ? '늦는 컨테이너' : !L ? '배정되지 않은 컨테이너' : '늦거나 배정되지 않은 컨테이너'
  const verb = !U ? '마감 안에 넣을' : '마감 안에 배정할'
  if (s.fixed === 0) return `${noun}가 ${s.total}건 있습니다. ${name}으로도 해결되지 않아 담당자 확인이 필요합니다.`
  if (s.fixed === s.total)
    return s.total === 1 ? `${name}을 쓰면 ${noun} 1건을 ${verb} 수 있습니다.` : `${name}을 쓰면 ${noun} ${s.total}건을 모두 ${verb} 수 있습니다.`
  return `${name}을 쓰면 ${noun} ${s.total}건 중 ${s.fixed}건을 ${verb} 수 있습니다.`
}
