import { useEffect, useRef, useState } from 'react'
import { ApiRequestError } from '../api/client'
import type { Method, Snapshot } from '../api/types'
import type { V2Client } from '../api/v2'
import { EMPTY_DRAFT, draftProblems, freezeLabel, isBlankDraft, isCompleteInput, listChanges, revisedSnapshot, toKstInput, type Confirmation, type Edits, type VehicleDraft } from '../lib/revision'
import { kstDateTime } from '../lib/time'

const FIELD_LABEL = { ready_at: '상차 준비시각', available_at: '차량 가용 시작', shift_end_at: '근무 종료' } as const

interface RevisionState { scenario_id: string; plan_id: string; base_plan_version: number; revision_id: string; confirmation: Confirmation }

/**
 * R4 조건 보완: 확인한 준비·가용·근무 시각만 바꿔 새 입력으로 저장하고 같은 방법·예산으로 다시 계산한다.
 * 원본 입력과 이전 결과는 서버에 그대로 남는다. 고정 작업·마감·이동시간은 바꿀 수 없다.
 */
/** 재계산 조건. 이전 실행이 있으면 그 방법·예산·seed, 입력 부족으로 계산이 막혔으면 막힌 요청의 값(이전 실행 없음). */
export interface Rerun { methods: Method[]; time_limit_seconds: number; seed: number; beforeRunId: string | null }

