// @vitest-environment jsdom
// 수신자 화면: 초대 비밀을 주소에서 지움, iPhone Safari는 수락 대신 홈 화면 안내, 이전 계획은 응답 불가, 명시 응답.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError } from '../api/client'
import type { RecipientClient, RecipientNotification, RecipientSession } from '../api/recipient'
import { claimKey, takeFragment, type PlatformInfo } from '../lib/recipient'
import { RecipientApp } from './RecipientApp'
import { createDemoRecipientClient } from '../api/recipientDemo'

const android: PlatformInfo = { ios: false, standalone: false, pushSupported: false }
const iphoneSafari: PlatformInfo = { ios: true, standalone: false, pushSupported: false }
const session: RecipientSession = { recipient_id: 'r', vehicle_ids: ['T1'], expires_at: '2026-11-12T00:00:00Z', csrf_token: 'c', subscription_status: 'missing', data_mode: 'simulated' }
const note = (over: Partial<RecipientNotification>): RecipientNotification => ({
  notification_id: 'N1', delivery_status: 'accepted', created_at: '2026-11-11T05:00:00Z', opened_at: null, response: 'none', responded_at: null,
  is_current: true, vehicle_ids: ['T1'], response_history: [],
  payload: { plan_version: 2, data_mode: 'simulated', vehicle_changes: [{ vehicle_id: 'T1', changes: [{ job_id: 'J2', kind: 'reassigned', before: null, before_outside_scope: true, after: { vehicle_id: 'T1', pickup_departure_at: '2026-11-11T05:42:00Z', gate_arrival_at: '2026-11-11T06:12:00Z' }, instruction: '' }] }] },
  ...over,
})
const required = () => new ApiRequestError(401, { code: 'RECIPIENT_REQUIRED', message: '' })

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  history.replaceState(null, '', '/')
  vi.restoreAllMocks()
})

