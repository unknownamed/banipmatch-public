import { useEffect, useMemo, useRef, useState } from 'react'
import s07 from '../fixtures/demo-02-missing-ready.synthetic.json'
import s08 from '../fixtures/demo-02-unconfirmed.synthetic.json'
import s02 from '../fixtures/demo-02-evening.synthetic.json'
import s09 from '../fixtures/demo-02-minor-earlier.synthetic.json'
import s10 from '../fixtures/demo-02-later.synthetic.json'
import runRequestJson from '@examples/02_run_request.json'
import type { ApiClient, RunRequest } from '../api/client'
import { ApiRequestError } from '../api/client'
import type { Snapshot } from '../api/types'
import type { V2Client } from '../api/v2'
import { shiftSnapshot } from '../lib/shift'
import { readableDetail } from '../lib/labels'
import { kstTime } from '../lib/time'
import { ConditionRevisionPanel } from './RevisionPanels'
import { buildRows } from '../lib/compare'
import { ALL_METHODS, isMethodRejection, newAttempt, runFor, type MethodId, type StartAttempt } from '../lib/startRun'
import { ComparisonSection, NOT_COMPUTED } from './ComparisonSection'
import { ChangeEvidence, Header } from './Panels'
import { withQueueRetry } from '../lib/queueRetry'
import { NowPanel } from './NowPanel'
import { FleetToday } from './FleetToday'
import { DispatchMap } from './DispatchMap'
import { Icon, type IconName } from './Icon'

// 홈은 담당자가 받은 변경을 처리하는 알림함이다(물류 관제 화면의 '조치가 필요한 예외 목록' 구성).
// 시연용 예제를 실제로 받을 수 있는 알림 종류로 보여 준다: 확정 공지(큰 영향·작은 영향·영향 없음) / 확정 전 공지 / 입력 누락.
type Tone = 'danger' | 'caution' | 'neutral'
const FILTERS: ['all' | Tone, string][] = [['all', '전체'], ['danger', '조치 필요'], ['caution', '확인 대기'], ['neutral', '영향 없음']]
const EXAMPLES = [
  { id: '02', group: 'todo', icon: 'warning', tone: 'danger', chip: '조치 필요', title: 'HJNC BHMN-2026-0045 반입 마감 2시간 30분 앞당김', meta: '모선 BM 하모니호, 터미널 확정 공지', go: '영향 확인하고 조정안 보기', stats: ['트럭 8대', '컨테이너 20개', '마감 넘김 예상 4개'], what: '원래 배차대로 가면 컨테이너 4개가 새 마감을 넘깁니다. 그중 1개는 상차 준비가 늦어 어떤 차량으로도 맞추기 어렵습니다.', snapshot: s02 },
  { id: '09', group: 'todo', icon: 'warning', tone: 'danger', chip: '조치 필요', title: 'PNIT BE221E 반입 마감 1시간 30분 앞당김', meta: '모선 BM 오션호, 터미널 확정 공지', go: '영향 확인하고 조정안 보기', stats: ['트럭 8대', '컨테이너 20개', '마감 넘김 예상 1개'], what: '원래 배차대로 가면 새벽식품(주) 컨테이너 1개가 새 마감을 넘깁니다. 차량 몇 대만 바꾸면 맞출 수 있는지 확인하세요.', snapshot: s09 },
  { id: '08', group: 'todo', icon: 'bell', tone: 'caution', chip: '확정 대기', title: 'HJNC BORT-2026-0112 반입 마감 1시간 앞당김 예정', meta: '모선 BM 오리엔트호, 터미널 공지 접수(확정 전)', go: '공지 내용과 지금 배차 보기', stats: ['트럭 8대', '컨테이너 20개'], what: '공지가 확정되기 전에는 배차를 바꾸지 않습니다. 열면 공지 내용과 지금 배차를 확인할 수 있습니다.', snapshot: s08 },
  { id: '07', group: 'todo', icon: 'edit', tone: 'caution', chip: '입력 확인', title: 'BNJU 100210 2 상차 준비 시각 미입력', meta: '다온물산(주), 사상 공단 상차지, BORT-2026-0112', go: '비어 있는 값 확인하기', stats: ['트럭 8대', '컨테이너 20개'], what: '준비 시각이 비어 있으면 계산할 수 없습니다. 화주에게 확인한 시각을 넣으면 바로 다시 계산합니다.', snapshot: s07 },
  { id: '10', group: 'todo', icon: 'clock', tone: 'neutral', chip: '영향 없음', title: 'HJNC BPNR-2026-0007 반입 마감 1시간 늦춰짐', meta: '모선 BM 파이오니어호 입항 지연, 터미널 확정 공지', go: '영향 확인하기', stats: ['트럭 8대', '컨테이너 20개', '마감 넘김 예상 0개'], what: '마감이 늦춰져 여유만 늘었습니다. 원래 배차 그대로 가도 되는지 확인만 하면 됩니다.', snapshot: s10 },
] as const satisfies readonly { id: string; group: 'todo'; icon: IconName; tone: Tone; chip: string; title: string; meta: string; go: string; stats: readonly string[]; what: string; snapshot: unknown }[]

