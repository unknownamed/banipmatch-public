import { describe, expect, it } from 'vitest'
import { issueText } from './issueText'

describe('issueText', () => {
  it('준비 지연 설명을 몇 분 늦는지로 풀어 쓴다', () => {
    const raw = '준비 2026-11-12T17:30:00Z + 터미널까지 운송 40분 + 여유 10분 = 2026-11-12T18:20:00Z > 마감 2026-11-12T18:00:00Z. 다른 작업을 모두 빼도 마감 안에 들어갈 수 없습니다.'
    const text = issueText('READY_TOO_LATE', raw)
    expect(text).toContain('02:30')
    expect(text).toContain('03:20')
    expect(text).toContain('반입 마감 03:00보다 20분 늦습니다')
    expect(text).not.toContain('>')
  })
  it('형식이 다르거나 다른 이유면 원문 시각만 바꿔 그대로 둔다', () => {
    expect(issueText('READY_TOO_LATE', '알 수 없는 형식')).toBe('알 수 없는 형식')
    expect(issueText('SHIFT_EXCEEDED', '근무 종료 2026-11-12T18:00:00Z 초과')).toBe('근무 종료 03:00 초과')
  })
})
