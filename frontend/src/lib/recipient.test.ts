// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { base64UrlToBytes, claimKey, inviteFromPaste, mustInstallFirst, platform, readFragment } from './recipient'

describe('초대 읽기', () => {
  it('fragment에서 초대·알림 ID를 읽는다', () => {
    expect(readFragment('#invite=a.b')).toEqual({ invite: 'a.b', notification: null })
    expect(readFragment('#notification=N-1')).toEqual({ invite: null, notification: 'N-1' })
  })
  it('붙여넣은 링크·invite=·비밀 자체를 모두 받고 엉뚱한 글은 거절한다', () => {
    expect(inviteFromPaste(' https://x.test/recipient#invite=a.b_c ')).toBe('a.b_c')
    expect(inviteFromPaste('invite=a.b')).toBe('a.b')
    expect(inviteFromPaste('a.b')).toBe('a.b')
    expect(inviteFromPaste('안녕하세요 링크 보내요')).toBeNull()
    expect(inviteFromPaste('')).toBeNull()
  })
})

describe('수락 멱등키', () => {
  it('같은 초대는 같은 키, 다른 초대는 다른 키이며 원문을 담지 않는다', async () => {
    const a = await claimKey('secret.one')
    expect(await claimKey('secret.one')).toBe(a)
    expect(await claimKey('secret.two')).not.toBe(a)
    expect(a).not.toContain('secret')
  })
  it('같은 초대라도 다른 휴대폰이면 다른 키라서 링크는 처음 연결한 휴대폰만 쓸 수 있다', async () => {
    const a = await claimKey('secret.one')
    localStorage.setItem('banipmatch.device', 'other-phone')
    expect(await claimKey('secret.one')).not.toBe(a)
  })
})

describe('iPhone 판별', () => {
  const nav = (ua: string, touch = 0, standalone?: boolean) => ({ userAgent: ua, maxTouchPoints: touch, standalone }) as unknown as Navigator
  const win = (matches: boolean) => ({ matchMedia: () => ({ matches }) }) as unknown as Window
  it('iPhone Safari는 홈 화면 추가가 먼저다', () => {
    expect(mustInstallFirst(platform(nav('iPhone OS 17'), win(false)))).toBe(true)
    expect(mustInstallFirst(platform(nav('iPhone OS 17', 5, true), win(false)))).toBe(false)
    expect(mustInstallFirst(platform(nav('Macintosh', 5), win(true)))).toBe(false)
  })
  it('Android·데스크톱은 바로 수락할 수 있다', () => {
    expect(mustInstallFirst(platform(nav('Android 14 Chrome'), win(false)))).toBe(false)
    expect(mustInstallFirst(platform(nav('Macintosh', 0), win(false)))).toBe(false)
  })
})

it('base64url 공개키를 바이트로 바꾼다', () => {
  expect([...base64UrlToBytes('AQID_w')]).toEqual([1, 2, 3, 255])
})
