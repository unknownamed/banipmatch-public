import { useCallback, useEffect, useState } from 'react'
import { ApiRequestError } from '../api/client'
import type { SessionState, V2Client } from '../api/v2'
import {
  CHANGE_LABEL, DELIVERY_LABEL, RESPONSE_LABEL, SUBSCRIPTION_LABEL, invitationLink, linkedRecipientFor, retryBlocker,
  type DispatchPreview, type DispatchState, type Followup, type RecipientSummary,
} from '../lib/dispatch'
import { kstDateTime, kstTime } from '../lib/time'
import { jobName, vehicleName, vehicleShort } from '../lib/labels'
import { driverMessage } from '../lib/driverMessage'

const enc = encodeURIComponent
const errText = (e: unknown) =>
  e instanceof ApiRequestError && e.body ? `HTTP ${e.status} ${e.body.code} — ${e.message}` : e instanceof Error ? e.message : String(e)

/**
 * 내부 승인 이후: 차량별 변경 명세 → 시험 수신자 초대·연결 → 명시적 전달 → 대상별 전달·사람 응답 상태.
 * 승인 ≠ 전달. 전달은 동의한 시험 수신자에게만, 담당자가 확인 상자를 체크하고 누를 때만 보낸다.
 */
export function DispatchPanel({ client, planId }: { client: V2Client; planId: string }) {
  const [preview, setPreview] = useState<{ data?: DispatchPreview; error?: unknown }>({})
  const [session, setSession] = useState<SessionState | null>(null)
  const [recipients, setRecipients] = useState<RecipientSummary[]>([])
  const [dispatchId, setDispatchId] = useState(() => new URLSearchParams(location.search).get('dispatch'))

  const loadRecipients = useCallback(
    () => client.get<{ recipients: RecipientSummary[] }>('/v2/recipients').then((r) => setRecipients(r.recipients.filter((x) => x.plan_id === planId)), () => {}),
    [client, planId],
  )
  useEffect(() => {
    let live = true
    client.get<DispatchPreview>(`/v2/plans/${enc(planId)}/dispatch-preview`).then((data) => live && setPreview({ data }), (error) => live && setPreview({ error }))
    client.session().then((s) => live && setSession(s), () => {})
    loadRecipients()
    const timer = setInterval(loadRecipients, 5000)
    return () => { live = false; clearInterval(timer) }
  }, [client, planId, loadRecipients])

  if (preview.error) {
    const notApproved = preview.error instanceof ApiRequestError && preview.error.body?.code === 'PLAN_VERSION_CONFLICT'
    return (
      <section className="card dispatch">
        <h2>변경 전달 · 응답</h2>
        <p className={notApproved ? 'muted' : 'warn'}>
          {notApproved ? '최신 입력으로 독립 검사를 통과하고 내부 승인한 계획만 전달 대상을 만들 수 있습니다.' : `변경 명세 조회 실패: ${errText(preview.error)}`}
        </p>
      </section>
    )
  }
  if (!preview.data) return <section className="card dispatch" role="status"><h2>변경 전달 · 응답</h2><p className="muted">변경 명세 불러오는 중…</p></section>
  const p = preview.data
  const authorized = !!session?.push_test_authorized

  return (
    <section className="card dispatch" aria-labelledby="dispatch-title">
      <h2 id="dispatch-title">
        기사 전달 · 응답
      </h2>
      <p className="muted small">
        확정한 계획 v{p.approved_version}({p.method}) 기준으로 바뀌는 차량입니다. 기사 앱으로 알림을 보내거나, 안내문을 복사해 문자·카톡으로 보낼 수 있습니다.
      </p>

      <h3>차량별 변경 내용</h3>
      <div className="vehicle-changes">
        {p.vehicle_changes.map((v) => (
          <div key={v.vehicle_id} className="vehicle-change">
            <p>
              <b>{vehicleName(v.vehicle_id)}</b>{' '}
              <span className={`badge ${v.recipient_status === 'active' ? 'change' : 'unassigned'}`}>
                {SUBSCRIPTION_LABEL[v.recipient_status as keyof typeof SUBSCRIPTION_LABEL] ?? v.recipient_status}
              </span>
            </p>
            <ul className="small">
              {v.changes.map((c) => (
                <li key={c.job_id}>
                  {jobName(c.job_id)} · {CHANGE_LABEL[c.kind] ?? c.kind}:{' '}
                  {c.before ? `${vehicleShort(c.before.vehicle_id)} ${kstTime(c.before.pickup_departure_at)} 출발` : '배정 없음'} →{' '}
                  {c.after ? `${vehicleShort(c.after.vehicle_id)} ${kstTime(c.after.pickup_departure_at)} 출발 · 게이트 ${kstTime(c.after.gate_arrival_at)}` : '미처리'}
                </li>
              ))}
            </ul>
            <CopyNotice text={driverMessage(v.vehicle_id, v.changes, p.approved_version)} />
          </div>
        ))}
      </div>

      {p.followups.length > 0 && <Followups items={p.followups} title="담당자가 확인할 사항" />}

      <Invitations client={client} planId={planId} vehicles={p.vehicle_changes.map((v) => v.vehicle_id)} authorized={authorized} recipients={recipients} onChange={loadRecipients} />

      <Send client={client} preview={p} authorized={authorized} dispatchId={dispatchId} onSent={(id) => {
        setDispatchId(id)
        const q = new URLSearchParams(location.search)
        q.set('dispatch', id)
        history.replaceState(null, '', `?${q}`)
      }} />

      {dispatchId && <DispatchStatus client={client} dispatchId={dispatchId} recipients={recipients} />}

      <details className="tech-info"><summary>유의사항</summary><ul className="small muted">{p.limits.map((l) => <li key={l}>{l}</li>)}</ul></details>
    </section>
  )
}

