// 담당자가 화면을 열자마자 보는 요약: 무엇이 문제인지 → 추천안으로 얼마나 해결되는지 → 지금 할 일.
// 계산 결과의 값만 쓴다(새 판단을 만들지 않는다).
import type { MethodResult } from '../api/types'
import { ISSUE_LABEL, type JobRow } from '../lib/compare'
import { jobName } from '../lib/labels'
import { Icon } from './Icon'

const go = (selector: string) => document.querySelector(selector)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

export function ActionSummary({ base, cand, recommended, rows, approved }: {
  base: MethodResult | undefined
  cand: MethodResult | undefined
  recommended: string | undefined
  rows: JobRow[]
  approved: boolean
}) {
  if (!base) return null
  const late = base.issues.filter(i => i.job_id && (i.code === 'CUTOFF_EXCEEDED' || i.code === 'READY_TOO_LATE')).map(i => i.job_id!)
  const lateSet = [...new Set(late)]
  const risk = base.metrics.fixed_risk_count
  if (lateSet.length === 0 && risk === 0)
    return (
      <section className="card action-summary ok" aria-label="요약">
        <p className="as-head"><b>원래 배차로 모든 컨테이너가 마감 안에 들어갑니다.</b></p>
        <p className="small muted">바꿀 필요가 없습니다. 아래에서 차량별 일정을 확인할 수 있습니다.</p>
      </section>
    )
  const unresolved = cand ? cand.unassigned_job_ids : []
  const fixed = cand ? lateSet.filter(id => !unresolved.includes(id)).length : 0
  const changed = cand ? cand.metrics.changed_job_ids.length : 0
  const reason = (id: string) => {
    const r = rows.find(x => x.job.job_id === id)
    const code = r?.candidateIssues[0]?.code
    return code ? ISSUE_LABEL[code] ?? code : '확인 필요'
  }
  return (
    <section className={`card action-summary${approved ? ' done' : ''}`} aria-label="요약">
      <div className="as-grid">
        <div className="as-cell bad">
          <span className="as-ic"><Icon name="warning" size={16} /></span>
          <span className="as-num">{lateSet.length}</span>
          <span className="as-label">원래 배차로<br />마감 넘김</span>
        </div>
        {cand && (
          <div className="as-cell good">
            <span className="as-ic"><Icon name="check" size={16} /></span>
            <span className="as-num">{fixed}</span>
            <span className="as-label">{cand.method}{cand.method === recommended ? '(추천)' : ''}로<br />해결</span>
          </div>
        )}
        {cand && (
          <div className="as-cell">
            <span className="as-ic"><Icon name="swap" size={16} /></span>
            <span className="as-num">{changed}</span>
            <span className="as-label">바뀌는<br />작업</span>
          </div>
        )}
        {cand && (
          <div className={`as-cell${unresolved.length ? ' warn' : ''}`}>
            <span className="as-ic"><Icon name="clock" size={16} /></span>
            <span className="as-num">{unresolved.length}</span>
            <span className="as-label">담당자<br />확인 필요</span>
          </div>
        )}
      </div>
      {unresolved.length > 0 && (
        <ul className="as-todo small">
          {unresolved.map(id => <li key={id}><b>{jobName(id)}</b> · {reason(id)}</li>)}
        </ul>
      )}
      <div className="as-actions">
        {approved ? (
          <>
            <span className="small"><b>내부 확정 완료.</b> 이제 바뀐 차량의 기사에게 전달합니다.</span>
            <button type="button" onClick={() => go('.card.dispatch')}>기사 전달로 이동</button>
          </>
        ) : (
          <>
            <button type="button" className="secondary" onClick={() => go('.comparison')}>조정안 자세히 보기</button>
            <button type="button" onClick={() => go('.side')}>확인하고 승인하기</button>
          </>
        )}
      </div>
    </section>
  )
}
