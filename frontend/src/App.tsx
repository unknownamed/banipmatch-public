import { useEffect, useMemo, useState } from 'react'
import type { ApiClient } from './api/client'
import { useDispatchView } from './api/useDispatchView'
import { ComparisonSection } from './components/ComparisonSection'
import { ApprovalPanel, type SharedApproval } from './components/ApprovalPanel'
import { ChangeEvidence, Header, RunStatusPanel, UnresolvedPanel } from './components/Panels'
import { acknowledgeIds, approvalGate, approvalIdempotencyKey, type ApprovalGate } from './lib/approval'
import { buildRows } from './lib/compare'
import { hasAssumedCondition } from './lib/revision'
import type { V2Client } from './api/v2'
import { ConditionRevisionPanel, NextPlanPanel, RevisionComparison } from './components/RevisionPanels'
import { DispatchPanel } from './components/DispatchPanel'

export function App({ client, scenarioId, runId }: { client: ApiClient; scenarioId: string; runId: string }) {
  const view = useDispatchView(client, scenarioId, runId)
  const [picked, setPicked] = useState<string | null>(null)
  const approvalKeys = useMemo(() => new Map<string, string>(), [client])
  // 승인 진행 상태는 방법 탭 전환으로 패널이 다시 만들어져도 유지한다. 실행이 바뀌면 버린다.
  const [approval, setApproval] = useState<{ key: string; value: SharedApproval }>({ key: '', value: null })
  const approvalScope = `${scenarioId}:${runId}:${client.mode}`

  const snapshot = view.scenario.state === 'ready' ? view.scenario.data : null
  const run = view.run.state === 'ready' ? view.run.data : null
  const results = view.results.state === 'ready' ? view.results.data.results : null
  const base = results?.find((r) => r.method === 'B0')
  const candidates = results?.filter((r) => r.method !== 'B0') ?? []
  const cand = candidates.find((r) => r.method === picked) ?? candidates[0]
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
  const anyFixture = results?.some((r) => r.result_origin === 'illustrative_fixture')
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
      {client.mode === 'fixture' && (
        <div className="banner" role="note">
          공통 예제(모의 자료) 화면입니다. 백엔드 없이 <code>docs/development/v0.1/예제 데이터</code>를 그대로 표시합니다.
        </div>
      )}
      {anyFixture && (
        <div className="banner fixture" role="alert">
          설명용 예시 결과(illustrative_fixture)입니다. 최적화 엔진이 계산한 결과가 아니며 성능 근거나 승인 대상으로 쓸 수 없습니다.
        </div>
      )}

      {view.scenario.state === 'loading' && <Skeleton label="입력 불러오는 중…" lines={3} />}
      {view.scenario.state === 'error' && <p className="card warn">입력 조회 실패: {view.scenario.message}</p>}

      {snapshot && (
        <>
          <Header s={snapshot} />
          <ChangeEvidence s={snapshot} />
        </>
      )}

      {view.run.state === 'loading' && <Skeleton label="실행 상태 조회 중…" lines={2} />}
      {view.run.state === 'error' && <p className="card warn">실행 상태 조회 실패: {view.run.message}</p>}
      {run && <RunStatusPanel run={run} results={results} />}
      {assumed && (
        <div className="banner fixture" role="alert">
          가정 시험 입력입니다. 준비·가용 조건에 가정이 섞여 있어 비교만 할 수 있고 승인·전달할 수 없습니다.
        </div>
      )}
      {v2 && revisionId && run && cand && view.results.state === 'ready' && (
        <RevisionComparison client={v2} revisionId={revisionId} beforeRunId={beforeRunId} afterRunId={run.run_id} method={cand.method} />
      )}

      {/* 넓은 화면: 왼쪽 비교, 오른쪽 미해결·승인. 좁으면 위아래로 쌓인다. */}
      <div className="workspace">
        {snapshot && (
          <ComparisonSection
            snapshot={snapshot}
            results={view.results}
            base={base}
            cand={cand}
            candidates={candidates}
            rows={rows}
            onPick={setPicked}
          />
        )}

        {snapshot && cand && (
          <aside className="side">
            <UnresolvedPanel rows={rows} cand={cand} />
            <ApprovalPanel
              key={`${scenarioId}:${runId}:${run?.base_plan_version}:${cand.method}:${approvalKey}`}
              gate={withPlanCheck(withPlanCheck(approvalGate(run, cand, scenarioId, view.results.state === 'ready' ? { snapshot, results: view.results.data, runId } : undefined), planMoved ? `현재 계획이 v${planNow!.version}입니다. 이 결과는 v${run!.base_plan_version} 기준이라 승인할 수 없습니다. 이미 승인됐다면 다시 보낼 필요가 없고, 아니면 최신 계획으로 다시 계산하세요.` : null), assumed ? '가정 시험 입력이라 승인할 수 없습니다. 확인된 조건으로 다시 보완해 계산하세요.' : null)}
              client={client} run={run} result={cand} idempotencyKey={approvalKey}
              shared={approval.key === approvalScope ? approval.value : null}
              onShared={(value) => setApproval({ key: approvalScope, value })}
            />
          </aside>
        )}
      </div>

      {/* 승인 뒤(이번 화면에서 승인했거나 계획 버전이 이미 올라간 경우) 전달 단계. 최종 확인은 서버의 dispatch-preview가 한다. */}
      {v2 && run && (approval.value?.status.state === 'done' || (planNow?.planId === run.plan_id && planNow.version > run.base_plan_version)) && (
        <DispatchPanel key={`${run.plan_id}:${planNow?.version}`} client={v2} planId={run.plan_id} />
      )}

      {v2 && snapshot && run && view.results.state === 'ready' && (approvedPlan
        ? <NextPlanPanel key={`${run.plan_id}:${planNow?.version}`} client={v2} planId={run.plan_id} rerun={{ methods: run.methods, time_limit_seconds: run.config.time_limit_seconds, seed: run.config.seed, beforeRunId: null }} />
        : <ConditionRevisionPanel key={snapshot.scenario_id} client={v2} snapshot={snapshot} rerun={{ methods: run.methods, time_limit_seconds: run.config.time_limit_seconds, seed: run.config.seed, beforeRunId: run.run_id }} />)}
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
