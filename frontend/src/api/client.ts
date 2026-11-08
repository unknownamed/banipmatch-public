import type { ApiError, ResultsResponse, Run, Snapshot } from './types'

/** 화면이 쓰는 조회 API. 구현은 fixture(공통 예제) 또는 http(백엔드) 중 하나. */
export interface ApiClient {
  readonly mode: 'fixture' | 'http'
  getScenario(scenarioId: string, signal?: AbortSignal): Promise<Snapshot>
  getRun(runId: string, signal?: AbortSignal): Promise<Run>
  getResults(runId: string, signal?: AbortSignal): Promise<ResultsResponse>
  /** http 모드 전용. 재시도에는 같은 Idempotency-Key와 같은 본문을 쓴다. */
  registerScenario?(snapshot: Snapshot, idempotencyKey: string): Promise<{ scenario_id: string; plan_id: string }>
  createRun?(request: RunRequest, idempotencyKey: string): Promise<Run>
}

export interface RunRequest {
  scenario_id: string
  base_plan_version: number
  methods: Run['methods']
  time_limit_seconds: number
  seed: number
}

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly body: ApiError | null,
  ) {
    super(body?.message ?? `HTTP ${status}`)
  }
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: ApiError | null = null
    try {
      const parsed = (await res.json()) as ApiError
      body = typeof parsed?.code === 'string' ? parsed : null // 공통 Error 객체만 인정
    } catch {
      body = null
    }
    throw new ApiRequestError(res.status, body)
  }
  return (await res.json()) as T
}

/**
 * 백엔드 /v1 연결용. 로컬 모의 API(PR #3)는 GET에도 Bearer 모의 토큰을 요구한다.
 * 토큰은 loopback 전용 모의 값이며 사용자 인증이 아니다.
 */
export function createHttpClient(baseUrl = '', token?: string): ApiClient {
  const auth: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}
  const get = (path: string, signal?: AbortSignal) => fetch(`${baseUrl}${path}`, { signal, headers: auth })
  const post = <T,>(path: string, body: unknown, key: string) =>
    fetch(`${baseUrl}${path}`, {
      method: 'POST',
      headers: { ...auth, 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: JSON.stringify(body),
    }).then(readJson<T>)
  return {
    mode: 'http',
    registerScenario: (snapshot, key) => post('/v1/scenarios', snapshot, key),
    createRun: (request, key) => post('/v1/runs', request, key),
    getScenario: (id, signal) => get(`/v1/scenarios/${encodeURIComponent(id)}`, signal).then(readJson<Snapshot>),
    getRun: (id, signal) => get(`/v1/runs/${encodeURIComponent(id)}`, signal).then(readJson<Run>),
    async getResults(id, signal) {
      const res = await get(`/v1/runs/${encodeURIComponent(id)}/results`, signal)
      if (res.status === 202) return { kind: 'pending', run: (await res.json()) as Run }
      return { kind: 'ready', results: await readJson(res) }
    },
  }
}
