// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import runJson from '@examples/03_run_status.json'
import resultsJson from '@examples/04_results_설명용.json'
import snapshotJson from '@examples/01_snapshot.json'
import type { ApiClient } from '../api/client'
import { ApiRequestError } from '../api/client'
import type { Approval, MethodResult, Plan, Results, Run, Snapshot } from '../api/types'
import { acknowledgeIds, approvalGate, approvalIdempotencyKey } from '../lib/approval'
import { ApprovalPanel, type SharedApproval } from './ApprovalPanel'

const run = runJson as unknown as Run
const results = resultsJson as unknown as Results
const snapshot = snapshotJson as unknown as Snapshot
const b3 = results.results.find((result) => result.method === 'B3')!
const computed: MethodResult = { ...b3, result_origin: 'computed', approval_eligible: true, validation_status: 'passed' }
const approval: Approval = { approval_id: 'A1', plan_id: run.plan_id, version: run.base_plan_version + 1, run_id: run.run_id, method: 'B3', approved_by: 'demo-reviewer', approved_at: '2026-11-08T01:00:00Z', external_actions_performed: false }
const plan: Plan = { plan_id: run.plan_id, version: approval.version, scenario_id: run.scenario_id, approval_id: approval.approval_id }
let container: HTMLDivElement
let root: Root

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

function clientWith(approve = vi.fn().mockResolvedValue(approval), getPlan = vi.fn().mockResolvedValue(plan)): ApiClient {
  return { mode: 'http', approve, getPlan, getScenario: vi.fn(), getRun: vi.fn(), getResults: vi.fn() }
}
async function render(client: ApiClient, result = computed, key = 'approve-stable') {
  await act(async () => root.render(<ApprovalPanel key={result.method} gate={approvalGate(run, result, run.scenario_id)} client={client} run={run} result={result} idempotencyKey={key} />))
}
async function acknowledge() {
  await act(async () => container.querySelector<HTMLInputElement>('input')!.click())
}
async function submit() {
  await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())
}
const button = () => container.querySelector<HTMLButtonElement>('button')!

