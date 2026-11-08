import type { MethodResult, Run, Snapshot } from '../api/types'
import { ISSUE_LABEL, PROOF_LABEL, type JobRow } from '../lib/compare'
import { kstDateTime, kstTime } from '../lib/time'

const DATA_MODE: Record<Snapshot['data_mode'], string> = { simulated: '모의', observed: '관측', mixed: '혼합' }
const VERIFY: Record<string, string> = { confirmed: '확정', unconfirmed: '미확정', conflict: '충돌' }
const EVIDENCE: Record<string, string> = {
  observed: '관측',
  simulated: '모의',
  assumed: '가정',
  inferred: '추정',
  manual_verified: '수동 확인',
}

export function Header({ s }: { s: Snapshot }) {
  return (
    <header className="top">
      <div>
        <h1>반입시간 변경 배차 점검</h1>
        <p className="muted">
          시나리오 <b>{s.scenario_id}</b> · 계획 <b>{s.plan_id}</b> v{s.base_plan_version} · 기준시각 {kstDateTime(s.as_of)}
        </p>
      </div>
      <span className={`badge mode-${s.data_mode}`} title="입력 자료 묶음의 data_mode">
        자료: {DATA_MODE[s.data_mode]}
      </span>
    </header>
  )
}

export function ChangeEvidence({ s }: { s: Snapshot }) {
  const c = s.change
  const w = s.windows.find((x) => x.window_id === c.new_window_id)
  return (
    <section className="card">
      <h2>변경 근거 · 터미널 반입 허용시간(항차)</h2>
      {/* service-comparison.md: 접안예정·반입시간·방문예약·내부계획을 구분해 표시 */}
      <p className="muted small">선박 접안예정(ETA)이나 트럭 방문예약 시간이 아니라, 항차별 컨테이너 반입 시작·마감입니다.</p>
      <table className="kv">
        <tbody>
          <tr>
            <th>적용 항차 · 터미널</th>
            <td>
              {c.voyage_id} · {c.terminal_id}
            </td>
          </tr>
          <tr>
            <th>이전 반입 허용시간</th>
            <td>
              {kstTime(c.previous_opens_at)} ~ {kstTime(c.previous_closes_at)}
            </td>
          </tr>
          <tr>
            <th>새 반입 허용시간</th>
            <td>
              {w ? (
                <>
                  {kstTime(w.opens_at)} ~ <b>{kstTime(w.closes_at)}</b>
                </>
              ) : (
                <span className="warn">새 시간창 {c.new_window_id}을(를) 입력에서 찾지 못함</span>
              )}
            </td>
          </tr>
          <tr>
            <th>확정 여부</th>
            <td>
              <span className={c.verification === 'confirmed' ? 'ok' : 'warn'}>{VERIFY[c.verification] ?? c.verification}</span>
              {c.confirmed_by && ` · ${c.confirmed_by}`} · 확인 {kstDateTime(c.confirmed_at)}
            </td>
          </tr>
          <tr>
            <th>출처</th>
            <td>
              {EVIDENCE[c.evidence.kind] ?? c.evidence.kind} · <code>{c.evidence.source_ref}</code> · 수신{' '}
              {kstDateTime(c.evidence.received_at)}
            </td>
          </tr>
        </tbody>
      </table>
      {c.verification !== 'confirmed' && (
        <p className="warn">확정되지 않은 변경입니다. 새 시간창 적용 계산과 승인은 막아야 합니다.</p>
      )}
    </section>
  )
}

const RUN_LABEL: Record<Run['status'], string> = {
  queued: '대기 중',
  running: '계산 중',
  completed: '완료',
  failed: '실패',
  cancelled: '취소됨',
}

// HEURISTIC·FEASIBLE을 최적해로 보이지 않게 한다(엔진 인계 2026-11-07 요청).
const SOLUTION_LABEL: Record<string, string> = {
  BASELINE: '원안 진단',
  HEURISTIC: '휴리스틱 결과 · 최적 아님',
  FEASIBLE: '실행 가능 · 최적 미증명',
  OPTIMAL: '최적',
  INFEASIBLE: '해 없음',
  UNKNOWN: '시간 내 해 미발견',
  MODEL_INVALID: '모델 오류',
  INPUT_INCOMPLETE: '입력 부족',
}

export function solutionLabel(r: MethodResult): string {
  const s = r.solution_status === 'OPTIMAL' && !r.objective_proven ? '최적 표시 · 증명 없음' : SOLUTION_LABEL[r.solution_status]
  return `${r.solution_status} (${s ?? '알 수 없음'})`
}

