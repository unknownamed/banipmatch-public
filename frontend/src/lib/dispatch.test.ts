import { describe, expect, it } from 'vitest'
import { invitationLink, linkedRecipientFor, retryBlocker, type NotificationState, type RecipientSummary } from './dispatch'

const n = (over: Partial<NotificationState>): NotificationState => ({
  notification_id: 'N', recipient_id: 'r', delivery_status: 'failed', error_code: null, attempts: 1, accepted_at: null, opened_at: null,
  response: 'none', responded_at: null, is_current: true, vehicle_ids: ['T1'], needs_followup: true, retry_not_before: null, response_history: [], ...over,
})

describe('전달 재시도', () => {
  const now = Date.parse('2026-11-11T05:00:00Z')
  it('접수·불명은 재시도 버튼 대상이 아니다(중복 수신 방지)', () => {
    expect(retryBlocker(n({ delivery_status: 'accepted' }), now)).toBeNull()
    expect(retryBlocker(n({ delivery_status: 'unknown' }), now)).toBeNull()
  })
  it('확실한 실패만 재시도할 수 있고 3회·대기 시각·이전 계획은 막는다', () => {
    expect(retryBlocker(n({}), now)).toBe('')
    expect(retryBlocker(n({ attempts: 3 }), now)).toMatch('세 번')
    expect(retryBlocker(n({ retry_not_before: '2026-11-11T05:01:00Z' }), now)).toMatch('잠시 뒤 다시 보낼 수 있습니다')
    expect(retryBlocker(n({ is_current: false }), now)).toMatch('이전 계획')
  })
})

describe('미연결 재시도 대상', () => {
  const r = (over: Partial<RecipientSummary>): RecipientSummary => ({ recipient_id: 'R1', plan_id: 'P', expires_at: '', revoked: false, vehicle_ids: ['T1'], subscription_status: 'active', ...over })
  it('차량을 모두 맡고 구독 중인 수신자만 고른다', () => {
    expect(linkedRecipientFor(['T1'], [r({})])).toBe('R1')
    expect(linkedRecipientFor(['T1'], [r({ revoked: true })])).toBeNull()
    expect(linkedRecipientFor(['T1'], [r({ subscription_status: 'missing' })])).toBeNull()
    expect(linkedRecipientFor(['T1', 'T2'], [r({})])).toBeNull()
  })
})

it('초대 비밀은 query가 아니라 fragment에 둔다', () => {
  const link = invitationLink('https://example.test', 'a.b+c')
  expect(link).toBe('https://example.test/recipient#invite=a.b%2Bc')
  expect(new URL(link).search).toBe('')
})
