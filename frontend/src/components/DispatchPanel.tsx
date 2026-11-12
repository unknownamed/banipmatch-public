import qrcode from 'qrcode-generator'
import { useCallback, useEffect, useState } from 'react'
import { ApiRequestError } from '../api/client'
import type { SessionState, V2Client } from '../api/v2'
import {
  DELIVERY_LABEL, RESPONSE_LABEL, SUBSCRIPTION_LABEL, invitationLink, linkedRecipientFor, retryBlocker,
  type DispatchPreview, type DispatchState, type Followup, type RecipientSummary,
} from '../lib/dispatch'
import { kstDateTime, kstTime } from '../lib/time'
import { jobName, vehicleName, vehicleShort } from '../lib/labels'
import { driverMessage, inviteMessage } from '../lib/driverMessage'
import { copyText } from '../lib/copyText'
import { BoxNo, Plate } from './Ids'
import { Icon } from './Icon'
import { ISSUE_LABEL } from '../lib/compare'
import { publishDriverLocations } from '../lib/driverLocations'
import { friendlyError } from '../lib/friendlyError'

const enc = encodeURIComponent
// 서버의 개발용 설명 대신 쉬운 안내를 보여 준다.
const errText = friendlyError

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
    () => client.get<{ recipients: RecipientSummary[] }>('/v2/recipients').then((r) => {
      const mine = r.recipients.filter((x) => x.plan_id === planId)
      setRecipients(mine)
      publishDriverLocations(mine)
    }, () => {}),
    [client, planId],
  )
  useEffect(() => {
    let live = true
    client.get<DispatchPreview>(`/v2/plans/${enc(planId)}/dispatch-preview`).then((data) => live && setPreview({ data }), (error) => live && setPreview({ error }))
    client.session().then((s) => live && setSession(s), () => {})
    loadRecipients()
    const timer = setInterval(loadRecipients, 5000)
    return () => { live = false; clearInterval(timer); publishDriverLocations([]) }
  }, [client, planId, loadRecipients])

  if (preview.error) {
    const notApproved = preview.error instanceof ApiRequestError && preview.error.body?.code === 'PLAN_VERSION_CONFLICT'
    return (
      <section className="card dispatch">
        <h2>기사 전달</h2>
        <p className={notApproved ? 'muted' : 'warn'}>
          {notApproved ? '배차를 확정한 뒤에 기사에게 전달할 수 있습니다.' : `전달할 변경 내용을 불러오지 못했습니다: ${errText(preview.error)}`}
        </p>
      </section>
    )
  }
  if (!preview.data) return <section className="card dispatch" role="status"><h2>기사 전달</h2><p className="muted">전달할 변경 내용 불러오는 중…</p></section>
  const p = preview.data
  const authorized = !!session?.push_test_authorized

  return (
    <section className="card dispatch" aria-labelledby="dispatch-title">
      <h2 id="dispatch-title">기사 전달</h2>

      <h3>차량별 변경 내용</h3>
      <div className="vehicle-changes">
        {p.vehicle_changes.map((v) => (
          <div key={v.vehicle_id} className="vehicle-change">
            <p>
              <Plate id={v.vehicle_id} />{' '}
              <span className={`st ${v.recipient_status === 'linked' || v.recipient_status === 'active' ? 'ok' : 'wait'}`}>
                {RECIPIENT_STATUS_LABEL[v.recipient_status] ?? SUBSCRIPTION_LABEL[v.recipient_status as keyof typeof SUBSCRIPTION_LABEL] ?? '연결 상태 확인 중'}
              </span>
            </p>
            <ul className="small">
              {v.changes.map((c) => (
                <li key={c.job_id}><BoxNo jobId={c.job_id} /> <span className="vc-text">{changeText(v.vehicle_id, c)}</span></li>
              ))}
            </ul>
            <CopyNotice text={driverMessage(v.vehicle_id, v.changes, p.approved_version)} />
          </div>
        ))}
      </div>

      {p.followups.length > 0 && <Followups items={p.followups} title="담당자가 확인할 사항" />}

      <div className="push-box">
        <h3>기사 앱으로 알림 보내기</h3>
        <PushGuide authorized={authorized} linked={recipients.some((r) => !r.revoked && r.subscription_status === 'active')} />
        {!authorized && <TeamCodeUnlock client={client} onUnlocked={setSession} />}
      </div>
      <Invitations client={client} planId={planId} vehicles={p.vehicle_changes.map((v) => v.vehicle_id)} authorized={authorized} recipients={recipients} onChange={loadRecipients}
        noticeFor={(id) => { const v = p.vehicle_changes.find((x) => x.vehicle_id === id); return v ? driverMessage(id, v.changes, p.approved_version) : `[반입맞춤 배차 변경] ${vehicleName(id)}` }} />

      <Send client={client} preview={p} authorized={authorized} linked={new Set(recipients.filter((r) => !r.revoked).flatMap((r) => r.vehicle_ids)).size} dispatchId={dispatchId} onSent={(id) => {
        setDispatchId(id)
        const q = new URLSearchParams(location.search)
        q.set('dispatch', id)
        history.replaceState(null, '', `?${q}`)
      }} />

      {dispatchId && <DispatchStatus client={client} dispatchId={dispatchId} recipients={recipients} />}
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
            <b>{f.job_id ? jobName(f.job_id) : '전체'}</b> <span className="badge unassigned">{ISSUE_LABEL[f.code] ?? '확인 필요'}</span>
            {f.check_next && <p className="small">{f.check_next}</p>}
            {f.contact_role && <p className="small">확인할 사람: {f.contact_role}</p>}
          </li>
        ))}
      </ul>
    </>
  )
}

