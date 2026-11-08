// @vitest-environment jsdom
// 새로고침 뒤에도 이미 바뀐 현재 계획을 승인 전에 알린다(브라우저 검수 2026-11-09).
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { App } from './App'
import { createFixtureClient } from './api/fixtureClient'

it('현재 계획 버전이 실행 기준과 다르면 승인 차단 이유를 보여준다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const getPlan = vi.fn().mockResolvedValue({ plan_id: 'P001', version: 2, scenario_id: 'S001', approval_id: 'A1' })
  const client = { ...createFixtureClient(0), getPlan }
  const el = document.createElement('div')
  const root = createRoot(el)
  await act(async () => root.render(<App client={client} scenarioId="S001" runId="R001" />))
  await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
  expect(getPlan).toHaveBeenCalledWith('P001')
  expect(el.textContent).toContain('현재 계획이 v2입니다')
  await act(async () => root.unmount())
})
