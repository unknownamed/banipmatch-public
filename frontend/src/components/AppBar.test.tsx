// @vitest-environment jsdom
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'
import { AppBar } from './AppBar'

afterEach(() => history.replaceState({}, '', '/'))

function destination(name: string, mode: 'http' | 'fixture' = 'http') {
  const node = document.createElement('div')
  node.innerHTML = renderToStaticMarkup(<AppBar mode={mode} />)
  const link = [...node.querySelectorAll('nav a')].find((a) => a.textContent === name)!
  return new URL(link.getAttribute('href')!, location.href)
}

describe('같은 계산 결과의 화면 이동', () => {
  it('지도 왕복 후 실행·시나리오·하위 경로를 보존한다', () => {
    history.replaceState({}, '', '/demo/?run=R1&scenario=S1')
    const map = destination('입항 선박')
    expect(map.pathname).toBe('/demo/')
    expect(map.searchParams.get('view')).toBe('map')
    expect(map.searchParams.get('run')).toBe('R1')
    expect(map.searchParams.get('scenario')).toBe('S1')
    history.replaceState({}, '', map.href)
    const review = destination('배차 점검')
    expect(review.pathname).toBe('/demo/')
    expect(review.searchParams.get('run')).toBe('R1')
    expect(review.searchParams.get('scenario')).toBe('S1')
    expect(review.searchParams.has('view')).toBe(false)
  })

  it.each([
    '?view=map&run=R1&scenario=S1',
    '?run=R1&view=map&scenario=S1',
    '?run=R1&scenario=S1&view=map',
  ])('view의 순서와 무관하게 비교 링크는 올바른 쿼리다: %s', (query) => {
    history.replaceState({}, '', `/demo/${query}`)
    const review = destination('배차 점검')
    expect(review.pathname).toBe('/demo/')
    expect(review.searchParams.get('run')).toBe('R1')
    expect(review.searchParams.get('scenario')).toBe('S1')
    expect(review.searchParams.has('view')).toBe(false)
  })

  it('계산 요청에서만 이전 실행을 명시적으로 비운다', () => {
    history.replaceState({}, '', '/demo/?view=map&run=R1&scenario=S1')
    const start = destination('새 점검')
    expect(start.pathname).toBe('/demo/')
    expect([...start.searchParams]).toEqual([])
  })

  it('예제 모드도 지정한 사례와 인코딩된 식별자를 보존한다', () => {
    const params = new URLSearchParams({ run: 'R/한글+1', scenario: 'S&2', view: 'map' })
    history.replaceState({}, '', `/?${params}`)
    const review = destination('배차 점검', 'fixture')
    expect(review.searchParams.get('run')).toBe('R/한글+1')
    expect(review.searchParams.get('scenario')).toBe('S&2')
    expect(review.searchParams.has('view')).toBe(false)
  })
})
