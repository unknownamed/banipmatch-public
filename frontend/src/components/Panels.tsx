import { issueText } from '../lib/issueText'
import type { MethodResult, Run, Snapshot } from '../api/types'
import { ISSUE_LABEL, type JobRow } from '../lib/compare'
import { Icon } from './Icon'
import { humanizeTimes, kstDateTime, kstTimeWithDay } from '../lib/time'
import { VESSELS } from '../lib/vesselApproach'
import { jobName } from '../lib/labels'

const DATA_MODE: Record<Snapshot['data_mode'], string> = { simulated: '모의', observed: '관측', mixed: '혼합' }
const VERIFY: Record<string, string> = { confirmed: '확정', unconfirmed: '미확정', conflict: '충돌' }

export function Header({ s }: { s: Snapshot }) {
  const c = s.change
  return (
    <header className="page-head top">
      <div>
        <nav className="crumbs" aria-label="위치"><a href="?">받은 변경</a><span aria-hidden="true">/</span>점검 결과</nav>
        <h1>{c.terminal_id} {c.voyage_id} 반입 마감 변경</h1>
        <p>{s.change.verification === 'confirmed' ? '새 마감으로 남은 배차를 점검했습니다' : '확정 전 공지라 배차는 그대로입니다'} ({kstDateTime(s.as_of)} 기준)</p>
      </div>
      {/* 데모 환경 배지가 위에 있으므로 모의 자료는 따로 표시하지 않는다. 실제·혼합 자료일 때만 구분 배지를 단다. */}
      {s.data_mode !== 'simulated' && (
        <span className={`badge mode-${s.data_mode}`} title="입력 자료 구분">
          {DATA_MODE[s.data_mode]} 자료
        </span>
      )}
    </header>
  )
}

const sourceLabel = (ref: string) => (ref.startsWith('fixture:') ? '데모 시나리오' : ref)
function shiftText(prev: string | null, next: string | null | undefined) {
  if (!prev || !next) return null
  const m = Math.round((Date.parse(next) - Date.parse(prev)) / 60000)
  if (m === 0) return '변동 없음'
  const a = Math.abs(m), t = a >= 60 ? `${Math.floor(a / 60)}시간${a % 60 ? ` ${a % 60}분` : ''}` : `${a}분`
  return m < 0 ? `${t} 앞당겨짐` : `${t} 늦춰짐`
}

