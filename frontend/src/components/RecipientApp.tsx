import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiRequestError } from '../api/client'
import type { RecipientClient, RecipientNotification, RecipientSession } from '../api/recipient'
import { RESPONSE_LABEL } from '../lib/dispatch'
import { base64UrlToBytes, claimKey, inviteFromPaste, inviteUrl, kakaoExternal, mustInstallFirst, platform, takeFragment, type Fragment, type PlatformInfo } from '../lib/recipient'
import { kstDateTime, kstTime } from '../lib/time'
import { formatContainer } from '../lib/labels'
import { copyText } from '../lib/copyText'
import { BoxNo, Plate } from './Ids'
import { friendlyError } from '../lib/friendlyError'

// 서버의 개발용 설명 대신 쉬운 안내를 보여 준다.
const errText = friendlyError
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
  // 이 화면이 열린 채로 새 초대 링크를 열면(같은 주소에 # 뒤만 바뀜) 새로고침 없이 초대를 받고 주소에서 지운다.
  useEffect(() => {
    const onHash = () => { const f = takeFragment(); if (f.invite) setInvite(f.invite) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // 카카오톡으로 받은 링크를 누르면 카톡 안 브라우저로 열린다. 거기서는 알림을 못 받으므로 기본 브라우저로 바로 넘긴다.
  const external = env.inApp === 'kakao' && !demo ? kakaoExternal(inviteUrl(location.origin, invite)) : null
  useEffect(() => { if (external) location.href = external }, [external])
  if (env.inApp && !demo)
    return (
      <Shell demo={demo}>
        <section className="card">
          <h2>기본 브라우저에서 열어 주세요</h2>
          <p>{env.inApp === 'kakao' ? '카카오톡 안에서는' : '이 앱 안에서는'} 배차 알림을 받을 수 없습니다.</p>
          {external
            ? <a className="btn-primary" href={external}>{env.ios ? 'Safari로 열기' : 'Chrome으로 열기'}</a>
            : <p className="small muted">오른쪽 위(또는 아래) 메뉴에서 <b>다른 브라우저로 열기</b>를 누르세요.</p>}
        </section>
      </Shell>
    )

  // 버튼 한 번: 알림 허용을 먼저 묻고(버튼을 누른 순간에만 물을 수 있음) → 연결 → 허용했으면 알림 구독까지.
  async function accept(token: string, before?: () => Promise<void>) {
    setBusy(true)
    setError(null)
    let permission: NotificationPermission | 'unsupported' = 'unsupported'
    if (env.pushSupported && !demo) { try { permission = await Notification.requestPermission() } catch { permission = 'default' } }
    try {
      if (before) await before()
      const s = await client.claim(token, await claimKey(token))
      setInvite(null)
      if (permission === 'granted') {
        try { await subscribePush(client); s.subscription_status = 'active' } catch { /* 연결은 됐으므로 아래 '알림 허용' 버튼으로 다시 시도 */ }
      }
      setSession({ ...s })
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  if (session === undefined) return <Shell demo={demo}><p className="muted" role="status">연결 확인 중…</p></Shell>
  // 이미 연결된 휴대폰으로 새 초대를 열면(다음 배차 등) 예전 연결 대신 새 초대를 받을지 묻는다.
  // 예전 연결을 끊고(같은 기기 쿠키를 새 연결로 바꿈) 새 초대로 연결한다. 알림 권한은 버튼을 누른 순간 먼저 묻는다.
  const switchTo = (token: string) => accept(token, () => client.leave().then(() => {}, () => {}))
  if (session && invite && !mustInstallFirst(env))
    return (
      <Shell demo={demo}>
        <section className="card">
          <h2>새 배차 초대</h2>
          <p>이 휴대폰을 새 배차 알림에 연결합니다. 예전 연결은 끊깁니다.</p>
          <button type="button" disabled={busy} onClick={() => switchTo(invite)}>{busy ? '연결 중…' : env.pushSupported ? '연결하고 알림 받기' : '연결하기'}</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => setInvite(null)}>예전 연결 유지</button>
        </section>
      </Shell>
    )
  if (session) return <Shell demo={demo}><Connected client={client} session={session} env={env} demo={demo} focus={boot.notification} onLeave={() => setSession(null)} /></Shell>

  const install = mustInstallFirst(env)
  return (
    <Shell demo={demo}>
      <section className="card">
        <h2>배차 알림 연결</h2>
        <p className="small muted">확정된 배차 변경을 이 휴대폰으로 받고 바로 응답합니다.</p>
        {install ? (
          <InstallGuide invite={invite} />
        ) : invite ? (
          <>
            <p>연결하면 이 휴대폰으로 배차 알림을 받습니다. 이름·전화번호는 저장하지 않습니다.</p>
            <button type="button" disabled={busy} onClick={() => accept(invite)}>{busy ? '연결 중…' : env.pushSupported ? '연결하고 알림 받기' : '연결하기'}</button>
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
      <header className="recipient-head"><img className="brand-mark" src="/brand.svg?v=navy1" alt="" width="28" height="28" /> 반입맞춤 기사</header>
      {children}
    </main>
  )
}

function InstallGuide({ invite }: { invite: string | null }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    setCopied(await copyText(inviteUrl(location.origin, invite)))
  }
  return (
    <div className="install-guide">
      <p><b>iPhone은 홈 화면 앱에서 알림을 받습니다.</b></p>
      <ol>
        {invite && <li><button type="button" className="btn-line" onClick={copy}>{copied ? '복사했습니다' : '초대 링크 복사'}</button></li>}
        <li>아래 공유 버튼 <span aria-hidden="true">⬆︎</span> → <b>홈 화면에 추가</b></li>
        <li>홈 화면의 <b>반입맞춤</b>을 열고 <b>붙여넣고 연결</b></li>
      </ol>
      <p className="small muted">iOS 16.4 이상, 초대는 받은 뒤 30분 안에 연결해 주세요.</p>
    </div>
  )
}

function PasteInvite({ busy, onInvite }: { busy: boolean; onInvite: (token: string) => void }) {
  const [text, setText] = useState('')
  const token = inviteFromPaste(text)
  const [pasteNote, setPasteNote] = useState<string | null>(null)
  // 복사해 둔 초대 링크를 한 번에 붙여 넣고 바로 연결한다(붙여넣기 허용은 휴대폰이 묻는다).
  async function pasteAndConnect() {
    setPasteNote(null)
    try {
      const t = inviteFromPaste(await navigator.clipboard.readText())
      if (t) { setText(''); onInvite(t) } else setPasteNote('복사한 내용이 초대 링크가 아닙니다. 받은 메시지에서 링크를 다시 복사해 주세요.')
    } catch { setPasteNote('붙여넣기를 허용하지 않았습니다. 아래 칸에 직접 붙여 넣어 주세요.') }
  }
  return (
    <div className="paste-invite">
      {typeof navigator !== 'undefined' && !!navigator.clipboard && (
        <button type="button" disabled={busy} onClick={pasteAndConnect}>{busy ? '연결 중…' : '붙여넣고 연결'}</button>
      )}
      {pasteNote && <p className="small warn" role="status">{pasteNote}</p>}
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
        <LocationShare client={client} session={session} />
      </section>

      {inbox.error !== undefined && <p className="card warn small" role="alert">알림 목록 조회 실패: {errText(inbox.error)}</p>}
      {inbox.items && !items.length && <p className="card muted">아직 받은 변경이 없습니다.</p>}
      {items.length > 1 && (
        <nav className="card recipient-list" aria-label="받은 변경">
          {items.map((n) => (
            <button key={n.notification_id} type="button" className="secondary" aria-current={n.notification_id === current?.notification_id} onClick={() => setSelected(n.notification_id)}>
              {kstTime(n.created_at)}, {n.is_current ? RESPONSE_LABEL[n.response] : '이전 계획'}
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

// 운행 중 내 위치 보내기: 기사가 직접 켜야 하고, 화면이 열려 있는 동안 1분마다 보낸다. 끄면 서버에서 바로 지운다.
const LOC_PREF = 'banipmatch.shareLocation'
const LOC_EVERY_MS = 60000

function LocationShare({ client, session }: { client: RecipientClient; session: RecipientSession }) {
  const supported = typeof navigator !== 'undefined' && 'geolocation' in navigator
  const [on, setOn] = useState(() => { try { return localStorage.getItem(LOC_PREF) === '1' } catch { return false } })
  const [last, setLast] = useState<string | null>(session.location_captured_at ?? null)
  const [note, setNote] = useState<string | null>(null)
  const save = (v: boolean) => { try { localStorage.setItem(LOC_PREF, v ? '1' : '0') } catch { /* 저장 못 해도 이번 화면에서는 동작 */ } }

  useEffect(() => {
    if (!on || !supported) return
    let alive = true
    const once = () => navigator.geolocation.getCurrentPosition(
      (p) => {
        if (!alive) return
        client.shareLocation({
          latitude: p.coords.latitude, longitude: p.coords.longitude,
          accuracy_m: Math.min(5000, Math.round(p.coords.accuracy ?? 0)), captured_at: new Date(p.timestamp).toISOString(),
        }).then((r) => { if (alive) { setLast(r.captured_at); setNote(null) } },
          (e) => alive && setNote(`위치를 보내지 못했습니다: ${errText(e)}`))
      },
      (err) => {
        if (!alive) return
        if (err.code === err.PERMISSION_DENIED) { setOn(false); save(false); setNote('위치 권한이 꺼져 있습니다. 브라우저(또는 iPhone 설정 → 개인정보 보호 → 위치 서비스)에서 허용해 주세요.') }
        else setNote('지금 위치를 확인하지 못했습니다. 1분 뒤 다시 시도합니다.')
      },
      { enableHighAccuracy: true, maximumAge: 30000, timeout: 20000 },
    )
    once()
    const t = setInterval(once, LOC_EVERY_MS)
    return () => { alive = false; clearInterval(t) }
  }, [on, supported, client])

  async function toggle(next: boolean) {
    setNote(null)
    setOn(next)
    save(next)
    if (!next) {
      try { await client.stopLocation(); setLast(null) } catch (e) { setNote(`위치 지우기 실패: ${errText(e)}`) }
    }
  }

  if (!supported) return null
  return (
    <div className="loc-share">
      <label className="lp-switch">
        <span className="lp-name">운행 중 내 위치 보내기<small>{on ? (last ? `${kstTime(last)} 위치 보냄, 이 화면이 열려 있는 동안 1분마다` : '위치 확인 중…') : '배차 담당자 지도에 내 차량 실제 위치가 보입니다. 끄면 바로 지워집니다.'}</small></span>
        <input type="checkbox" role="switch" checked={on} onChange={(e) => void toggle(e.target.checked)} />
        <i aria-hidden="true" />
      </label>
      {note && <p className="small warn" role="status">{note}</p>}
    </div>
  )
}

/** 알림 구독: 서비스 워커 등록 → 브라우저 구독 → 서버 저장. 권한은 이미 허용된 상태여야 한다. */
async function subscribePush(client: RecipientClient) {
  const config = await client.pushConfig()
  if (!config.configured || !config.application_server_key) throw new Error('알림 서버가 준비되지 않았습니다. 잠시 후 다시 시도하세요.')
  const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
  await navigator.serviceWorker.ready
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlToBytes(config.application_server_key) }))
  return client.subscribe(sub.toJSON())
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
      const saved = await subscribePush(client)
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
        <p className="muted">계획이 바뀐 이전 알림입니다. 최신 알림을 확인하세요.</p>
      </section>
    )
  return (
    <section className="card recipient-detail" aria-labelledby="detail-title">
      <h2 id="detail-title">변경 내용 <span className="rc-when">{kstTime(d.created_at)} 받음</span></h2>
      <p className="rc-lead">담당자가 확정한 배차 변경입니다. 게이트 도착 시각을 지켜 주세요.</p>
      {d.payload.vehicle_changes.map((v) => (
        <div key={v.vehicle_id}>
          <h3><Plate plate={v.plate_no} id={v.vehicle_id} /></h3>
          <ul className="rc-list">
            {/* 기사가 할 일(새로 맡음·시각 변경)을 먼저, 빠진 작업은 맨 아래 */}
            {[...v.changes].sort((x, y) => Number(!!x.before && x.before.vehicle_id === v.vehicle_id && (!x.after || x.after.vehicle_id !== v.vehicle_id)) - Number(!!y.before && y.before.vehicle_id === v.vehicle_id && (!y.after || y.after.vehicle_id !== v.vehicle_id))).map((c) => {
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
                <div className="rc-top"><span className="rc-box">{d?.container_no ? <BoxNo no={d.container_no} /> : name}</span>{d?.size && <span className="rc-size">{d.size}</span>}<span className={`rc-tag ${tone}`}>{tag}</span></div>
                {d?.origin_name && <div className="rc-route">{d.origin_name} → {d.terminal_id} 게이트</div>}
                {outgoing || !c.after ? (
                  <p className="rc-note">{c.kind === 'removed_from_plan' ? '담당자가 확인 중입니다. 별도 연락 전까지 이 작업은 하지 않습니다.' : '다른 차량이 맡습니다. 이 작업은 하지 않습니다.'}</p>
                ) : (
                  <div className="rc-times">
                    <span>상차지 출발 {c.before && mine(c.before.vehicle_id) && c.before.pickup_departure_at !== c.after.pickup_departure_at && <s>{t(c.before.pickup_departure_at)}</s>} <b>{t(c.after.pickup_departure_at)}</b></span>
                    <span>게이트 도착 <b>{t(c.after.gate_arrival_at)}</b></span>
                  </div>
                )}
                {(d?.cargo_owner || d?.voyage_id) && <div className="rc-meta">{[d?.cargo_owner && `화주 ${d.cargo_owner}`, d?.voyage_id && `항차 ${d.voyage_id}`].filter(Boolean).join(', ')}</div>}
              </li>
              )
            })}
          </ul>
        </div>
      ))}

      <h3 className="rc-answer">응답 <span className={`st ${d.response === 'none' ? 'wait' : d.response === 'cannot_perform' ? 'bad' : 'ok'}`}>{d.response === 'none' ? '아직 응답 안 함' : `${RESPONSE_LABEL[d.response]}${d.responded_at ? `, ${kstTime(d.responded_at)}` : ''}`}</span></h3>
      <textarea className="rc-memo" rows={2} maxLength={300} value={note} disabled={busy} onChange={(e) => setNote(e.target.value)} placeholder="메모 (선택)" aria-label="메모" />
      <div className="respond-buttons">
        <button type="button" disabled={busy} className="rb-primary" onClick={() => respond('can_perform')}>수행 가능</button>
        <button type="button" disabled={busy} className="danger" onClick={() => respond('cannot_perform')}>수행 곤란</button>
        <button type="button" disabled={busy} className="rb-ghost" onClick={() => respond('acknowledged')}>내용만 확인함</button>
      </div>
      {sendError !== null && (
        <p className="warn small" role="alert">
          {isCode(sendError, 'NOTIFICATION_SUPERSEDED') ? '그 사이 계획이 바뀌어 이 알림에는 응답할 수 없습니다. 최신 알림을 확인하세요.' : `응답 실패: ${errText(sendError)}`}
        </p>
      )}
    </section>
  )
}
