// 담당자 대응 API v0.2(/v2) 연결. 인증은 서버가 주는 HttpOnly 세션 쿠키이고,
// 화면은 CSRF 값만 메모리에 들고 있는다(저장소·로그에 남기지 않음). 관리자 토큰은 쓰지 않는다.
import { readJson, type ApiClient } from './client'
import type { Plan, ResultsResponse, Run, Snapshot } from './types'
import { withQueueRetry } from '../lib/queueRetry'

export interface SessionPlan {
  plan_id: string
  version: number
  scenario_id: string
  latest_run_id: string | null
  latest_revision_id: string | null
}

export interface SessionState {
  session_id: string
  expires_at: string
  csrf_token: string
  push_test_authorized: boolean
  data_mode: string
  plans: SessionPlan[]
  limits: Record<string, unknown>
}

export interface V2Client extends ApiClient {
  /** 기존 세션을 복구하고, 없으면 새로 만든다. 새 세션은 빈 자료 범위다. */
  session(): Promise<SessionState>
  /** 시연 시각으로 옮긴 명시적 모의 예제(01). 실제 자료가 아니다. */
  defaultExample(): Promise<Snapshot>
  get<T>(path: string, signal?: AbortSignal): Promise<T>
  /** 쓰기 요청. 재시도에는 같은 Idempotency-Key와 같은 본문을 쓴다. */
  post<T>(path: string, body: unknown, idempotencyKey: string): Promise<T>
}

const enc = encodeURIComponent

export function createV2Client(base = ''): V2Client {
  let current: Promise<SessionState> | null = null

  async function open(): Promise<SessionState> {
    // 많은 사람이 한꺼번에 열 때 서버가 잠깐 바쁘면(503 REQUEST_CAPACITY) 조금 기다렸다 다시 연다.
    return withQueueRetry(async () => {
      const res = await fetch(`${base}/v2/session`)
      if (res.status !== 401 && res.status !== 410) return readJson<SessionState>(res)
      // 쿠키가 없거나 만료됨 → 새 세션. 생성 요청은 Origin만 검사한다(브라우저가 자동으로 붙임).
      return readJson<SessionState>(await fetch(`${base}/v2/session`, { method: 'POST' }))
    }, undefined, 10, 1500)
  }

  function session() {
    current ??= open().catch((e) => {
      current = null
      throw e
    })
    return current
  }

  const get = <T,>(path: string, signal?: AbortSignal) => fetch(`${base}${path}`, { signal }).then(readJson<T>)

  async function post<T>(path: string, body: unknown, key: string): Promise<T> {
    const { csrf_token } = await session()
    const res = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, 'X-CSRF-Token': csrf_token },
      body: JSON.stringify(body),
    })
    // 세션이 끝났으면 다음 요청에서 새 세션을 연다. 이전 자료는 새 세션에서 보이지 않는다.
    if (res.status === 401 || res.status === 410) current = null
    return readJson<T>(res)
  }

  return {
    mode: 'http',
    session,
    get,
    post,
    defaultExample: () => session().then(() => get<Snapshot>('/v2/examples/default')),
    registerScenario: (snapshot, key) => post('/v2/scenarios', snapshot, key),
    createRun: (request, key) => post<Run>('/v2/runs', request, key),
    approve: (planId, request, key) => post(`/v2/plans/${enc(planId)}/approvals`, request, key),
    getPlan: (planId) => get<Plan>(`/v2/plans/${enc(planId)}`),
    getScenario: (id, signal) => get<Snapshot>(`/v2/scenarios/${enc(id)}`, signal),
    getRun: (id, signal) => get<Run>(`/v2/runs/${enc(id)}`, signal),
    async getResults(id, signal): Promise<ResultsResponse> {
      const res = await fetch(`${base}/v2/runs/${enc(id)}/results`, { signal })
      if (res.status === 202) return { kind: 'pending', run: (await res.json()) as Run }
      return { kind: 'ready', results: await readJson(res) }
    },
  }
}
