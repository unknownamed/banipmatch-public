// 승인 요청: 확인 대상 작업, 실패 안내, 버튼 차단, POST 본문·키.
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import runJson from '@examples/03_run_status.json'
import resultsJson from '@examples/04_results_설명용.json'
import type { MethodResult, Results, Run } from '../api/types'
import { createHttpClient } from '../api/client'
import { acknowledgeIds, approvalErrorHint, approvalGate } from '../lib/approval'
import { ApprovalPanel } from './ApprovalPanel'

const run = runJson as unknown as Run
const b3 = (resultsJson as unknown as Results).results.find((r) => r.method === 'B3')!
const computed: MethodResult = { ...b3, result_origin: 'computed', approval_eligible: true, validation_status: 'passed' }

afterEach(() => vi.unstubAllGlobals())

describe('확인 대상 작업', () => {
  it('미처리와 고정 잔여 위험을 합쳐 중복 없이 정렬한다', () => {
    expect(acknowledgeIds(b3)).toEqual(['J3'])
    const risky: MethodResult = {
      ...b3,
      issues: [...b3.issues, { job_id: 'J0', code: 'FIXED_RESIDUAL_RISK', explanation: 'x', proof_level: 'constraint_check', evidence_refs: [] }],
    }
    expect(acknowledgeIds(risky)).toEqual(['J0', 'J3'])
  })
})

describe('실패 안내', () => {
  it('Error.code에 따라 할 일을 구분한다', () => {
    expect(approvalErrorHint(409, 'PLAN_VERSION_CONFLICT')).toContain('다시 계산')
    expect(approvalErrorHint(409, 'IDEMPOTENCY_CONFLICT')).toContain('다른 내용')
    expect(approvalErrorHint(422, 'RESULT_NOT_COMPUTED')).toContain('실제 계산 결과가 아니라')
    expect(approvalErrorHint(503, 'ANY')).toContain('잠시 후')
    expect(approvalErrorHint(422, 'OTHER')).toBeNull()
  })
})

describe('승인 버튼', () => {
  const client = createHttpClient('', 'tok')
  const html = (r: MethodResult) =>
    renderToStaticMarkup(<ApprovalPanel gate={approvalGate(run, r, 'S001')} client={client} run={run} result={r} />)

  it('설명용 결과는 버튼이 닫히고 이유가 보인다', () => {
    expect(html(b3)).toMatch(/<button[^>]*disabled/)
    expect(html(b3)).toContain('실제 계산 결과가 아니라')
  })

  it('승인 가능 결과라도 미처리 작업을 확인하기 전에는 닫혀 있다', () => {
    const h = html(computed)
    expect(h).toContain('J3')
    expect(h).toMatch(/<button[^>]*disabled/)
  })
})

describe('승인 POST', () => {
  it('계획 경로·본문·멱등키·토큰을 보낸다', async () => {
    const calls: { url: string; init: RequestInit }[] = []
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
      calls.push({ url, init })
      return new Response(JSON.stringify({ approval_id: 'A1', plan_id: 'P001', version: 2 }), { status: 201 })
    })
    const body = { run_id: 'R001', method: 'B3' as const, expected_version: 1, acknowledged_job_ids: ['J3'] }
    await createHttpClient('', 'tok').approve!('P001', body, 'approve-k')
    expect(calls[0].url).toBe('/v1/plans/P001/approvals')
    expect(JSON.parse(calls[0].init.body as string)).toEqual(body)
    const h = calls[0].init.headers as Record<string, string>
    expect(h['Idempotency-Key']).toBe('approve-k')
    expect(h['Authorization']).toBe('Bearer tok')
  })
})
