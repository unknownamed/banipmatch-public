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
