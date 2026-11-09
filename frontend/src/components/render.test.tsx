// PR #4 리뷰: 결과 대기·실패·B0 단독에서도 원안 표가 남는지, 지표 이름이 실제 의미와 맞는지.
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import snapshotJson from '@examples/01_snapshot.json'
import runJson from '@examples/03_run_status.json'
import resultsJson from '@examples/04_results_설명용.json'
import type { Results, Run, Snapshot } from '../api/types'
import type { DispatchView } from '../api/useDispatchView'
import { ApiRequestError } from '../api/client'
import { buildRows } from '../lib/compare'
import { ComparisonSection } from './ComparisonSection'
import { ComparisonTable } from './ComparisonTable'
import { RunStatusPanel } from './Panels'
import { isInputRejection } from './StartRunPanel'

const snapshot = snapshotJson as unknown as Snapshot
const run = runJson as unknown as Run
const results = resultsJson as unknown as Results
const b0 = results.results.find((r) => r.method === 'B0')!
const b3 = results.results.find((r) => r.method === 'B3')!

it('실계산 목표 단계의 계약 필드와 상태를 표시한다', () => {
  const html = renderToStaticMarkup(<RunStatusPanel run={run} results={[{
    ...b3, result_origin: 'computed', objective_stages: [
      { objective: 'unassigned', status: 'OPTIMAL', value: 1, best_bound: 1 },
      { objective: 'changed', status: 'FEASIBLE', value: 2, best_bound: 1 },
    ],
  }]} />)
  expect(html).toContain('unassigned:OPTIMAL')
  expect(html).toContain('changed:FEASIBLE')
  expect(html).not.toContain('undefined')
})

function render(state: DispatchView['results'], withB0 = false, withB3 = false, layout: 'vehicle' | 'job' = 'job') {
  const base = withB0 ? b0 : undefined
  const cand = withB3 ? b3 : undefined
  return renderToStaticMarkup(
    <ComparisonSection
      snapshot={snapshot}
      results={state}
      base={base}
      cand={cand}
      candidates={cand ? [cand] : []}
      rows={buildRows(snapshot, base, cand)}
      onPick={() => {}}
      initialLayout={layout}
    />,
  )
}

const hasBaselineTable = (html: string) => ['J0', 'J1', 'J2', 'J3'].every((id) => html.includes(`<b>${id}</b>`)) && html.includes('T1</b> #2')

describe('원안 표는 결과 상태와 무관하게 남는다', () => {
  it('차량별 보기(기본)도 계산 중에 원안 막대를 보여준다', () => {
    const html = render({ state: 'pending', run: { ...run, status: 'running' } }, false, false, 'vehicle')
    expect(['J0', 'J1', 'J2', 'J3'].every((id) => html.includes(`>${id}<`) || html.includes(` ${id}<`))).toBe(true)
    expect(html).toContain('원안(입력)')
    expect(html).not.toContain('조정안</span>')
  })

  it('계산 중(202)', () => {
    const html = render({ state: 'pending', run: { ...run, status: 'running' } })
    expect(hasBaselineTable(html)).toBe(true)
    expect(html).toContain('원안(입력)')
    expect(html).not.toContain('조정안</th>')
  })

  it('결과 조회 실패', () => {
    const html = render({ state: 'error', message: '실행 실패' })
    expect(hasBaselineTable(html)).toBe(true)
    expect(html).toContain('결과를 표시할 수 없습니다')
  })

  it('B0 단독 결과', () => {
    const html = render({ state: 'ready', data: { ...results, results: [b0] } }, true, false)
    expect(hasBaselineTable(html)).toBe(true)
    expect(html).toContain('B0 원안')
    expect(html).toContain('원안 진단만 표시')
    expect(html).not.toContain('조정안</th>')
  })

  it('조정안이 있으면 지표는 제약 위반으로 표시하고 마감 위반으로 단정하지 않는다', () => {
    const html = render({ state: 'ready', data: results }, true, true)
    expect(html).toContain('B3 조정안</th>')
    expect(html).toContain('제약 위반 작업(조정 가능)')
    expect(html).not.toContain('마감 위반')
  })
})

describe('미확인 입력 표시', () => {
  it('07 입력의 null 준비시각은 0이나 정상으로 채우지 않고 미확인으로 보인다', async () => {
    const s07 = (await import('@examples/07_snapshot_입력누락.json')).default as unknown as Snapshot
    const html = renderToStaticMarkup(
      <ComparisonTable rows={buildRows(s07, undefined, undefined)} asOf={s07.as_of} baseLabel="원안(입력)" candLabel={null} />,
    )
    expect(html.match(/준비시각 미확인/g)).toHaveLength(1)
    expect(html).toContain('<b>J1</b>')
  })
})

