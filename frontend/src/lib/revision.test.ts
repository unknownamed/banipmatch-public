import { describe, expect, it } from 'vitest'
import snapshotJson from '@examples/01_snapshot.json'
import type { Snapshot } from '../api/types'
import { EMPTY_DRAFT, draftProblems, freezeLabel, fromKstInput, hasAssumedCondition, listChanges, revisedSnapshot, toKstInput } from './revision'

const s = snapshotJson as unknown as Snapshot
const movable = s.jobs.find((j) => !j.frozen)!
const frozen = s.jobs.find((j) => j.frozen)!

describe('조건 보완 입력', () => {
  it('고정 사유 코드를 한국어로, 모르는 값은 원문 그대로 보여준다', () => {
    expect(freezeLabel('ALREADY_DEPARTED')).toBe('이미 출발')
    expect(freezeLabel('NEW_CODE')).toBe('NEW_CODE')
    expect(freezeLabel(null)).toBe('사유 미기재')
  })

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
      'vehicle:T2:shift_end_at': '2026-11-11T13:4', // 입력 중
      'vehicle:T2:available_at': '2026-11-11T25:00', // 없는 시각
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
    // 모의 자료는 모의 시계가 흐르지 않으므로 같은 기준시각에서 조건만 바꾼다.
    expect(row.evidence.received_at).toBe(s.as_of)
    expect(next.as_of).toBe(s.as_of)
  })

  it('실제·혼합 자료는 확인 시각(분 단위)으로 기준시각을 옮긴다', () => {
    const observed = { ...structuredClone(s), data_mode: 'mixed' } as Snapshot
    const changes = listChanges(observed, { [`job:${movable.job_id}:ready_at`]: '2026-11-07T09:30' })
    const next = revisedSnapshot(observed, changes, 'confirmed_simulation', new Date('2026-11-07T00:10:42.5Z'))
    expect(next.jobs.find((j) => j.job_id === movable.job_id)!.evidence.received_at).toBe('2026-11-07T00:10:00Z')
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

describe('차량 추가', () => {
  const ok = { vehicle_id: 'T9', start_location_id: 'D', capacity_kg: '30000', equipment_types: ['DRY40'], available_at: '2026-11-07T09:30', shift_end_at: '2026-11-07T18:00' }
  it('빠진 값은 채우지 않고 무엇이 빠졌는지 알려준다', () => {
    expect(draftProblems(s, EMPTY_DRAFT)).toHaveLength(6)
    expect(draftProblems(s, { ...ok, vehicle_id: 'T1' })).toEqual(['이미 있는 차량'])
    expect(draftProblems(s, { ...ok, start_location_id: 'NEW' })).toEqual(['시작 위치'])
    expect(draftProblems(s, { ...ok, shift_end_at: '2026-11-07T09:00' })).toEqual(['근무 종료가 운행 시작보다 늦어야 함'])
    expect(draftProblems(s, ok)).toEqual([])
  })
  it('추가 차량은 입력한 값 그대로 들어가고 기존 차량·원본은 바뀌지 않는다', () => {
    const next = revisedSnapshot(s, [], 'confirmed_simulation', new Date('2026-11-07T00:10:00Z'), [ok])
    const added = next.vehicles!.find((v) => v.vehicle_id === 'T9')!
    expect(added).toMatchObject({ start_location_id: 'D', capacity_kg: 30000, equipment_types: ['DRY40'], available_at: '2026-11-07T00:30:00Z', shift_end_at: '2026-11-07T09:00:00Z' })
    expect(added.evidence.source_ref).toBe('dispatcher:condition-revision')
    expect(next.vehicles!.length).toBe(s.vehicles!.length + 1)
    expect(s.vehicles!.some((v) => v.vehicle_id === 'T9')).toBe(false)
    expect(hasAssumedCondition(revisedSnapshot(s, [], 'assumed', new Date('2026-11-07T00:10:00Z'), [ok]))).toBe(true)
  })
})
