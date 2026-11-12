// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import snapshotJson from '@examples/01_snapshot.json'
import type { Snapshot } from '../api/types'
import type { V2Client } from '../api/v2'
import { ConditionRevisionPanel, NextPlanPanel } from './RevisionPanels'

const snapshot = snapshotJson as unknown as Snapshot
const rerun = { methods: ['B0', 'B1'] as ['B0', 'B1'], time_limit_seconds: 2, seed: 7, beforeRunId: 'R1' }
let el: HTMLDivElement
let root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-11T05:00:05Z'))
  el = document.createElement('div'); document.body.append(el); root = createRoot(el)
})
afterEach(async () => { await act(async () => root.unmount()); el.remove(); vi.useRealTimers() })
async function fill(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function click(text: string) {
  const button = [...el.querySelectorAll('button')].find((b) => b.textContent === text)!
  expect(button.disabled).toBe(false)
  await act(async () => button.click())
}
async function edit(client: V2Client) {
  await act(async () => root.render(<ConditionRevisionPanel client={client} snapshot={snapshot} rerun={rerun} />))
  const input = el.querySelector<HTMLInputElement>('input[aria-label="시각(24시간제)"]')!
  await fill(input, input.value === '13:00' ? '12:50' : '13:00')
  await fill(el.querySelector('textarea')!, '모의 준비시각 확인')
}

it('분 경계를 넘겨 저장을 재시도해도 같은 본문·키를 보낸다', async () => {
  const post = vi.fn().mockRejectedValue(new Error('응답 유실'))
  await edit({ post } as unknown as V2Client)
  await click('다시 계산')
  const first = JSON.stringify(post.mock.calls[0])
  vi.setSystemTime(new Date('2026-11-11T05:02:05Z'))
  await click('다시 시도')
  expect(JSON.stringify(post.mock.calls[1])).toBe(first)
  await fill(el.querySelector('textarea')!, '다른 근거 확인')
  await click('다시 시도')
  expect(post.mock.calls[2][2]).not.toBe(post.mock.calls[0][2])
})

it('저장이 끝난 뒤 계산만 실패하면 등록을 반복하지 않고 같은 계산을 재시도한다', async () => {
  const post = vi.fn().mockResolvedValue({ scenario_id: 'S2', plan_id: 'P1', base_plan_version: 1, revision_id: 'RV1' })
  const createRun = vi.fn().mockRejectedValue(new Error('일시 장애'))
  await edit({ post, createRun } as unknown as V2Client)
  await click('다시 계산')
  vi.setSystemTime(new Date('2026-11-11T05:03:05Z'))
  await click('다시 시도')
  expect(post).toHaveBeenCalledTimes(1)
  expect(createRun.mock.calls[1]).toEqual(createRun.mock.calls[0])
})

it('확정 원안을 그대로 등록하며 재시도에도 새 next-input을 만들지 않는다', async () => {
  const next = { ...snapshot, scenario_id: 'S-next', base_plan_version: 2, baseline_unassigned_job_ids: ['J3'] }
  const get = vi.fn().mockResolvedValue(next)
  const registerScenario = vi.fn().mockRejectedValueOnce(new Error('응답 유실')).mockResolvedValue({ scenario_id: 'S-next' })
  const createRun = vi.fn().mockRejectedValue(new Error('일시 장애'))
  const client = { get, registerScenario, createRun } as unknown as V2Client
  await act(async () => root.render(<NextPlanPanel client={client} planId="P001" rerun={rerun} />))
  expect(el.textContent).toContain('기사에게 보낸 알림은 지난 알림')
  await click('확정한 배차로 새 점검')
  vi.setSystemTime(new Date('2026-11-11T05:04:05Z'))
  await click('다시 시도')
  await click('다시 시도')
  expect(get).toHaveBeenCalledOnce()
  expect(get).toHaveBeenCalledWith('/v2/plans/P001/next-input')
  expect(registerScenario).toHaveBeenCalledTimes(2)
  expect(registerScenario.mock.calls[1]).toEqual(registerScenario.mock.calls[0])
  expect(registerScenario.mock.calls[0][0]).toEqual(next)
  expect(createRun.mock.calls[1]).toEqual(createRun.mock.calls[0])
  expect(createRun.mock.calls[0][0].base_plan_version).toBe(2)
})

it("'오늘 운행 불가'는 근무 종료를 운행 시작(또는 기준 시각)으로 당겨 보내고, 출발한 작업이 있는 차량은 뺄 수 없다", async () => {
  const post = vi.fn().mockResolvedValue({ scenario_id: 'S2', plan_id: 'P1', base_plan_version: 1, revision_id: 'RV1' })
  const createRun = vi.fn().mockResolvedValue({ run_id: 'R2' })
  await act(async () => root.render(<ConditionRevisionPanel client={{ post, createRun } as unknown as V2Client} snapshot={snapshot} rerun={rerun} />))
  const departed = new Set(snapshot.baseline_assignments.filter((a) => snapshot.jobs.find((j) => j.job_id === a.job_id)?.frozen).map((a) => a.vehicle_id))
  const target = snapshot.vehicles!.find((v) => !departed.has(v.vehicle_id))!
  const rows = [...el.querySelectorAll('.rev-row')].filter((r) => r.querySelector('button, .muted'))
  for (const r of rows) {
    const id = snapshot.vehicles!.find((v) => r.textContent!.includes(v.vehicle_id))?.vehicle_id
    if (id && departed.has(id)) expect(r.textContent).toContain('출발한 작업이 있어 뺄 수 없음')
  }
  const row = rows.find((r) => r.querySelector('b')?.textContent?.includes(target.vehicle_id))!
  await act(async () => row.querySelector<HTMLButtonElement>('button')!.click())
  expect(el.querySelector('.rev-diff')!.textContent).toContain('오늘 운행 불가')
  await fill(el.querySelector('textarea')!, '기사 연락, 차량 고장')
  await click('다시 계산')
  const sent = post.mock.calls[0][1].snapshot as Snapshot
  const v = sent.vehicles!.find((x) => x.vehicle_id === target.vehicle_id)!
  const floor = Math.max(Date.parse(snapshot.as_of), target.available_at ? Date.parse(target.available_at) : 0)
  expect(Date.parse(v.shift_end_at!)).toBeGreaterThanOrEqual(floor)
  expect(Date.parse(v.shift_end_at!) - floor).toBeLessThan(60_000)
  expect(Date.parse(v.shift_end_at!)).toBeGreaterThanOrEqual(Date.parse(v.available_at ?? v.shift_end_at!))
})