describe('승인 상태 전이', () => {
  it('위험·미처리를 확인한 뒤 한 번만 전송하고 성공 후 다시 보내지 않는다', async () => {
    const approve = vi.fn().mockResolvedValue(approval)
    await render(clientWith(approve))
    expect(button().disabled).toBe(true)
    await acknowledge()
    expect(button().disabled).toBe(false)
    await submit()
    expect(approve).toHaveBeenCalledWith(run.plan_id, { run_id: run.run_id, method: 'B3', expected_version: run.base_plan_version, acknowledged_job_ids: ['J3'] }, 'approve-stable')
    expect(container.textContent).toContain('내부 계획 v2 승인됨')
    expect(container.textContent).toContain('외부 반영 없음')
    expect(button().disabled).toBe(true)
    await submit()
    expect(approve).toHaveBeenCalledTimes(1)
  })

  it('같은 렌더 안의 중복 클릭과 전송 중 확인 체크 변경을 차단한다', async () => {
    let resolve!: (a: Approval) => void
    const approve = vi.fn(() => new Promise<Approval>((done) => { resolve = done }))
    await render(clientWith(approve))
    await acknowledge()
    await act(async () => { button().click(); button().click() })
    expect(approve).toHaveBeenCalledTimes(1)
    expect(button().disabled).toBe(true)
    expect(container.querySelector<HTMLInputElement>('input')!.disabled).toBe(true)
    await act(async () => resolve(approval))
  })

  it('응답 유실은 성공·실패를 단정하지 않고 같은 키와 본문으로 재시도한다', async () => {
    const approve = vi.fn().mockRejectedValueOnce(new TypeError('connection lost')).mockResolvedValueOnce(approval)
    await render(clientWith(approve))
    await acknowledge()
    await submit()
    expect(container.textContent).toContain('승인 결과 확인 필요')
    expect(container.textContent).toContain('이미 처리됐을 수 있습니다')
    expect(button().disabled).toBe(false)
    await submit()
    expect(approve.mock.calls[1]).toEqual(approve.mock.calls[0])
    expect(container.textContent).toContain('승인됨')
  })

  it.each([[409, 'PLAN_VERSION_CONFLICT'], [422, 'RESULT_NOT_COMPUTED'], [503, 'WINDOW_UNCONFIRMED'], [503, 'INPUT_EXPIRED'], [503, 'APPROVAL_NOT_IMPLEMENTED']])('HTTP %s %s 뒤 오래된 요청을 반복하지 않는다', async (status, code) => {
    const approve = vi.fn().mockRejectedValue(new ApiRequestError(Number(status), { code: String(code), message: 'rejected' }))
    await render(clientWith(approve))
    await acknowledge()
    await submit()
    expect(button().disabled).toBe(true)
    await submit()
    expect(approve).toHaveBeenCalledTimes(1)
    expect(container.textContent).not.toContain('승인됨')
    // 확정 거절은 '결과 확인 필요'나 '다시 시도'로 보이지 않는다(브라우저 검수 2026-11-09).
    expect(container.textContent).toContain('승인 거절')
    expect(container.textContent).not.toContain('결과 확인 필요')
    expect(button().textContent).not.toContain('다시 시도')
  })

  it('저장소 장애는 유효기간으로 오인하지 않고 같은 요청으로 재시도할 수 있다', async () => {
    const approve = vi.fn().mockRejectedValue(new ApiRequestError(503, { code: 'STORAGE_UNAVAILABLE', message: 'unavailable' }))
    await render(clientWith(approve))
    await acknowledge()
    await submit()
    expect(container.textContent).toContain('저장소를 사용할 수 없습니다')
    expect(container.textContent).not.toContain('유효기간이 충족되지')
    expect(button().disabled).toBe(false)
  })

  it.each([{ plan_id: 'P-other' }, { run_id: 'R-other' }, { method: 'B1' }, { version: 99 }, { external_actions_performed: true }])('잘못된 성공 응답 %j는 승인 완료로 표시하지 않는다', async (patch) => {
    const getPlan = vi.fn().mockResolvedValue(plan)
    await render(clientWith(vi.fn().mockResolvedValue({ ...approval, ...patch }), getPlan))
    await acknowledge()
    await submit()
    expect(container.textContent).toContain('승인 응답의 계획')
    expect(container.textContent).not.toContain('승인됨')
    expect(button().disabled).toBe(true)
    expect(getPlan).not.toHaveBeenCalled()
  })

  it('승인 응답 뒤 현재 계획 조회 실패를 숨기지 않고 POST를 반복하지 않는다', async () => {
    const approve = vi.fn().mockResolvedValue(approval)
    await render(clientWith(approve, vi.fn().mockRejectedValue(new Error('offline'))))
    await acknowledge()
    await submit()
    expect(container.textContent).toContain('승인됨')
    expect(container.textContent).toContain('현재 계획을 조회하지 못했습니다')
    expect(button().disabled).toBe(true)
    expect(approve).toHaveBeenCalledTimes(1)
  })

  it('성공 상태의 null 응답도 승인 완료나 재전송 대상으로 취급하지 않는다', async () => {
    await render(clientWith(vi.fn().mockResolvedValue(null)))
    await acknowledge()
    await submit()
    expect(container.textContent).toContain('승인 응답의 계획')
    expect(container.textContent).not.toContain('승인됨')
    expect(button().disabled).toBe(true)
  })

  it.each([{ version: 3 }, { scenario_id: 'S-new' }, { approval_id: 'A-other' }])('승인 후 최신 계획이 다르면 %j 명시한다', async (patch) => {
    await render(clientWith(vi.fn().mockResolvedValue(approval), vi.fn().mockResolvedValue({ ...plan, ...patch })))
    await acknowledge()
    await submit()
    expect(container.textContent).toContain('이번 승인과 다릅니다')
    expect(button().disabled).toBe(true)
  })
})

describe('요청·결과 경계', () => {
  it.each(['UNKNOWN', 'INFEASIBLE', 'MODEL_INVALID', 'INPUT_INCOMPLETE', 'BASELINE'] as const)('%s 결과의 잘못된 eligible 표시를 승인으로 보내지 않는다', (solution_status) => {
    expect(approvalGate(run, { ...computed, solution_status }, run.scenario_id).allowed).toBe(false)
  })
  it('목적 단계 UNKNOWN은 유효한 FEASIBLE 결과의 승인을 막는 전체 해 상태가 아니다', () => {
    const result: MethodResult = { ...computed, solution_status: 'FEASIBLE', objective_proven: false, objective_stages: [{ objective: 'unassigned', status: 'UNKNOWN', value: null, best_bound: null }] }
    expect(approvalGate(run, result, run.scenario_id).allowed).toBe(true)
  })
  it('입력·실행·결과의 계획 버전과 현재 요청 ID를 대조한다', () => {
    const context = { snapshot, results, runId: run.run_id }
    expect(approvalGate(run, computed, run.scenario_id, context).allowed).toBe(true)
    expect(approvalGate(run, computed, run.scenario_id, { ...context, snapshot: { ...snapshot, base_plan_version: 2 } }).allowed).toBe(false)
    expect(approvalGate(run, computed, run.scenario_id, { ...context, results: { ...results, base_plan_version: 2 } }).allowed).toBe(false)
    expect(approvalGate(run, computed, run.scenario_id, { ...context, runId: 'R-other' }).allowed).toBe(false)
    expect(approvalGate(run, computed, null, context).allowed).toBe(false)
  })
  it('방법 전환 뒤 같은 요청 키를 복원하고 다른 요청과 구분한다', () => {
    const cache = new Map<string, string>()
    const request = { run_id: run.run_id, method: 'B3' as const, expected_version: run.base_plan_version, acknowledged_job_ids: acknowledgeIds(computed) }
    const first = approvalIdempotencyKey(cache, run.plan_id, request)
    const other = approvalIdempotencyKey(cache, run.plan_id, { ...request, method: 'B1' })
    expect(other).not.toBe(first)
    expect(approvalIdempotencyKey(cache, run.plan_id, request)).toBe(first)
  })
})

