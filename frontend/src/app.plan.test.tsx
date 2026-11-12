// @vitest-environment jsdom
// 새로고침 뒤에도 이미 바뀐 현재 계획을 승인 전에 알린다(브라우저 검수 2026-11-09).
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { App } from './App'
import { createFixtureClient } from './api/fixtureClient'
import type { V2Client } from './api/v2'

it('현재 계획 버전이 실행 기준과 다르면 승인 차단 이유를 보여준다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const getPlan = vi.fn().mockResolvedValue({ plan_id: 'P001', version: 2, scenario_id: 'S001', approval_id: 'A1' })
  const client = { ...createFixtureClient(0), getPlan }
  const el = document.createElement('div')
  const root = createRoot(el)
  await act(async () => root.render(<App client={client} scenarioId="S001" runId="R001" />))
  await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
  expect(getPlan).toHaveBeenCalledWith('P001')
  expect(el.textContent).toContain('그사이 배차가 이미 확정·변경되어')
  await act(async () => root.unmount())
})

it('v2 확정 후에는 이전 입력 편집 대신 확정 원안으로 새 점검을 시작하게 한다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const client = { ...createFixtureClient(0), session: vi.fn().mockResolvedValue({ push_test_authorized: false }),
    get: vi.fn().mockRejectedValue(new Error('preview unavailable')),
    getPlan: vi.fn().mockResolvedValue({ plan_id: 'P001', version: 2, scenario_id: 'S001', approval_id: 'A1' }),
  } as unknown as V2Client
  const el = document.createElement('div'); const root = createRoot(el)
  await act(async () => root.render(<App client={client} scenarioId="S001" runId="R001" />))
  await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
  expect(el.textContent).toContain('확정한 배차로 새 점검')
  expect(el.textContent).not.toContain('조건 보완 · 재계산')
  await act(async () => root.unmount())
})

it('계획 버전이 바뀌어도 변경 전달 카드는 하나만 남는다(같은 형제 키 금지)', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const make = (version: number) => ({ ...createFixtureClient(0), session: vi.fn().mockResolvedValue({ push_test_authorized: false }),
    get: vi.fn().mockReturnValue(new Promise(() => {})),
    getPlan: vi.fn().mockResolvedValue({ plan_id: 'P001', version, scenario_id: 'S001', approval_id: 'A1' }),
  } as unknown as V2Client)
  const el = document.createElement('div'); const root = createRoot(el)
  await act(async () => root.render(<App client={make(2)} scenarioId="S001" runId="R001" />))
  await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
  await act(async () => root.render(<App client={make(3)} scenarioId="S001" runId="R001" />))
  await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
  expect(el.querySelectorAll('section.card.dispatch')).toHaveLength(1)
  await act(async () => root.unmount())
})
