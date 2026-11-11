// @vitest-environment jsdom
// 부분 응답에서 모든 행이 제외되면 '정상 0건'으로 보이면 안 된다(PR #65 리뷰).
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import fixture from '../fixtures/reference-preview.synthetic.json'
import type { ReferenceView } from '../lib/reference'
import { ReferenceStatus } from './ReferencePanel'

const base = (id: string) => structuredClone(fixture.cases.find((c) => c.id === id)!.view) as unknown as ReferenceView

it('부분 응답의 전부 제외와 정상 0건을 구분한다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const allExcluded = base('partial')
  Object.assign(allExcluded.current!, { items: [], row_count: 1, reported_count: 1, excluded_rows: 1 })
  const box = document.createElement('div')
  const root = createRoot(box)
  await act(async () => root.render(<ReferenceStatus view={allExcluded} />))
  expect(box.textContent).not.toContain('정상 응답으로 0건')
  expect(box.textContent).toContain('표시 가능 0건')
  expect(box.textContent).toContain('제외 1건')
  await act(async () => root.render(<ReferenceStatus view={base('empty')} />))
  expect(box.textContent).toContain('정상 응답으로 0건')
  await act(async () => root.unmount())
})
