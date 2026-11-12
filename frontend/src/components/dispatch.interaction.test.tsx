// @vitest-environment jsdom
// 승인 이후 전달 화면: 허가 없는 세션 차단, 초대 링크(fragment), 명시 전달(같은 승인 = 같은 멱등키), 대상별 상태.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SessionState, V2Client } from '../api/v2'
import type { DispatchPreview, DispatchState } from '../lib/dispatch'
import { DispatchPanel } from './DispatchPanel'

const preview: DispatchPreview = {
  plan_id: 'P1', scenario_id: 'S1', method: 'B1', data_mode: 'simulated', approval_id: 'A1', approved_version: 2, run_id: 'R1',
  unassigned_job_ids: ['J3'], limits: ['모의 검수'],
  followups: [{ code: 'READY_TOO_LATE', job_id: 'J3', check_next: '상차 준비 완료 시각을 확인하세요.', contact_role: '화주' }],
  vehicle_changes: [
    { vehicle_id: 'T1', recipient_id: null, recipient_status: 'unlinked', followups: [], changes: [{ job_id: 'J1', kind: 'reassigned', before: { vehicle_id: 'T1' }, after: { vehicle_id: 'T2' }, instruction: '' }] },
  ],
}
const dispatch: DispatchState = {
  dispatch_id: 'D1', plan_version: 2, is_current: true, external_transport_completed: false, followups: [],
  notifications: [
    { notification_id: 'N1', recipient_id: 'R', delivery_status: 'accepted', error_code: null, attempts: 1, accepted_at: '2026-11-11T05:00:00Z', opened_at: null, response: 'none', responded_at: null, is_current: true, vehicle_ids: ['T1'], needs_followup: true, retry_not_before: null, response_history: [] },
    { notification_id: 'N2', recipient_id: null, delivery_status: 'failed', error_code: 'PUSH_REJECTED', attempts: 1, accepted_at: null, opened_at: null, response: 'none', responded_at: null, is_current: true, vehicle_ids: ['T2'], needs_followup: true, retry_not_before: null, response_history: [] },
  ],
}
const session = (authorized: boolean) => ({ push_test_authorized: authorized, csrf_token: 'c' }) as SessionState

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  history.replaceState(null, '', '/')
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

function fakeClient(authorized: boolean) {
  const post = vi.fn(async (path: string) => {
    if (path === '/v2/invitations') return { invitation_id: 'I1', invitation_token: 'tok.en', expires_at: '2026-11-11T05:30:00Z' }
    if (path.endsWith('/dispatches')) return { dispatch_id: 'D1' }
    return {}
  })
  const get = vi.fn(async (path: string) => {
    if (path.endsWith('/dispatch-preview')) return preview
    if (path === '/v2/recipients') return { recipients: [] }
    if (path === '/v2/dispatches/D1') return dispatch
    throw new Error(path)
  })
  return { client: { session: vi.fn().mockResolvedValue(session(authorized)), get, post } as unknown as V2Client, post }
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const clickText = async (text: string) => {
  const el = [...container.querySelectorAll('button, label')].find((b) => b.textContent?.includes(text)) as HTMLElement
  await act(async () => (el.tagName === 'LABEL' ? el.querySelector('input')! : el).click())
}

describe('변경 전달 화면', () => {
  it('허가 없는 세션은 명세·확인할 사항만 보이고 초대·전달 버튼이 없다', async () => {
    const { client } = fakeClient(false)
    await act(async () => root.render(<DispatchPanel client={client} planId="P1" />))
    await flush()
    expect(container.textContent).toContain('J1 · 차량 변경')
    expect(container.textContent).toContain('상차 준비 완료 시각을 확인하세요.')
    expect(container.textContent).toContain('앱 알림 발송 권한이 없습니다')
    expect(container.textContent).not.toContain('연결 링크 만들기')
    expect([...container.querySelectorAll('button')].some((b) => b.textContent === '기사에게 보내기')).toBe(false)
  })

  it('동의 체크 후 초대를 만들고 비밀은 fragment 링크로만 보여준다', async () => {
    const { client, post } = fakeClient(true)
    await act(async () => root.render(<DispatchPanel client={client} planId="P1" />))
    await flush()
    await clickText('T1')
    expect(container.querySelector<HTMLButtonElement>('fieldset.invite button')!.disabled).toBe(true)
    await clickText('이 차량 기사에게만 연결 링크')
    await clickText('연결 링크 만들기')
    await flush()
    expect(post).toHaveBeenCalledWith('/v2/invitations', { plan_id: 'P1', vehicle_ids: ['T1'], consent_acknowledged: true }, expect.stringMatching(/^invite-/))
    const link = container.querySelector<HTMLInputElement>('.invite-link input')!.value
    expect(link).toMatch(/\/recipient#invite=tok\.en$/)
    expect(location.search).not.toContain('tok')
  })

  it('확인 후에만 전달하고, 같은 승인은 같은 멱등키, 접수는 읽음이 아니며 실패만 다시 보낼 수 있다', async () => {
    const { client, post } = fakeClient(true)
    await act(async () => root.render(<DispatchPanel client={client} planId="P1" />))
    await flush()
    const sendButton = () => [...container.querySelectorAll('button')].find((b) => b.textContent === '기사에게 보내기')!
    expect(sendButton().disabled).toBe(true)
    await clickText('기사 휴대폰으로 보냅니다')
    await act(async () => sendButton().click())
    await flush()
    expect(post).toHaveBeenCalledWith('/v2/plans/P1/dispatches', { approval_id: 'A1', expected_version: 2, confirm_test_send: true }, 'dispatch-A1')
    expect(location.search).toContain('dispatch=D1')
    const rows = [...container.querySelectorAll('.dispatch-status tbody tr')].map((r) => r.textContent)
    expect(rows[0]).toContain('중계망 접수 · 읽음 아님')
    expect(rows[0]).not.toContain('다시 보내기')
    expect(rows[1]).toContain('전송 실패')
    expect(rows[1]).toContain('다시 보내기')
  })
})
