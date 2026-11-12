// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { VesselApproachMap } from './VesselApproachMap'
import type { Snapshot } from '../api/types'

const iso = (minFromNow: number) => new Date(Date.now() + minFromNow * 60000).toISOString()

async function mount(node: React.ReactNode) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const box = document.createElement('div')
  const root = createRoot(box)
  await act(async () => root.render(node))
  return { box, unmount: () => act(async () => root.unmount()) }
}

it('지도 키가 없어도 선박 목록·남은 시간·모의 표시를 보여 주고 묘박 선박은 도착 시각을 만들지 않는다', async () => {
  const { box, unmount } = await mount(<VesselApproachMap />)
  expect(box.textContent).toContain('시연용 모의 자료')
  expect(box.textContent).toContain('후 도착 추정')
  expect(box.textContent).toContain('속력 0이라 도착 시각을 산정하지 않음')
  expect(box.textContent).toContain('다른 신항 터미널 선박')
  await unmount()
})

it('계산 시나리오가 있으면 같은 항차의 반입 마감·변경 전 값과 배차 화면 링크를 붙인다', async () => {
  const snapshot = {
    scenario_id: 'S-test',
    windows: [{ window_id: 'W1', voyage_id: 'V1', terminal_id: 'HJNC', opens_at: iso(-60), closes_at: iso(90), verification: 'confirmed' }],
    change: { change_id: 'C1', voyage_id: 'V1', terminal_id: 'HJNC', previous_opens_at: iso(-60), previous_closes_at: iso(180), new_window_id: 'W1', verification: 'confirmed' },
  } as unknown as Snapshot
  const { box, unmount } = await mount(<VesselApproachMap link={{ snapshot, reviewHref: '?scenario=S-test&run=R1' }} />)
  expect(box.textContent).toContain('지금 점검 중인 배차')
  expect(box.textContent).toMatch(/변경 전 \d\d:\d\d/)
  const go = [...box.querySelectorAll('a')].find(a => a.textContent?.includes('V1 항차 배차 점검'))
  expect(go?.getAttribute('href')).toBe('?scenario=S-test&run=R1')
  await unmount()
})