const AUTOSTART = 'banipmatch.autostart'

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
  const [filter, setFilter] = useState<'all' | Tone>('all')
  const [query, setQuery] = useState('')
  // 홈 지도와 아래 차량 표는 같은 차량을 함께 고른다.
  const [homePick, setHomePick] = useState<string | null>(null)
  // 예제마다 한 시도를 유지한다. 실패 후 "다시 시도"는 같은 본문·같은 멱등키. 새 시도는 새로고침.
  const [attempts] = useState(() => new Map<string, StartAttempt>())
  const [status, setStatus] = useState<Status>({ state: 'idle' })
  // 같은 입력·조건으로 B0~B3를 모두 계산해 비교한다(B0는 비교 기준). 담당자가 방법을 고르지 않는다.
  const picked: ReadonlySet<MethodId> = new Set(ALL_METHODS)
  const v2 = 'defaultExample' in client ? (client as V2Client) : null
  const example = EXAMPLES.find((e) => e.id === exampleId)!
  const q = query.trim().toLowerCase().replace(/\s/g, '')
  const shown = EXAMPLES.filter((e) => (filter === 'all' || e.tone === filter) && (!q || `${e.title}${e.meta}${e.what}`.toLowerCase().replace(/\s/g, '').includes(q)))
  // 홈의 '오늘 저녁 배차 현황'은 예제 02의 현재 배차표를 지금 시각으로 옮겨 보여 준다(모의).
  const tonight = useMemo(() => shiftSnapshot(s02 as unknown as Snapshot, new Date()), [])
  // 07·08도 같은 규칙으로 지금 시각에 옮긴다(만료가 아니라 원래 의도한 입력 누락·미확인 변경으로 막히게).
  const source = !v2 ? (example.snapshot as unknown as Snapshot) : shiftSnapshot(example.snapshot as unknown as Snapshot, new Date())
  if (source && !attempts.has(exampleId)) attempts.set(exampleId, newAttempt(source, runRequestJson as unknown as RunRequest))
  const attempt = attempts.get(exampleId)

  // 기록을 비운 뒤 다시 열렸으면 고르던 변경을 바로 이어서 계산한다(한 번만).
  const startRef = useRef<() => void>(() => {})
  // 표시는 읽기만 하고(개발 모드의 두 번 실행에도 남도록), 실제로 이어서 시작할 때 지운다.
  const [resume, setResume] = useState<string | null>(() => {
    try { return sessionStorage.getItem(AUTOSTART) } catch { return null }
  })
  useEffect(() => {
    if (!resume) return
    if (exampleId !== resume) { if (EXAMPLES.some((e) => e.id === resume)) setExampleId(resume as typeof exampleId); else setResume(null); return }
    if (attempt && status.state === 'idle') {
      try { sessionStorage.removeItem(AUTOSTART) } catch { /* 없음 */ }
      setResume(null)
      startRef.current()
    }
  }, [resume, exampleId, attempt, status.state])

  if (!attempt)
    return (
      <main>
        <p className="card" role="status">변경 내용을 불러오는 중…</p>
      </main>
    )

  startRef.current = () => { void start() }
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
        // 막힌 이유 바로 아래에 공지 내용·지금 배차가 이어지도록 그 자리로 옮겨 준다.
        window.setTimeout(() => document.querySelector('.rejected-input')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 300)
      } else if (v2 && error instanceof ApiRequestError && ['SCENARIO_LIMIT', 'RUN_LIMIT'].includes(error.body?.code ?? '')) {
        // 이 브라우저의 보관 기록이 가득 찼다. 지난 기록을 다시 여는 화면은 없으므로 비우고 같은 변경을 바로 다시 계산한다.
        try { sessionStorage.setItem(AUTOSTART, exampleId) } catch { /* 저장 못 하면 버튼으로 다시 시작 */ }
        await v2.reset().catch(() => {})
        location.href = '?'
      } else setStatus({ state: 'error', step, error })
    }
  }

  const err = status.state === 'error' ? status.error : null
  return (
    <main>
      <header className="page-head">
        <div>
          <h1>받은 변경</h1>
        </div>
      </header>
      <div className="start-grid">
      <div className="start-left">
      <section className="card start-main inbox-card">
        <div className="toolbar">
          <div className="seg" role="group" aria-label="변경 종류">
            {FILTERS.map(([id, label]) => (
              <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}>
                {label}<span className="n">{EXAMPLES.filter((e) => id === 'all' || e.tone === id).length}</span>
              </button>
            ))}
          </div>
          <label className="search">
            <Icon name="search" size={15} />
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="항차·컨테이너 번호·화주 검색" aria-label="받은 변경 검색" />
          </label>
        </div>
        <div role="radiogroup" aria-label="처리할 변경 선택" className="inbox">
          {shown.length === 0 && <p className="ib-empty">조건에 맞는 변경이 없습니다.</p>}
          {shown.map((e) => {
            const on = exampleId === e.id
            return (
              <div key={e.id} className={`ib-item${on ? ' on' : ''}`}>
                <button
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
                  <span className={`ib-ic ${e.tone}`}><Icon name={e.icon} size={16} /></span>
                  <span className="ib-main">
                    <span className="ib-title"><b>{e.title}</b></span>
                    <span className="ib-meta"><span className={`st ${e.tone === 'danger' ? 'bad' : e.tone === 'caution' ? 'warn' : 'ok'}`}>{e.chip}</span><span>{e.meta}</span></span>
                  </span>
                  <span className="ib-when">{receivedAgo(e.snapshot as unknown as Snapshot)}</span>
                </button>
                {on && (
                  <div className="ib-detail">
                    <p className="ib-what">{e.what}</p>
                    <div className="ib-facts">
                      {source && <Countdown snapshot={source} />}
                      <span>{e.stats.join(', ')}</span>
                    </div>
                    {status.state !== 'rejected' && (
                      <button type="button" className="ib-go" disabled={status.state === 'sending'} onClick={start}>
                        {status.state === 'sending' ? `${status.step} 중…` : status.state === 'error' ? '다시 시도' : e.go}
                        <Icon name="arrow" size={15} />
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        {err !== null && (
          <div className="warn" role="alert">
            {err instanceof ApiRequestError && err.body?.code === 'SCENARIO_LIMIT' ? (
              <>
                <p><b>이 브라우저에 쌓인 점검 기록이 많아 새 점검을 저장할 수 없습니다.</b></p>
                <button type="button" className="secondary" onClick={async () => { await v2?.reset(); location.href = '?' }}>기록 비우고 새로 시작</button>
              </>
            ) : (
              <>
                <p>
                  <b>계산을 시작하지 못했습니다.</b>{' '}
                  {err instanceof ApiRequestError && err.body ? err.message : '서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.'}
                </p>
                <p className="small">다시 시도해도 같은 내용이 두 번 등록되지 않습니다.</p>
              </>
            )}
          </div>
        )}
        {status.state === 'rejected' && status.error.body!.code === 'WINDOW_UNCONFIRMED' && (
          <div className="note-box" role="status">
            <p><b>확정 전 공지라 배차를 바꾸지 않았습니다.</b></p>
            <p>{unconfirmedPreview(status.snapshot)}</p>
            <p className="small">터미널이 확정하면 새 변경으로 다시 받습니다.</p>
          </div>
        )}
        {status.state === 'rejected' && status.error.body!.code !== 'WINDOW_UNCONFIRMED' && (
          <div className="warn" role="alert">
            <p><b>비어 있거나 맞지 않는 값이 있어 계산하지 못했습니다.</b></p>
            <ul className="reject-list">
              {status.error.body!.details?.map((d, k) => {
                const r = readableDetail(d.path, d.reason, status.snapshot)
                return <li key={`${d.path}:${k}`}><b>{r.what}</b>: {r.why}</li>
              })}
            </ul>
            <p className="small">화주나 기사에게 확인한 값을 아래 ‘조건 보완’에 넣고 다시 계산하세요.</p>
          </div>
        )}
      </section>
      <NowPanel />
      </div>
      {/* 관제 화면처럼 첫 화면 오른쪽에 오늘 저녁 차량 지도를 크게 둔다(현재 배차표 기준 위치) */}
      <div className="card home-map">
        <DispatchMap snapshot={tonight} base={undefined} cand={undefined} selectedJob={null} onSelectJob={() => {}} compact pickedVehicleId={homePick} onPickVehicle={setHomePick} />
      </div>
      </div>
      {status.state !== 'rejected' && <FleetToday snapshot={tonight} picked={homePick} onPick={setHomePick} />}
      {status.state === 'rejected' && <RejectedInput snapshot={status.snapshot} reason={status.error.message} />}
      {status.state === 'rejected' && v2 && status.error.body!.code !== 'WINDOW_UNCONFIRMED' && (
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
function RejectedInput({ snapshot }: { snapshot: Snapshot; reason?: string }) {
  return (
    <>
      <span className="rejected-input" aria-hidden="true" />
      <Header s={snapshot} />
      <ChangeEvidence s={snapshot} />
      <ComparisonSection
        snapshot={snapshot}
        results={{ state: 'error', message: `${NOT_COMPUTED} 지금 배차 일정입니다.` }}
        base={undefined}
        cand={undefined}
        candidates={[]}
        rows={buildRows(snapshot, undefined, undefined)}
        onPick={() => {}}
        unchanged
      />
    </>
  )
}

/** 확정 전 공지대로 바뀌면 지금 배차(원안)로 몇 개가 늦는지 미리 센다. 배차는 바꾸지 않는다. */
function unconfirmedPreview(s: Snapshot): string {
  const w = s.windows.find((x) => x.window_id === s.change.new_window_id)
  if (!w?.closes_at) return '공지된 새 마감을 확인하지 못했습니다.'
  const jobs = new Set(s.jobs.filter((j) => j.voyage_id === s.change.voyage_id && j.terminal_id === s.change.terminal_id).map((j) => j.job_id))
  const mine = s.baseline_assignments.filter((a) => jobs.has(a.job_id))
  const late = mine.filter((a) => Date.parse(a.gate_arrival_at) + s.policy.buffer_minutes * 60_000 > Date.parse(w.closes_at!)).length
  return late === 0
    ? `공지대로 확정돼도 지금 배차로 이 항차 컨테이너 ${mine.length}개 모두 마감 안에 들어갑니다.`
    : `공지대로 확정되면 지금 배차로 이 항차 컨테이너 ${mine.length}개 중 ${late}개가 마감을 넘깁니다. 확정되면 바로 조정안을 계산하세요.`
}

const pick = (r: RunRequest) => ({ methods: r.methods, time_limit_seconds: r.time_limit_seconds, seed: r.seed })

/** 공지를 받은 시각을 '방금 / N분 전'으로(예제는 지금 시각 기준으로 옮겨 쓴다). */
function receivedAgo(s: Snapshot) {
  const t = s.change.confirmed_at ?? s.change.evidence.received_at
  // 예제의 기준시각(10분 경계)이 아니라 실제 지금 기준으로 센다.
  const min = t ? Math.round((Date.now() - (Date.parse(t) - Date.parse(s.as_of) + Math.floor(Date.now() / 600000) * 600000)) / 60000) : null
  return min === null ? '' : min <= 1 ? '방금' : `${min}분 전`
}

/** 선택한 변경의 (새) 반입 마감까지 남은 시간. 1초마다 줄어든다. */
function Countdown({ snapshot }: { snapshot: Snapshot }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const w = snapshot.windows.find((x) => x.window_id === snapshot.change.new_window_id)
  if (!w?.closes_at) return null
  const left = Math.max(0, Math.floor((Date.parse(w.closes_at) - now) / 1000))
  const hh = Math.floor(left / 3600), mm = Math.floor((left % 3600) / 60), ss = left % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  const confirmed = snapshot.change.verification === 'confirmed'
  return (
    <span className="countdown">
      {confirmed ? '새 반입 마감' : '공지대로라면 새 마감'} <b>{kstTime(w.closes_at)}</b>까지 <b className="cd-num">{hh}:{pad(mm)}:{pad(ss)}</b>
    </span>
  )
}
