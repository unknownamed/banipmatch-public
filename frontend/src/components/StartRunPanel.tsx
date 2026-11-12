import { useEffect, useState } from 'react'
import s01 from '@examples/01_snapshot.json'
import s07 from '@examples/07_snapshot_입력누락.json'
import s08 from '@examples/08_snapshot_미확인변경.json'
import s02 from '../fixtures/demo-02-evening.synthetic.json'
import runRequestJson from '@examples/02_run_request.json'
import type { ApiClient, RunRequest } from '../api/client'
import { ApiRequestError } from '../api/client'
import type { Snapshot } from '../api/types'
import type { V2Client } from '../api/v2'
import { shiftSnapshot } from '../lib/shift'
import { ConditionRevisionPanel } from './RevisionPanels'
import { buildRows } from '../lib/compare'
import { ALL_METHODS, isMethodRejection, newAttempt, runFor, type MethodId, type StartAttempt } from '../lib/startRun'
import { ComparisonSection } from './ComparisonSection'
import { ChangeEvidence, Header } from './Panels'

const EXAMPLES = [
  { id: '02', label: '신항 저녁 배차', size: '트럭 6대 · 작업 16건', what: 'V1 · HJNC 반입 마감이 2시간 30분 앞당겨졌습니다. 원래 배차로는 4건이 마감을 넘깁니다.', tag: '추천', snapshot: s02 },
  { id: '01', label: '작은 배차', size: '트럭 2대 · 작업 4건', what: 'V1 반입 마감이 앞당겨진 간단한 상황입니다. 흐름을 빠르게 확인할 때 씁니다.', tag: '', snapshot: s01 },
  { id: '07', label: '입력이 빠진 경우', size: '준비 시각 미확인', what: '상차 준비 시각이 비어 있어 계산이 멈춥니다. 확인한 값을 넣어 다시 계산하는 과정을 봅니다.', tag: '', snapshot: s07 },
  { id: '08', label: '확정되지 않은 변경', size: '터미널 공지 미확정', what: '변경이 확정되지 않아 계산하지 않습니다. 잘못된 정보로 배차를 바꾸지 않도록 막는 예입니다.', tag: '', snapshot: s08 },
] as const
const METHOD_TEXT: Record<string, string> = {
  B0: '원래 배차 그대로 점검(항상 포함)',
  B1: '마감 빠른 순 재배치',
  B2: '전체 재최적화',
  B3: '최소 변경 최적화',
}

type Status =
  | { state: 'idle' }
  | { state: 'sending'; step: string }
  | { state: 'error'; step: string; error: unknown }
  /** 입력은 등록됐지만 입력 오류·미확인 변경으로 계산이 거절됨. */
  | { state: 'rejected'; error: ApiRequestError; snapshot: Snapshot }

// 503은 저장소 일시 장애에도 쓰인다. 503 중 입력 확인이 필요한 코드만 재시도를 막는다.
export const isInputRejection = (e: unknown): e is ApiRequestError =>
  e instanceof ApiRequestError && !!e.body &&
  ((e.status === 422 && !isMethodRejection(e.body.code)) || (e.status === 503 && e.body.code === 'WINDOW_UNCONFIRMED'))

