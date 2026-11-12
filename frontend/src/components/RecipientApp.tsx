import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiRequestError } from '../api/client'
import type { RecipientClient, RecipientNotification, RecipientSession } from '../api/recipient'
import { RESPONSE_LABEL } from '../lib/dispatch'
import { base64UrlToBytes, claimKey, inviteFromPaste, mustInstallFirst, platform, type Fragment, type PlatformInfo } from '../lib/recipient'
import { kstDateTime, kstTime } from '../lib/time'
import { formatContainer } from '../lib/labels'

const errText = (e: unknown) =>
  e instanceof ApiRequestError && e.body ? `${e.body.code} — ${e.message}` : e instanceof Error ? e.message : String(e)
const isCode = (e: unknown, ...codes: string[]) => e instanceof ApiRequestError && !!e.body && codes.includes(e.body.code)

/**
 * 기사 역할 시험 수신자 화면. 내 차량의 확정 변경만 보고 확인·수행 가능·곤란을 답한다.
 * 다른 차량·기사의 일정은 서버가 가리고, 전화번호·이름은 받지 않는다.
 */
export function RecipientApp({ client, boot, env = platform(navigator, window), demo = false }: { client: RecipientClient; boot: Fragment; env?: PlatformInfo; demo?: boolean }) {
  const [invite, setInvite] = useState<string | null>(boot.invite)
  const [session, setSession] = useState<RecipientSession | null | undefined>(undefined)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    client.restore().then(setSession, () => setSession(null))
  }, [client])

  async function accept(token: string) {
    setBusy(true)
    setError(null)
    try {
      setSession(await client.claim(token, await claimKey(token)))
      setInvite(null)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  if (session === undefined) return <Shell demo={demo}><p className="muted" role="status">연결 확인 중…</p></Shell>
  if (session) return <Shell demo={demo}><Connected client={client} session={session} env={env} demo={demo} focus={boot.notification} onLeave={() => setSession(null)} /></Shell>

  const install = mustInstallFirst(env)
  return (
    <Shell demo={demo}>
      <section className="card">
        <h2>배차 알림 연결</h2>
        <p className="small muted">확정된 배차 변경을 이 휴대폰으로 받고 바로 응답합니다.</p>
        {install ? (
          <InstallGuide hasInvite={!!invite} />
        ) : invite ? (
          <>
            <p>연결하면 이 휴대폰이 지정된 차량의 배차 알림을 받습니다. 이름·전화번호는 저장하지 않습니다.</p>
            <button type="button" disabled={busy} onClick={() => accept(invite)}>{busy ? '수락 중…' : '초대 수락'}</button>
          </>
        ) : (
          <PasteInvite busy={busy} onInvite={accept} />
        )}
        {error !== null && (
          <p className="warn small" role="alert">
            {isCode(error, 'INVITATION_USED')
              ? '이미 다른 곳에서 수락한 초대입니다. iPhone이면 Safari가 아닌 홈 화면 앱에서 수락해야 합니다. 담당자에게 새 초대를 요청하세요.'
              : isCode(error, 'INVITATION_EXPIRED')
                ? '초대가 만료됐습니다(30분). 담당자에게 새 초대를 요청하세요.'
                : isCode(error, 'RECIPIENT_REQUIRED', 'REQUEST_VALIDATION')
                  ? '초대 링크가 올바르지 않거나 해제됐습니다. 받은 링크 전체를 다시 복사했는지 확인하고, 안 되면 담당자에게 새 초대를 요청하세요.'
                : `수락 실패: ${errText(error)}`}
          </p>
        )}
      </section>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode; demo?: boolean }) {
  return (
    <main className="recipient">
      <header className="recipient-head"><img className="brand-mark" src="/brand.svg" alt="" width="28" height="28" /> 반입맞춤 기사</header>
      {children}
    </main>
  )
}

function InstallGuide({ hasInvite }: { hasInvite: boolean }) {
  return (
    <div className="install-guide">
      <p><b>iPhone은 홈 화면 앱에서만 알림을 받을 수 있습니다.</b> 여기(Safari)에서는 수락하지 마세요. Safari와 홈 화면 앱은 연결 정보가 따로 저장됩니다.</p>
      <ol>
        <li>아래 공유 버튼 <span aria-hidden="true">⬆︎</span> → <b>홈 화면에 추가</b></li>
        <li>홈 화면의 <b>반입맞춤</b> 아이콘으로 실행</li>
        <li>받은 초대 링크를 다시 복사해 앱 안에 붙여넣기(30분 안)</li>
      </ol>
      {hasInvite && <p className="small muted">초대 링크는 이 화면에 저장하지 않았습니다. 처음 받은 메시지에서 다시 복사하세요.</p>}
      <p className="small muted">iOS 16.4 이상에서 지원됩니다. 이전 버전은 알림을 받을 수 없습니다.</p>
    </div>
  )
}

function PasteInvite({ busy, onInvite }: { busy: boolean; onInvite: (token: string) => void }) {
  const [text, setText] = useState('')
  const token = inviteFromPaste(text)
  return (
    <div className="paste-invite">
      <label>
        받은 초대 링크 붙여넣기
        <input value={text} autoComplete="off" spellCheck={false} placeholder="https://…/recipient#invite=…" onChange={(e) => setText(e.target.value)} />
      </label>
      {text && !token && <p className="small warn">초대 링크 형식이 아닙니다.</p>}
      <button type="button" disabled={busy || !token} onClick={() => token && onInvite(token)}>{busy ? '수락 중…' : '초대 수락'}</button>
    </div>
  )
}

function Connected({ client, session, env, demo, focus, onLeave }: { client: RecipientClient; session: RecipientSession; env: PlatformInfo; demo: boolean; focus: string | null; onLeave: () => void }) {
  const [inbox, setInbox] = useState<{ items?: RecipientNotification[]; error?: unknown }>({})
  const [selected, setSelected] = useState<string | null>(focus)
  const [leaving, setLeaving] = useState(false)
  const [leaveError, setLeaveError] = useState<unknown>(null)
  async function leave() {
    setLeaving(true)
    setLeaveError(null)
    try { await client.leave(); onLeave() }
    catch (e) { setLeaveError(e) }
    finally { setLeaving(false) }
  }
  const load = useCallback(() => client.inbox().then((r) => setInbox({ items: r.notifications }), (error) => setInbox((s) => ({ ...s, error }))), [client])
  useEffect(() => {
    load()
    // 알림을 놓쳐도 화면을 열어 두면 확인할 수 있게 가끔만 다시 묻는다.
    const t = setInterval(load, 30000)
    // 앱이 열린 채 알림을 누르면 Service Worker가 알림 ID를 보내 준다.
    const onMessage = (e: MessageEvent) => typeof e.data?.notification_id === 'string' && (setSelected(e.data.notification_id), load())
    navigator.serviceWorker?.addEventListener('message', onMessage)
    return () => {
      clearInterval(t)
      navigator.serviceWorker?.removeEventListener('message', onMessage)
    }
  }, [load])

  const items = [...(inbox.items ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  // 고른 알림 → 최신 계획 알림 → 가장 최근 알림(이전 계획뿐이어도 '이전 계획'임을 보여준다).
  const current = items.find((n) => n.notification_id === selected) ?? items.find((n) => n.is_current) ?? items[0]

  return (
    <>
      <section className="card">
        <h2>내 배차 알림</h2>
        <p className="small muted">연결 만료 {kstDateTime(session.expires_at)}</p>
        {!demo && <PushControl client={client} session={session} env={env} />}
      </section>

      {inbox.error !== undefined && <p className="card warn small" role="alert">알림 목록 조회 실패: {errText(inbox.error)}</p>}
      {inbox.items && !items.length && <p className="card muted">아직 받은 변경이 없습니다.</p>}
      {items.length > 1 && (
        <nav className="card recipient-list" aria-label="받은 변경">
          {items.map((n) => (
            <button key={n.notification_id} type="button" className="secondary" aria-current={n.notification_id === current?.notification_id} onClick={() => setSelected(n.notification_id)}>
              {kstTime(n.created_at)} · {n.is_current ? RESPONSE_LABEL[n.response] : '이전 계획'}
            </button>
          ))}
        </nav>
      )}
      {current && <NotificationDetail key={current.notification_id} client={client} summary={current} onChanged={load} />}

      <p className="small"><button type="button" className="secondary" disabled={leaving} onClick={leave}>이 기기 연결 해제</button></p>
      {leaveError !== null && <p className="warn small" role="alert">연결 해제 실패: {errText(leaveError)}. 연결은 유지됩니다. 다시 시도해 주세요.</p>}
    </>
  )
}

function PushControl({ client, session, env }: { client: RecipientClient; session: RecipientSession; env: PlatformInfo }) {
  const [status, setStatus] = useState(session.subscription_status)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const permission = env.pushSupported ? Notification.permission : 'unsupported'

  async function enable() {
    setBusy(true)
    setNote(null)
    try {
      // 권한 요청은 반드시 버튼을 누른 동작 안에서 한다(자동 요청하지 않음).
      const result = await Notification.requestPermission()
      if (result !== 'granted') return setNote('알림이 허용되지 않았습니다. 화면을 직접 열어 변경을 확인할 수 있습니다.')
      const config = await client.pushConfig()
      if (!config.configured || !config.application_server_key) return setNote('알림 서버가 준비되지 않았습니다. 잠시 후 다시 시도하세요.')
      const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
      await navigator.serviceWorker.ready
      const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlToBytes(config.application_server_key) }))
      const saved = await client.subscribe(sub.toJSON())
      setStatus(saved.subscription_status as RecipientSession['subscription_status'])
    } catch (e) {
      setNote(`알림 연결 실패: ${errText(e)}`)
    } finally {
      setBusy(false)
    }
  }

  async function disable() {
    setBusy(true)
    try {
      const reg = await navigator.serviceWorker?.getRegistration('/')
      await (await reg?.pushManager.getSubscription())?.unsubscribe()
      const r = await client.unsubscribe()
      setStatus(r.subscription_status as RecipientSession['subscription_status'])
      setNote('알림을 껐습니다. 담당자 화면에는 구독 해제로 표시됩니다.')
    } catch (e) {
      setNote(`알림 끄기 실패: ${errText(e)}`)
    } finally {
      setBusy(false)
    }
  }

  if (!env.pushSupported)
    return <p className="small warn">이 브라우저는 알림을 지원하지 않습니다{env.ios ? '(iPhone은 iOS 16.4 이상에서 홈 화면에 추가한 뒤 사용)' : ''}. 이 화면을 열어 직접 확인해 주세요.</p>
  return (
    <div className="push-control">
      {status === 'active' && permission === 'granted' ? (
        <p className="small"><span className="badge change">알림 받는 중</span> 잠금 화면에는 &ldquo;변경 내용을 확인해 주세요&rdquo;만 표시됩니다.</p>
      ) : permission === 'denied' ? (
        <p className="small warn">알림이 차단돼 있습니다. 브라우저(또는 iPhone 설정 → 알림 → 반입맞춤)에서 허용으로 바꾼 뒤 다시 여세요.</p>
      ) : (
        <button type="button" disabled={busy} onClick={enable}>{busy ? '연결 중…' : '알림 허용'}</button>
      )}
      {status === 'active' && <button type="button" className="secondary" disabled={busy} onClick={disable}>알림 끄기</button>}
      {note && <p className="small muted" role="status">{note}</p>}
    </div>
  )
}

