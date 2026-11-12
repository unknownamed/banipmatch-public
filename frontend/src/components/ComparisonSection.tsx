import { useState } from 'react'
import type { DispatchView } from '../api/useDispatchView'
import type { MethodResult, Snapshot } from '../api/types'
import { lockedViolations, type JobRow } from '../lib/compare'
import { ComparisonTable } from './ComparisonTable'
import { MetricsRow } from './Panels'
import { VehicleTimeline } from './VehicleTimeline'

interface Props {
  snapshot: Snapshot
  results: DispatchView['results']
  base: MethodResult | undefined
  cand: MethodResult | undefined
  candidates: MethodResult[]
  rows: JobRow[]
  onPick: (method: string) => void
  /** 처음 보일 보기. 기본은 차량별 일정 */
  initialLayout?: 'vehicle' | 'job'
}

/**
 * 원안 표는 입력(snapshot)만 있으면 항상 보인다. 결과가 대기·실패·B0 단독이어도 원안은 남기고,
 * 조정안 열과 지표만 결과가 준비됐을 때 연다. (PR #4 리뷰 반영)
 */
export function ComparisonSection({ snapshot, results, base, cand, candidates, rows, onPick, initialLayout = 'vehicle' }: Props) {
  const list = results.state === 'ready' ? results.data.results : null
  const broken = lockedViolations(rows)
  // 휴대폰 폭에서는 가로 스크롤이 필요한 타임라인 대신 작업별 카드부터 보여 준다.
  const narrow = typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 640px)').matches
  const [layout, setLayout] = useState(narrow ? 'job' : initialLayout)
  const candLabel = cand ? `${cand.method} 조정안` : null
  const baseLabel = base ? 'B0 원안' : '원안(입력)'
  return (
    <section className="card comparison">
      <h2>원안 · 조정안 비교</h2>
      {results.state === 'loading' && <p className="muted">결과 조회 중… 아래 원안은 입력 기준으로 먼저 보여줍니다.</p>}
      {results.state === 'pending' && <p className="muted">계산 중입니다. 결과가 도착하면 조정안을 자동으로 표시합니다.</p>}
      {results.state === 'error' && <p className="warn">결과를 표시할 수 없습니다: {results.message}</p>}
      {list && list.length === 0 && <p className="warn">결과 목록이 비어 있습니다. 해결 완료가 아닙니다.</p>}
      {list && list.length > 0 && !cand && <p className="muted">조정안(B1~B3) 결과가 없습니다. 원안 진단만 표시합니다.</p>}

      {candidates.length > 1 && (
        <div className="tabs" role="tablist">
          {candidates.map((r) => (
            <button key={r.method} role="tab" aria-selected={r === cand} onClick={() => onPick(r.method)}>
              {r.method}
            </button>
          ))}
        </div>
      )}
      {base && cand && <MetricsRow base={base} cand={cand} />}
      {base && cand && cand.metrics.unassigned_count > base.metrics.unassigned_count && (
        <p className="warn">
          미처리가 {base.metrics.unassigned_count}건 → {cand.metrics.unassigned_count}건으로 늘었습니다. 제약 위반 감소에는 미처리로 남긴 작업이
          포함되어 있으므로 전체 해결이 아닙니다.
        </p>
      )}
      {broken.length > 0 && (
        <p className="warn">고정 작업 {broken.join(', ')}이(가) 조정안에서 바뀌었거나 빠졌습니다. 엔진·검증 담당 확인이 필요합니다.</p>
      )}
      <div className="tabs" role="tablist" aria-label="보기 방식">
        <button role="tab" aria-selected={layout === 'vehicle'} onClick={() => setLayout('vehicle')}>
          차량별 일정
        </button>
        <button role="tab" aria-selected={layout === 'job'} onClick={() => setLayout('job')}>
          작업별 표
        </button>
      </div>
      {layout === 'vehicle' ? (
        <VehicleTimeline rows={rows} baseLabel={baseLabel} candLabel={candLabel} />
      ) : (
        <ComparisonTable rows={rows} asOf={snapshot.as_of} baseLabel={baseLabel} candLabel={candLabel} />
      )}
    </section>
  )
}