describe('방법 탭 전환 중 승인 상태 유지 (PR #9 리뷰)', () => {
  const b1: MethodResult = { ...computed, method: 'B1' }
  let pick!: (m: MethodResult) => void
  // App처럼 승인 상태를 패널 밖에 두고, 방법이 바뀌면 패널을 새로 만든다.
  function Host({ client }: { client: ApiClient }) {
    const [result, setResult] = useState(computed)
    const [shared, setShared] = useState<SharedApproval>(null)
    pick = setResult
    return <ApprovalPanel key={result.method} gate={approvalGate(run, result, run.scenario_id)} client={client} run={run} result={result} idempotencyKey={`k-${result.method}`} shared={shared} onShared={setShared} />
  }

  it('전송 중 다른 방법으로 갔다 돌아와도 진행·성공 상태가 남고 다른 방법은 보내지 않는다', async () => {
    let resolve!: (a: Approval) => void
    const approve = vi.fn(() => new Promise<Approval>((done) => { resolve = done }))
    await act(async () => root.render(<Host client={clientWith(approve)} />))
    await acknowledge()
    await submit()
    await act(async () => pick(b1))
    expect(container.textContent).toContain('B3 조정안이 승인 요청 중')
    expect(button().disabled).toBe(true)
    expect(container.querySelector<HTMLInputElement>('input')!.disabled).toBe(true)
    await act(async () => resolve(approval))
    expect(container.textContent).toContain('B3 조정안이 승인되었습니다')
    await submit()
    await act(async () => pick(computed))
    expect(container.textContent).toContain('내부 계획 v2 승인됨')
    expect(button().disabled).toBe(true)
    expect(approve).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['통신 실패 후 전환', new TypeError('connection lost'), false],
    ['통신 응답 대기 중 전환', new TypeError('connection lost'), true],
    ['저장소 장애 후 전환', new ApiRequestError(503, { code: 'STORAGE_UNAVAILABLE', message: 'unavailable' }), false],
    ['저장소 응답 대기 중 전환', new ApiRequestError(503, { code: 'STORAGE_UNAVAILABLE', message: 'unavailable' }), true],
  ])('%s 뒤 위험 작업을 다시 확인하고 같은 본문·키로 재시도한다', async (_label, error, switchWhileSending) => {
    let reject!: (error: unknown) => void
    const approve = vi.fn().mockImplementationOnce(() => new Promise<Approval>((_resolve, fail) => { reject = fail })).mockResolvedValueOnce(approval)
    const client = clientWith(approve)
    await act(async () => root.render(<Host client={client} />))
    await acknowledge()
    await submit()
    if (switchWhileSending) await act(async () => pick(b1))
    await act(async () => reject(error))
    if (!switchWhileSending) await act(async () => pick(b1))
    expect(button().disabled).toBe(true)
    expect(container.querySelector<HTMLInputElement>('input')!.disabled).toBe(true)
    await act(async () => pick(computed))
    const checkbox = container.querySelector<HTMLInputElement>('input')!
    expect(checkbox.checked).toBe(false)
    expect(checkbox.disabled).toBe(false)
    expect(button().disabled).toBe(true)
    await acknowledge()
    expect(button().disabled).toBe(false)
    await submit()
    expect(approve).toHaveBeenCalledTimes(2)
    expect(approve.mock.calls[1]).toEqual(approve.mock.calls[0])
    expect(container.textContent).toContain('내부 계획 v2 승인됨')
  })

  it('재시도 불가 거절은 방법을 바꿨다가 돌아와도 확인·재전송을 막는다', async () => {
    const approve = vi.fn().mockRejectedValue(new ApiRequestError(409, { code: 'PLAN_VERSION_CONFLICT', message: 'conflict' }))
    await act(async () => root.render(<Host client={clientWith(approve)} />))
    await acknowledge()
    await submit()
    await act(async () => pick(b1))
    await act(async () => pick(computed))
    expect(container.querySelector<HTMLInputElement>('input')!.disabled).toBe(true)
    expect(button().disabled).toBe(true)
    await submit()
    expect(approve).toHaveBeenCalledTimes(1)
  })
})
