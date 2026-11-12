import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import snapshotJson from '@examples/01_snapshot.json'
import resultsJson from '@examples/04_results_설명용.json'
import type { Results, Snapshot } from '../api/types'
import { buildRows } from '../lib/compare'
import { timelineModel, VehicleTimeline } from './VehicleTimeline'

const snapshot = snapshotJson as unknown as Snapshot
const results = resultsJson as unknown as Results
const candidate = results.results.find((r) => r.method === 'B3')!
const render = (s: Snapshot, cand = false) => renderToStaticMarkup(
  <VehicleTimeline rows={buildRows(s, undefined, cand ? candidate : undefined)} baseLabel="원안(입력)" candLabel={cand ? 'B3 조정안' : null} />,
)

// 서버 계약에서 도착·복귀 null을 허용한다. 타입 선언보다 넓은 런타임 입력도 검증한다.
function missingTime(s: Snapshot, field: string) {
  Object.assign(s.baseline_assignments[0], { [field]: null })
}

describe('차량별 일정의 미확인·미배정 보존', () => {
  it.each(['return_at', 'gate_arrival_at', 'pickup_departure_at'])('%s 누락이 다른 작업의 시간축을 손상하지 않는다', (field) => {
    const s = structuredClone(snapshot)
    missingTime(s, field)
    const model = timelineModel(buildRows(s, undefined, undefined), false)!
    expect(model.ticks.length).toBeGreaterThan(0)
    expect(model.incomplete.map((a) => a.jobId)).toEqual(['J0'])
    const otherBars = model.vehicles.flatMap((v) => v.base)
    expect(otherBars.map((a) => a.jobId)).toEqual(['J1', 'J2', 'J3'])
    expect(otherBars.every((b) => [b.left, b.width, b.arrival].every(Number.isFinite))).toBe(true)
    const html = render(s)
    expect(html).toContain('J0 · 출발')
    expect(html).toContain('미확인')
    expect(html).toContain('시각 확인 필요')
    expect(html).not.toMatch(/NaN|Infinity/)
  })

  it('알려진 시각이 하나도 없어도 모든 작업과 미확인 상태를 남긴다', () => {
    const s = structuredClone(snapshot)
    s.baseline_assignments.forEach((a) => Object.assign(a, { pickup_departure_at: null, gate_arrival_at: null, return_at: null }))
    const model = timelineModel(buildRows(s, undefined, undefined), false)!
    expect(model.ticks).toEqual([])
    expect(model.incomplete).toHaveLength(s.jobs.length)
    const html = render(s)
    for (const job of s.jobs) expect(html).toContain(job.job_id)
    expect(html).toContain('확인된 배정 시각이 없어')
    expect(html).not.toMatch(/NaN|Infinity/)
  })

  it('일부 원안 미배정을 계산 전에도 별도 목록에 남긴다', () => {
    const s = structuredClone(snapshot)
    s.baseline_assignments = s.baseline_assignments.filter((a) => a.job_id !== 'J2')
    s.baseline_unassigned_job_ids = ['J2']
    const model = timelineModel(buildRows(s, undefined, undefined), false)!
    expect(model.baselineUnassigned).toEqual(['J2'])
    expect(model.unassigned).toEqual([])
    expect(render(s)).toContain('원안(입력) 배정 없음: J2')
  })

  it('전체 원안 미배정에서도 목록을 유지하고 후보에만 있는 배정은 그린다', () => {
    const s = structuredClone(snapshot)
    s.baseline_assignments = []
    s.baseline_unassigned_job_ids = s.jobs.map((j) => j.job_id)
    const html = render(s)
    for (const id of s.baseline_unassigned_job_ids) expect(html).toContain(id)
    expect(html).toContain('원안(입력) 배정 없음:')
    const model = timelineModel(buildRows(s, undefined, candidate), true)!
    expect(model.vehicles.flatMap((v) => v.cand).map((b) => b.jobId).sort()).toEqual(candidate.assignments.map((a) => a.job_id).sort())
    expect(model.unassigned).toEqual(candidate.unassigned_job_ids)
    expect(render(s, true)).toContain('조정안에서 맡을 차량을 찾지 못했습니다')
  })

  it('응답에서 빠진 작업을 정당한 미처리와 구분한다', () => {
    const cand = structuredClone(candidate)
    cand.assignments = cand.assignments.filter((a) => a.job_id !== 'J2')
    const rows = buildRows(snapshot, undefined, cand)
    const html = renderToStaticMarkup(<VehicleTimeline rows={rows} baseLabel="원안" candLabel="B3 조정안" />)
    expect(timelineModel(rows, true)!.missing).toEqual(['J2'])
    expect(html).toContain('조정안 결과 누락(배정·미처리 모두 아님): J2')
    expect(timelineModel(rows, true)!.unassigned).toEqual(['J3'])
  })
})