function fake(over: Partial<RecipientClient> = {}) {
  return {
    restore: vi.fn().mockRejectedValue(required()),
    claim: vi.fn().mockResolvedValue(session),
    inbox: vi.fn().mockResolvedValue({ notifications: [] }),
    notification: vi.fn(),
    opened: vi.fn().mockImplementation(async () => note({ opened_at: '2026-11-11T05:01:00Z' })),
    respond: vi.fn().mockImplementation(async (_id: string, response: RecipientNotification['response']) => note({ response, responded_at: '2026-11-11T05:02:00Z' })),
    leave: vi.fn(), pushConfig: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn(),
    ...over,
  } as unknown as RecipientClient
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const button = (text: string) => [...container.querySelectorAll('button')].find((b) => b.textContent === text)

describe('수신자 화면', () => {
  it('목록 갱신에서 이전 계획이 되면 같은 알림 상세와 응답을 즉시 가린다', async () => {
    let poll: (() => void) | undefined
    vi.spyOn(globalThis, 'setInterval').mockImplementation(((fn: () => void) => { poll = fn; return 0 }) as never)
    const inbox = vi.fn().mockResolvedValueOnce({ notifications: [note({})] }).mockResolvedValue({ notifications: [note({ is_current: false, payload: null })] })
    const client = fake({ restore: vi.fn().mockResolvedValue(session), inbox, notification: vi.fn().mockResolvedValue(note({})) })
    await act(async () => root.render(<RecipientApp client={client} boot={takeFragment()} env={android} />))
    await flush()
    expect(button('수행 가능')).toBeDefined()
    await act(async () => { poll!() })
    await flush()
    expect(button('수행 가능')).toBeUndefined()
    expect(container.textContent).toContain('이전 계획의 알림')
  })

  it('연결 해제 실패는 연결 상태를 유지하고 실패를 알린다', async () => {
    const client = fake({ restore: vi.fn().mockResolvedValue(session), leave: vi.fn().mockRejectedValue(new Error('offline')) })
    await act(async () => root.render(<RecipientApp client={client} boot={takeFragment()} env={android} />))
    await flush()
    await act(async () => button('이 기기 연결 해제')!.click())
    expect(container.textContent).toContain('내 차량 T1')
    expect(container.textContent).toContain('연결 해제 실패')
  })

  it('응답이 유실돼 같은 내용을 다시 보내면 같은 키를 사용한다', async () => {
    const respond = vi.fn().mockRejectedValueOnce(new Error('response lost')).mockResolvedValue(note({ response: 'can_perform' }))
    const client = fake({ restore: vi.fn().mockResolvedValue(session), inbox: vi.fn().mockResolvedValue({ notifications: [note({})] }), notification: vi.fn().mockResolvedValue(note({})), respond })
    await act(async () => root.render(<RecipientApp client={client} boot={takeFragment()} env={android} />))
    await flush()
    await act(async () => button('수행 가능')!.click())
    await act(async () => button('수행 가능')!.click())
    expect(respond).toHaveBeenCalledTimes(2)
    expect(respond.mock.calls[0]).toEqual(respond.mock.calls[1])
  })

  it('초대 비밀을 주소에서 지우고, 같은 초대에는 해시 기반 같은 키로 수락한다', async () => {
    history.replaceState(null, '', '/recipient#invite=sec.ret')
    const client = fake()
    await act(async () => root.render(<RecipientApp client={client} boot={takeFragment()} env={android} />))
    await flush()
    expect(location.hash).toBe('')
    await act(async () => button('초대 수락')!.click())
    await flush()
    expect(client.claim).toHaveBeenCalledWith('sec.ret', await claimKey('sec.ret'))
    expect(container.textContent).toContain('내 차량 T1')
    expect(container.textContent).toContain('알림을 지원하지 않습니다')
  })

  it('iPhone Safari에서는 수락 버튼 대신 홈 화면 추가 안내만 보여준다', async () => {
    history.replaceState(null, '', '/recipient#invite=sec.ret')
    const client = fake()
    await act(async () => root.render(<RecipientApp client={client} boot={takeFragment()} env={iphoneSafari} />))
    await flush()
    expect(container.textContent).toContain('홈 화면에 추가')
    expect(button('초대 수락')).toBeUndefined()
    expect(client.claim).not.toHaveBeenCalled()
  })

  it('이미 쓴 초대는 iPhone 쿠키 분리 안내와 함께 알린다', async () => {
    const client = fake({ claim: vi.fn().mockRejectedValue(new ApiRequestError(409, { code: 'INVITATION_USED', message: '' })) })
    history.replaceState(null, '', '/recipient#invite=sec.ret')
    await act(async () => root.render(<RecipientApp client={client} boot={takeFragment()} env={android} />))
    await flush()
    await act(async () => button('초대 수락')!.click())
    await flush()
    expect(container.textContent).toContain('홈 화면 앱에서 수락해야 합니다')
  })

  it('최신 알림은 열람 기록 후 내 차량 변경만 보이고, 응답은 명시적으로 보낸다', async () => {
    const client = fake({ restore: vi.fn().mockResolvedValue(session), inbox: vi.fn().mockResolvedValue({ notifications: [note({})] }), notification: vi.fn().mockResolvedValue(note({})) })
    await act(async () => root.render(<RecipientApp client={client} boot={takeFragment()} env={android} />))
    await flush()
    await flush()
    expect(client.opened).toHaveBeenCalledWith('N1')
    expect(container.textContent).toContain('다른 차량(상세 비공개)')
    expect(container.textContent).toContain('응답 없음')
    await act(async () => button('수행 곤란')!.click())
    await flush()
    expect(client.respond).toHaveBeenCalledWith('N1', 'cannot_perform', '', expect.stringMatching(/^respond-N1-/))
    expect(container.textContent).toContain('수행 곤란 · 후속 확인')
  })

  it('이전 계획(payload 없음)은 상세를 보여주지 않고 응답 버튼도 없다', async () => {
    const old = note({ is_current: false, payload: null, delivery_status: 'superseded' })
    const client = fake({ restore: vi.fn().mockResolvedValue(session), inbox: vi.fn().mockResolvedValue({ notifications: [old] }), notification: vi.fn().mockResolvedValue(old) })
    await act(async () => root.render(<RecipientApp client={client} boot={takeFragment()} env={android} />))
    await flush()
    await flush()
    expect(container.textContent).toContain('이전 계획의 알림')
    expect(button('수행 가능')).toBeUndefined()
    expect(client.opened).not.toHaveBeenCalled()
  })

  it('모의 링크는 서버 없이 수락→변경→응답까지 보여주고 모의임을 밝힌다', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    await act(async () => root.render(<RecipientApp client={createDemoRecipientClient()} boot={{ invite: 'demo-invite', notification: null }} env={android} demo />))
    await flush()
    expect(container.textContent).toContain('모의 화면입니다')
    await act(async () => button('초대 수락')!.click())
    await flush()
    await flush()
    expect(container.textContent).toContain('J2')
    await act(async () => button('수행 가능')!.click())
    await flush()
    expect(container.textContent).toContain('현재: 수행 가능')
    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })

  it('목록에서 이전 계획이 된 알림은 상세가 아직 최신으로 와도 가린다', async () => {
    const client = fake({ restore: vi.fn().mockResolvedValue(session), inbox: vi.fn().mockResolvedValue({ notifications: [note({ is_current: false, payload: null })] }), notification: vi.fn().mockResolvedValue(note({})) })
    await act(async () => root.render(<RecipientApp client={client} boot={{ invite: null, notification: 'N1' }} env={android} />))
    await flush()
    await flush()
    expect(container.textContent).toContain('이전 계획의 알림')
    expect(button('수행 가능')).toBeUndefined()
  })

  it('응답 중 NOTIFICATION_SUPERSEDED면 상세와 응답 버튼을 바로 지운다', async () => {
    const client = fake({
      restore: vi.fn().mockResolvedValue(session), inbox: vi.fn().mockResolvedValue({ notifications: [note({})] }), notification: vi.fn().mockResolvedValue(note({})),
      respond: vi.fn().mockRejectedValue(new ApiRequestError(409, { code: 'NOTIFICATION_SUPERSEDED', message: '' })),
    })
    await act(async () => root.render(<RecipientApp client={client} boot={{ invite: null, notification: null }} env={android} />))
    await flush()
    await flush()
    await act(async () => button('수행 가능')!.click())
    await flush()
    expect(container.textContent).toContain('이전 계획의 알림')
    expect(button('수행 가능')).toBeUndefined()
  })

  it('연결 해제가 실패하면 화면을 바꾸지 않고 다시 시도하게 한다', async () => {
    const client = fake({ restore: vi.fn().mockResolvedValue(session), leave: vi.fn().mockRejectedValue(new Error('network')) })
    await act(async () => root.render(<RecipientApp client={client} boot={{ invite: null, notification: null }} env={android} />))
    await flush()
    await act(async () => button('이 기기 연결 해제')!.click())
    await flush()
    expect(container.textContent).toContain('내 차량 T1')
    expect(container.textContent).toContain('연결 해제 실패')
  })

  it('메모는 서버 한도와 같은 300자까지만 받는다', async () => {
    const client = fake({ restore: vi.fn().mockResolvedValue(session), inbox: vi.fn().mockResolvedValue({ notifications: [note({})] }), notification: vi.fn().mockResolvedValue(note({})) })
    await act(async () => root.render(<RecipientApp client={client} boot={{ invite: null, notification: null }} env={android} />))
    await flush()
    await flush()
    expect(container.querySelector('textarea')!.maxLength).toBe(300)
  })
})

