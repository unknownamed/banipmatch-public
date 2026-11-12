import { ResultNav } from './components/ResultNav'
import { useEffect, useMemo, useState } from 'react'
import type { ApiClient } from './api/client'
import type { MethodResult } from './api/types'
import { useDispatchView } from './api/useDispatchView'
import { ComparisonSection } from './components/ComparisonSection'
import { ApprovalPanel, type SharedApproval } from './components/ApprovalPanel'
import { ChangeEvidence, Header, RunStatusPanel, UnresolvedPanel } from './components/Panels'
import { acknowledgeIds, approvalGate, approvalIdempotencyKey, type ApprovalGate } from './lib/approval'
import { buildRows } from './lib/compare'
import { Icon } from './components/Icon'
import { hasAssumedCondition } from './lib/revision'
import type { V2Client } from './api/v2'
import { ConditionRevisionPanel, NextPlanPanel, RevisionComparison } from './components/RevisionPanels'
import { DispatchPanel } from './components/DispatchPanel'
import { registerLabels } from './lib/labels'
import { ActionSummary } from './components/ActionSummary'

function recommend(list: MethodResult[]): MethodResult | undefined {
  const ok = list.filter((r) => r.result_origin === 'computed' && r.validation_status !== 'failed')
  const key = (r: MethodResult) => [r.metrics.unassigned_count, r.metrics.movable_violation_count, r.metrics.fixed_risk_count, r.metrics.changed_job_ids.length]
  return [...ok].sort((a, b) => { const x = key(a), y = key(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i]; return 0 })[0]
}