/** http 모드에서 run 파라미터가 없을 때: 공통 예제로 입력 등록 → 계산 요청 → 결과 화면으로 이동. */
export function StartRunPanel({ client }: { client: ApiClient }) {
  const [exampleId, setExampleId] = useState<(typeof EXAMPLES)[number]['id']>('02')
  // 예제마다 한 시도를 유지한다. 실패 후 "다시 시도"는 같은 본문·같은 멱등키. 새 시도는 새로고침.
  const [attempts] = useState(() => new Map<string, StartAttempt>())
  const [status, setStatus] = useState<Status>({ state: 'idle' })
  // B0는 비교 기준이라 항상 포함한다. 기본은 명세대로 B0~B3 전체.
  const [picked, setPicked] = useState<ReadonlySet<MethodId>>(() => new Set(ALL_METHODS))
  // v2 서버는 예제 01을 현재 시연 시각으로 옮겨 준다(기준시각 경과로 승인이 막히지 않게). 모의 자료라는 점은 같다.
  const v2 = 'defaultExample' in client ? (client as V2Client) : null
  const [fresh, setFresh] = useState<{ snapshot?: Snapshot; error?: unknown }>({})
  useEffect(() => {
    v2?.defaultExample().then((snapshot) => setFresh({ snapshot }), (error) => setFresh({ error }))
  }, [v2])
  const example = EXAMPLES.find((e) => e.id === exampleId)!
  // 07·08도 같은 규칙으로 지금 시각에 옮긴다(만료가 아니라 원래 의도한 입력 누락·미확인 변경으로 막히게).
  const source = !v2 ? (example.snapshot as unknown as Snapshot) : exampleId === '01' ? fresh.snapshot : shiftSnapshot(example.snapshot as unknown as Snapshot, new Date())
  if (source && !attempts.has(exampleId)) attempts.set(exampleId, newAttempt(source, runRequestJson as unknown as RunRequest))
  const attempt = attempts.get(exampleId)

  if (!attempt)
    return (
      <main>
        <p className={fresh.error ? 'card warn' : 'card'} role={fresh.error ? 'alert' : 'status'}>
          {fresh.error ? `시연 예제를 받지 못했습니다: ${fresh.error instanceof Error ? fresh.error.message : String(fresh.error)}. 백엔드 실행(BANIPMATCH_WORKFLOW=1)을 확인하세요.` : '시연 세션과 예제 준비 중…'}
        </p>
      </main>
    )

  async function start() {
    if (!attempt) return
    let step = '입력 등록'
    try {
      setStatus({ state: 'sending', step })
      await client.registerScenario!(attempt.snapshot, attempt.scenarioKey)
      step = '계산 요청'
      setStatus({ state: 'sending', step })
      const { body, key } = runFor(attempt, picked)
      const run = await client.createRun!(body, key)
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
      <section className="start-hero">
        <h1>반입 마감이 바뀌었을 때, 남은 배차를 다시 맞춥니다</h1>
        <ol className="start-steps">
          <li className="on"><b>1</b> 상황 선택</li>
          <li><b>2</b> 영향 확인 · 조정안 비교</li>
          <li><b>3</b> 확정 · 기사 전달</li>
        </ol>
      </section>
      <section className="card">
        <h2>어떤 상황인가요?</h2>
        <p className="muted small">시연용 모의 배차입니다. 시각은 지금 기준으로 맞춰지며, 다른 접속자의 배차와 섞이지 않습니다.</p>
        <div className="scenario-cards" role="radiogroup" aria-label="상황 선택">
          {EXAMPLES.map((e) => (
            <button
              key={e.id}
              type="button"
              role="radio"
              aria-checked={exampleId === e.id}
              className={`scenario-card${exampleId === e.id ? ' on' : ''}`}
              disabled={status.state === 'sending'}
              onClick={() => {
                setExampleId(e.id)
                setStatus({ state: 'idle' })
              }}
            >
              <span className="sc-top"><b>{e.label}</b>{e.tag && <span className="sc-tag">{e.tag}</span>}</span>
              <span className="sc-size">{e.size}</span>
              <span className="sc-what">{e.what}</span>
            </button>
          ))}
        </div>
        <details className="tech-info start-advanced">
          <summary>고급 설정 · 계산 방법</summary>
          <fieldset disabled={status.state === 'sending'}>
            {ALL_METHODS.map((m) => (
              <label key={m} className="method-pick">
                <input
                  type="checkbox"
                  checked={m === 'B0' || picked.has(m)}
                  disabled={m === 'B0'}
                  onChange={(e) => {
                    const next = new Set(picked)
                    if (e.target.checked) next.add(m)
                    else next.delete(m)
                    setPicked(next)
                    if (status.state === 'error') setStatus({ state: 'idle' })
                  }}
                />{' '}
                <b>{m}</b> {METHOD_TEXT[m]}
              </label>
            ))}
            {!v2 && <p className="muted small">공통 예제는 기준시각이 지난 모의 자료라 승인이 입력 유효기간 만료로 거절될 수 있습니다.</p>}
          </fieldset>
        </details>
        {status.state !== 'rejected' && (
          <button type="button" disabled={status.state === 'sending'} onClick={start}>
            {status.state === 'sending' ? `${status.step} 중…` : status.state === 'error' ? '다시 시도' : '배차 점검 시작'}
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
            {err instanceof ApiRequestError && isMethodRejection(err.body?.code) ? (
              <p>서버가 이 방법을 계산하지 않습니다. 설명용 모드는 B0·B3만 제공합니다. 방법 선택을 바꾼 뒤 다시 요청하세요.</p>
            ) : (
              <p className="muted small">다시 시도하면 같은 요청·같은 멱등키로 보내 중복 등록·중복 실행이 생기지 않습니다.</p>
            )}
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
      {status.state === 'rejected' && v2 && (
        <ConditionRevisionPanel
          client={v2}
          snapshot={status.snapshot}
          rerun={{ ...pick(runFor(attempt, picked).body), beforeRunId: null }}
        />
      )}
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

const pick = (r: RunRequest) => ({ methods: r.methods, time_limit_seconds: r.time_limit_seconds, seed: r.seed })