export function ConditionRevisionPanel({ client, snapshot, rerun }: { client: V2Client; snapshot: Snapshot; rerun: Rerun }) {
  const [edits, setEdits] = useState<Edits>({})
  const [reason, setReason] = useState('')
  const [confirmation, setConfirmation] = useState<Confirmation>('confirmed_simulation')
  const [draft, setDraft] = useState<VehicleDraft>(EMPTY_DRAFT)
  const [status, setStatus] = useState<{ state: 'idle' } | { state: 'sending'; step: string } | { state: 'error'; step: string; error: unknown }>({ state: 'idle' })
  // 같은 내용으로 다시 시도하면 같은 멱등키를 쓴다. 내용이 바뀌면 새 키.
  const attempt = useRef<{ sig: string; id: string } | null>(null)
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

  async function submit() {
    const sig = JSON.stringify([changes, added, reason.trim(), confirmation])
    if (attempt.current?.sig !== sig) attempt.current = { sig, id: crypto.randomUUID() }
    const id = attempt.current.id
    let step = '새 입력 저장'
    try {
      setStatus({ state: 'sending', step })
      const after = revisedSnapshot(snapshot, changes, confirmation, new Date(), added)
      const rev = await client.post<RevisionState>(`/v2/scenarios/${encodeURIComponent(snapshot.scenario_id)}/revisions`, { snapshot: after, reason: reason.trim(), confirmation }, `revision-${id}`)
      step = '재계산 요청'
      setStatus({ state: 'sending', step })
      // 전후 비교가 공정하도록 이전 실행과 같은 방법·제한시간·seed를 쓴다.
      const next = await client.createRun!(
        { scenario_id: rev.scenario_id, base_plan_version: rev.base_plan_version, methods: rerun.methods, time_limit_seconds: rerun.time_limit_seconds, seed: rerun.seed },
        `revision-run-${id}`,
      )
      const q = new URLSearchParams({ scenario: rev.scenario_id, run: next.run_id, revision: rev.revision_id })
      if (rerun.beforeRunId) q.set('before', rerun.beforeRunId)
      location.search = `?${q}`
    } catch (error) {
      setStatus({ state: 'error', step, error })
    }
  }

  const movable = snapshot.jobs.filter((j) => !j.frozen)
  const frozen = snapshot.jobs.filter((j) => j.frozen)
  // 브라우저 기본 시각 입력은 기기 설정에 따라 오전/오후로 보인다. 화면 표기와 같은 24시간제로 받기 위해 날짜+시각(HH:MM)으로 나눈다.
  const timeInput = (value: string, onChange: (v: string) => void, label: string, hint: string) => {
    const [date, time = ''] = value.split('T')
    const invalid = !!value && !isCompleteInput(value)
    return (
      <div className="rev-field" role="group" aria-label={`${label} (KST)`}>
        <span className="small muted">{label} · {hint}</span>
        <span className="rev-inputs">
          <input type="date" aria-label="날짜" value={date} disabled={sending} onChange={(e) => onChange(`${e.target.value}T${time}`)} />
          <input
            type="text" inputMode="numeric" aria-label="시각(24시간제)" placeholder="13:40" maxLength={5} size={5}
            value={time} aria-invalid={invalid} disabled={sending}
            onChange={(e) => onChange(`${date}T${e.target.value}`)}
          />
        </span>
        {invalid && <span className="small warn">시각은 00:00~23:59 형식으로 입력하세요.</span>}
      </div>
    )
  }
  const field = (key: string, current: string | null, label: string) =>
    timeInput(edits[key] ?? toKstInput(current), (v) => set(key, v), label, `현재 ${current ? kstDateTime(current) : '미확인'}`)

  return (
    <section className="card revision" aria-labelledby="rev-title">
      <h2 id="rev-title">조건 보완 · 재계산</h2>
      <p className="muted small">
        담당자가 확인한 상차 준비·차량 가용·근무 시각만 바꿔 <b>새 입력</b>으로 다시 계산합니다. 원래 입력과 이전 결과는 그대로 남습니다.
        고정·출발 작업, 반입 마감, 이동시간은 바꿀 수 없습니다. 실제 차량을 확보하거나 준비를 완료시키는 기능이 아닙니다.
      </p>

      <fieldset disabled={sending}>
        <legend>작업 준비시각</legend>
        {movable.map((j) => <div key={j.job_id} className="rev-row"><b>{j.job_id}</b>{field(`job:${j.job_id}:ready_at`, j.ready_at, FIELD_LABEL.ready_at)}</div>)}
        {frozen.map((j) => <div key={j.job_id} className="rev-row muted"><b>{j.job_id}</b><span className="small">고정 · {freezeLabel(j.freeze_reason)} — 수정 불가</span></div>)}
      </fieldset>

      {!!snapshot.vehicles?.length && (
        <fieldset disabled={sending}>
          <legend>차량 가용 · 근무</legend>
          {snapshot.vehicles.map((v) => (
            <div key={v.vehicle_id} className="rev-row">
              <b>{v.vehicle_id}</b>
              {field(`vehicle:${v.vehicle_id}:available_at`, v.available_at, FIELD_LABEL.available_at)}
              {field(`vehicle:${v.vehicle_id}:shift_end_at`, v.shift_end_at, FIELD_LABEL.shift_end_at)}
            </div>
          ))}
        </fieldset>
      )}

      <fieldset disabled={sending} className="rev-add">
        <legend>차량 추가 (선택)</legend>
        <p className="small muted">
          외부에서 확보가 확인된 차량만 넣으세요. 이 화면은 차량을 구해 주지 않습니다. 모든 값을 직접 입력하며 다른 차량 값으로 채우지 않습니다.
          시작 위치는 이동시간이 이미 있는 기존 위치에서만 고를 수 있습니다.
        </p>
        <div className="rev-row">
          <label className="rev-field"><span className="small muted">차량 ID</span><input value={draft.vehicle_id} maxLength={32} placeholder="예: T3" onChange={(e) => setD({ vehicle_id: e.target.value })} /></label>
          <label className="rev-field">
            <span className="small muted">시작 위치</span>
            <select value={draft.start_location_id} onChange={(e) => setD({ start_location_id: e.target.value })}>
              <option value="">선택</option>
              {snapshot.locations?.map((l) => <option key={l.location_id} value={l.location_id}>{l.location_id} · {l.name}</option>)}
            </select>
          </label>
          <label className="rev-field"><span className="small muted">적재 가능 중량(kg)</span><input inputMode="numeric" value={draft.capacity_kg} size={8} onChange={(e) => setD({ capacity_kg: e.target.value })} /></label>
        </div>
        <div className="rev-row">
          <span className="small muted">장비</span>
          {equipmentOptions.map((t) => (
            <label key={t} className="small">
              <input type="checkbox" checked={draft.equipment_types.includes(t)} onChange={(e) => setD({ equipment_types: e.target.checked ? [...draft.equipment_types, t] : draft.equipment_types.filter((x) => x !== t) })} /> {t}
            </label>
          ))}
        </div>
        <div className="rev-row">
          {timeInput(draft.available_at, (v) => setD({ available_at: v }), '가용 시작', '필수')}
          {timeInput(draft.shift_end_at, (v) => setD({ shift_end_at: v }), '근무 종료', '필수')}
        </div>
        {draftOpen && missing.length > 0 && <p className="small warn">추가 차량에 빠진 값: {missing.join(', ')}. 모두 채워야 함께 보냅니다.</p>}
        {draftOpen && <button type="button" className="secondary" onClick={() => setDraft(EMPTY_DRAFT)}>차량 추가 취소</button>}
      </fieldset>

      <fieldset disabled={sending}>
        <legend>조건 구분</legend>
        <label className="rev-choice">
          <input type="radio" name="confirmation" checked={confirmation === 'confirmed_simulation'} onChange={() => setConfirmation('confirmed_simulation')} />
          확인된 조건 <span className="small muted">— 모의 배차에서 담당자가 확인한 값. 실제 현장 확인과는 다릅니다.</span>
        </label>
        <label className="rev-choice">
          <input type="radio" name="confirmation" checked={confirmation === 'assumed'} onChange={() => setConfirmation('assumed')} />
          가정 시험 <span className="small muted">— &lsquo;이렇게 되면?&rsquo; 비교만. 승인·전달할 수 없습니다.</span>
        </label>
      </fieldset>

      <label className="rev-reason">
        수정 이유 (필수)
        <textarea value={reason} maxLength={1000} rows={2} disabled={sending} placeholder="예: 화주에게 J3 상차 준비 13:40 완료 확인" onChange={(e) => setReason(e.target.value)} />
      </label>

      {(changes.length > 0 || added.length > 0) && (
        <ul className="rev-diff" aria-label="바뀌는 조건">
          {changes.map((c) => (
            <li key={c.key}>{c.id} {FIELD_LABEL[c.field]}: {c.before ? kstDateTime(c.before) : '미확인'} → <b>{kstDateTime(c.after)}</b></li>
          ))}
          {added.map((d) => (
            <li key={d.vehicle_id}>차량 추가: <b>{d.vehicle_id.trim()}</b> · {d.start_location_id} 출발 · {d.capacity_kg}kg · {d.equipment_types.join('/')} · 가용 {d.available_at.replace('T', ' ')} ~ 근무 종료 {d.shift_end_at.replace('T', ' ')} KST</li>
          ))}
        </ul>
      )}

      <button type="button" disabled={sending || anyInvalid || missing.length > 0 || (!changes.length && !added.length) || !reason.trim()} onClick={submit}>
        {sending ? `${status.step} 중…` : status.state === 'error' ? '다시 시도' : '새 입력으로 재계산'}
      </button>
      {!changes.length && !added.length && <p className="small muted">바꿀 값을 하나 이상 입력하거나 차량을 추가하세요.</p>}
      {status.state === 'error' && <ErrorNote step={status.step} error={status.error} />}
    </section>
  )
}

