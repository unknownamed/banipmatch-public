import type { ApiError, ResultsResponse, Run, Snapshot } from './types'

/** 화면이 쓰는 조회 API. 구현은 fixture(공통 예제) 또는 http(백엔드) 중 하나. */
export interface ApiClient {
  readonly mode: 'fixture' | 'http'
  getScenario(scenarioId: string, signal?: AbortSignal): Promise<Snapshot>
  getRun(runId: string, signal?: AbortSignal): Promise<Run>
  getResults(runId: string, signal?: AbortSignal): Promise<ResultsResponse>
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
      body = (await res.json()) as ApiError
    } catch {
      body = null
    }
    throw new ApiRequestError(res.status, body)
  }
  return (await res.json()) as T
}

/** 백엔드 /v1 연결용. 아직 서버가 없으므로 기본값은 fixture. */
export function createHttpClient(baseUrl = ''): ApiClient {
  return {
    mode: 'http',
    getScenario: (id, signal) => fetch(`${baseUrl}/v1/scenarios/${encodeURIComponent(id)}`, { signal }).then(readJson<Snapshot>),
    getRun: (id, signal) => fetch(`${baseUrl}/v1/runs/${encodeURIComponent(id)}`, { signal }).then(readJson<Run>),
    async getResults(id, signal) {
      const res = await fetch(`${baseUrl}/v1/runs/${encodeURIComponent(id)}/results`, { signal })
      if (res.status === 202) return { kind: 'pending', run: (await res.json()) as Run }
      return { kind: 'ready', results: await readJson(res) }
    },
  }
}
