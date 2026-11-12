// 담당자가 화면을 열자마자 보는 요약: 무엇이 문제인지 → 추천안으로 얼마나 해결되는지 → 지금 할 일.
// 계산 결과의 값만 쓴다(새 판단을 만들지 않는다).
import type { MethodResult } from '../api/types'
import { ISSUE_LABEL, type JobRow } from '../lib/compare'
import { planName } from '../lib/labels'
import { BoxNo } from './Ids'

const go = (selector: string) => document.querySelector(selector)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

export function ActionSummary({ base, cand, rows, approved }: {
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
        <p className="small muted">바꿀 배차가 없습니다.</p>
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
  const name = cand ? planName(cand.method) : ''
  const headline = !cand
    ? `원래 배차대로 가면 컨테이너 ${lateSet.length}건이 새 마감을 넘깁니다.`
    : fixed === lateSet.length
      ? fixed === 1
        ? `${name}을 쓰면 늦는 컨테이너 1건을 마감 안에 넣을 수 있습니다.`
        : `${name}을 쓰면 늦는 컨테이너 ${fixed}건을 모두 마감 안에 넣을 수 있습니다.`
      : `${name}을 쓰면 늦는 컨테이너 ${lateSet.length}건 중 ${fixed}건을 마감 안에 넣을 수 있습니다.`
  return (
    <section className={`card action-summary${approved ? ' done' : ''}`} aria-label="요약">
      <div className="as-top">
        <div>
          <p className="as-kicker">{approved ? '확정 완료' : '판단 요약'}</p>
          <h2 className="as-headline">{headline}</h2>
          {cand && <p className="as-sub">작업 {changed}건의 차량이나 시각이 바뀌고{unresolved.length ? `, ${unresolved.length}건은 담당자가 확인해야 합니다.` : ', 남는 문제는 없습니다.'}</p>}
        </div>
      </div>
      <dl className="stat-strip">
        <div className="ss-bad"><dt>원래 배차로 마감 넘김</dt><dd><b>{lateSet.length}</b><span>건</span></dd></div>
        {cand && <div className="ss-good"><dt>{name}으로 해결</dt><dd><b>{fixed}</b><span>건</span></dd></div>}
        {cand && <div><dt>바뀌는 작업</dt><dd><b>{changed}</b><span>건</span></dd></div>}
        {cand && <div className={unresolved.length ? 'ss-warn' : undefined}><dt>담당자 확인 필요</dt><dd><b>{unresolved.length}</b><span>건</span></dd></div>}
      </dl>
      {unresolved.length > 0 && (
        <ul className="as-todo">
          {unresolved.map(id => <li key={id}><span className="st warn">확인 필요</span> <BoxNo jobId={id} /> <span className="muted">{reason(id)}</span></li>)}
        </ul>
      )}
      <div className="as-actions">
        {approved ? (
          <>
            <span className="small"><b>배차를 확정했습니다.</b> 이제 바뀐 차량의 기사에게 알려 주세요.</span>
            <button type="button" onClick={() => go('.card.dispatch')}>기사 전달로 이동</button>
          </>
        ) : (
          <>
            <button type="button" className="secondary" onClick={() => go('.comparison')}>조정안 자세히 보기</button>
            <button type="button" onClick={() => go('.side')}>확인하고 확정하기</button>
          </>
        )}
      </div>
    </section>
  )
}
