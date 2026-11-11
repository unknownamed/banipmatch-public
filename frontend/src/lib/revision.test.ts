import { describe, expect, it } from 'vitest'
import snapshotJson from '@examples/01_snapshot.json'
import type { Snapshot } from '../api/types'
import { fromKstInput, hasAssumedCondition, listChanges, revisedSnapshot, toKstInput } from './revision'

const s = snapshotJson as unknown as Snapshot
const movable = s.jobs.find((j) => !j.frozen)!
const frozen = s.jobs.find((j) => j.frozen)!

describe('조건 보완 입력', () => {
  it('KST 입력값과 UTC를 왕복한다', () => {
    expect(fromKstInput('2026-11-11T13:30')).toBe('2026-11-11T04:30:00Z')
    expect(toKstInput('2026-11-11T04:30:00Z')).toBe('2026-11-11T13:30')
    expect(toKstInput(null)).toBe('')
  })

  it('같은 값·빈 칸·고정 작업은 변경으로 보내지 않는다', () => {
    const changes = listChanges(s, {
      [`job:${movable.job_id}:ready_at`]: toKstInput(movable.ready_at),
      [`job:${frozen.job_id}:ready_at`]: '2026-11-11T09:00',
      'vehicle:T1:shift_end_at': '',
    })
    expect(changes).toEqual([])
  })

  it('바뀐 행만 고치고 근거 출처를 남기며 원본은 그대로 둔다', () => {
    const changes = listChanges(s, { [`job:${movable.job_id}:ready_at`]: '2026-11-07T09:30' })
    expect(changes).toHaveLength(1)
    const next = revisedSnapshot(s, changes, 'confirmed_simulation', new Date('2026-11-07T00:10:42.5Z'))
    const row = next.jobs.find((j) => j.job_id === movable.job_id)!
    expect(row.ready_at).toBe('2026-11-07T00:30:00Z')
    expect(row.evidence.kind).toBe(movable.evidence.kind)
    expect(row.evidence.source_ref).toBe('dispatcher:condition-revision')
    expect(s.jobs.find((j) => j.job_id === movable.job_id)!.ready_at).toBe(movable.ready_at)
    expect(hasAssumedCondition(next)).toBe(false)
    // 확인 시각을 분 단위로 내리고 기준시각도 그 시각으로 옮긴다.
    expect(row.evidence.received_at).toBe('2026-11-07T00:10:00Z')
    expect(next.as_of).toBe('2026-11-07T00:10:00Z')
  })

  it('기준시각을 과거로 되돌리지 않는다', () => {
    const changes = listChanges(s, { [`job:${movable.job_id}:ready_at`]: '2026-11-07T09:30' })
    const next = revisedSnapshot(s, changes, 'confirmed_simulation', new Date('2020-01-01T00:00:00Z'))
    expect(next.as_of).toBe(s.as_of)
  })

  it('가정 시험은 근거를 assumed로 표시해 승인 대상에서 빠진다', () => {
    const changes = listChanges(s, { [`job:${movable.job_id}:ready_at`]: '2026-11-07T09:30' })
    const next = revisedSnapshot(s, changes, 'assumed', new Date('2026-11-07T00:10:00Z'))
    expect(hasAssumedCondition(next)).toBe(true)
  })
})
