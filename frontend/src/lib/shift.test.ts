import { expect, it } from 'vitest'
import s07 from '@examples/07_snapshot_입력누락.json'
import type { Snapshot } from '../api/types'
import { shiftSnapshot } from './shift'

const src = s07 as unknown as Snapshot

it('모든 시각을 같은 양만큼 옮기고, 미확인(null)은 채우지 않는다', () => {
  const out = shiftSnapshot(src, new Date('2026-11-11T05:30:42Z'))
  expect(out.as_of).toBe('2026-11-11T05:30:00Z')
  const gap = (s: Snapshot) => Date.parse(s.policy.input_valid_until!) - Date.parse(s.as_of)
  expect(gap(out)).toBe(gap(src))
  const missing = src.jobs.filter((j) => j.ready_at === null).map((j) => j.job_id)
  expect(missing.length).toBeGreaterThan(0)
  expect(out.jobs.filter((j) => j.ready_at === null).map((j) => j.job_id)).toEqual(missing)
  expect(src.as_of).not.toBe(out.as_of) // 원본은 그대로
})
