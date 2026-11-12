// @vitest-environment jsdom
// 기사 위치 보내기: 기사가 켜야만 보내고, 끄면 서버에서 지우며, 권한이 거부되면 꺼진다. 담당자 지도용 저장소는 해제된 연결 위치를 버린다.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiRequestError } from '../api/client'
import type { RecipientClient, RecipientSession } from '../api/recipient'
import { takeFragment, type PlatformInfo } from '../lib/recipient'
import { publishDriverLocations, useDriverLocations } from '../lib/driverLocations'
import { RecipientApp } from './RecipientApp'

const env: PlatformInfo = { ios: false, standalone: false, pushSupported: false }
const session: RecipientSession = { recipient_id: 'r', vehicle_ids: ['T1'], expires_at: '2026-11-14T00:00:00Z', csrf_token: 'c', subscription_status: 'missing', data_mode: 'simulated' }
let container: HTMLDivElement
let root: Root
let position: ((p: unknown) => void) | null = null
let failure: ((e: unknown) => void) | null = null

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  localStorage.clear()
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
    getCurrentPosition: (ok: (p: unknown) => void, bad: (e: unknown) => void) => { position = ok; failure = bad },
  } })
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.restoreAllMocks()
})

function client(over: Partial<RecipientClient> = {}) {
  return {
    restore: vi.fn().mockResolvedValue(session), inbox: vi.fn().mockResolvedValue({ notifications: [] }),
    claim: vi.fn(), notification: vi.fn(), opened: vi.fn(), respond: vi.fn(), leave: vi.fn(), pushConfig: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn(),
    shareLocation: vi.fn().mockImplementation(async (p: { captured_at: string }) => ({ location_shared: true, captured_at: p.captured_at })),
    stopLocation: vi.fn().mockResolvedValue({ location_shared: false, captured_at: null }),
    ...over,
  } as unknown as RecipientClient
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const toggle = () => container.querySelector<HTMLInputElement>('.loc-share input[role=switch]')!

it('기사가 켜기 전에는 위치를 묻거나 보내지 않고, 켜면 보내고 끄면 지운다', async () => {
  const c = client()
  await act(async () => root.render(<RecipientApp client={c} boot={takeFragment()} env={env} />))
  await flush()
  expect(toggle().checked).toBe(false)
  expect(position).toBeNull()
  await act(async () => toggle().click())
  await act(async () => position!({ coords: { latitude: 35.07, longitude: 128.82, accuracy: 12 }, timestamp: Date.parse('2026-11-13T01:00:00Z') }))
  await flush()
  expect(c.shareLocation).toHaveBeenCalledWith({ latitude: 35.07, longitude: 128.82, accuracy_m: 12, captured_at: '2026-11-13T01:00:00.000Z' })
  expect(localStorage.getItem('banipmatch.shareLocation')).toBe('1')
  await act(async () => toggle().click())
  await flush()
  expect(c.stopLocation).toHaveBeenCalledTimes(1)
  expect(toggle().checked).toBe(false)
})

it('위치 권한을 거부하면 스위치가 꺼지고 이유를 보여 준다', async () => {
  const c = client()
  await act(async () => root.render(<RecipientApp client={c} boot={takeFragment()} env={env} />))
  await flush()
  await act(async () => toggle().click())
  await act(async () => failure!({ code: 1, PERMISSION_DENIED: 1 }))
  expect(toggle().checked).toBe(false)
  expect(container.textContent).toContain('위치 권한이 꺼져 있습니다')
  expect(c.shareLocation).not.toHaveBeenCalled()
})

it('전송 실패는 숨기지 않는다', async () => {
  const c = client({ shareLocation: vi.fn().mockRejectedValue(new ApiRequestError(422, { code: 'LOCATION_STALE', message: '10분 안에 측정한 위치만 받음' })) })
  await act(async () => root.render(<RecipientApp client={c} boot={takeFragment()} env={env} />))
  await flush()
  await act(async () => toggle().click())
  await act(async () => position!({ coords: { latitude: 35.07, longitude: 128.82, accuracy: 12 }, timestamp: Date.now() }))
  await flush()
  expect(container.textContent).toContain('위치를 보내지 못했습니다')
})

it('담당자 지도용 위치는 해제된 연결을 버리고 차량별로 나눈다', async () => {
  const loc = { latitude: 35.1, longitude: 128.8, accuracy_m: 10, captured_at: '2026-11-13T01:00:00Z', received_at: '2026-11-13T01:00:02Z' }
  let renders = 0
  function Probe() { renders++; return <p>{[...useDriverLocations().keys()].join(',')}</p> }
  await act(async () => root.render(<Probe />))
  await act(async () => publishDriverLocations([{ revoked: false, vehicle_ids: ['T1', 'T2'], location: loc }, { revoked: true, vehicle_ids: ['T3'], location: loc }, { revoked: false, vehicle_ids: ['T4'], location: null }]))
  expect(container.textContent).toBe('T1,T2')
  const before = renders
  await act(async () => publishDriverLocations([{ revoked: false, vehicle_ids: ['T1', 'T2'], location: { ...loc } }]))
  expect(renders).toBe(before)
  await act(async () => publishDriverLocations([]))
  expect(container.textContent).toBe('')
})