export function ChangeEvidence({ s }: { s: Snapshot }) {
  const c = s.change
  const w = s.windows.find((x) => x.window_id === c.new_window_id)
  const moved = shiftText(c.previous_closes_at, w?.closes_at)
  // 모의 선박 일정에 같은 항차가 있으면, 반입 마감 변경과 함께 바뀐 모선 접안 예정을 보여 준다(HJNC 공개 일정의 '접안 10시간 전 마감' 간격).
  // 접안 10시간 전 마감 간격은 HJNC 공개 일정에서 확인한 값이라 HJNC에만 적용한다.
  const vessel = c.terminal_id === 'HJNC' ? VESSELS.find((v) => v.voyage === c.voyage_id && v.terminal === c.terminal_id) : undefined
  const later = !!(w?.closes_at && c.previous_closes_at && Date.parse(w.closes_at) > Date.parse(c.previous_closes_at))
  const plus10 = (t: string) => new Date(Date.parse(t) + 10 * 3600_000).toISOString()
  const berth = vessel?.name && w?.closes_at && c.previous_closes_at ? { name: vessel.name, prev: plus10(c.previous_closes_at), next: plus10(w.closes_at) } : null
  return (
    <section className="card evidence">
      <h2>반입 마감 변경</h2>
      {w && (
        <p className="change-lead">
          반입 마감 <s>{kstTimeWithDay(c.previous_closes_at, s.as_of)}</s> → <b className={`change-new${later ? ' later' : ''}`}>{kstTimeWithDay(w.closes_at, s.as_of)}</b>
          {moved && <span className={`change-delta${later ? ' later' : ''}`}>{moved}</span>}
        </p>
      )}
      {w && berth && (
        <p className="change-why">
          <Icon name="ship" size={15} /> <span>모선 <b>{berth.name}</b> 접안 예정도 {c.verification === 'confirmed' ? (later ? '늦춰졌습니다' : '앞당겨졌습니다') : (later ? '늦춰질 예정입니다(확정 전)' : '앞당겨질 예정입니다(확정 전)')}: <s>{kstTimeWithDay(berth.prev, s.as_of)}</s> → <b>{kstTimeWithDay(berth.next, s.as_of)}</b>.</span>
        </p>
      )}
      {/* service-comparison.md: 접안예정·반입시간·방문예약·내부계획을 구분해 표시 */}
      <dl className="evidence-strip">
        <div>
          <dt>반입 시작</dt>
          <dd>{kstTimeWithDay(w?.opens_at ?? c.previous_opens_at, s.as_of)}</dd>
        </div>
        <div>
          <dt>상태</dt>
          <dd>
            <span className={c.verification === 'confirmed' ? 'ok' : 'warn'}>{VERIFY[c.verification] ?? c.verification}</span>
            <div className="small">{c.confirmed_at ? `${kstDateTime(c.confirmed_at)} 확정` : '터미널 확정 대기'}</div>
          </dd>
        </div>
        <div>
          <dt>근거</dt>
          <dd>
            {c.evidence.source_ref.startsWith('fixture:') ? `${c.terminal_id} 반입 마감 변경 공지` : sourceLabel(c.evidence.source_ref)}
          </dd>
        </div>
      </dl>
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
  HEURISTIC: '빠른 계산(최적 아님)',
  FEASIBLE: '실행 가능(최적 미확인)',
  OPTIMAL: '최적',
  INFEASIBLE: '해 없음',
  UNKNOWN: '시간 내 해 미발견',
  MODEL_INVALID: '모델 오류',
  INPUT_INCOMPLETE: '입력 부족',
}

export function solutionLabel(r: MethodResult): string {
  const s = r.solution_status === 'OPTIMAL' && !r.objective_proven ? '최적(확인 안 됨)' : SOLUTION_LABEL[r.solution_status]
  return s ?? `알 수 없음(${r.solution_status})`
}

const METHOD_LABEL: Record<string, string> = {
  B0: '원래 배차 그대로 점검',
  B1: '마감 빠른 순 재배치',
  B2: '전체 재최적화',
  B3: '최소 변경 최적화',
}
const CHECK_LABEL: Record<string, string> = { passed: '통과', failed: '실패', not_run: '해당 없음' }

export function RunStatusPanel({ run, results }: { run: Run; results: MethodResult[] | null }) {
  return (
    <section className="card">
      <h2>조정안 계산</h2>
      <p>
        <span className={`st ${run.status === 'failed' || run.status === 'cancelled' ? 'bad' : 'run'}`}>{RUN_LABEL[run.status]}</span>{' '}
        {run.status === 'failed' || run.status === 'cancelled'
          ? '조정안을 만들지 못했습니다.'
          : `원래 배차와 조정안 ${Math.max(0, run.methods.length - 1)}가지를 같은 조건으로 계산하고 있습니다. 보통 ${run.config.time_limit_seconds}초 안에 끝납니다.`}
      </p>
      {run.status === 'failed' && (
        <div className="warn" role="alert">
          <p>실패 이유: {run.error ? run.error.message : '사유 미제공'}</p>
          {/* 실패 방법·이유는 details에 온다(예: "B2: 실행 제한시간 초과"). 실패한 실행의 결과는 승인하지 않는다. */}
          {run.error?.details?.map((d, i) => (
            <p key={i} className="small">
              <code>{d.path}</code> {d.reason}
            </p>
          ))}
          {run.error && <p className="muted small">오류 코드 {run.error.code}{run.error.request_id ? `, 요청 ${run.error.request_id}` : ''}</p>}
          <p className="muted small">이번 계산 결과는 저장하지 않았습니다. 받은 변경에서 다시 계산하세요.</p>
        </div>
      )}
      {results && (
        <div className="table-wrap">
          <table className="grid small stack run-table">
            <thead>
              <tr>
                <th className="nowrap">방법</th>
                <th>결과 출처</th>
                <th>결과</th>
                <th className="col-tech">엔진</th>
                <th className="col-tech">목표 단계</th>
                <th>독립 검사</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.method}>
                  <td className="method-cell"><b>{r.method}</b> <span className="muted small">{METHOD_LABEL[r.method] ?? ''}</span></td>
                  <td data-label="결과 출처">
                    {r.result_origin === 'illustrative_fixture' ? (
                      <span className="badge fixture">설명용 예시</span>
                    ) : (
                      <span className="badge">엔진 계산</span>
                    )}
                  </td>
                  <td data-label="결과">{solutionLabel(r)}</td>
                  <td className="col-tech" data-label="엔진">
                    <code>{r.engine_version}</code>
                  </td>
                  <td className="col-tech" data-label="목표 단계">{r.objective_stages.length ? r.objective_stages.map((o) => `${o.objective}:${o.status}`).join(', ') : '없음(계산 안 함)'}</td>
                  <td data-label="독립 검사">{CHECK_LABEL[r.validation_status] ?? r.validation_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// 모든 지표는 작을수록 좋다. 나빠진 값은 강조하고, 값이 없으면 비교하지 않는다.
function Metric({ label, a, b, icon }: { label: string; a: number | null; b: number | null; icon: Parameters<typeof Icon>[0]['name'] }) {
  const trend = a === null || b === null || a === b ? '' : b > a ? 'worse' : 'better'
  // 막대는 응답에 있는 원안·조정안 두 값만 같은 척도로 그린다. 값이 없으면 그리지 않는다.
  return (
    <div className={`metric ${trend}`}>
      <div className="metric-head">
        <span className="metric-icon">
          <Icon name={icon} size={14} />
        </span>
        <span className="metric-label">{label}</span>
      </div>
      <div className="metric-body">
        <div>
          <div className="metric-value">{b ?? '미제공'}</div>
          <div className="metric-base">
            {trend && (
              <span className="metric-delta">
                <Icon name={trend === 'worse' ? 'up' : 'down'} size={11} /> {Math.abs(b! - a!)}{' '}
              </span>
            )}
            원래 배차 {a ?? '미제공'}
          </div>
        </div>
      </div>
    </div>
  )
}
export function MetricsRow({ base, cand }: { base: MethodResult; cand: MethodResult }) {
  return (
    <div className="metrics">
      <Metric label="미배정" icon="warning" a={base.metrics.unassigned_count} b={cand.metrics.unassigned_count} />
      {/* movable_violation_count는 마감 외 제약 위반도 포함한다(PR #4 리뷰). 마감만 따로 세려면 계약 합의 필요 */}
      <Metric label="마감·조건 위반" icon="clock" a={base.metrics.movable_violation_count} b={cand.metrics.movable_violation_count} />
      <Metric label="출발한 차량 위험" icon="lock" a={base.metrics.fixed_risk_count} b={cand.metrics.fixed_risk_count} />
      <Metric label="바뀌는 작업" icon="swap" a={base.metrics.changed_job_ids.length} b={cand.metrics.changed_job_ids.length} />
      <Metric
        label="총 이동 시간(분)"
        icon="truck"
        a={base.metrics.movable_travel_minutes}
        b={cand.metrics.movable_travel_minutes}
      />
    </div>
  )
}

// 이유별 다음 행동(R3). 해결을 보장하지 않고, 확인할 곳과 다음 단계만 안내한다.
const NEXT_STEP: Record<string, string> = {
  READY_TOO_LATE: '화주에게 상차 준비를 앞당길 수 있는지 확인하세요. 가능하면 아래 ‘조건 보완’에서 준비 시각을 고쳐 다시 계산하고, 어렵다면 선사와 차기 모선 선적을 협의하세요.',
  SEARCH_LIMIT: '더 쓸 수 있는 차량이 있는지 확인하세요. 있으면 아래 ‘조건 보완’에서 차량을 추가해 다시 계산합니다.',
  VEHICLE_UNAVAILABLE: '기사에게 차량 가용 시각과 근무 종료 시각을 확인한 뒤 ‘조건 보완’에서 고쳐 다시 계산하세요.',
  SHIFT_EXCEEDED: '기사 근무 연장이 가능한지 확인한 뒤 ‘조건 보완’에서 근무 종료 시각을 고쳐 다시 계산하세요.',
  CUTOFF_EXCEEDED: '터미널에 예외 반입이 가능한지 문의하고, 어렵다면 선사와 차기 모선 선적을 협의하세요.',
  INCOMPATIBLE_EQUIPMENT: '컨테이너 규격에 맞는 장비 차량이 있는지 확인하세요.',
  CAPACITY_EXCEEDED: '이 중량을 실을 수 있는 차량이 있는지 확인하세요.',
  INPUT_MISSING: '비어 있는 값(준비 시각·이동 시간 등)을 확인해 입력하세요.',
}

export function UnresolvedPanel({ rows, cand }: { rows: JobRow[]; cand: MethodResult }) {
  const unresolved = rows.filter((r) => r.candidateUnassigned)
  const lockedRisk = rows.filter((r) => r.locked && r.candidateIssues.length > 0)
  const general = cand.issues.filter((i) => i.job_id === null)
  // 확인할 것이 없으면 빈 칸을 보여 주지 않는다(요약에 이미 '남는 문제 없음'이 있다).
  if (unresolved.length === 0 && lockedRisk.length === 0 && general.length === 0) return null
  return (
    <section className="card unresolved">
      <h2>확인 필요 {unresolved.length + lockedRisk.length > 0 && <span className="count-pill">{unresolved.length + lockedRisk.length}</span>}</h2>
      {unresolved.map((r) => (
        <div key={r.job.job_id} className="issue-card">
          <p className="issue-title">
            <b>{jobName(r.job.job_id)}</b> <span className="badge unassigned">미배정</span>{' '}
            {r.candidateIssues.map((i) => ISSUE_LABEL[i.code] ?? i.code).join(', ') || '이유 미제공'}
          </p>
          {r.candidateIssues.length === 0 && <p className="warn small">배정하지 못한 이유를 받지 못했습니다. 화주나 기사에게 직접 확인하세요.</p>}
          {r.candidateIssues.map((i, k) => (
            <div key={k} className="issue-body small">
              <p>{issueText(i.code, i.explanation)}</p>
              {NEXT_STEP[i.code] && <p className="next-step"><b>할 일</b> {NEXT_STEP[i.code]}</p>}
            </div>
          ))}
        </div>
      ))}
      {lockedRisk.map((r) => (
        <div key={`l-${r.job.job_id}`} className="issue-card">
          <p className="issue-title"><b>{jobName(r.job.job_id)}</b> <span className="badge lock">출발함</span> 마감 위험(배차 유지)</p>
          {r.candidateIssues.map((i, k) => (
            <p key={k} className="small">{humanizeTimes(i.explanation)}</p>
          ))}
          <p className="next-step small"><b>할 일</b> 기사에게 현재 위치와 게이트 도착 예상 시각을 확인하세요.</p>
        </div>
      ))}
      {general.map((i, k) => (
        <p key={`g-${k}`} className="warn">
          {ISSUE_LABEL[i.code] ?? i.code}: {humanizeTimes(i.explanation)}
        </p>
      ))}
    </section>
  )
}