export function App({ client, scenarioId, runId }: { client: ApiClient; scenarioId: string; runId: string }) {
  const view = useDispatchView(client, scenarioId, runId)
  const [picked, setPicked] = useState<string | null>(null)
  const approvalKeys = useMemo(() => new Map<string, string>(), [client])
  // 승인 진행 상태는 방법 탭 전환으로 패널이 다시 만들어져도 유지한다. 실행이 바뀌면 버린다.
  const [approval, setApproval] = useState<{ key: string; value: SharedApproval }>({ key: '', value: null })
  const approvalScope = `${scenarioId}:${runId}:${client.mode}`

  const snapshot = view.scenario.state === 'ready' ? view.scenario.data : null
  registerLabels(snapshot)
  const run = view.run.state === 'ready' ? view.run.data : null
  const results = view.results.state === 'ready' ? view.results.data.results : null
  const base = results?.find((r) => r.method === 'B0')
  const candidates = results?.filter((r) => r.method !== 'B0') ?? []
  // 처음 열 때는 추천안을 보여 준다: 미처리 → 조정 가능 위반 → 고정 위험 → 변경 수가 적은 순. 사용자가 고르면 그 안을 따른다.
  const recommended = recommend(candidates)
  const cand = candidates.find((r) => r.method === picked) ?? recommended ?? candidates[0]
  const rows = useMemo(() => (snapshot ? buildRows(snapshot, base, cand) : []), [snapshot, base, cand])
  // 새로고침 뒤에도 이미 다른 승인으로 바뀐 계획을 409 전에 알린다. 최종 판단은 서버가 한다.
  const [planNow, setPlanNow] = useState<{ planId: string; version: number } | null>(null)
  useEffect(() => {
    if (!run || !client.getPlan) return
    let live = true
    client.getPlan(run.plan_id).then((p) => live && p.plan_id === run.plan_id && setPlanNow({ planId: p.plan_id, version: p.version })).catch(() => {})
    return () => { live = false }
  }, [client, run?.plan_id, approval.value?.status.state])
  const planMoved = run && planNow?.planId === run.plan_id && planNow.version !== run.base_plan_version && approval.value?.status.state !== 'done'
  const approvedPlan = approval.value?.status.state === 'done' || !!(run && planNow?.planId === run.plan_id && planNow.version > run.base_plan_version)
  // 원래 배차로 마감 문제가 없고 조정안도 바꿀 것이 없으면(예: 마감 늦춰짐) 확인만 하고 끝낸다. 승인·기사 전달·조건 보완을 띄우지 않는다.
  const unchanged = view.results.state === 'ready' && !!base && !!cand && base.metrics.movable_violation_count === 0 && base.metrics.fixed_risk_count === 0
    && base.metrics.unassigned_count === 0 && cand.metrics.unassigned_count === 0 && cand.metrics.changed_job_ids.length === 0
    && !base.issues.some((i) => i.code === 'INPUT_MISSING')
  const v2 = 'session' in client ? (client as V2Client) : null
  const params = new URLSearchParams(location.search)
  const revisionId = params.get('revision')
  const beforeRunId = params.get('before')
  const assumed = snapshot ? hasAssumedCondition(snapshot) : false
  const approvalKey = run && cand ? approvalIdempotencyKey(approvalKeys, run.plan_id, {
    run_id: run.run_id, method: cand.method, expected_version: run.base_plan_version, acknowledged_job_ids: acknowledgeIds(cand),
  }) : undefined

  return (
    <main>
      {view.scenario.state === 'loading' && <Skeleton label="변경 내용 불러오는 중…" lines={3} />}
      {view.scenario.state === 'error' && <p className="card warn">변경 내용을 불러오지 못했습니다: {view.scenario.message}</p>}

      {snapshot && (
        <>
          <Header s={snapshot} />
          {view.results.state === 'ready' && <ResultNav brief={unchanged} />}
          {view.results.state === 'ready' && (
            <ActionSummary base={base} cand={cand} recommended={recommended?.method} rows={rows}
              approved={!!run && (approval.value?.status.state === 'done' || (planNow?.planId === run.plan_id && planNow.version > run.base_plan_version))} />
          )}
          <ChangeEvidence s={snapshot} />
        </>
      )}

      {view.run.state === 'loading' && <Skeleton label="계산 상태 확인 중…" lines={2} />}
      {view.run.state === 'error' && <p className="card warn">계산 상태를 확인하지 못했습니다: {view.run.message}</p>}
      {run && run.status !== 'completed' && <RunStatusPanel run={run} results={results} />}
      {assumed && (
        <div className="banner fixture" role="alert">
          확인 전인 값을 가정해 계산한 결과입니다. 비교만 할 수 있고 확정·기사 전달은 할 수 없습니다.
        </div>
      )}
      {v2 && revisionId && run && cand && view.results.state === 'ready' && (
        <RevisionComparison client={v2} revisionId={revisionId} beforeRunId={beforeRunId} afterRunId={run.run_id} method={cand.method} snapshot={snapshot} />
      )}

      {/* 넓은 화면: 왼쪽 비교, 오른쪽 미해결·승인. 좁으면 위아래로 쌓인다. */}
      <div className="workspace">
        {snapshot && (
          <ComparisonSection
            snapshot={snapshot}
            results={view.results}
            base={base}
            cand={unchanged ? undefined : cand}
            candidates={unchanged ? [] : candidates}
            recommended={recommended?.method}
            rows={unchanged ? buildRows(snapshot, base, undefined) : rows}
            onPick={setPicked}
            unchanged={unchanged}
          />
        )}

        {snapshot && cand && unchanged && (
          <aside className="side">
            <section className="card all-clear">
              <h2><Icon name="check" size={18} /> 확인 완료</h2>
              <p>원래 배차 그대로 진행합니다.</p>
              <a className="button secondary" href="?">받은 변경으로 돌아가기</a>
            </section>
          </aside>
        )}
        {snapshot && cand && !unchanged && (
          <aside className="side">
            <UnresolvedPanel rows={rows} cand={cand} />
            <ApprovalPanel
              key={`${scenarioId}:${runId}:${run?.base_plan_version}:${cand.method}:${approvalKey}`}
              gate={withPlanCheck(withPlanCheck(approvalGate(run, cand, scenarioId, view.results.state === 'ready' ? { snapshot, results: view.results.data, runId } : undefined), planMoved ? '그사이 배차가 이미 확정·변경되어 이 결과로는 승인할 수 없습니다. 이미 승인한 것이면 그대로 두고, 아니면 최신 배차로 다시 계산하세요.' : null), assumed ? '가정한 값으로 계산한 결과라 확정할 수 없습니다. 확인된 값으로 다시 계산하세요.' : null)}
              client={client} run={run} result={cand} idempotencyKey={approvalKey}
              shared={approval.key === approvalScope ? approval.value : null}
              onShared={(value) => setApproval({ key: approvalScope, value })}
            />
          </aside>
        )}
      </div>

      {/* 승인 뒤(이번 화면에서 승인했거나 계획 버전이 이미 올라간 경우) 전달 단계. 최종 확인은 서버의 dispatch-preview가 한다. */}
      {v2 && run && (approval.value?.status.state === 'done' || (planNow?.planId === run.plan_id && planNow.version > run.base_plan_version)) && (
        <DispatchPanel key={`dispatch:${run.plan_id}:${planNow?.version}`} client={v2} planId={run.plan_id} />
      )}

      {v2 && snapshot && run && view.results.state === 'ready' && !unchanged && (approvedPlan
        ? <NextPlanPanel key={`next:${run.plan_id}:${planNow?.version}`} client={v2} planId={run.plan_id} rerun={{ methods: run.methods, time_limit_seconds: run.config.time_limit_seconds, seed: run.config.seed, beforeRunId: null }} />
        : <ConditionRevisionPanel key={snapshot.scenario_id} client={v2} snapshot={snapshot} focus={[...(cand?.unassigned_job_ids ?? []), ...(cand?.issues ?? []).flatMap((i) => i.job_id ? [i.job_id] : [])]} rerun={{ methods: run.methods, time_limit_seconds: run.config.time_limit_seconds, seed: run.config.seed, beforeRunId: run.run_id }} />)}

      {/* 계산 방법별 상태·독립 검사는 검증용 정보라 아래에 둔다(실패하면 위에 바로 보인다). */}
    </main>
  )
}

function withPlanCheck(gate: ApprovalGate, reason: string | null): ApprovalGate {
  return reason ? { allowed: false, reasons: [...gate.reasons, reason] } : gate
}

/** 불러오는 동안 실제 카드 크기의 회색 자리표시. 글자는 화면 낭독기용으로 남긴다. */
function Skeleton({ label, lines }: { label: string; lines: number }) {
  return (
    <div className="card skeleton" role="status" aria-busy="true">
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, i) => (
        <i key={i} style={{ width: `${88 - i * 18}%` }} />
      ))}
    </div>
  )
}
