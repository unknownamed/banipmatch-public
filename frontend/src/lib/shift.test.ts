import { expect, it } from 'vitest'
import s07 from '@examples/07_snapshot_입력누락.json'
import type { Snapshot } from '../api/types'
import { shiftSnapshot } from './shift'

const src = s07 as unknown as Snapshot

it('모든 시각을 같은 양만큼 옮기고, 미확인(null)은 채우지 않는다', () => {
  const out = shiftSnapshot(src, new Date('2026-11-11T05:30:42Z'))
  expect(out.as_of).toBe('2026-11-11T05:30:00Z')
  expect(shiftSnapshot(src, new Date('2026-11-11T05:39:59Z')).as_of).toBe('2026-11-11T05:30:00Z')
  const gap = (s: Snapshot) => Date.parse(s.policy.input_valid_until!) - Date.parse(s.as_of)
  expect(gap(out)).toBe(gap(src))
  const missing = src.jobs.filter((j) => j.ready_at === null).map((j) => j.job_id)
  expect(missing.length).toBeGreaterThan(0)
  expect(out.jobs.filter((j) => j.ready_at === null).map((j) => j.job_id)).toEqual(missing)
  expect(src.as_of).not.toBe(out.as_of) // 원본은 그대로
})

it('오늘 저녁 배차를 옮겨도 마감은 10분 단위, 반입 시작은 접안일 3일 전 00:00(KST)이다', async () => {
  const s02 = (await import('../fixtures/demo-02-evening.synthetic.json')).default as unknown as Snapshot
  const out = shiftSnapshot(s02, new Date('2026-11-12T14:31:17Z'))
  for (const w of out.windows) {
    expect(new Date(w.closes_at!).getUTCMinutes() % 10).toBe(0)
    const kst = new Date(Date.parse(w.opens_at!) + 9 * 3600_000)
    expect([kst.getUTCHours(), kst.getUTCMinutes()]).toEqual([0, 0])
    const berthKst = new Date(Date.parse(w.closes_at!) + 19 * 3600_000)
    const days = (Date.UTC(berthKst.getUTCFullYear(), berthKst.getUTCMonth(), berthKst.getUTCDate()) - (Date.parse(w.opens_at!) + 9 * 3600_000)) / 86400_000
    expect(days).toBe(3)
  }
})

it('오늘 저녁 배차의 첫 출발은 기준 10분 뒤 이후라, 10분 단위 이동으로 승인 전 작업이 출발한 것처럼 보이지 않는다', async () => {
  const s02 = (await import('../fixtures/demo-02-evening.synthetic.json')).default as unknown as Snapshot
  const frozen = new Set(s02.jobs.filter((j) => j.frozen).map((j) => j.job_id))
  const first = Math.min(...s02.baseline_assignments.filter((a) => !frozen.has(a.job_id)).map((a) => Date.parse(a.pickup_departure_at)))
  expect(first - Date.parse(s02.as_of)).toBeGreaterThanOrEqual(10 * 60_000)
})
