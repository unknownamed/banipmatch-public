import { useEffect, useRef, useState } from 'react'
import { ApiRequestError } from '../api/client'
import type { Method, Snapshot } from '../api/types'
import type { V2Client } from '../api/v2'
import { EMPTY_DRAFT, draftProblems, freezeLabel, isBlankDraft, isCompleteInput, listChanges, revisedSnapshot, toKstInput, type Confirmation, type Edits, type VehicleDraft } from '../lib/revision'
import { kstDateTime } from '../lib/time'
import { jobName, vehicleName } from '../lib/labels'
import { withQueueRetry } from '../lib/queueRetry'

const FIELD_LABEL = { ready_at: '상차 준비 시각', available_at: '운행 시작', shift_end_at: '근무 종료' } as const

interface RevisionState { scenario_id: string; plan_id: string; base_plan_version: number; revision_id: string; confirmation: Confirmation }

/**
 * R4 조건 보완: 확인한 준비·가용·근무 시각만 바꿔 새 입력으로 저장하고 같은 방법·예산으로 다시 계산한다.
 * 원본 입력과 이전 결과는 서버에 그대로 남는다. 고정 작업·마감·이동시간은 바꿀 수 없다.
 */
/** 재계산 조건. 이전 실행이 있으면 그 방법·예산·seed, 입력 부족으로 계산이 막혔으면 막힌 요청의 값(이전 실행 없음). */
export interface Rerun { methods: Method[]; time_limit_seconds: number; seed: number; beforeRunId: string | null }