describe('계산 요청 거절과 일시 장애 구분', () => {
  it('07의 입력 누락은 같은 입력의 재시도로 해결되지 않는다', () => {
    expect(isInputRejection(new ApiRequestError(422, {
      code: 'INPUT_INCOMPLETE', message: '미확인 입력이 있어 설명용 결과를 적용할 수 없음',
    }))).toBe(true)
  })

  it('08의 반입시간 미확인은 503이어도 입력 확인이 필요하다', () => {
    expect(isInputRejection(new ApiRequestError(503, {
      code: 'WINDOW_UNCONFIRMED', message: '반입시간 변경 확인이 필요함',
    }))).toBe(true)
  })

  it('저장소 503은 입력 수정 대상이 아니므로 일반 오류·재시도 경로를 유지한다', () => {
    expect(isInputRejection(new ApiRequestError(503, {
      code: 'STORAGE_UNAVAILABLE', message: '저장소를 사용할 수 없음',
    }))).toBe(false)
  })

  it('설명용 모드의 B1/B2 미제공은 입력 거절이 아니라 방법을 바꿔 다시 요청할 오류다', () => {
    expect(isInputRejection(new ApiRequestError(422, {
      code: 'DEMO_METHOD_UNAVAILABLE', message: '제공된 설명용 결과는 B0·B3뿐임',
    }))).toBe(false)
  })

  it('본문 없는 503과 연결 실패를 입력 거절로 단정하지 않는다', () => {
    expect(isInputRejection(new ApiRequestError(503, null))).toBe(false)
    expect(isInputRejection(new Error('Failed to fetch'))).toBe(false)
  })
})

describe('고정 작업 표시', () => {
  it('보존되면 원안 유지, 시각이 바뀌면 경고', () => {
    const ok = renderToStaticMarkup(<ComparisonTable rows={buildRows(snapshot, b0, b3)} asOf={snapshot.as_of} baseLabel="B0" candLabel="B3" />)
    expect(ok).toContain('원안 유지')
    const moved = { ...b3, assignments: b3.assignments.map((a) => (a.job_id === 'J0' ? { ...a, return_at: '2026-11-07T01:05:00Z' } : a)) }
    const bad = renderToStaticMarkup(<ComparisonTable rows={buildRows(snapshot, b0, moved)} asOf={snapshot.as_of} baseLabel="B0" candLabel="B3" />)
    expect(bad).toContain('고정 작업 변경됨')
    expect(bad).not.toContain('원안 유지')
  })
})

describe('실행 실패 표시', () => {
  it('Run.error의 실패 방법·이유(details)를 보여준다', () => {
    const failed: Run = { ...run, status: 'failed', error: {
      code: 'RUN_EXECUTION_FAILED', message: '실행 실패', request_id: 'req-1',
      details: [{ path: '/methods', reason: 'B2: 실행 제한시간 초과' }],
    } }
    const html = renderToStaticMarkup(<RunStatusPanel run={failed} results={null} />)
    expect(html).toContain('RUN_EXECUTION_FAILED')
    expect(html).toContain('B2: 실행 제한시간 초과')
    expect(html).toContain('req-1')
  })

  it('error가 없으면 사유 미제공으로 표시한다', () => {
    const html = renderToStaticMarkup(<RunStatusPanel run={{ ...run, status: 'failed', error: null }} results={null} />)
    expect(html).toContain('사유 미제공')
  })
})

describe('차량별 일정', () => {
  it('원안·조정안 막대를 같은 축에 두고 마감 초과·고정·변경·미처리를 표시한다', async () => {
    const { timelineModel } = await import('./VehicleTimeline')
    const b0 = results.results.find((r) => r.method === 'B0')!
    const b3 = results.results.find((r) => r.method === 'B3')!
    const m = timelineModel(buildRows(snapshot, b0, b3), true)!
    expect(m.vehicles.map((v) => v.id)).toEqual(['T1', 'T2'])
    const t1 = m.vehicles[0]
    expect(t1.base.find((b) => b.jobId === 'J0')!.locked).toBe(true)
    expect(t1.base.find((b) => b.jobId === 'J1')!.late).toBe(true) // 원안 J1 도착 10:40 > 마감 10:30
    expect(t1.cand.find((b) => b.jobId === 'J0')!.changed).toBe(false)
    expect(t1.cand.find((b) => b.jobId === 'J2')!.changed).toBe(true)
    expect(m.unassigned).toEqual(['J3'])
    expect(m.deadlines.map((d) => d.label)).toContain('V1 마감 10:30')
    for (const b of [...t1.base, ...t1.cand]) {
      expect(b.left).toBeGreaterThanOrEqual(0)
      expect(b.left + b.width).toBeLessThanOrEqual(100.0001)
    }
  })

  it('조정안이 없으면 원안 줄만 그리고, 배정이 없으면 모델을 만들지 않는다', async () => {
    const { timelineModel } = await import('./VehicleTimeline')
    const m = timelineModel(buildRows(snapshot, undefined, undefined), false)!
    expect(m.vehicles.every((v) => v.cand.length === 0)).toBe(true)
    expect(m.unassigned).toEqual([])
    expect(timelineModel([], true)).toBeNull()
  })
})
