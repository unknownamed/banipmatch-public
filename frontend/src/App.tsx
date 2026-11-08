import { useMemo, useState } from 'react'
import type { ApiClient } from './api/client'
import { useDispatchView } from './api/useDispatchView'
import { ComparisonSection } from './components/ComparisonSection'
import { ApprovalPanel } from './components/ApprovalPanel'
import { ChangeEvidence, Header, RunStatusPanel, UnresolvedPanel } from './components/Panels'
import { approvalGate } from './lib/approval'
import { buildRows } from './lib/compare'

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
          <ApprovalPanel key={`${run?.run_id}:${cand.method}`} gate={approvalGate(run, cand, snapshot.scenario_id)} client={client} run={run} result={cand} />
        </>
      )}
    </main>
  )
}
