// 수신자(기사 역할 시험 팀원) 화면의 순수 로직. 초대 비밀은 메모리에만 두고 주소·저장소·로그에 남기지 않는다.

/** 주소 fragment(#invite=… / #notification=…)를 읽는다. 초대가 있으면 호출한 쪽이 즉시 주소에서 지운다. */
export interface Fragment { invite: string | null; notification: string | null }
export function readFragment(hash: string): Fragment {
  const p = new URLSearchParams(hash.replace(/^#/, ''))
  return { invite: p.get('invite'), notification: p.get('notification') }
}

/** 앱 시작 시 한 번만: fragment를 읽고 주소에서 지운다(뒤로 가기·공유·로그로 남지 않게). */
export function takeFragment(): Fragment {
  const f = readFragment(location.hash)
  if (location.hash) history.replaceState(null, '', location.pathname)
  return f
}

/** 붙여넣은 값에서 초대 비밀을 꺼낸다. 전체 링크·`invite=…`·비밀 자체 모두 받는다. */
export function inviteFromPaste(text: string): string | null {
  const t = text.trim()
  if (!t) return null
  const hashAt = t.indexOf('#')
  if (hashAt >= 0) return readFragment(t.slice(hashAt)).invite
  if (t.startsWith('invite=')) return readFragment(t).invite
  return /^[A-Za-z0-9._~-]+$/.test(t) ? t : null
}

/**
 * 같은 초대로 다시 수락할 때 같은 멱등키가 가도록 초대 비밀의 해시로 키를 만든다.
 * (iPhone 홈 화면 앱은 Safari와 쿠키가 달라 재수락이 필요할 수 있다. 키가 다르면 서버가 409 INVITATION_USED.)
 * 키에는 비밀 원문이 아니라 해시만 들어간다.
 */
export async function claimKey(invite: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`claim:${invite}`))
  return `claim-${[...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 40)}`
}

export interface PlatformInfo {
  ios: boolean; standalone: boolean; pushSupported: boolean
  /** 카카오톡·네이버·인스타그램 등 앱 안 브라우저. 알림(웹 푸시)을 받을 수 없다. */
  inApp?: 'kakao' | 'other' | null
}

/** iPhone/iPad의 웹 푸시는 홈 화면에 추가한 웹앱(standalone)에서만 된다. */
export function platform(nav: Navigator, win: Window): PlatformInfo {
  const ua = nav.userAgent
  // iPadOS는 데스크톱 Safari처럼 보이므로 터치 지점 수로 구분한다.
  const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && nav.maxTouchPoints > 1)
  const standalone = win.matchMedia?.('(display-mode: standalone)').matches || (nav as Navigator & { standalone?: boolean }).standalone === true
  const pushSupported = 'serviceWorker' in nav && 'PushManager' in win && 'Notification' in win
  const inApp = /KAKAOTALK/i.test(ua) ? 'kakao' : /NAVER\(inapp|Instagram|FBAN|FBAV|\bLine\/|DaumApps|everytimeApp/i.test(ua) ? 'other' : null
  return { ios, standalone, pushSupported, inApp }
}

/** 초대 링크(비밀은 주소 # 뒤에만 둔다. 서버로 전송되지 않는다). */
export const inviteUrl = (origin: string, invite: string | null) => `${origin}/recipient${invite ? `#invite=${encodeURIComponent(invite)}` : ''}`

/** 카카오톡 안 브라우저에서 기본 브라우저(Chrome·Safari)로 같은 주소를 여는 카카오톡 공식 주소 형식. */
export const kakaoExternal = (url: string) => `kakaotalk://web/openExternal?url=${encodeURIComponent(url)}`

/** iPhone Safari(홈 화면 앱 아님)에서는 여기서 수락하지 말고 홈 화면 앱에서 수락해야 한다. */
export const mustInstallFirst = (p: PlatformInfo) => p.ios && !p.standalone

/** VAPID 공개키(base64url) → applicationServerKey. */
export function base64UrlToBytes(value: string): Uint8Array {
  const b64 = value.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(value.length / 4) * 4, '=')
  const raw = atob(b64)
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}