function NotificationDetail({ client, summary, onChanged }: { client: RecipientClient; summary: RecipientNotification; onChanged: () => void }) {
  const id = summary.notification_id
  const [n, setN] = useState<{ data?: RecipientNotification; error?: unknown }>({})
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [sendError, setSendError] = useState<unknown>(null)
  const attempt = useRef<{ body: string; key: string } | null>(null)

  useEffect(() => {
    let live = true
    client.notification(id).then(async (data) => {
      if (!live) return
      setN({ data })
      // 열람 기록. 확인·수행 가능으로 해석하지 않는다. 이전 계획은 기록하지 않는다.
      if (data.is_current && data.payload && !data.opened_at) client.opened(id).then((d) => live && setN({ data: d }), () => {})
    }, (error) => live && setN({ error }))
    return () => { live = false }
  }, [client, id, summary])

  async function respond(response: 'acknowledged' | 'can_perform' | 'cannot_perform') {
    setBusy(true)
    setSendError(null)
    const body = JSON.stringify([id, response, note.trim()])
    if (attempt.current?.body !== body) attempt.current = { body, key: `respond-${id}-${crypto.randomUUID()}` }
    try {
      setN({ data: await client.respond(id, response, note.trim(), attempt.current.key) })
      attempt.current = null
      setNote('')
      onChanged()
    } catch (e) {
      setSendError(e)
    } finally {
      setBusy(false)
    }
  }

  if (n.error) return <p className="card warn small" role="alert">변경 내용 조회 실패: {errText(n.error)}</p>
  if (!n.data) return <p className="card muted" role="status">변경 내용 불러오는 중…</p>
  const d = n.data
  if (!summary.is_current || !d.is_current || !d.payload || isCode(sendError, 'NOTIFICATION_SUPERSEDED'))
    return (
      <section className="card">
        <h2>이전 계획의 알림</h2>
        <p className="muted">담당자가 이후 계획을 바꿔 이 알림의 상세를 가렸습니다. 새 운송 지시가 아니며 응답할 수 없습니다. 최신 알림을 확인하세요.</p>
      </section>
    )
  return (
    <section className="card recipient-detail" aria-labelledby="detail-title">
      <h2 id="detail-title">변경 내용 <span className="small muted">계획 v{d.payload.plan_version} · {kstDateTime(d.created_at)}</span></h2>
      <p className="rc-lead">담당자가 확정한 배차 변경입니다. 게이트 도착 시각을 지켜 주세요.</p>
      {d.payload.vehicle_changes.map((v) => (
        <div key={v.vehicle_id}>
          <h3>{v.plate_no ?? v.vehicle_id}</h3>
          <ul className="rc-list">
            {v.changes.map((c) => {
              const d = c.display
              const name = d?.container_no ? formatContainer(d.container_no) : c.job_id
              const mine = (vid?: string) => vid === v.vehicle_id
              const outgoing = !!c.before && mine(c.before.vehicle_id) && (!c.after || !mine(c.after.vehicle_id))
              const incoming = !!c.after && mine(c.after.vehicle_id) && (!c.before || !mine(c.before.vehicle_id))
              const tag = c.kind === 'removed_from_plan' ? '보류' : outgoing ? '이 차량에서 빠짐' : incoming ? '새로 맡음' : '시각 변경'
              const tone = outgoing || c.kind === 'removed_from_plan' ? 'out' : incoming ? 'in' : 'time'
              const t = (x?: string | null) => kstTime(x ?? null)
              return (
              <li key={c.job_id} className={`rc-item ${tone}`}>
                <div className="rc-top"><b className="rc-box">{name}</b>{d?.size && <span className="rc-size">{d.size}</span>}<span className={`rc-tag ${tone}`}>{tag}</span></div>
                {d?.origin_name && <div className="rc-route">{d.origin_name} → {d.terminal_id} 게이트</div>}
                {outgoing || !c.after ? (
                  <p className="rc-note">{c.kind === 'removed_from_plan' ? '담당자가 확인 중입니다. 별도 연락 전까지 이 작업은 하지 않습니다.' : '다른 차량이 맡습니다. 이 작업은 하지 않습니다.'}</p>
                ) : (
                  <div className="rc-times">
                    <span>출발 {c.before && mine(c.before.vehicle_id) && c.before.pickup_departure_at !== c.after.pickup_departure_at && <s>{t(c.before.pickup_departure_at)}</s>} <b>{t(c.after.pickup_departure_at)}</b></span>
                    <span>게이트 도착 <b>{t(c.after.gate_arrival_at)}</b></span>
                  </div>
                )}
                {(d?.cargo_owner || d?.voyage_id) && <div className="rc-meta">{[d?.cargo_owner && `화주 ${d.cargo_owner}`, d?.voyage_id && `항차 ${d.voyage_id}`].filter(Boolean).join(' · ')}</div>}
              </li>
              )
            })}
          </ul>
        </div>
      ))}

      <h3>응답</h3>
      <p className="small">현재: <b>{RESPONSE_LABEL[d.response]}</b>{d.responded_at && ` · ${kstTime(d.responded_at)}`}</p>
      <label className="rev-reason">
        메모 (선택 · 개인정보 쓰지 않기)
        <textarea rows={2} maxLength={300} value={note} disabled={busy} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="respond-buttons">
        <button type="button" disabled={busy} className="rb-primary" onClick={() => respond('can_perform')}>수행 가능</button>
        <button type="button" disabled={busy} className="danger" onClick={() => respond('cannot_perform')}>수행 곤란</button>
        <button type="button" disabled={busy} className="rb-ghost" onClick={() => respond('acknowledged')}>내용만 확인함</button>
      </div>
      <p className="small muted">&lsquo;수행 곤란&rsquo;은 담당자에게 후속 확인으로 전달됩니다. 자동으로 다른 차량에 다시 배정되지 않습니다.</p>
      {sendError !== null && (
        <p className="warn small" role="alert">
          {isCode(sendError, 'NOTIFICATION_SUPERSEDED') ? '그 사이 계획이 바뀌어 이 알림에는 응답할 수 없습니다. 최신 알림을 확인하세요.' : `응답 실패: ${errText(sendError)}`}
        </p>
      )}
    </section>
  )
}
