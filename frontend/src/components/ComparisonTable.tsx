import type { Assignment } from '../api/types'
import { ISSUE_LABEL, lockedPreserved, type ChangeKind, type JobRow } from '../lib/compare'
import { kstTimeWithDay } from '../lib/time'

const CHANGE_LABEL: Record<ChangeKind, string> = { vehicle: '차량', order: '순서', time: '시각' }

function Cell({ a, refUtc }: { a: Assignment | undefined; refUtc: string }) {
  if (!a) return <span className="muted">배정 없음</span>
  return (
    <>
      <b>{a.vehicle_id}</b> #{a.sequence}
      <div className="muted small">
        출발 {kstTimeWithDay(a.pickup_departure_at, refUtc)} · 도착 {kstTimeWithDay(a.gate_arrival_at, refUtc)} · 복귀{' '}
        {kstTimeWithDay(a.return_at, refUtc)}
      </div>
    </>
  )
}

/** candLabel이 null이면 조정안 결과가 아직 없으므로 원안 열만 그린다. */
export function ComparisonTable({
  rows,
  asOf,
  baseLabel,
  candLabel,
}: {
  rows: JobRow[]
  asOf: string
  baseLabel: string
  candLabel: string | null
}) {
  const hasCand = candLabel !== null
  return (
    <div className="table-wrap">
      <table className="grid">
        <thead>
          <tr>
            <th>작업</th>
            <th>마감</th>
            <th>{baseLabel}</th>
            {hasCand && <th>{candLabel}</th>}
            {hasCand && <th>변경 · 이유</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const preserved = lockedPreserved(r, hasCand)
            return (
              <tr key={r.job.job_id} className={r.candidateUnassigned ? 'row-unassigned' : r.locked ? 'row-locked' : ''}>
                <td>
                  <b>{r.job.job_id}</b> <span className="muted">{r.job.voyage_id}</span>
                  {r.locked && (
                    <div>
                      <span className="badge lock" title={r.job.freeze_reason ?? undefined}>
                        🔒 고정{r.job.state === 'departed' ? ' · 출발함' : ''}
                      </span>
                    </div>
                  )}
                </td>
                <td>{kstTimeWithDay(r.window?.closes_at ?? null, asOf)}</td>
                <td>
                  <Cell a={r.baseline} refUtc={asOf} />
                  {r.baselineIssues.map((i, k) => (
                    <div key={k} className="warn small">
                      ⚠ {ISSUE_LABEL[i.code] ?? i.code}
                    </div>
                  ))}
                </td>
                {hasCand && (
                  <td>
                    {r.candidateUnassigned ? (
                      <span className="badge unassigned">미처리</span>
                    ) : r.candidateMissing ? (
                      <span className="warn">결과에 없음(배정·미처리 모두 아님)</span>
                    ) : (
                      <Cell a={r.candidate} refUtc={asOf} />
                    )}
                  </td>
                )}
                {hasCand && (
                  <td>
                    {r.locked ? (
                      preserved ? (
                        <span className="muted">원안 유지</span>
                      ) : (
                        <span className="warn">⚠ 고정 작업 변경됨 · 확인 필요</span>
                      )
                    ) : r.changes.length ? (
                      r.changes.map((c) => (
                        <span key={c} className="badge change">
                          {CHANGE_LABEL[c]} 변경
                        </span>
                      ))
                    ) : r.candidateUnassigned ? null : (
                      <span className="muted">변경 없음</span>
                    )}
                    {r.candidateIssues.map((i, k) => (
                      <div key={k} className="small">
                        {ISSUE_LABEL[i.code] ?? i.code}
                      </div>
                    ))}
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
