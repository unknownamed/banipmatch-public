import { useState } from 'react'
import snapshotJson from '@examples/01_snapshot.json'
import runRequestJson from '@examples/02_run_request.json'
import type { ApiClient, RunRequest } from '../api/client'
import { ApiRequestError } from '../api/client'
import type { Snapshot } from '../api/types'
import { newAttempt, type StartAttempt } from '../lib/startRun'

type Status = { state: 'idle' } | { state: 'sending'; step: string } | { state: 'error'; step: string; error: unknown }

/** http 모드에서 run 파라미터가 없을 때: 공통 예제로 입력 등록 → 계산 요청 → 결과 화면으로 이동. */
export function StartRunPanel({ client }: { client: ApiClient }) {
  // 실패 후 "다시 시도"는 같은 본문·같은 멱등키를 쓴다. 새 시도는 새로고침.
  const [attempt] = useState<StartAttempt>(() =>
    newAttempt(snapshotJson as unknown as Snapshot, runRequestJson as unknown as RunRequest),
  )
  const [status, setStatus] = useState<Status>({ state: 'idle' })

  async function start() {
    let step = '입력 등록'
    try {
      setStatus({ state: 'sending', step })
      await client.registerScenario!(attempt.snapshot, attempt.scenarioKey)
      step = '계산 요청'
      setStatus({ state: 'sending', step })
      const run = await client.createRun!(attempt.run, attempt.runKey)
      location.search = `?scenario=${encodeURIComponent(run.scenario_id)}&run=${encodeURIComponent(run.run_id)}`
    } catch (error) {
      setStatus({ state: 'error', step, error })
    }
  }

  const err = status.state === 'error' ? status.error : null
  return (
    <main>
      <div className="banner" role="note">
        로컬 모의 API에 연결된 화면입니다. 공통 예제 01 입력을 새 ID({attempt.snapshot.scenario_id})로 등록하고 B0·B3 계산을 요청합니다.
      </div>
      <section className="card">
        <h2>예제로 계산 요청</h2>
        <p className="muted">
          현재 서버는 설명용 결과(illustrative_fixture)만 돌려줍니다. 실제 최적화 계산이 아니며 승인할 수 없습니다.
        </p>
        <button type="button" disabled={status.state === 'sending'} onClick={start}>
          {status.state === 'sending' ? `${status.step} 중…` : status.state === 'error' ? '다시 시도' : '입력 등록 후 계산 요청'}
        </button>
        {err !== null && (
          <div className="warn" role="alert">
            <p>
              {status.state === 'error' && status.step} 실패:{' '}
              {err instanceof ApiRequestError && err.body
                ? `HTTP ${err.status} ${err.body.code} — ${err.message}`
                : err instanceof ApiRequestError
                  ? `HTTP ${err.status}, 서버 오류 본문 없음. 개발 서버 프록시가 백엔드(127.0.0.1:8000)에 닿지 못했을 수 있습니다. python -m backend 실행 여부를 확인하세요.`
                  : err instanceof Error
                  ? `서버에 연결하지 못했습니다(${err.message}). python -m backend 실행 여부를 확인하세요.`
                  : String(err)}
            </p>
            {err instanceof ApiRequestError && err.status === 401 && (
              <p>VITE_API_TOKEN이 서버의 BANIPMATCH_DEMO_TOKEN과 같은지 확인하세요.</p>
            )}
            {err instanceof ApiRequestError &&
              err.body?.details?.map((d) => (
                <p key={d.path} className="small">
                  <code>{d.path}</code> {d.reason}
                </p>
              ))}
            <p className="muted small">다시 시도하면 같은 요청·같은 멱등키로 보내 중복 등록·중복 실행이 생기지 않습니다.</p>
          </div>
        )}
      </section>
    </main>
  )
}
