// @vitest-environment jsdom
// 조건 보완 재시도: 분이 바뀌어도 첫 본문을 그대로 쓰고, 저장이 끝났으면 계산만 다시 한다(PR #64 리뷰 P1).
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import snapshotJson from '@examples/01_snapshot.json'
import type { Method, Snapshot } from '../api/types'
import type { V2Client } from '../api/v2'
import { ConditionRevisionPanel, NextInputCard } from './RevisionPanels'

const snapshot = snapshotJson as unknown as Snapshot
const rerun = { methods: ['B0', 'B1'] as Method[], time_limit_seconds: 10, seed: 42 }
let container: HTMLDivElement
let root: Root

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.useFakeTimers({ toFake: ['Date'] })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.useRealTimers()
})

const flush = () => act(async () => { await Promise.resolve() })
const type = async (el: HTMLInputElement | HTMLTextAreaElement, value: string) => {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const submitButton = () => [...container.querySelectorAll<HTMLButtonElement>('.revision > button')].find((b) => /재계산|다시 시도/.test(b.textContent ?? ''))!

it('재시도는 같은 본문을 쓰고, 저장이 끝났으면 계산만 같은 키로 다시 보낸다', async () => {
  vi.setSystemTime(new Date('2026-11-07T00:05:30Z'))
  const post = vi.fn().mockResolvedValue({ scenario_id: 'S-new', plan_id: 'P001', base_plan_version: 1, revision_id: 'V1', confirmation: 'confirmed_simulation' })
  const createRun = vi.fn().mockRejectedValueOnce(new Error('network')).mockRejectedValueOnce(new Error('network again'))
  const client = { post, createRun } as unknown as V2Client
  await act(async () => root.render(<ConditionRevisionPanel client={client} snapshot={snapshot} rerun={{ ...rerun, beforeRunId: 'R0' }} />))
  const job = snapshot.jobs.find((j) => !j.frozen)!
  const row = [...container.querySelectorAll('.rev-row')].find((r) => r.querySelector('b')?.textContent === job.job_id)!
  await type(row.querySelector<HTMLInputElement>('input[aria-label="시각(24시간제)"]')!, '09:31')
  await type(container.querySelector('textarea')!, '확인')
  await act(async () => submitButton().click())
  await flush()
  vi.setSystemTime(new Date('2026-11-07T00:07:10Z')) // 분이 바뀜
  await act(async () => submitButton().click())
  await flush()
  expect(post).toHaveBeenCalledTimes(1)
  expect(createRun).toHaveBeenCalledTimes(2)
  expect(createRun.mock.calls[0][1]).toBe(createRun.mock.calls[1][1])
})

it('승인 뒤 새 원안은 한 번 받은 원안·키로 등록과 계산을 재시도한다', async () => {
  const next = { ...snapshot, scenario_id: 'S-next', base_plan_version: 2 }
  const get = vi.fn().mockResolvedValue(next)
  const registerScenario = vi.fn().mockResolvedValue({ scenario_id: 'S-next', plan_id: 'P001' })
  const createRun = vi.fn().mockRejectedValueOnce(new Error('network')).mockRejectedValueOnce(new Error('again'))
  const client = { get, registerScenario, createRun } as unknown as V2Client
  await act(async () => root.render(<NextInputCard client={client} planId="P001" rerun={rerun} />))
  const btn = () => container.querySelector<HTMLButtonElement>('.revision button')!
  await act(async () => btn().click())
  await flush()
  await act(async () => btn().click())
  await flush()
  expect(get).toHaveBeenCalledTimes(1)
  expect(registerScenario).toHaveBeenCalledTimes(1)
  expect(createRun).toHaveBeenCalledTimes(2)
  expect(createRun.mock.calls[0][0]).toMatchObject({ scenario_id: 'S-next', base_plan_version: 2 })
})