const EQUIP_LABEL: Record<string, string> = { DRY20: '20ft', DRY40: '40ft', REEFER20: '20ft 냉동', REEFER40: '40ft 냉동' }
export function ConditionRevisionPanel({ client, snapshot, rerun, focus = [] }: { client: V2Client; snapshot: Snapshot; rerun: Rerun; focus?: readonly string[] }) {
  const [edits, setEdits] = useState<Edits>({})
  const [reason, setReason] = useState('')
  const [confirmation, setConfirmation] = useState<Confirmation>('confirmed_simulation')
  const [draft, setDraft] = useState<VehicleDraft>(EMPTY_DRAFT)
  const [status, setStatus] = useState<{ state: 'idle' } | { state: 'sending'; step: string } | { state: 'error'; step: string; error: unknown }>({ state: 'idle' })
  // 같은 내용으로 다시 시도하면 같은 멱등키를 쓴다. 내용이 바뀌면 새 키.
  const attempt = useRef<{ sig: string; id: string; body: { snapshot: Snapshot; reason: string; confirmation: Confirmation }; revision?: RevisionState } | null>(null)
  const changes = listChanges(snapshot, edits)
  const sending = status.state === 'sending'
  // 입력 중이거나 잘못된 시각이 있으면 그 값만 빼고 보내지 않도록 전체 제출을 막는다.
  const anyInvalid = Object.values(edits).some((v) => v && !isCompleteInput(v))
  // 차량 추가는 선택. 무언가 입력했으면 빠진 값이 없을 때만 보낸다(다른 차량 값으로 채우지 않음).
  const draftOpen = !isBlankDraft(draft)
  const missing = draftOpen ? draftProblems(snapshot, draft) : []
  const added = draftOpen && !missing.length ? [draft] : []
  const setD = (patch: Partial<VehicleDraft>) => {
    setDraft((d) => ({ ...d, ...patch }))
    if (status.state === 'error') setStatus({ state: 'idle' })
  }
  const equipmentOptions = [...new Set([...snapshot.jobs.map((j) => j.equipment_type), ...(snapshot.vehicles ?? []).flatMap((v) => v.equipment_types)])].sort()
  const set = (key: string, value: string) => {
    setEdits((e) => ({ ...e, [key]: value }))
    if (status.state === 'error') setStatus({ state: 'idle' })
  }
  const unset = (key: string) => setEdits((e) => { const n = { ...e }; delete n[key]; return n })
  // '오늘 운행 불가': 고장·기사 사정으로 이 차량을 빼고 다시 계산한다. 근무 종료를 운행 시작(또는 기준 시각)으로 당겨
  // 남은 작업을 맡을 수 없게 한다. 이미 출발한 작업이 있는 차량은 뺄 수 없다(출발 작업은 그대로 둔다).
  const offAt = (v: NonNullable<Snapshot['vehicles']>[number]) => {
    const start = Math.max(Date.parse(snapshot.as_of), v.available_at ? Date.parse(v.available_at) : 0)
    return toKstInput(new Date(Math.ceil(start / 60000) * 60000).toISOString())
  }
  const departedOn = (vehicleId: string) => snapshot.baseline_assignments.some((a) => a.vehicle_id === vehicleId && snapshot.jobs.find((j) => j.job_id === a.job_id)?.frozen)
  const isOff = (vehicleId: string) => {
    const v = snapshot.vehicles?.find((x) => x.vehicle_id === vehicleId)
    return !!v && edits[`vehicle:${vehicleId}:shift_end_at`] === offAt(v)
  }

  async function submit() {
    const sig = JSON.stringify([snapshot, changes, added, reason.trim(), confirmation, rerun])
    let step = '새 입력 저장'
    try {
      setStatus({ state: 'sending', step })
      // 시각까지 첫 요청 그대로 유지한다. 응답 유실 후 재시도에서도 같은 키/본문이어야 한다.
      if (attempt.current?.sig !== sig) attempt.current = {
        sig, id: crypto.randomUUID(),
        body: { snapshot: revisedSnapshot(snapshot, changes, confirmation, new Date(), added), reason: reason.trim(), confirmation },
      }
      const current = attempt.current
      const { id } = current
      current.revision ??= await client.post<RevisionState>(`/v2/scenarios/${encodeURIComponent(snapshot.scenario_id)}/revisions`, current.body, `revision-${id}`)
      const rev = current.revision
      step = '재계산 요청'
      setStatus({ state: 'sending', step })
      // 전후 비교가 공정하도록 이전 실행과 같은 방법·제한시간·seed를 쓴다.
      const next = await withQueueRetry(() => client.createRun!(
        { scenario_id: rev.scenario_id, base_plan_version: rev.base_plan_version, methods: rerun.methods, time_limit_seconds: rerun.time_limit_seconds, seed: rerun.seed },
        `revision-run-${id}`,
      ), () => setStatus({ state: 'sending', step: '다른 사용자 계산을 기다리는' }))
      const q = new URLSearchParams({ scenario: rev.scenario_id, run: next.run_id, revision: rev.revision_id })
      if (rerun.beforeRunId) q.set('before', rerun.beforeRunId)
      location.search = `?${q}`
    } catch (error) {
      setStatus({ state: 'error', step, error })
    }
  }

  const movable = snapshot.jobs.filter((j) => !j.frozen)
  const isFocus = (j: (typeof movable)[number]) => j.ready_at === null || focus.includes(j.job_id) || !!edits[`job:${j.job_id}:ready_at`]
  const jobRow = (j: (typeof movable)[number]) => <div key={j.job_id} className="rev-row"><b>{jobName(j.job_id)}</b>{field(`job:${j.job_id}:ready_at`, j.ready_at, FIELD_LABEL.ready_at)}</div>
  const frozen = snapshot.jobs.filter((j) => j.frozen)
  // 브라우저 기본 시각 입력은 기기 설정에 따라 오전/오후로 보인다. 화면 표기와 같은 24시간제로 받기 위해 날짜+시각(HH:MM)으로 나눈다.
  // 비어 있던 값은 날짜 칸도 비어 있다. 시각만 넣으면 기준 시각의 날짜(오늘)로 채운다.
  const today = toKstInput(snapshot.as_of).slice(0, 10)
  const timeInput = (value: string, onChange: (v: string) => void, label: string, hint: string) => {
    const [date, time = ''] = value.split('T')
    const invalid = !!value && !isCompleteInput(value)
    // 어느 칸이 문제인지 알려 준다: 시각 형식이 틀렸는지, 날짜가 빠졌는지.
    const timeBad = !!time && !/^([01]\d|2[0-3]):[0-5]\d$/.test(time)
    const problem = !invalid ? null : timeBad || !time ? '시각은 00:00~23:59 형식으로 입력하세요.' : !date ? '날짜를 고르세요.' : '날짜와 시각을 확인하세요.'
    return (
      <div className="rev-field" role="group" aria-label={`${label} (KST)`}>
        <span className="small muted">{label}<span className="rev-now">{hint}</span></span>
        <span className="rev-inputs">
          <input type="date" aria-label="날짜" value={date} disabled={sending} aria-invalid={invalid && !date} onChange={(e) => onChange(`${e.target.value}T${time}`)} />
          <input
            type="text" inputMode="numeric" aria-label="시각(24시간제)" placeholder="13:40" maxLength={5} size={5}
            value={time} aria-invalid={invalid && (timeBad || !time)} disabled={sending}
            onChange={(e) => onChange(`${date || today}T${e.target.value}`)}
          />
        </span>
        {problem && <span className="small warn">{problem}</span>}
      </div>
    )
  }
  const field = (key: string, current: string | null, label: string) =>
    timeInput(edits[key] ?? toKstInput(current), (v) => set(key, v), label, current ? kstDateTime(current) : '미확인')

  return (
    <section className="card revision" aria-labelledby="rev-title">
      <h2 id="rev-title">조건 보완</h2>

      <fieldset disabled={sending}>
        <legend>상차 준비 시각</legend>
        {/* 확인이 필요한 작업(미배정·위반·준비 시각 없음)을 먼저 펼치고, 나머지는 접어 둔다 */}
        {movable.filter(isFocus).map(jobRow)}
        {movable.some((j) => !isFocus(j)) && (
          <details className="rev-more">
            <summary>{movable.some(isFocus) ? '다른 작업' : '작업'} {movable.filter((j) => !isFocus(j)).length + frozen.length}건</summary>
            {movable.filter((j) => !isFocus(j)).map(jobRow)}
            {frozen.map((j) => <div key={j.job_id} className="rev-row muted"><b>{jobName(j.job_id)}</b><span className="small">{freezeLabel(j.freeze_reason)}, 수정할 수 없음</span></div>)}
          </details>
        )}
      </fieldset>

      {!!snapshot.vehicles?.length && (
        <fieldset disabled={sending}>
          <legend>차량 근무 시간</legend>
          <details className="rev-more" open={snapshot.vehicles.some((v) => isOff(v.vehicle_id)) || undefined}>
          <summary>차량 {snapshot.vehicles.length}대, 근무 시간 또는 운행 불가</summary>
          {snapshot.vehicles.map((v) => {
            const key = `vehicle:${v.vehicle_id}:shift_end_at`
            const off = isOff(v.vehicle_id)
            const departed = departedOn(v.vehicle_id)
            return (
              <div key={v.vehicle_id} className={`rev-row${off ? ' rev-off' : ''}`}>
                <b>{vehicleName(v.vehicle_id)}</b>
                {off ? <span className="small">남은 작업을 다른 차량으로 다시 배정합니다.</span> : (
                  <>
                    {field(`vehicle:${v.vehicle_id}:available_at`, v.available_at, FIELD_LABEL.available_at)}
                    {field(key, v.shift_end_at, FIELD_LABEL.shift_end_at)}
                  </>
                )}
                {departed
                  ? <span className="small muted">출발한 작업이 있어 뺄 수 없음</span>
                  : <button type="button" className="chip-toggle" aria-pressed={off} onClick={() => {
                      if (off) unset(key)
                      else { set(key, offAt(v)); unset(`vehicle:${v.vehicle_id}:available_at`) }
                    }}>오늘 운행 불가</button>}
              </div>
            )
          })}
          </details>
        </fieldset>
      )}

      <fieldset disabled={sending} className="rev-add">
        <legend>차량 추가</legend>
        <details className="rev-more" open={draftOpen}>
        <summary>외부에서 확보한 차량 넣기</summary>
        <div className="rev-row">
          <label className="rev-field"><span className="small muted">차량 번호</span><input value={draft.plate ?? ''} maxLength={20} placeholder="부산 95바 3021" onChange={(e) => setD({ plate: e.target.value })} /></label>
          <label className="rev-field">
            <span className="small muted">시작 위치</span>
            <select value={draft.start_location_id} onChange={(e) => setD({ start_location_id: e.target.value })}>
              <option value="">선택</option>
              {snapshot.locations?.map((l) => <option key={l.location_id} value={l.location_id}>{l.name.replace('(모의)', '').trim()}</option>)}
            </select>
          </label>
          <label className="rev-field"><span className="small muted">최대 적재 중량(kg)</span><input inputMode="numeric" value={draft.capacity_kg} size={8} onChange={(e) => setD({ capacity_kg: e.target.value })} /></label>
        </div>
        <div className="rev-row" role="group" aria-label="실을 수 있는 컨테이너">
          <span className="small muted">실을 수 있는 컨테이너</span>
          {equipmentOptions.map((t) => {
            const on = draft.equipment_types.includes(t)
            return (
              <button key={t} type="button" className="chip-toggle" aria-pressed={on} onClick={() => setD({ equipment_types: on ? draft.equipment_types.filter((x) => x !== t) : [...draft.equipment_types, t] })}>
                {EQUIP_LABEL[t] ?? t}
              </button>
            )
          })}
        </div>
        <div className="rev-row">
          {timeInput(draft.available_at, (v) => setD({ available_at: v }), '운행 시작', '')}
          {timeInput(draft.shift_end_at, (v) => setD({ shift_end_at: v }), '근무 종료', '')}
        </div>
        {draftOpen && missing.length > 0 && <p className="small warn">빠진 값: {missing.join(', ')}</p>}
        {draftOpen && <button type="button" className="secondary" onClick={() => setDraft(EMPTY_DRAFT)}>차량 추가 취소</button>}
        </details>
      </fieldset>

      <div className="rev-confirm">
        <span className="small muted">값 확인</span>
        <div className="seg" role="group" aria-label="값 확인">
          <button type="button" disabled={sending} aria-pressed={confirmation === 'confirmed_simulation'} onClick={() => setConfirmation('confirmed_simulation')}>확인한 값</button>
          <button type="button" disabled={sending} aria-pressed={confirmation === 'assumed'} onClick={() => setConfirmation('assumed')}>확인 전(미리 계산)</button>
        </div>
        {confirmation === 'assumed' && <span className="small warn">결과만 미리 보고 확정은 할 수 없습니다.</span>}
      </div>

      <label className="rev-reason">
        변경 이유
        <textarea value={reason} maxLength={1000} rows={2} disabled={sending} placeholder="누구에게 무엇을 확인했는지 적어 주세요" onChange={(e) => setReason(e.target.value)} />
      </label>

      {(changes.length > 0 || added.length > 0) && (
        <ul className="rev-diff" aria-label="바뀌는 조건">
          {changes.map((c) => (
            c.field === 'shift_end_at' && isOff(c.id)
              ? <li key={c.key}>{vehicleName(c.id)}: <b>오늘 운행 불가</b></li>
              : <li key={c.key}>{c.field === 'ready_at' ? jobName(c.id) : vehicleName(c.id)} {FIELD_LABEL[c.field]}: {c.before ? kstDateTime(c.before) : '미확인'} → <b>{kstDateTime(c.after)}</b></li>
          ))}
          {added.map((d) => (
            <li key={d.vehicle_id || d.plate}>차량 추가: <b>{d.plate?.trim() || d.vehicle_id.trim()}</b>, {snapshot.locations?.find((l) => l.location_id === d.start_location_id)?.name.replace('(모의)', '').trim() ?? d.start_location_id}에서 {d.available_at.slice(11)}부터 {d.shift_end_at.slice(11)}까지, {d.equipment_types.map((t) => EQUIP_LABEL[t] ?? t).join('/')}</li>
          ))}
        </ul>
      )}

      <button type="button" disabled={sending || anyInvalid || missing.length > 0 || (!changes.length && !added.length) || !reason.trim()} onClick={submit}>
        {sending ? `${status.step} 중…` : status.state === 'error' ? '다시 시도' : '다시 계산'}
      </button>
      {!changes.length && !added.length && <p className="small muted">바꿀 값을 입력하세요.</p>}
      {status.state === 'error' && <ErrorNote step={status.step} error={status.error} />}
    </section>
  )
}

