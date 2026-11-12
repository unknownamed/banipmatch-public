// 카카오톡 등 앱 안 브라우저 감지와 기본 브라우저로 넘기는 주소. 초대 비밀은 주소 # 뒤에만 있다.
import { expect, it } from 'vitest'
import { inviteFromPaste, inviteUrl, kakaoExternal, platform } from './recipient'

const nav = (ua: string) => ({ userAgent: ua, maxTouchPoints: 5 }) as unknown as Navigator
const win = { matchMedia: () => ({ matches: false }) } as unknown as Window

it('카카오톡·기타 앱 안 브라우저를 구분한다', () => {
  expect(platform(nav('Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile Safari/537.36 KAKAOTALK 10.4.5'), win).inApp).toBe('kakao')
  expect(platform(nav('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Instagram 300.0'), win).inApp).toBe('other')
  expect(platform(nav('Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile Safari/537.36'), win).inApp).toBeNull()
})

it('기본 브라우저로 넘기는 주소에도 초대가 그대로 남고, 다시 꺼낼 수 있다', () => {
  const url = inviteUrl('https://banipmatch.duckdns.org', 'abc.DEF-123_~')
  expect(url).toBe('https://banipmatch.duckdns.org/recipient#invite=abc.DEF-123_~')
  const ext = kakaoExternal(url)
  expect(ext.startsWith('kakaotalk://web/openExternal?url=')).toBe(true)
  expect(inviteFromPaste(decodeURIComponent(ext.split('url=')[1]))).toBe('abc.DEF-123_~')
  expect(inviteUrl('https://x', null)).toBe('https://x/recipient')
})
