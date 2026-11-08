// POST 계산 요청이 토큰·멱등키를 붙이고, 재시도에 같은 키·같은 본문을 쓰는지 확인.
import { afterEach, describe, expect, it, vi } from 'vitest'
import snapshotJson from '@examples/01_snapshot.json'
import runRequestJson from '@examples/02_run_request.json'
import type { Snapshot } from './types'
import { ApiRequestError, createHttpClient, type RunRequest } from './client'
import { newAttempt } from '../lib/startRun'

const snapshot = snapshotJson as unknown as Snapshot
const runReq = runRequestJson as unknown as RunRequest

afterEach(() => vi.unstubAllGlobals())

function stubFetch(...responses: [number, unknown][]) {
  const calls: { url: string; init: RequestInit }[] = []
  vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
    calls.push({ url, init })
    const [status, body] = responses.shift()!
    return new Response(JSON.stringify(body), { status })
  })
  return calls
}

describe('계산 요청 준비', () => {
  it('새 ID를 입력과 실행 요청에 같이 쓰고 원본 예제는 바꾸지 않는다', () => {
    const a = newAttempt(snapshot, runReq, '11111111-2222-3333-4444-555555555555')
    expect(a.snapshot.scenario_id).toBe('S-111111112222')
    expect(a.snapshot.plan_id).toBe('P-111111112222')
    expect(a.run.scenario_id).toBe(a.snapshot.scenario_id)
    expect(a.scenarioKey).not.toBe(a.runKey)
    expect(snapshot.scenario_id).toBe('S001')
  })
})

describe('http POST', () => {
  it('토큰·멱등키를 붙이고 재시도에 같은 키·본문을 보낸다', async () => {
    const calls = stubFetch([503, { code: 'X', message: '일시 오류' }], [201, { scenario_id: 'S-1', plan_id: 'P-1' }])
    const client = createHttpClient('', 'tok')
    const a = newAttempt(snapshot, runReq)
    await expect(client.registerScenario!(a.snapshot, a.scenarioKey)).rejects.toBeInstanceOf(ApiRequestError)
    await client.registerScenario!(a.snapshot, a.scenarioKey)
    const headers = calls.map((c) => c.init.headers as Record<string, string>)
    expect(calls.map((c) => c.init.method)).toEqual(['POST', 'POST'])
    expect(headers[0]['Authorization']).toBe('Bearer tok')
    expect(headers[0]['Idempotency-Key']).toBe(a.scenarioKey)
    expect(headers[1]['Idempotency-Key']).toBe(headers[0]['Idempotency-Key'])
    expect(calls[1].init.body).toBe(calls[0].init.body)
  })

  it('오류 응답의 code·details를 그대로 전달한다', async () => {
    stubFetch([409, { code: 'SCENARIO_EXISTS', message: '이미 등록된 입력 ID임', details: [{ path: 'scenario_id', reason: '중복' }] }])
    const client = createHttpClient('', 'tok')
    const e = await client.createRun!(runReq, 'k').catch((x) => x)
    expect(e).toBeInstanceOf(ApiRequestError)
    expect(e.status).toBe(409)
    expect(e.body.code).toBe('SCENARIO_EXISTS')
    expect(e.body.details[0].path).toBe('scenario_id')
  })
})