function ErrorNote({ step, error }: { step: string; error: unknown }) {
  return (
    <div className="warn" role="alert">
      <p>
        {step} 실패: {error instanceof ApiRequestError && error.body ? `HTTP ${error.status} ${error.body.code} — ${error.message}` : error instanceof Error ? error.message : String(error)}
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
  ['changed_assignments', '배정 바뀜'],
  ['fixed_risks_added', '고정 위험 생김'],
  ['fixed_risks_removed', '고정 위험 없어짐'],
  ['fixed_risks_remaining', '고정 위험 남음'],
] as const

const DELTAS = [
  ['unassigned_count', '미처리'],
  ['movable_violation_count', '제약 위반'],
  ['fixed_risk_count', '고정 위험'],
  ['changed_job_count', '변경 작업'],
  ['movable_travel_minutes', '이동(분)'],
] as const

/** 조건 보완 전후 비교(대겸 비교 로직의 서버 결과). 개선율로 해석하지 못하는 경우는 서버가 준 한계를 그대로 보여준다. */
export function RevisionComparison({ client, revisionId, beforeRunId, afterRunId, method }: { client: V2Client; revisionId: string; beforeRunId: string | null; afterRunId: string; method: string }) {
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

  if (state.error) return <section className="card"><h2>조건 보완 전후 비교 ({method})</h2><ErrorNote step="비교 조회" error={state.error} /></section>
  if (!state.data) return <section className="card" role="status"><h2>조건 보완 전후 비교 ({method})</h2><p className="muted">비교 불러오는 중…</p></section>
  const { confirmation, comparison: c } = state.data
  return (
    <section className="card revision-compare" aria-labelledby="revcmp-title">
      <h2 id="revcmp-title">
        조건 보완 전후 비교 ({method}){' '}
        <span className={`badge ${confirmation === 'assumed' ? 'fixture' : 'lock'}`}>{confirmation === 'assumed' ? '가정 시험 · 승인 불가' : '확인된 조건(모의)'}</span>
      </h2>
      <p className="small">수정 이유: {c.revision.reason}</p>
      <ul className="rev-diff">
        {c.revision.changes.map((x) => (
          <li key={`${x.entity_id}:${x.field}`}>{x.entity_id} {FIELD_LABEL[x.field] ?? x.field}: {x.before ? kstDateTime(x.before) : '미확인'} → <b>{x.after ? kstDateTime(x.after) : '미확인'}</b></li>
        ))}
        {c.revision.added_vehicles.map((v) => (
          <li key={v.vehicle_id}>차량 추가: <b>{v.vehicle_id}</b> · {v.start_location_id} 출발 (확보 여부는 담당자가 외부에서 확인)</li>
        ))}
      </ul>
      {c.before.status === 'input_blocked' && (
        <p className="warn small">이전 입력은 {c.before.error?.code} 때문에 계산되지 않았습니다. 이전 미처리를 0건으로 보고 비교하지 않습니다.</p>
      )}
      {c.job_transitions && (
        <dl className="rev-transitions">
          {TRANSITIONS.filter(([k]) => c.job_transitions![k].length).map(([k, label]) => (
            <div key={k}><dt>{label}</dt><dd>{c.job_transitions![k].join(', ')}</dd></div>
          ))}
        </dl>
      )}
      {c.metric_deltas && (
        <table className="grid small rev-deltas">
          <thead><tr>{DELTAS.map(([, l]) => <th key={l} scope="col">{l}</th>)}</tr></thead>
          <tbody><tr>{DELTAS.map(([k]) => <td key={k}>{signed(c.metric_deltas![k])}</td>)}</tr></tbody>
        </table>
      )}
      <ul className="small muted">
        {c.comparison_limits.map((l) => <li key={l}>{l}</li>)}
      </ul>
    </section>
  )
}

const signed = (n: number | undefined) => (n === undefined ? '—' : n > 0 ? `+${n}` : String(n))
