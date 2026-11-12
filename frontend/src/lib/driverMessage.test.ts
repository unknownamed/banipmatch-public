import { expect, it } from 'vitest'
import demo from '../fixtures/demo-02-evening.synthetic.json'
import type { Snapshot } from '../api/types'
import { registerLabels } from './labels'
import { driverMessage } from './driverMessage'

it('기사 안내문은 번호판·컨테이너 번호·상차지·게이트 시각으로 쓰고 넘겨준 작업도 알린다', () => {
  registerLabels(demo as unknown as Snapshot)
  const text = driverMessage('T3', [
    { job_id: 'J03', kind: 'vehicle', before: { vehicle_id: 'T6', pickup_departure_at: '2026-11-07T11:00:00Z', gate_arrival_at: '2026-11-07T11:15:00Z' }, after: { vehicle_id: 'T3', pickup_departure_at: '2026-11-07T10:20:00Z', gate_arrival_at: '2026-11-07T10:35:00Z' } },
    { job_id: 'J04', kind: 'vehicle', before: { vehicle_id: 'T3', pickup_departure_at: '2026-11-07T10:00:00Z', gate_arrival_at: '2026-11-07T10:40:00Z' }, after: null },
  ], 2)
  expect(text).toContain('부산 91사 3315')
  expect(text).toContain('BNJU 100203')
  expect(text).toContain('녹산산단 상차지 19:20 출발 → HJNC 게이트 19:35 도착')
  expect(text).toContain('7136 차량에서 넘어온 작업')
  expect(text).toContain('미배정(담당자 확인 중)')
  expect(text).not.toContain('J03')
})
