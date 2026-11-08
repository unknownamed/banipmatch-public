// 공통 예제 01(입력)·02(실행 요청)로 서버에 계산을 요청할 준비물.
// 서버는 같은 scenario_id 재등록을 409로 막으므로 시도마다 새 ID를 붙인다(tools/demo_api.py와 같은 방식).
// 한 시도의 본문·멱등키는 재시도 동안 그대로 유지해야 중복 실행이 생기지 않는다.
import type { RunRequest } from '../api/client'
import type { Snapshot } from '../api/types'

export interface StartAttempt {
  snapshot: Snapshot
  run: RunRequest
  scenarioKey: string
  runKey: string
}

export function newAttempt(snapshot: Snapshot, run: RunRequest, id: string = crypto.randomUUID()): StartAttempt {
  const suffix = id.replace(/-/g, '').slice(0, 12)
  const scenario_id = `S-${suffix}`
  return {
    snapshot: { ...snapshot, scenario_id, plan_id: `P-${suffix}` },
    run: { ...run, scenario_id },
    scenarioKey: `scenario-${id}`,
    runKey: `run-${id}`,
  }
}

export const ALL_METHODS = ['B0', 'B1', 'B2', 'B3'] as const
export type MethodId = (typeof ALL_METHODS)[number]

/** 선택한 방법으로 실행 요청을 만든다. 본문이 바뀌면 멱등키도 바뀌어야 하므로 방법을 키에 넣는다. */
export function runFor(attempt: StartAttempt, picked: ReadonlySet<MethodId>): { body: RunRequest; key: string } {
  const methods = ALL_METHODS.filter((m) => m === 'B0' || picked.has(m))
  return { body: { ...attempt.run, methods }, key: `${attempt.runKey}:${methods.join('')}` }
}

/** 서버가 지원하지 않는 방법이라 거절한 경우. 입력 문제가 아니므로 방법을 바꿔 다시 요청한다. */
export const isMethodRejection = (code: string | undefined) => code === 'DEMO_METHOD_UNAVAILABLE' || code === 'METHOD_NOT_IMPLEMENTED'
