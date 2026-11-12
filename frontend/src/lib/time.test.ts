import { expect, it } from 'vitest'
import { humanizeTimes } from './time'

// PR #73(길웅) 아이디어: 서버 설명문 안의 UTC 시각만 KST로 바꾸고 나머지 글자는 그대로 둔다.
it('설명문 안의 UTC 시각만 KST로 바꾼다', () => {
  expect(humanizeTimes('마감 2026-11-12T09:34:00Z 이후 준비')).toBe('마감 18:34 이후 준비')
  expect(humanizeTimes('시각 없음 J3')).toBe('시각 없음 J3')
})
