import { useMemo, useState } from 'react'
import type { ApiClient } from './api/client'
import { useDispatchView } from './api/useDispatchView'
import { ComparisonTable } from './components/ComparisonTable'
import { ApprovalPanel, ChangeEvidence, Header, MetricsRow, RunStatusPanel, UnresolvedPanel } from './components/Panels'
import { approvalGate } from './lib/approval'
import { buildRows, lockedViolations } from './lib/compare'

export function App({ client, scenarioId, runId }: { client: ApiClient; scenarioId: string; runId: string }) {
  const view = useDispatchView(client, scenarioId, runId)
  const [picked, setPicked] = useState<string | null>(null)

  const snapshot = view.scenario.state === 'ready' ? view.scenario.data : null
  const run = view.run.state === 'ready' ? view.run.data : null
  const results = view.results.state === 'ready' ? view.results.data.results : null
  const base = results?.find((r) => r.method === 'B0')
  const candidates = results?.filter((r) => r.method !== 'B0') ?? []
  const cand = candidates.find((r) => r.method === picked) ?? candidates[0]
  const rows = useMemo(() => (snapshot ? buildRows(snapshot, base, cand) : []), [snapshot, base, cand])
  const anyFixture = results?.some((r) => r.result_origin === 'illustrative_fixture')
  const broken = lockedViolations(rows)

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

      <section className="card">
        <h2>원안 · 조정안 비교</h2>
        {view.results.state === 'loading' && <p className="muted">결과 조회 중… (원안과 근거는 위에서 먼저 확인할 수 있습니다)</p>}
        {view.results.state === 'pending' && <p className="muted">계산 중입니다. 결과가 도착하면 자동으로 표시합니다.</p>}
        {view.results.state === 'error' && <p className="warn">결과를 표시할 수 없습니다: {view.results.message}</p>}
        {results && results.length === 0 && <p className="warn">결과 목록이 비어 있습니다. 해결 완료가 아닙니다.</p>}
        {snapshot && results && cand && (
          <>
            {candidates.length > 1 && (
              <div className="tabs" role="tablist">
                {candidates.map((r) => (
                  <button key={r.method} role="tab" aria-selected={r === cand} onClick={() => setPicked(r.method)}>
                    {r.method}
                  </button>
                ))}
              </div>
            )}
            {base && <MetricsRow base={base} cand={cand} />}
            {base && cand.metrics.unassigned_count > base.metrics.unassigned_count && (
              <p className="warn">
                미처리가 {base.metrics.unassigned_count}건 → {cand.metrics.unassigned_count}건으로 늘었습니다. 마감 위반 감소에는 미처리로 남긴 작업이
                포함되어 있으므로 전체 해결이 아닙니다.
              </p>
            )}
            {broken.length > 0 && (
              <p className="warn">고정 작업 {broken.join(', ')}이(가) 조정안에서 바뀌었거나 빠졌습니다. 엔진·검증 담당 확인이 필요합니다.</p>
            )}
            <ComparisonTable rows={rows} asOf={snapshot.as_of} baseLabel={base ? 'B0 원안' : '원안(입력)'} candLabel={`${cand.method} 조정안`} />
          </>
        )}
      </section>

      {snapshot && cand && (
        <>
          <UnresolvedPanel rows={rows} cand={cand} />
          <ApprovalPanel gate={approvalGate(run, cand, snapshot.scenario_id)} method={cand.method} />
        </>
      )}
    </main>
  )
}
