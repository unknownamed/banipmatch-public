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
import { withQueueRetry } from '../lib/queueRetry'
import { NowPanel } from './NowPanel'
import { Icon, type IconName } from './Icon'

// 홈은 담당자가 받은 변경을 처리하는 알림함이다(물류 관제 화면의 '조치가 필요한 예외 목록' 구성).
// 시연용 예제를 실제로 받을 수 있는 알림 종류로 보여 준다: 확정 공지 / 확정 전 공지 / 입력 누락 / 연습.
type Tone = 'danger' | 'caution' | 'neutral'
const EXAMPLES = [
  { id: '02', group: 'todo', icon: 'warning', tone: 'danger', chip: '확정 · 조치 필요', title: 'HJNC · BH045E 반입 마감 2시간 30분 앞당김', meta: '모선 BM 하모니호 · 터미널 공지 확정', stats: ['트럭 8대', '컨테이너 20개', '마감 넘김 예상 4개'], what: '원래 배차대로 가면 컨테이너 4개가 새 마감을 넘깁니다. 같은 저녁 PNIT 반입 작업은 영향이 없습니다.', snapshot: s02 },
  { id: '08', group: 'todo', icon: 'bell', tone: 'caution', chip: '확정 대기', title: 'HJNC · 반입 마감 변경 공지(확정 전)', meta: '터미널 공지 접수 · 아직 확정되지 않음', stats: ['트럭 2대', '작업 4건'], what: '확정되기 전에는 배차를 바꾸지 않습니다. 열어 보면 계산이 막히는 이유와 원래 배차를 확인할 수 있습니다.', snapshot: s08 },
  { id: '07', group: 'todo', icon: 'edit', tone: 'caution', chip: '입력 확인', title: '상차 준비 시각이 빠진 작업', meta: '운송 계획 입력 누락 · 반입 마감 변경 확정', stats: ['트럭 2대', '작업 4건'], what: '준비 시각이 비어 있으면 계산할 수 없습니다. 화주에게 확인한 시각을 넣어 다시 계산합니다.', snapshot: s07 },
  { id: '01', group: 'practice', icon: 'box', tone: 'neutral', chip: '연습', title: '작은 배차로 흐름 익히기', meta: '트럭 2대 · 작업 4건 · 반입 마감 1시간 30분 앞당김', stats: ['트럭 2대', '작업 4건'], what: '처음 쓰는 담당자가 점검 → 비교 → 확정 → 기사 전달 흐름을 빠르게 익히는 예제입니다.', snapshot: s01 },
] as const satisfies readonly { id: string; group: 'todo' | 'practice'; icon: IconName; tone: Tone; chip: string; title: string; meta: string; stats: readonly string[]; what: string; snapshot: unknown }[]
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
      const run = await withQueueRetry(() => client.createRun!(body, key), () => setStatus({ state: 'sending', step: '다른 사용자 계산을 기다리는' }))
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
        <h1>받은 변경</h1>
        <p className="start-lead">반입 마감 변경을 골라 남은 배차에 주는 영향을 확인하고, 바꿀 차량만 기사에게 전달합니다.</p>
        <ol className="start-steps">
          <li className="on"><b>1</b> 변경 선택</li>
          <li><b>2</b> 영향 확인 · 조정안 비교</li>
          <li><b>3</b> 확정 · 기사 전달</li>
        </ol>
      </section>
      <div className="start-grid">
      <section className="card start-main">
        <div role="radiogroup" aria-label="처리할 변경 선택" className="inbox">
          {(['todo', 'practice'] as const).map((g) => (
            <div key={g} className="inbox-group">
              <h2 className="inbox-head">
                {g === 'todo' ? '처리할 변경' : '연습용'}
                <span className="inbox-count">{EXAMPLES.filter((e) => e.group === g).length}</span>
              </h2>
              {EXAMPLES.filter((e) => e.group === g).map((e) => {
                const on = exampleId === e.id
                return (
                  <button
                    key={e.id}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    className={`inbox-row${on ? ' on' : ''}`}
                    disabled={status.state === 'sending'}
                    onClick={() => {
                      setExampleId(e.id)
                      setStatus({ state: 'idle' })
                    }}
                  >
                    <span className={`ib-ic ${e.tone}`}><Icon name={e.icon} size={18} /></span>
                    <span className="ib-main">
                      <span className="ib-title"><b>{e.title}</b><span className={`ib-chip ${e.tone}`}>{e.chip}</span></span>
                      <span className="ib-meta">{e.meta}</span>
                      {on && <span className="ib-what">{e.what}</span>}
                      {on && <span className="sc-stats">{e.stats.map((t) => <span key={t}>{t}</span>)}</span>}
                    </span>
                    <span className="ib-radio" aria-hidden="true" />
                  </button>
                )
              })}
            </div>
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
            {status.state === 'sending' ? `${status.step} 중…` : status.state === 'error' ? '다시 시도' : '선택한 변경 영향 확인'}
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
              <p className="muted small">다시 시도해도 중복으로 등록되지 않습니다.</p>
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
      <NowPanel />
      </div>
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