function Followups({ items, title }: { items: Followup[]; title: string }) {
  return (
    <>
      <h3>{title}</h3>
      <ul className="followups">
        {items.map((f, i) => (
          <li key={`${f.job_id}:${f.code}:${i}`}>
            <b>{f.job_id ? jobName(f.job_id) : '전체'}</b> <code className="small">{f.code}</code>
            {f.check_next && <p className="small">{f.check_next}</p>}
            {f.contact_role && <p className="small muted">확인 담당: {f.contact_role} · 해결을 보장하지 않습니다.</p>}
          </li>
        ))}
      </ul>
    </>
  )
}

function Invitations({ client, planId, vehicles, authorized, recipients, onChange }: {
  client: V2Client; planId: string; vehicles: string[]; authorized: boolean; recipients: RecipientSummary[]; onChange: () => void
}) {
  const [picked, setPicked] = useState<string[]>([])
  const [consent, setConsent] = useState(false)
  const [invite, setInvite] = useState<{ link: string; expires_at: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const taken = new Set(recipients.filter((r) => !r.revoked).flatMap((r) => r.vehicle_ids))

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const r = await client.post<{ invitation_token: string; expires_at: string }>('/v2/invitations', { plan_id: planId, vehicle_ids: picked, consent_acknowledged: true }, `invite-${crypto.randomUUID()}`)
      // 초대 비밀은 이 화면 메모리에만 둔다. 저장소·로그·주소 query에 남기지 않는다.
      setInvite({ link: invitationLink(location.origin, r.invitation_token), expires_at: r.expires_at })
      setPicked([])
      setConsent(false)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  async function revoke(id: string) {
    try {
      await client.post(`/v2/recipients/${enc(id)}/revoke`, {}, `revoke-${id}`)
    } catch (e) {
      setError(e)
    }
    onChange()
  }

  return (
    <>
      <h3>기사 앱 연결</h3>
      {!authorized && (
        <p className="small warn">
          이 계정은 앱 알림 발송 권한이 없습니다. 위의 안내문 복사로 전달할 수 있습니다. (시연에서는 동의한 팀원 휴대폰에만 관리자가 권한을 엽니다.)
        </p>
      )}
      {recipients.length > 0 && (
        <table className="grid small">
          <thead><tr><th scope="col">기사 휴대폰</th><th scope="col">차량</th><th scope="col">상태</th><th scope="col">연결 만료</th><th /></tr></thead>
          <tbody>
            {recipients.map((r) => (
              <tr key={r.recipient_id}>
                <td className="muted">기기 {r.recipient_id.slice(-4)}</td>
                <td>{r.vehicle_ids.map(vehicleName).join(', ')}</td>
                <td>{r.revoked ? '해제됨' : SUBSCRIPTION_LABEL[r.subscription_status]}</td>
                <td>{kstDateTime(r.expires_at)}</td>
                <td>{!r.revoked && <button type="button" className="secondary" onClick={() => revoke(r.recipient_id)}>연결 해제</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {authorized && (
        <fieldset disabled={busy} className="invite">
          <legend className="small">연결할 차량 (이미 연결된 차량은 해제 후 다시 연결)</legend>
          {vehicles.map((v) => (
            <label key={v} className="rev-choice">
              <input type="checkbox" disabled={taken.has(v)} checked={picked.includes(v)} onChange={(e) => setPicked((x) => (e.target.checked ? [...x, v] : x.filter((y) => y !== v)))} />
              {' '}{vehicleName(v)}{taken.has(v) && <span className="small muted"> · 연결됨</span>}
            </label>
          ))}
          <label className="rev-choice">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />{' '}
            이 차량 기사에게만 연결 링크를 보냅니다. 기사가 휴대폰에서 열고 알림을 허용하면 연결됩니다. 이름·전화번호는 저장하지 않습니다.
          </label>
          <button type="button" disabled={!picked.length || !consent} onClick={create}>연결 링크 만들기</button>
        </fieldset>
      )}
      {invite && (
        <div className="invite-link" role="status">
          <p className="small">연결 링크(1회용 · {kstDateTime(invite.expires_at)}까지). 기사에게 이 링크를 보내 주세요.</p>
          <input readOnly value={invite.link} aria-label="초대 링크" onFocus={(e) => e.currentTarget.select()} />
          <button type="button" className="secondary" onClick={() => navigator.clipboard?.writeText(invite.link)}>복사</button>
          <p className="small muted">
            iPhone은 Safari에서 바로 열지 말고, 먼저 반입맞춤을 홈 화면에 추가한 뒤 홈 화면 앱 안에 이 링크를 붙여넣어야 알림을 받을 수 있습니다.
          </p>
        </div>
      )}
      {error !== null && <p className="warn small" role="alert">{errText(error)}</p>}
    </>
  )
}

function Send({ client, preview, authorized, dispatchId, onSent }: {
  client: V2Client; preview: DispatchPreview; authorized: boolean; dispatchId: string | null; onSent: (id: string) => void
}) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  if (!authorized && !dispatchId) return null

  async function send() {
    setBusy(true)
    setError(null)
    try {
      // 같은 승인에는 같은 멱등키 → 재시도·새로고침에도 중복 발송되지 않는다(서버도 같은 승인 중복 전송을 막음).
      const r = await client.post<{ dispatch_id: string }>(`/v2/plans/${enc(preview.plan_id)}/dispatches`, {
        approval_id: preview.approval_id, expected_version: preview.approved_version, confirm_test_send: true,
      }, `dispatch-${preview.approval_id}`)
      onSent(r.dispatch_id)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h3>앱 알림 보내기</h3>
      {dispatchId ? (
        <p className="small muted">이 계획의 변경을 이미 보냈습니다. 아래에서 기사 응답을 확인하세요.</p>
      ) : (
        <fieldset disabled={busy}>
          <label className="rev-choice">
            <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />{' '}
            확정한 계획 v{preview.approved_version}의 변경을 연결된 기사 휴대폰으로 보냅니다. 잠금 화면에는 ‘배차 변경 확인 요청’만 표시됩니다.
          </label>
          <button type="button" disabled={!confirm} onClick={send}>{busy ? '보내는 중…' : '기사에게 보내기'}</button>
        </fieldset>
      )}
      {error !== null && <p className="warn small" role="alert">전달 실패: {errText(error)}</p>}
    </>
  )
}

function DispatchStatus({ client, dispatchId, recipients }: { client: V2Client; dispatchId: string; recipients: RecipientSummary[] }) {
  const [state, setState] = useState<{ data?: DispatchState; error?: unknown; at?: number }>({})
  const [retryError, setRetryError] = useState<unknown>(null)
  const load = useCallback(
    () => client.get<DispatchState>(`/v2/dispatches/${enc(dispatchId)}`).then((data) => setState({ data, at: Date.now() }), (error) => setState((s) => ({ ...s, error }))),
    [client, dispatchId],
  )
  useEffect(() => {
    load()
    // 응답은 사람이 하므로 짧게 자주 묻지 않는다(서버 조회 한도 분당 180회 안).
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load])

  async function retry(id: string, recipientId: string | null) {
    setRetryError(null)
    try {
      await client.post(`/v2/notifications/${enc(id)}/retry`, { confirm_test_send: true, ...(recipientId ? { recipient_id: recipientId } : {}) }, `retry-${id}-${crypto.randomUUID()}`)
      load()
    } catch (e) {
      setRetryError(e)
    }
  }

  if (!state.data) return state.error ? <p className="warn small">전달 상태 조회 실패: {errText(state.error)}</p> : <p className="muted small" role="status">전달 상태 불러오는 중…</p>
  const d = state.data
  return (
    <>
      <h3>대상별 전달 · 응답 {!d.is_current && <span className="badge fixture">이전 계획</span>}</h3>
      <p className="small muted">
        중계망 접수는 읽음이 아니고, 확인·수행 가능은 운송 완료가 아닙니다. 응답이 없으면 자동으로 재촉하지 않습니다. 갱신 {state.at ? kstTime(new Date(state.at).toISOString()) : ''}
      </p>
      <table className="grid small dispatch-status">
        <thead>
          <tr><th scope="col">차량</th><th scope="col">전달</th><th scope="col">시도</th><th scope="col">열람</th><th scope="col">응답</th><th scope="col">후속</th><th /></tr>
        </thead>
        <tbody>
          {d.notifications.map((n) => {
            const blocker = retryBlocker(n, Date.now())
            const target = n.delivery_status === 'unlinked' ? linkedRecipientFor(n.vehicle_ids, recipients) : null
            return (
              <tr key={n.notification_id}>
                <td>{n.vehicle_ids.join(', ')}</td>
                <td>{DELIVERY_LABEL[n.delivery_status] ?? n.delivery_status}{n.error_code && <span className="small muted"> ({n.error_code})</span>}</td>
                <td>{n.attempts}</td>
                <td>{n.opened_at ? kstTime(n.opened_at) : '—'}</td>
                <td>
                  {RESPONSE_LABEL[n.response] ?? n.response}
                  {n.responded_at && <span className="small muted"> · {kstTime(n.responded_at)}</span>}
                  {n.response_history.at(-1)?.note && <span className="small muted"> · “{n.response_history.at(-1)!.note}”</span>}
                </td>
                <td>{n.needs_followup ? <span className="badge unassigned">확인 필요</span> : '—'}</td>
                <td>
                  {blocker === '' && (n.delivery_status !== 'unlinked' || target) && (
                    <button type="button" className="secondary" onClick={() => retry(n.notification_id, target)}>다시 보내기</button>
                  )}
                  {blocker === '' && n.delivery_status === 'unlinked' && !target && <span className="small muted">수신자 연결 후 재시도</span>}
                  {blocker && <span className="small muted">{blocker}</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {retryError !== null && <p className="warn small" role="alert">재시도 실패: {errText(retryError)}</p>}
      {d.followups.length > 0 && <Followups items={d.followups} title="후속 확인 목록" />}
    </>
  )
}

/** 웹 푸시를 받지 못하는 기사에게 문자·카톡으로 보낼 안내문. 자동 발송하지 않고 복사만 한다. */
function CopyNotice({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  return (
    <div className="copy-notice">
      <button type="button" className="secondary" onClick={() => navigator.clipboard?.writeText(text).then(() => setState('copied'), () => setState('failed')) ?? setState('failed')}>
        {state === 'copied' ? '복사됨 · 문자/카톡에 붙여넣기' : '기사 안내문 복사'}
      </button>
      {state === 'failed' && <span className="warn small"> 복사하지 못했습니다. 아래 내용을 직접 선택해 복사하세요.</span>}
      <details>
        <summary className="small muted">안내문 미리보기</summary>
        <pre className="notice-text">{text}</pre>
      </details>
    </div>
  )
}