/** 승인된 배정을 새 원안으로 삼는다. 응답 유실 시 첫 next-input/등록 요청을 그대로 재사용한다. */
export function NextPlanPanel({ client, planId, rerun }: { client: V2Client; planId: string; rerun: Rerun }) {
  const attempt = useRef<{ id: string; snapshot?: Snapshot; registered?: boolean } | null>(null)
  const [status, setStatus] = useState<{ busy: boolean; step: string; error?: unknown }>({ busy: false, step: '' })
  async function start() {
    attempt.current ??= { id: crypto.randomUUID() }
    const current = attempt.current
    let step = '확정 계획 조회'
    try {
      setStatus({ busy: true, step })
      current.snapshot ??= await client.get<Snapshot>(`/v2/plans/${encodeURIComponent(planId)}/next-input`)
      step = '새 원안 등록'
      setStatus({ busy: true, step })
      if (!current.registered) {
        await client.registerScenario!(current.snapshot, `next-input-${current.id}`)
        current.registered = true
      }
      step = '새 기준 계산'
      setStatus({ busy: true, step })
      const snap = current.snapshot!
      const next = await withQueueRetry(() => client.createRun!({ scenario_id: snap.scenario_id, base_plan_version: snap.base_plan_version,
        methods: rerun.methods, time_limit_seconds: rerun.time_limit_seconds, seed: rerun.seed }, `next-run-${current.id}`), () => setStatus({ busy: true, step: '다른 사용자 계산을 기다리는' }))
      location.search = `?${new URLSearchParams({ scenario: next.scenario_id, run: next.run_id })}`
    } catch (error) { setStatus({ busy: false, step, error }) }
  }
  return <section className="card">
    <h2>이어서 점검</h2>
    <p className="small">새로 점검하면 기사에게 보낸 알림은 지난 알림이 됩니다. 기사 응답을 확인한 뒤 시작하세요.</p>

    <button type="button" disabled={status.busy} onClick={start}>{status.busy ? `${status.step} 중…` : status.error ? '다시 시도' : '확정한 배차로 새 점검'}</button>
    {status.error != null && <ErrorNote step={status.step} error={status.error} />}
  </section>
}

