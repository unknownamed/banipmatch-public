// 공통 예제(01 snapshot, 03 run status, 04 설명용 결과)를 그대로 돌려주는 조회 클라이언트.
// 값은 원본 JSON 그대로이며 화면에서 보충·수정하지 않는다.
import snapshot from '@examples/01_snapshot.json'
import runStatus from '@examples/03_run_status.json'
import results from '@examples/04_results_설명용.json'
import type { ApiClient } from './client'
import { ApiRequestError } from './client'
import type { Results, Run, Snapshot } from './types'

const SNAPSHOT = snapshot as unknown as Snapshot
const RUN = runStatus as unknown as Run
const RESULTS = results as unknown as Results

function notFound(what: string, id: string): never {
  throw new ApiRequestError(404, { code: 'NOT_FOUND', message: `${what} ${id} 없음 (예제에는 ${what === '시나리오' ? SNAPSHOT.scenario_id : RUN.run_id}만 있음)` })
}

export function createFixtureClient(delayMs = 150): ApiClient {
  const wait = <T,>(value: () => T, signal?: AbortSignal) =>
    new Promise<T>((resolve, reject) => {
      const t = setTimeout(() => {
        try {
          resolve(structuredClone(value()))
        } catch (e) {
          reject(e)
        }
      }, delayMs)
      signal?.addEventListener('abort', () => {
        clearTimeout(t)
        reject(new DOMException('aborted', 'AbortError'))
      })
    })

  return {
    mode: 'fixture',
    getScenario: (id, signal) => wait(() => (id === SNAPSHOT.scenario_id ? SNAPSHOT : notFound('시나리오', id)), signal),
    getRun: (id, signal) => wait(() => (id === RUN.run_id ? RUN : notFound('실행', id)), signal),
    getResults: (id, signal) =>
      wait(() => (id === RESULTS.run_id ? { kind: 'ready' as const, results: RESULTS } : notFound('실행', id)), signal),
  }
}

export const FIXTURE_IDS = { scenarioId: SNAPSHOT.scenario_id, runId: RUN.run_id }
