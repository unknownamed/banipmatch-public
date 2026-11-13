import { describe, expect, it } from 'vitest'
import type { MethodResult } from '../api/types'
import { headline, problemLabel, summarize } from './summary'

const result = (o: { late?: string[]; unassigned?: string[]; risk?: number; changed?: string[] }) => ({
  issues: (o.late ?? []).map(job_id => ({ code: 'CUTOFF_EXCEEDED', job_id })),
  unassigned_job_ids: o.unassigned ?? [],
  metrics: { fixed_risk_count: o.risk ?? 0, changed_job_ids: o.changed ?? [] },
}) as unknown as MethodResult

describe('점검 요약', () => {
  it('늦는 작업도 미배정도 없으면 요약 문제 없음', () => {
    expect(summarize(result({}), result({}))).toBeNull()
  })

  it('늦는 작업만 있으면 기존 문장 그대로', () => {
    const s = summarize(result({ late: ['A', 'B', 'C', 'D'] }), result({ unassigned: ['D'], changed: ['A', 'B', 'E', 'F', 'G'] }))!
    expect(problemLabel(s)).toBe('원래 배차로 마감 넘김')
    expect(s.total).toBe(4)
    expect(headline(s, '최소 변경안')).toBe('최소 변경안을 쓰면 늦는 컨테이너 4건 중 3건을 마감 안에 넣을 수 있습니다.')
  })

  it('확정본에서 배정 보류한 작업이 원래 배차에 없으면 문제로 센다', () => {
    // 원래 배차(B0)의 미배정 = 확정본에서 보류한 작업. 조정안으로도 못 맡음.
    const s = summarize(result({ unassigned: ['X'] }), result({ unassigned: ['X'] }))!
    expect(s).not.toBeNull()
    expect(problemLabel(s)).toBe('원래 배차에서 미배정')
    expect(s.fixed).toBe(0)
    expect(headline(s, '최소 변경안')).toBe('배정되지 않은 컨테이너가 1건 있습니다. 최소 변경안으로도 해결되지 않아 담당자 확인이 필요합니다.')
  })

  it('조건 보완으로 미배정이 배정되면 해결로 센다', () => {
    const s = summarize(result({ unassigned: ['X'] }), result({ changed: ['X', 'Y'] }))!
    expect(s.fixed).toBe(1)
    expect(headline(s, '최소 변경안')).toBe('최소 변경안을 쓰면 배정되지 않은 컨테이너 1건을 마감 안에 배정할 수 있습니다.')
  })

  it('늦는 작업과 미배정이 함께 있으면 둘 다 센다(중복 없이)', () => {
    const s = summarize(result({ late: ['A', 'X'], unassigned: ['X', 'Y'] }), undefined)!
    expect(s.late).toEqual(['A', 'X'])
    expect(s.unassigned).toEqual(['Y'])
    expect(problemLabel(s)).toBe('마감 넘김·미배정')
    expect(headline(s, null)).toBe('원래 배차대로 가면 컨테이너 2건이 마감을 넘기고, 1건은 배정되지 않았습니다.')
  })

  it('출발한 작업 위험만 있으면 확인 필요로 안내', () => {
    const s = summarize(result({ risk: 1 }), result({}))!
    expect(headline(s, '최소 변경안')).toBe('이미 출발한 작업 1건에 마감 위험이 있습니다. 담당자 확인이 필요합니다.')
  })
})
