import { useEffect, useState } from 'react'
import type { ApiClient } from './client'
import { ApiRequestError } from './client'
import type { Results, Run, Snapshot } from './types'

export type Load<T> =
  | { state: 'loading' }
  | { state: 'error'; message: string; status?: number }
  | { state: 'ready'; data: T }

export interface DispatchView {
  scenario: Load<Snapshot>
  run: Load<Run>
  /** pending = 서버가 202로 아직 계산 중이라고 응답 */
  results: Load<Results> | { state: 'pending'; run: Run }
}

const TERMINAL: Run['status'][] = ['completed', 'failed', 'cancelled']

function errorOf(e: unknown): { state: 'error'; message: string; status?: number } {
  if (e instanceof ApiRequestError) return { state: 'error', message: e.message, status: e.status }
  return { state: 'error', message: e instanceof Error ? e.message : String(e) }
}

/**
 * 입력(scenario)과 실행(run)을 따로 불러온다. 결과가 늦어도 입력·변경 근거는 먼저 보인다.
 * - scenarioId/runId 가 바뀌면 이전 요청을 abort 하고, 늦게 온 이전 응답은 버린다.
 * - 결과가 202(계산 중)이면 간격을 늘려 다시 조회하고 run이 끝나면 멈춘다. POST는 하지 않는다.
 * - 응답의 scenario_id/run_id 가 요청과 다르면 화면에 쓰지 않고 오류로 보인다.
 */
export function useDispatchView(client: ApiClient, scenarioId: string, runId: string): DispatchView {
  const [view, setView] = useState<DispatchView>({
    scenario: { state: 'loading' },
    run: { state: 'loading' },
    results: { state: 'loading' },
  })

  useEffect(() => {
    const ac = new AbortController()
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const set = (patch: Partial<DispatchView>) => alive && setView((v) => ({ ...v, ...patch }))
    setView({ scenario: { state: 'loading' }, run: { state: 'loading' }, results: { state: 'loading' } })

    client
      .getScenario(scenarioId, ac.signal)
      .then((s) =>
        set({
          scenario:
            s.scenario_id === scenarioId
              ? { state: 'ready', data: s }
              : { state: 'error', message: `요청한 입력 ${scenarioId} 대신 ${s.scenario_id} 응답을 받아 표시하지 않았습니다.` },
        }),
      )
      .catch((e) => alive && !ac.signal.aborted && set({ scenario: errorOf(e) }))

    const mismatch = (got: { run_id: string; scenario_id: string }) =>
      got.run_id !== runId
        ? `요청한 실행 ${runId} 대신 ${got.run_id} 응답`
        : got.scenario_id !== scenarioId
          ? `실행 ${runId}의 입력은 ${got.scenario_id}로 현재 입력 ${scenarioId}와 다릅니다`
          : null

    let delay = 1000
    const poll = async () => {
      let runLoaded = false
      try {
        const run = await client.getRun(runId, ac.signal)
        runLoaded = true
        const bad = mismatch(run)
        if (bad) {
          set({ run: { state: 'error', message: bad }, results: { state: 'error', message: bad } })
          return
        }
        set({ run: { state: 'ready', data: run } })
        if (run.status === 'failed' || run.status === 'cancelled') {
          set({ results: { state: 'error', message: run.status === 'failed' ? '실행 실패' : '실행 취소' } })
          return
        }
        const res = await client.getResults(runId, ac.signal)
        if (res.kind === 'pending' || !TERMINAL.includes(run.status)) {
          set({ results: { state: 'pending', run: res.kind === 'pending' ? res.run : run } })
          timer = setTimeout(poll, delay)
          delay = Math.min(delay * 2, 10_000)
          return
        }
        const bad2 = mismatch(res.results)
        set({ results: bad2 ? { state: 'error', message: bad2 } : { state: 'ready', data: res.results } })
      } catch (e) {
        if (!alive || ac.signal.aborted) return
        // 결과 조회만 실패하면 실행 상태는 그대로 두고 결과 칸에만 오류를 보인다.
        const err = errorOf(e)
        set(runLoaded ? { results: err } : { run: err, results: err })
      }
    }
    void poll()

    return () => {
      alive = false
      ac.abort()
      if (timer) clearTimeout(timer)
    }
  }, [client, scenarioId, runId])

  return view
}
