import { describe, expect, it } from 'vitest'
import demo from '../fixtures/demo-02-evening.synthetic.json'
import type { Snapshot } from '../api/types'
import { gateStatus, vehiclesAt } from './fleetPosition'

const s = demo as unknown as Snapshot
const t0 = Date.parse(s.as_of)
const min = (m: number) => t0 + m * 60000

describe('배차 일정 기반 차량 위치 추정', () => {
  it('모든 차량에 위치와 단계가 있고 출처는 계획 기반 추정이다', () => {
    const list = vehiclesAt(s, s.baseline_assignments, min(5))
    expect(list).toHaveLength(8)
    expect(list.every(v => v.pos && v.source === 'plan_inferred')).toBe(true)
  })

  it('이미 출발한 J01 차량은 게이트로 운송 중이거나 반입 중이다', () => {
    const t1 = vehiclesAt(s, s.baseline_assignments, min(-5)).find(v => v.vehicleId === 'T1')!
    expect(t1.jobId).toBe('J01')
    expect(t1.phase).toBe('to_gate')
    expect(t1.pos!.lat).toBeLessThan(35.0951)
  })

  it('운송 구간 중간이면 상차지와 게이트 사이에 있다', () => {
    const a = s.baseline_assignments.find(x => x.job_id === 'J04')!
    const mid = (Date.parse(a.pickup_departure_at) + Date.parse(a.gate_arrival_at)) / 2
    const t3 = vehiclesAt(s, s.baseline_assignments, mid).find(v => v.vehicleId === 'T3')!
    expect(t3.phase).toBe('to_gate')
    const lats = [35.153, 35.0814]
    expect(t3.pos!.lat).toBeGreaterThan(Math.min(...lats))
    expect(t3.pos!.lat).toBeLessThan(Math.max(...lats))
  })

  it('마감 여유를 도착+여유 기준으로 계산하고 초과면 late', () => {
    expect(gateStatus('2026-11-07T11:00:00Z', '2026-11-07T11:40:00Z', 10)).toEqual({ marginMin: 30, gate: 'ok' })
    expect(gateStatus('2026-11-07T11:25:00Z', '2026-11-07T11:40:00Z', 10)).toEqual({ marginMin: 5, gate: 'tight' })
    expect(gateStatus('2026-11-07T11:35:00Z', '2026-11-07T11:40:00Z', 10).gate).toBe('late')
  })

  it('원안에서 변경된 마감을 넘기는 작업은 late로 표시된다', () => {
    const late = s.baseline_assignments.map(a => vehiclesAt(s, s.baseline_assignments, Date.parse(a.pickup_departure_at) - 1))
      .flat().filter(v => v.gate === 'late').map(v => v.jobId)
    expect(new Set(late)).toEqual(new Set(['J03', 'J06', 'J07', 'J08']))
  })
})

it('기사 휴대폰 위치가 일정상 위치에서 떨어진 만큼 늦어질 시간을 어림한다(직선 x 1.3 ÷ 40km/h)', async () => {
  const { lagMinutes } = await import('./fleetPosition')
  const noksan = { lat: 35.0866, lon: 128.8410 }
  expect(lagMinutes(noksan, noksan)).toBe(0)
  // 창원 경남도청(약 25km) → 약 49분
  const lag = lagMinutes(noksan, { lat: 35.2378, lon: 128.6919 })
  expect(lag).toBeGreaterThan(40)
  expect(lag).toBeLessThan(60)
  expect(lagMinutes(null, noksan)).toBe(0)
})