function ErrorNote({ step, error }: { step: string; error: unknown }) {
  return (
    <div className="warn" role="alert">
      <p>
        {step} 실패: {error instanceof Error ? error.message : String(error)}
      </p>
      {error instanceof ApiRequestError && error.body?.details?.map((d) => <p key={d.path} className="small"><code>{d.path}</code> {d.reason}</p>)}
    </div>
  )
}

interface Comparison {
  revision: { reason: string; changes: { entity: string; entity_id: string; field: keyof typeof FIELD_LABEL; before: string | null; after: string | null }[]; added_vehicles: { vehicle_id: string; start_location_id: string }[] }
  before: { status: 'computed' | 'input_blocked'; error?: { code: string; message: string } }
  after: { status: string }
  job_transitions: Record<'became_assigned' | 'became_unassigned' | 'remained_unassigned' | 'changed_assignments' | 'fixed_risks_added' | 'fixed_risks_removed' | 'fixed_risks_remaining', string[]> | null
  metric_deltas: Record<string, number> | null
  comparison_limits: string[]
}

const TRANSITIONS = [
  ['became_assigned', '새로 배정됨'],
  ['became_unassigned', '새로 미처리됨'],
  ['remained_unassigned', '계속 미처리'],
  ['changed_assignments', '이전 계산과 차량·출발 시각이 달라진 작업'],
  ['fixed_risks_added', '출발 차량 위험 생김'],
  ['fixed_risks_removed', '출발 차량 위험 없어짐'],
  ['fixed_risks_remaining', '출발 차량 위험 남음'],
] as const