export function RunStatusPanel({ run, results }: { run: Run; results: MethodResult[] | null }) {
  return (
    <section className="card">
      <h2>계산 상태</h2>
      <p>
        실행 <b>{run.run_id}</b> · <span className={`badge run-${run.status}`}>{RUN_LABEL[run.status]}</span> · 방법{' '}
        {run.methods.join(', ')} · 제한 {run.config.time_limit_seconds}초 · seed {run.config.seed}
      </p>
      {run.status === 'failed' && (
        <div className="warn" role="alert">
          <p>실패 이유: {run.error ? `${run.error.code} — ${run.error.message}` : '사유 미제공'}</p>
          {/* 실패 방법·이유는 details에 온다(예: "B2: 실행 제한시간 초과"). 실패한 실행의 결과는 승인하지 않는다. */}
          {run.error?.details?.map((d, i) => (
            <p key={i} className="small">
              <code>{d.path}</code> {d.reason}
            </p>
          ))}
          {run.error?.request_id && <p className="muted small">요청 ID {run.error.request_id} (서버 기록 확인용)</p>}
          <p className="muted small">한 방법이라도 실패하면 이 실행의 결과는 저장되지 않습니다. 원인을 확인한 뒤 새로 계산을 요청하세요.</p>
        </div>
      )}
      {results && (
        <table className="grid small">
          <thead>
            <tr>
              <th>방법</th>
              <th>결과 출처</th>
              <th>해 상태</th>
              <th>엔진</th>
              <th>목표 단계</th>
              <th>독립 검사</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.method}>
                <td>{r.method}</td>
                <td>
                  {r.result_origin === 'illustrative_fixture' ? (
                    <span className="badge fixture">설명용 예시</span>
                  ) : (
                    <span className="badge">계산</span>
                  )}
                </td>
                <td>{solutionLabel(r)}</td>
                <td>
                  <code>{r.engine_version}</code>
                </td>
                <td>{r.objective_stages.length ? r.objective_stages.map((o) => `${o.objective}:${o.status}`).join(', ') : '없음(계산 안 함)'}</td>
                <td>{r.validation_status === 'not_run' ? '실행 안 함' : r.validation_status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function Metric({ label, a, b }: { label: string; a: number | string | null; b: number | string | null }) {
  return (
    <div className="metric">
      <div className="muted">{label}</div>
      <div>
        <span>{a ?? '미제공'}</span> → <b>{b ?? '미제공'}</b>
      </div>
    </div>
  )
}

export function MetricsRow({ base, cand }: { base: MethodResult; cand: MethodResult }) {
  return (
    <div className="metrics">
      <Metric label="미처리" a={base.metrics.unassigned_count} b={cand.metrics.unassigned_count} />
      {/* movable_violation_count는 마감 외 제약 위반도 포함한다(PR #4 리뷰). 마감만 따로 세려면 계약 합의 필요 */}
      <Metric label="제약 위반 작업(조정 가능)" a={base.metrics.movable_violation_count} b={cand.metrics.movable_violation_count} />
      <Metric label="고정 작업 위험" a={base.metrics.fixed_risk_count} b={cand.metrics.fixed_risk_count} />
      <Metric label="변경 작업 수" a={base.metrics.changed_job_ids.length} b={cand.metrics.changed_job_ids.length} />
      <Metric
        label="이동 부담(분)"
        a={base.metrics.movable_travel_minutes}
        b={cand.metrics.movable_travel_minutes}
      />
    </div>
  )
}

export function UnresolvedPanel({ rows, cand }: { rows: JobRow[]; cand: MethodResult }) {
  const unresolved = rows.filter((r) => r.candidateUnassigned)
  const lockedRisk = rows.filter((r) => r.locked && r.candidateIssues.length > 0)
  const general = cand.issues.filter((i) => i.job_id === null)
  return (
    <section className="card">
      <h2>미해결 · 고정 위험</h2>
      {unresolved.length === 0 && lockedRisk.length === 0 && general.length === 0 && <p className="muted">응답에 미해결 항목이 없습니다.</p>}
      {unresolved.map((r) => (
        <details key={r.job.job_id} open className="issue">
          <summary>
            <b>{r.job.job_id}</b> 미처리 — {r.candidateIssues.map((i) => ISSUE_LABEL[i.code] ?? i.code).join(', ') || '이유 미제공'}
          </summary>
          {r.candidateIssues.length === 0 && <p className="warn">응답에 이유가 없습니다. 엔진 담당에게 확인이 필요합니다.</p>}
          {r.candidateIssues.map((i, k) => (
            <ul key={k}>
              <li>{i.explanation}</li>
              <li className="muted">
                근거 수준: {PROOF_LABEL[i.proof_level]} · 근거: {i.evidence_refs.join(', ') || '없음'}
              </li>
              <li className="muted">
                추가 확인: 준비시각 {kstDateTime(r.job.ready_at)} · 마감 {kstTime(r.window?.closes_at)}
              </li>
            </ul>
          ))}
        </details>
      ))}
      {lockedRisk.map((r) => (
        <details key={`l-${r.job.job_id}`} open className="issue">
          <summary>
            <b>{r.job.job_id}</b> 고정 작업 잔여 위험 (유지됨)
          </summary>
          {r.candidateIssues.map((i, k) => (
            <p key={k}>{i.explanation}</p>
          ))}
        </details>
      ))}
      {general.map((i, k) => (
        <p key={`g-${k}`} className="warn">
          {ISSUE_LABEL[i.code] ?? i.code}: {i.explanation}
        </p>
      ))}
    </section>
  )
}
