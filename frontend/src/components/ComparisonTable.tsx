import type { Assignment } from '../api/types'
import { ISSUE_LABEL, lockedPreserved, type ChangeKind, type JobRow } from '../lib/compare'
import { Icon } from './Icon'
import { kstTimeWithDay } from '../lib/time'

const CHANGE_LABEL: Record<ChangeKind, string> = { vehicle: '차량', order: '순서', time: '시각' }

// 도착이 그 작업 시간창 마감보다 늦으면 몇 분 넘었는지 응답 시각으로 계산해 빨갛게 보여준다.
function lateMinutes(a: Assignment, closesAt: string | null | undefined): number | null {
  if (!closesAt) return null
  const diff = Math.round((Date.parse(a.gate_arrival_at) - Date.parse(closesAt)) / 60_000)
  return diff > 0 ? diff : null
}

function Cell({ a, refUtc, closesAt }: { a: Assignment | undefined; refUtc: string; closesAt: string | null | undefined }) {
  if (!a) return <span className="muted">배정 없음</span>
  const late = lateMinutes(a, closesAt)
  return (
    <>
      <b>{a.vehicle_id}</b> #{a.sequence}
      <div className="muted small">
        출발 {kstTimeWithDay(a.pickup_departure_at, refUtc)} · 도착{' '}
        <span className={late ? 'late-time' : undefined}>
          {kstTimeWithDay(a.gate_arrival_at, refUtc)}
          {late && ` (마감 ${late}분 초과)`}
        </span>{' '}
        · 복귀 {kstTimeWithDay(a.return_at, refUtc)}
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
                <td className="job-cell">
                  <b>{r.job.job_id}</b>
                  <div className="muted small">
                    {r.job.voyage_id} · {r.job.terminal_id}
                  </div>
                  {r.job.ready_at === null && <div className="warn small">준비시각 미확인</div>}
                  {r.locked && (
                    <div>
                      <span className="badge lock" title={r.job.freeze_reason ?? undefined}>
                        <Icon name="lock" /> 고정{r.job.state === 'departed' ? ' · 출발함' : ''}
                      </span>
                    </div>
                  )}
                </td>
                <td>{kstTimeWithDay(r.window?.closes_at ?? null, asOf)}</td>
                <td>
                  <Cell a={r.baseline} refUtc={asOf} closesAt={r.window?.closes_at} />
                  {r.baselineIssues.map((i, k) => (
                    <div key={k} className="warn small">
                      <Icon name="warning" /> {ISSUE_LABEL[i.code] ?? i.code}
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
                      <Cell a={r.candidate} refUtc={asOf} closesAt={r.window?.closes_at} />
                    )}
                  </td>
                )}
                {hasCand && (
                  <td>
                    {r.locked ? (
                      preserved ? (
                        <span className="dot dot-muted">원안 유지</span>
                      ) : (
                        <span className="dot dot-warn">고정 작업 변경됨 · 확인 필요</span>
                      )
                    ) : r.changes.length ? (
                      <span className="dot dot-ok">{r.changes.map((c) => CHANGE_LABEL[c]).join('·')} 변경</span>
                    ) : r.candidateUnassigned ? (
                      <span className="dot dot-warn">미처리</span>
                    ) : (
                      <span className="dot dot-muted">변경 없음</span>
                    )}
                    {r.candidateIssues.map((i, k) => (
                      <div key={k} className="small issue-text">
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