/** 초대 링크를 휴대폰 카메라로 바로 열 수 있게 QR 그림(데이터 주소)으로 만든다. 링크는 이 화면 메모리에만 둔다. */
function qrDataUrl(text: string): string {
  const qr = qrcode(0, 'M')
  qr.addData(text)
  qr.make()
  return qr.createDataURL(5, 2)
}

// 변경 명세의 차량별 연결 상태(서버 값: linked / unsubscribed / unlinked)
const RECIPIENT_STATUS_LABEL: Record<string, string> = { linked: '알림 받는 중', unsubscribed: '연결됨, 알림 꺼짐', unlinked: '휴대폰 미연결' }

function Invitations({ client, planId, vehicles, authorized, recipients, onChange, noticeFor }: {
  client: V2Client; planId: string; vehicles: string[]; authorized: boolean; recipients: RecipientSummary[]; onChange: () => void
  noticeFor: (vehicleId: string) => string
}) {
  const [invite, setInvite] = useState<{ vehicle: string; link: string; expires_at: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [copied, setCopied] = useState<'no' | 'ok' | 'failed'>('no')
  const [error, setError] = useState<unknown>(null)
  const linkedBy = new Map(recipients.filter((r) => !r.revoked).flatMap((r) => r.vehicle_ids.map((v) => [v, r] as const)))
  // 기사가 연결을 마치면 그 차량의 QR·링크 상자를 닫는다.
  const linkedNow = invite ? linkedBy.has(invite.vehicle) : false
  useEffect(() => { if (linkedNow) setInvite(null) }, [linkedNow])

  // 차량 줄의 버튼 한 번으로 그 차량용 1회용 링크를 만들고, 바뀐 배차 안내문·연결 방법·링크를 한 번에 복사한다.
  // (선택 기사에게만 보내고 이름·번호는 저장하지 않음)
  const messageFor = (i: { vehicle: string; link: string; expires_at: string }) => inviteMessage(noticeFor(i.vehicle), i.link, i.expires_at)
  async function create(vehicle: string) {
    setBusy(vehicle)
    setError(null)
    setCopied('no')
    try {
      const r = await client.post<{ invitation_token: string; expires_at: string }>('/v2/invitations', { plan_id: planId, vehicle_ids: [vehicle], consent_acknowledged: true }, `invite-${crypto.randomUUID()}`)
      // 초대 비밀은 이 화면 메모리에만 둔다. 저장소·로그·주소 query에 남기지 않는다.
      const next = { vehicle, link: invitationLink(location.origin, r.invitation_token), expires_at: r.expires_at }
      setInvite(next)
      setCopied((await copyText(messageFor(next))) ? 'ok' : 'failed')
    } catch (e) {
      setError(e)
    } finally {
      setBusy(null)
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

  if (!authorized && recipients.length === 0) return null
  return (
    <>
      <h3>기사 휴대폰 연결</h3>
      <p className="small muted">링크는 그 차량 기사에게만 보내세요. 이름과 전화번호는 저장하지 않습니다.</p>
      <ul className="link-list">
        {vehicles.map((v) => {
          const r = linkedBy.get(v)
          return (
            <li key={v}>
              <Plate id={v} />
              {r ? (
                <>
                  <span className={`st ${r.subscription_status === 'active' ? 'ok' : 'warn'}`}>{SUBSCRIPTION_LABEL[r.subscription_status]}</span>
                  <button type="button" className="btn-line subtle" onClick={() => revoke(r.recipient_id)}>연결 해제</button>
                </>
              ) : (
                <>
                  <span className={`st ${invite?.vehicle === v ? 'run' : 'wait'}`}>{invite?.vehicle === v ? '기사 연결 기다리는 중' : '연결 안 됨'}</span>
                  {authorized && <button type="button" className="btn-line" disabled={busy !== null} onClick={() => create(v)}>{busy === v ? '만드는 중…' : '안내문·연결 링크 복사'}</button>}
                </>
              )}
            </li>
          )
        })}
      </ul>
      {invite && (
        <div className="invite-link" role="status">
          <div className="invite-body">
            {copied === 'ok'
              ? <p><b>{vehicleName(invite.vehicle)}</b> 안내문과 연결 링크를 복사했습니다. 카톡이나 문자 창에 붙여 넣어 기사에게 보내세요.</p>
              : <p><b>{vehicleName(invite.vehicle)}</b> 기사에게 보낼 안내문과 연결 링크입니다.</p>}
            <p className="small muted">링크는 한 번만 쓸 수 있고 {kstDateTime(invite.expires_at)}까지 유효합니다.</p>
            <div className="invite-copy">
              <button type="button" className="btn-line" onClick={async () => setCopied((await copyText(messageFor(invite))) ? 'ok' : 'failed')}>
                <Icon name="link" size={14} />다시 복사
              </button>
            </div>
            {copied === 'failed' && (
              <p className="small warn">복사하지 못했습니다. 아래 내용을 직접 선택해 복사하세요.<br /><span className="invite-raw">{messageFor(invite)}</span></p>
            )}
            <details className="invite-qr-more">
              <summary className="small">기사가 옆에 있으면 QR로 연결</summary>
              <img className="invite-qr" src={qrDataUrl(invite.link)} alt="연결 링크 QR 코드" width={164} height={164} />
            </details>
          </div>
        </div>
      )}
      {error !== null && <p className="warn small" role="alert">{errText(error)}</p>}
    </>
  )
}

function Send({ client, preview, authorized, dispatchId, onSent, linked }: {
  client: V2Client; preview: DispatchPreview; authorized: boolean; dispatchId: string | null; onSent: (id: string) => void; linked: number
}) {
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
      <h3>알림 보내기</h3>
      {dispatchId ? (
        <p className="small muted">이 배차의 변경을 이미 보냈습니다. 아래에서 기사 응답을 확인하세요.</p>
      ) : (
        <div className="send-row">
          <button type="button" className="btn-primary" disabled={busy || linked === 0} onClick={send}>{busy ? '보내는 중…' : `연결된 기사에게 보내기${linked ? ` (${linked}대)` : ''}`}</button>
          <span className="small muted">{linked === 0 ? '먼저 위에서 기사 휴대폰을 연결하세요.' : '잠금 화면에는 ‘배차 변경 확인 요청’만 보입니다.'}</span>
        </div>
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
      <h3>전달 결과와 응답 {!d.is_current && <span className="badge fixture">이전 계획</span>}</h3>
      <p className="small muted">{state.at ? `${kstTime(new Date(state.at).toISOString())} 기준, 자동으로 새로 고침` : ''}</p>
      <table className="grid small dispatch-status">
        <thead>
          <tr><th scope="col">차량</th><th scope="col">전달</th><th scope="col">열람</th><th scope="col">응답</th><th /></tr>
        </thead>
        <tbody>
          {d.notifications.map((n) => {
            const blocker = retryBlocker(n, Date.now())
            const target = n.delivery_status === 'unlinked' ? linkedRecipientFor(n.vehicle_ids, recipients) : null
            return (
              <tr key={n.notification_id}>
                <td>{n.vehicle_ids.map(vehicleName).join(', ')}</td>
                <td>{DELIVERY_LABEL[n.delivery_status] ?? n.delivery_status}</td>
                <td>{n.opened_at ? kstTime(n.opened_at) : '—'}</td>
                <td>
                  {RESPONSE_LABEL[n.response] ?? n.response}
                  {n.responded_at && <span className="small muted">, {kstTime(n.responded_at)}</span>}
                  {n.response_history.at(-1)?.note && <span className="small muted">, “{n.response_history.at(-1)!.note}”</span>}
                </td>
                <td>
                  {n.response !== 'none' ? null : <>
                    {blocker === '' && (n.delivery_status !== 'unlinked' || target) && (
                      <button type="button" className="btn-line" onClick={() => retry(n.notification_id, target)}>다시 보내기</button>
                    )}
                    {blocker === '' && n.delivery_status === 'unlinked' && !target && <span className="small muted">휴대폰을 연결하면 보낼 수 있음</span>}
                    {blocker && <span className="small muted">{blocker}</span>}
                  </>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {retryError !== null && <p className="warn small" role="alert">다시 보내지 못했습니다: {errText(retryError)}</p>}
    </>
  )
}

/** 웹 푸시를 받지 못하는 기사에게 문자·카톡으로 보낼 안내문. 자동 발송하지 않고 복사만 한다. */
function CopyNotice({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  return (
    <div className="copy-notice">
      <button type="button" className="secondary" onClick={async () => setState((await copyText(text)) ? 'copied' : 'failed')}>
        {state === 'copied' ? '복사했습니다. 문자나 카톡에 붙여 넣으세요' : '기사 안내문 복사'}
      </button>
      {state === 'failed' && <span className="warn small"> 복사하지 못했습니다. 아래 내용을 직접 선택해 복사하세요.</span>}
      <details>
        <summary className="small muted">안내문 미리보기</summary>
        <pre className="notice-text">{text}</pre>
      </details>
    </div>
  )
}

/** 앱 알림이 실제로 오기까지의 순서. 지금 어디까지 됐는지 표시한다. */
function PushGuide({ authorized, linked }: { authorized: boolean; linked: boolean }) {
  const steps: [string, boolean][] = [
    ['알림 사용 코드로 알림 기능 켜기', authorized],
    ['차량의 ‘안내문·연결 링크 복사’를 눌러 카톡이나 문자로 기사에게 보내기', linked],
    ['기사가 링크를 눌러 ‘연결하고 알림 받기’', linked],
    ['‘연결된 기사에게 보내기’를 누르면 응답이 이 화면에 표시됨', false],
  ]
  return (
    <ol className="push-guide small" aria-label="앱 알림 받는 방법">
      {steps.map(([text, done], i) => <li key={i} className={done ? 'done' : ''}><b>{done ? '✓' : i + 1}</b>{text}</li>)}
    </ol>
  )
}

function TeamCodeUnlock({ client, onUnlocked }: { client: V2Client; onUnlocked: (s: SessionState) => void }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function submit() {
    setBusy(true); setError(null)
    try {
      onUnlocked(await client.post<SessionState>('/v2/session/push-authorization', { team_code: code }, `team-code-${crypto.randomUUID()}`))
    } catch (e) {
      const c = e instanceof ApiRequestError ? e.body?.code : null
      setError(c === 'TEAM_CODE_INVALID' ? '코드가 맞지 않습니다.' : c === 'RATE_LIMITED' ? '시도가 많습니다. 10분 뒤 다시 해 주세요.' : c === 'TEAM_CODE_NOT_CONFIGURED' ? '이 서버에서는 알림 사용 코드를 쓰지 않습니다.' : errText(e))
    } finally { setBusy(false) }
  }
  return (
    <form className="team-code" onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <label className="small">알림 사용 코드 <input value={code} onChange={(e) => setCode(e.target.value)} maxLength={32} autoComplete="off" spellCheck={false} /></label>
      <button type="submit" disabled={busy || !code.trim()}>{busy ? '확인 중…' : '알림 기능 켜기'}</button>
      {error && <span className="warn small" role="alert">{error}</span>}
    </form>
  )
}

type Slot = { vehicle_id?: string; sequence?: number; pickup_departure_at?: string | null; gate_arrival_at?: string | null } | null | undefined
/** 차량 카드 안에서 한 작업이 어떻게 바뀌는지, 기사가 바로 알아듣게 한 줄로. */
function changeText(vehicleId: string, c: { kind: string; before?: Slot; after?: Slot }) {
  const t = (x: string | null | undefined) => kstTime(x ?? null)
  const b = c.before, a = c.after
  if (!a) return '배정 보류(운송 취소 아님, 담당자 확인 중)'
  const when = `상차지 출발 ${t(a.pickup_departure_at)}, 게이트 도착 ${t(a.gate_arrival_at)}`
  if (!b) return `새로 배정, ${when}`
  if (b.vehicle_id !== a.vehicle_id)
    return b.vehicle_id === vehicleId ? `다른 차량(${vehicleShort(a.vehicle_id)})으로 넘어감, 이 차량은 수행하지 않음` : `${vehicleShort(b.vehicle_id)} 차량에서 넘어옴, ${when}`
  const moved = b.pickup_departure_at !== a.pickup_departure_at
  const order = b.sequence !== a.sequence ? `, 순서 ${b.sequence}번째 → ${a.sequence}번째` : ''
  return moved ? `상차지 출발 ${t(b.pickup_departure_at)} → ${t(a.pickup_departure_at)}, 게이트 도착 ${t(a.gate_arrival_at)}${order}` : `시각 그대로${order}`
}
