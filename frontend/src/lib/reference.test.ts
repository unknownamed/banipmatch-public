import { describe, expect, it } from 'vitest'
import fixture from '../fixtures/reference-preview.synthetic.json'
import { display, type ReferenceView } from './reference'

const view = (id: string) => fixture.cases.find((c) => c.id === id)!.view as unknown as ReferenceView

describe('참고 자료 상태 표시', () => {
  it('정상 수신만 정상 표시이며 계산 입력·승인으로 쓰지 않는다', () => {
    const v = view('received')
    expect(display(v)).toMatchObject({ tone: 'ok', sampleIsPrevious: false })
    expect(v.engine_conversion).toBe('blocked')
    expect(v.approval_eligible).toBe(false)
  })
  it('실패는 이전 표본이 있어도 실패로 먼저 보이고, 표본은 이전 수신으로 표시한다', () => {
    const d = display(view('failed_cached'))
    expect(d.tone).toBe('danger')
    expect(d.headline).toContain('조회 실패')
    expect(d.headline).toContain('이전 수신 표본')
    expect(d.sampleIsPrevious).toBe(true)
  })
  it('이전 표본 없는 실패는 자료 없음이며 모의로 바꾸지 않는다', () => {
    const v = view('failed')
    expect(display(v)).toMatchObject({ tone: 'danger', sample: null })
    expect(v.automatic_mock_fallback).toBe(false)
  })
  it('0건은 실패가 아니고, 부분·오래됨은 경고로 구분한다', () => {
    expect(display(view('empty'))).toMatchObject({ tone: 'warn', headline: '정상 응답 · 0건' })
    expect(display(view('partial')).headline).toBe('부분 응답')
    expect(display(view('stale')).headline).toContain('오래됨')
  })
})