const DELTAS = [
  ['unassigned_count', '미처리'],
  ['movable_violation_count', '마감·조건 위반'],
  ['fixed_risk_count', '출발한 차량 위험'],
  ['changed_job_count', '변경 작업'],
  ['movable_travel_minutes', '이동(분)'],
] as const

/** 조건 보완 전후 비교(대겸 비교 로직의 서버 결과). 개선율로 해석하지 못하는 경우는 서버가 준 한계를 그대로 보여준다. */
export function RevisionComparison({ client, revisionId, beforeRunId, afterRunId, method, snapshot }: { client: V2Client; revisionId: string; beforeRunId: string | null; afterRunId: string; method: string; snapshot?: Snapshot | null }) {
  // 근무 종료를 운행 시작(또는 기준 시각) 이전으로 당긴 차량은 '오늘 운행 불가'로 뺀 차량이다.
  const offVehicle = (id: string, after: string | null) => {
    const v = snapshot?.vehicles?.find((x) => x.vehicle_id === id)
    return !!(v && after && Date.parse(after) <= Math.max(Date.parse(snapshot!.as_of), v.available_at ? Date.parse(v.available_at) : 0))
  }
  const [state, setState] = useState<{ data?: { confirmation: Confirmation; comparison: Comparison }; error?: unknown }>({})
  useEffect(() => {
    let live = true
    setState({})
    // 이전 입력이 부족해 계산되지 않았으면 이전 실행 없이 비교한다(서버가 '이전 계산 없음'으로 표시).
    const q = new URLSearchParams({ after_run_id: afterRunId, method })
    if (beforeRunId) q.set('before_run_id', beforeRunId)
    client.get<{ confirmation: Confirmation; comparison: Comparison }>(`/v2/revisions/${encodeURIComponent(revisionId)}/comparison?${q}`)
      .then((data) => live && setState({ data }), (error) => live && setState({ error }))
    return () => { live = false }
  }, [client, revisionId, beforeRunId, afterRunId, method])

  if (state.error) return <section className="card"><h2>조건 보완 결과</h2><ErrorNote step="비교 조회" error={state.error} /></section>
  if (!state.data) return <section className="card" role="status"><h2>조건 보완 결과</h2><p className="muted">비교 불러오는 중…</p></section>
  const { confirmation, comparison: c } = state.data
  return (
    <section className="card revision-compare" aria-labelledby="revcmp-title">
      <h2 id="revcmp-title">
        조건 보완 결과{' '}
        <span className={`badge ${confirmation === 'assumed' ? 'fixture' : 'lock'}`}>{confirmation === 'assumed' ? '확인 전 값(확정 불가)' : '확인한 값'}</span>
      </h2>
      <p className="small">수정 이유: {c.revision.reason}</p>
      <ul className="rev-diff">
        {c.revision.changes.map((x) => (
          x.field === 'shift_end_at' && offVehicle(x.entity_id, x.after)
            ? <li key={`${x.entity_id}:${x.field}`}>{vehicleName(x.entity_id)}: <b>오늘 운행 불가</b></li>
            : <li key={`${x.entity_id}:${x.field}`}>{x.field.startsWith('vehicle') || x.field === 'available_at' || x.field === 'shift_end_at' ? vehicleName(x.entity_id) : jobName(x.entity_id)} {FIELD_LABEL[x.field] ?? x.field}: {x.before ? kstDateTime(x.before) : '미확인'} → <b>{x.after ? kstDateTime(x.after) : '미확인'}</b></li>
        ))}
        {c.revision.added_vehicles.map((v) => (
          <li key={v.vehicle_id}>차량 추가: <b>{vehicleName(v.vehicle_id)}</b></li>
        ))}
      </ul>
      {c.before.status === 'input_blocked' && (
        <p className="small">이전 결과가 없어 새 결과만 보여 줍니다.</p>
      )}
      {c.job_transitions && (
        <dl className="rev-transitions">
          {TRANSITIONS.filter(([k]) => c.job_transitions![k].length).map(([k, label]) => (
            <div key={k}><dt>{label}</dt><dd>{c.job_transitions![k].map(jobName).join(', ')}</dd></div>
          ))}
        </dl>
      )}
      {c.metric_deltas && (DELTAS.some(([k]) => c.metric_deltas![k]) ? (
        <table className="grid small rev-deltas">
          <caption className="small muted">이전 계산보다</caption>
          <thead><tr>{DELTAS.map(([, l]) => <th key={l} scope="col">{l}</th>)}</tr></thead>
          <tbody><tr>{DELTAS.map(([k]) => <td key={k}>{signed(c.metric_deltas![k])}</td>)}</tr></tbody>
        </table>
      ) : <p className="small">이전 계산과 비교해 미처리·위반·변경 작업 수와 이동 시간이 같습니다.</p>)}
      {/* 두 계산 사이에 기준 시각이 바뀌었으면 결과 차이가 보완 때문만은 아닐 수 있다는 점만 짧게 알린다. */}
      {c.before.status !== 'input_blocked' && c.comparison_limits.some((l) => l.includes('기준시각')) && (
        <p className="small muted">그사이 시간이 지나 결과 차이에는 시간 경과도 섞여 있습니다.</p>
      )}

    </section>
  )
}

const signed = (n: number | undefined) => (n === undefined ? '—' : n > 0 ? `+${n}` : String(n))
