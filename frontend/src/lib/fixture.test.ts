// 공통 예제(01, 03, 04)로 화면 판정이 첫 통합 기준과 맞는지 확인한다.
import { describe, expect, it } from 'vitest'
import snapshotJson from '@examples/01_snapshot.json'
import runJson from '@examples/03_run_status.json'
import resultsJson from '@examples/04_results_설명용.json'
import type { MethodResult, Results, Run, Snapshot } from '../api/types'
import { approvalGate } from './approval'
import { buildRows, lockedViolations } from './compare'
import { kstTime, kstTimeWithDay } from './time'

const snapshot = snapshotJson as unknown as Snapshot
const run = runJson as unknown as Run
const results = resultsJson as unknown as Results
const b0 = results.results.find((r) => r.method === 'B0')!
const b3 = results.results.find((r) => r.method === 'B3')!
const rows = buildRows(snapshot, b0, b3)
const row = (id: string) => rows.find((r) => r.job.job_id === id)!

describe('공통 예제 비교', () => {
  it('J0은 고정이며 조정안에서도 원안 그대로 유지된다', () => {
    expect(row('J0').locked).toBe(true)
    expect(row('J0').candidate).toEqual(row('J0').baseline)
    expect(lockedViolations(rows)).toEqual([])
  })

  it('J1/J2는 응답 metrics 대로 차량·시각 변경으로 표시된다', () => {
    expect(row('J1').changes).toEqual(['vehicle', 'time'])
    expect(row('J2').changes).toEqual(['vehicle', 'time'])
    expect(row('J1').candidate?.vehicle_id).toBe('T2')
    expect(row('J2').candidate?.vehicle_id).toBe('T1')
  })

  it('J3은 미처리이며 READY_TOO_LATE 이유가 붙는다', () => {
    expect(row('J3').candidateUnassigned).toBe(true)
    expect(row('J3').candidateIssues.map((i) => i.code)).toEqual(['READY_TOO_LATE'])
  })

  it('원안 B0의 J1 마감 초과 진단을 보존한다', () => {
    expect(row('J1').baselineIssues.map((i) => i.code)).toContain('CUTOFF_EXCEEDED')
  })

  // PR #4 리뷰: 도착·복귀만 바뀌어도 고정 위반이다
  const shiftJ0 = (patch: Partial<MethodResult['assignments'][number]>): MethodResult => ({
    ...b3,
    assignments: b3.assignments.map((a) => (a.job_id === 'J0' ? { ...a, ...patch } : a)),
  })

  it('고정 작업의 도착 시각만 바뀌어도 감지한다', () => {
    expect(lockedViolations(buildRows(snapshot, b0, shiftJ0({ gate_arrival_at: '2026-11-07T00:25:00Z' })))).toEqual(['J0'])
  })

  it('고정 작업의 복귀 시각만 바뀌어도 감지한다', () => {
    expect(lockedViolations(buildRows(snapshot, b0, shiftJ0({ return_at: '2026-11-07T01:05:00Z' })))).toEqual(['J0'])
  })

  it('조정안이 없으면(계산 전) 고정 위반으로 보지 않는다', () => {
    expect(lockedViolations(buildRows(snapshot, b0, undefined))).toEqual([])
  })

  it('고정 작업이 조정안에서 빠지면 감지한다', () => {
    const broken: MethodResult = { ...b3, assignments: b3.assignments.filter((a) => a.job_id !== 'J0') }
    expect(lockedViolations(buildRows(snapshot, b0, broken))).toEqual(['J0'])
    expect(buildRows(snapshot, b0, broken).find((r) => r.job.job_id === 'J0')!.candidateMissing).toBe(true)
  })
})

describe('승인 차단', () => {
  it('설명용 결과(illustrative_fixture)는 승인 버튼을 열지 않는다', () => {
    const g = approvalGate(run, b3, snapshot.scenario_id)
    expect(g.allowed).toBe(false)
    expect(g.reasons.join(' ')).toContain('실제 계산 결과가 아니라')
  })

  it('computed·approval_eligible·passed 이고 입력이 같을 때만 연다', () => {
    const ok: MethodResult = { ...b3, result_origin: 'computed', approval_eligible: true, validation_status: 'passed' }
    expect(approvalGate(run, ok, 'S001').allowed).toBe(true)
    expect(approvalGate(run, ok, 'S002').allowed).toBe(false)
    expect(approvalGate({ ...run, status: 'failed' }, ok, 'S001').allowed).toBe(false)
  })
})

describe('시각 표시', () => {
  it('UTC Z를 한국 시각으로 바꾸고 null은 미확인으로 둔다', () => {
    expect(kstTime('2026-11-07T01:30:00Z')).toBe('10:30')
    expect(kstTime(null)).toBe('미확인')
    expect(kstTimeWithDay('2026-11-06T23:50:00Z', snapshot.as_of)).toBe('08:50')
  })
})
