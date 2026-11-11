// /v2 연결: 세션 복구/생성, 쓰기 요청의 CSRF·멱등키, 세션 만료 뒤 재생성을 확인.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError } from './client'
import { createV2Client } from './v2'

afterEach(() => vi.unstubAllGlobals())

const session = (csrf: string) => ({
  session_id: 'sess', expires_at: '2026-11-12T00:00:00Z', csrf_token: csrf, push_test_authorized: false, data_mode: 'demo', plans: [], limits: {},
})

function stubFetch(...responses: [number, unknown][]) {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const [status, body] = responses.shift()!
    return new Response(JSON.stringify(body), { status })
  })
  return calls
}

describe('v2 세션', () => {
  it('쿠키 세션이 없으면(401) 새로 만들고, 같은 세션을 다시 묻지 않는다', async () => {
    const calls = stubFetch([401, { code: 'SESSION_REQUIRED', message: '' }], [201, session('c1')])
    const c = createV2Client()
    expect((await c.session()).csrf_token).toBe('c1')
    await c.session()
    expect(calls.map((x) => `${x.init?.method ?? 'GET'} ${x.url}`)).toEqual(['GET /v2/session', 'POST /v2/session'])
  })

  it('쓰기 요청에 CSRF 값과 멱등키를 붙이고, 토큰을 URL에 넣지 않는다', async () => {
    const calls = stubFetch([200, session('c1')], [201, { scenario_id: 'S', plan_id: 'P' }])
    const c = createV2Client()
    await c.registerScenario!({ scenario_id: 'S' } as never, 'k1')
    const h = calls[1].init!.headers as Record<string, string>
    expect(calls[1].url).toBe('/v2/scenarios')
    expect(h['X-CSRF-Token']).toBe('c1')
    expect(h['Idempotency-Key']).toBe('k1')
  })

  it('세션 만료(410) 뒤에는 다음 요청에서 새 세션을 연다', async () => {
    const calls = stubFetch(
      [200, session('old')],
      [410, { code: 'SESSION_EXPIRED', message: '만료' }],
      [410, { code: 'SESSION_EXPIRED', message: '만료된 쿠키' }],
      [201, session('new')],
      [202, { run_id: 'R' }],
    )
    const c = createV2Client()
    await expect(c.createRun!({} as never, 'k')).rejects.toBeInstanceOf(ApiRequestError)
    await c.createRun!({} as never, 'k')
    expect((calls[4].init!.headers as Record<string, string>)['X-CSRF-Token']).toBe('new')
  })

  it('계산 중(202)이면 결과 대기로 돌려준다', async () => {
    stubFetch([202, { run_id: 'R', status: 'running' }])
    const r = await createV2Client().getResults('R')
    expect(r.kind).toBe('pending')
  })
})
