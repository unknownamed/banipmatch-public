import { useState } from 'react'
import s01 from '@examples/01_snapshot.json'
import s07 from '@examples/07_snapshot_입력누락.json'
import s08 from '@examples/08_snapshot_미확인변경.json'
import runRequestJson from '@examples/02_run_request.json'
import type { ApiClient, RunRequest } from '../api/client'
import { ApiRequestError } from '../api/client'
import type { Snapshot } from '../api/types'
import { buildRows } from '../lib/compare'
import { newAttempt, type StartAttempt } from '../lib/startRun'
import { ComparisonSection } from './ComparisonSection'
import { ChangeEvidence, Header } from './Panels'

const EXAMPLES = [
  { id: '01', label: '01 정상 입력', snapshot: s01 },
  { id: '07', label: '07 입력 누락 (J1 준비시각 미확인)', snapshot: s07 },
  { id: '08', label: '08 미확인 변경 (반입시간 변경 미확정)', snapshot: s08 },
] as const

type Status =
  | { state: 'idle' }
  | { state: 'sending'; step: string }
  | { state: 'error'; step: string; error: unknown }
  /** 입력은 등록됐지만 입력 오류·미확인 변경으로 계산이 거절됨. */
  | { state: 'rejected'; error: ApiRequestError; snapshot: Snapshot }

// 503은 저장소 일시 장애에도 쓰인다. 503 중 입력 확인이 필요한 코드만 재시도를 막는다.
export const isInputRejection = (e: unknown): e is ApiRequestError =>
  e instanceof ApiRequestError && !!e.body &&
  (e.status === 422 || (e.status === 503 && e.body.code === 'WINDOW_UNCONFIRMED'))

/** http 모드에서 run 파라미터가 없을 때: 공통 예제로 입력 등록 → 계산 요청 → 결과 화면으로 이동. */
export function StartRunPanel({ client }: { client: ApiClient }) {
  const [exampleId, setExampleId] = useState<(typeof EXAMPLES)[number]['id']>('01')
  // 예제마다 한 시도를 유지한다. 실패 후 "다시 시도"는 같은 본문·같은 멱등키. 새 시도는 새로고침.
  const [attempts] = useState(() => new Map<string, StartAttempt>())
  const [status, setStatus] = useState<Status>({ state: 'idle' })
  const example = EXAMPLES.find((e) => e.id === exampleId)!
  if (!attempts.has(exampleId))
    attempts.set(exampleId, newAttempt(example.snapshot as unknown as Snapshot, runRequestJson as unknown as RunRequest))
  const attempt = attempts.get(exampleId)!

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
      if (step === '계산 요청' && isInputRejection(error)) {
        // 등록된 입력을 서버에서 다시 읽어 보여준다(화면이 가진 사본이 아니라 저장된 원본).
        const saved = await client.getScenario(attempt.snapshot.scenario_id).catch(() => attempt.snapshot)
        setStatus({ state: 'rejected', error, snapshot: saved })
      } else setStatus({ state: 'error', step, error })
    }
  }

  const err = status.state === 'error' ? status.error : null
  return (
    <main>
      <div className="banner" role="note">
        로컬 모의 API에 연결된 화면입니다. 공통 예제 입력을 새 ID({attempt.snapshot.scenario_id})로 등록하고 B0·B3 계산을 요청합니다.
      </div>
      <section className="card">
        <h2>예제로 계산 요청</h2>
        <p className="muted">
          서버 설정에 따라 설명용 결과(illustrative_fixture, 승인 불가) 또는 엔진 실계산 결과를 돌려줍니다. 결과 화면의 &lsquo;결과 출처&rsquo;로 구분하세요.
          공통 예제는 기준시각이 지난 모의 자료라 실계산이어도 승인은 입력 유효기간 만료(503 INPUT_EXPIRED)로 거절될 수 있습니다.
        </p>
        <p>
          <label>
            입력 예제{' '}
            <select
              value={exampleId}
              disabled={status.state === 'sending'}
              onChange={(e) => {
                setExampleId(e.target.value as typeof exampleId)
                setStatus({ state: 'idle' })
              }}
            >
              {EXAMPLES.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.label}
                </option>
              ))}
            </select>
          </label>
        </p>
        {status.state !== 'rejected' && (
          <button type="button" disabled={status.state === 'sending'} onClick={start}>
            {status.state === 'sending' ? `${status.step} 중…` : status.state === 'error' ? '다시 시도' : '입력 등록 후 계산 요청'}
          </button>
        )}
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
        {status.state === 'rejected' && (
          <div className="warn" role="alert">
            <p>
              <b>입력은 등록됐지만 계산이 막혔습니다.</b> HTTP {status.error.status} {status.error.body!.code} — {status.error.message}
            </p>
            {status.error.body!.details?.map((d) => (
              <p key={d.path} className="small">
                <code>{d.path}</code> {d.reason}
              </p>
            ))}
            <p className="muted small">같은 요청을 다시 보내도 풀리지 않습니다. 누락·미확인 값을 확인한 뒤 새 입력으로 등록해야 합니다.</p>
          </div>
        )}
      </section>
      {status.state === 'rejected' && <RejectedInput snapshot={status.snapshot} reason={status.error.message} />}
    </main>
  )
}

/** 계산이 막혀도 담당자가 입력·변경 근거·원안은 볼 수 있게 한다. 조정안 열은 없다. */
function RejectedInput({ snapshot, reason }: { snapshot: Snapshot; reason: string }) {
  return (
    <>
      <Header s={snapshot} />
      <ChangeEvidence s={snapshot} />
      <ComparisonSection
        snapshot={snapshot}
        results={{ state: 'error', message: `계산 요청 거절 — ${reason}` }}
        base={undefined}
        cand={undefined}
        candidates={[]}
        rows={buildRows(snapshot, undefined, undefined)}
        onPick={() => {}}
      />
    </>
  )
}
