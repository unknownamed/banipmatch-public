import { useEffect, useMemo, useState } from 'react'
import type { ApiClient } from './api/client'
import { useDispatchView } from './api/useDispatchView'
import { ComparisonSection } from './components/ComparisonSection'
import { ApprovalPanel, type SharedApproval } from './components/ApprovalPanel'
import { ChangeEvidence, Header, RunStatusPanel, UnresolvedPanel } from './components/Panels'
import { acknowledgeIds, approvalGate, approvalIdempotencyKey, type ApprovalGate } from './lib/approval'
import { buildRows } from './lib/compare'

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
  const anyFixture = results?.some((r) => r.result_origin === 'illustrative_fixture')
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

      {view.scenario.state === 'loading' && <p className="card">입력 불러오는 중…</p>}
      {view.scenario.state === 'error' && <p className="card warn">입력 조회 실패: {view.scenario.message}</p>}

      {snapshot && (
        <>
          <Header s={snapshot} />
          <ChangeEvidence s={snapshot} />
        </>
      )}

      {view.run.state === 'loading' && <p className="card">실행 상태 조회 중…</p>}
      {view.run.state === 'error' && <p className="card warn">실행 상태 조회 실패: {view.run.message}</p>}
      {run && <RunStatusPanel run={run} results={results} />}

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
        <>
          <UnresolvedPanel rows={rows} cand={cand} />
          <ApprovalPanel
            key={`${scenarioId}:${runId}:${run?.base_plan_version}:${cand.method}:${approvalKey}`}
            gate={withPlanCheck(approvalGate(run, cand, scenarioId, view.results.state === 'ready' ? { snapshot, results: view.results.data, runId } : undefined), planMoved ? `현재 계획이 v${planNow!.version}입니다. 이 결과는 v${run!.base_plan_version} 기준이라 승인할 수 없습니다. 이미 승인됐다면 다시 보낼 필요가 없고, 아니면 최신 계획으로 다시 계산하세요.` : null)}
            client={client} run={run} result={cand} idempotencyKey={approvalKey}
            shared={approval.key === approvalScope ? approval.value : null}
            onShared={(value) => setApproval({ key: approvalScope, value })}
          />
        </>
      )}
    </main>
  )
}

function withPlanCheck(gate: ApprovalGate, reason: string | null): ApprovalGate {
  return reason ? { allowed: false, reasons: [...gate.reasons, reason] } : gate
}
