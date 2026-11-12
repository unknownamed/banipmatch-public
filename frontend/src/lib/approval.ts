// 승인 버튼을 열지 판단하는 화면 쪽 조건. 최종 판단은 서버(안선효)가 다시 한다.
// 여기서는 "서버에 보내도 거절될 것이 확실한 경우"를 미리 막고 이유를 보여준다.
import type { Approval, ApprovalRequest, MethodResult, Plan, Results, Run, Snapshot } from '../api/types'

export interface ApprovalGate {
  allowed: boolean
  reasons: string[]
}

export function approvalGate(run: Run | null, result: MethodResult | undefined, activeScenarioId: string | null, context?: { snapshot: Snapshot; results: Results; runId: string }): ApprovalGate {
  const reasons: string[] = []
  if (!run || !result) return { allowed: false, reasons: ['계산 결과가 아직 없습니다.'] }
  if (result.result_origin === 'illustrative_fixture')
    reasons.push('실제 계산 결과가 아니라 승인할 수 없습니다.')
  if (result.method === 'B0') reasons.push('원래 배차는 승인할 조정안이 아닙니다.')
  if (!['HEURISTIC', 'OPTIMAL', 'FEASIBLE'].includes(result.solution_status))
    reasons.push('쓸 수 있는 조정안을 찾지 못해 승인할 수 없습니다.')
  if (run.status !== 'completed') reasons.push('계산이 아직 끝나지 않았습니다.')
  if (!result.approval_eligible) reasons.push('서버 검사에서 승인할 수 없는 결과로 표시됐습니다.')
  if (result.validation_status !== 'passed')
    reasons.push('일정 검사를 통과하지 못했습니다.')
  if (!activeScenarioId || run.scenario_id !== activeScenarioId)
    reasons.push('지금 보고 있는 변경과 다른 계산 결과입니다.')
  if (!run.methods.includes(result.method)) reasons.push('이번 계산에서 요청한 조정안이 아닙니다.')
  if (context) {
    const { snapshot, results, runId } = context
    if (run.run_id !== runId || results.run_id !== runId || results.scenario_id !== activeScenarioId)
      reasons.push('화면의 변경 내용과 계산 결과가 맞지 않습니다. 새로고침하세요.')
    if (snapshot.plan_id !== run.plan_id || snapshot.base_plan_version !== run.base_plan_version || results.base_plan_version !== run.base_plan_version)
      reasons.push('계산한 뒤 배차가 바뀌었습니다. 최신 배차로 다시 계산하세요.')
  }
  return { allowed: reasons.length === 0, reasons }
}

/** 승인 전에 담당자가 확인해야 하는 작업: 미처리 ∪ 고정 작업 잔여 위험. */
export function acknowledgeIds(result: MethodResult): string[] {
  const risky = result.issues.filter((i) => i.code === 'FIXED_RESIDUAL_RISK' && i.job_id).map((i) => i.job_id!)
  return [...new Set([...result.unassigned_job_ids, ...risky])].sort()
}

/** 승인 실패 응답을 담당자가 할 일로 바꾼다. Error.code 기준이며 모르는 코드는 서버 메시지만 쓴다. */
export function approvalErrorHint(status: number, code: string | undefined): string | null {
  if (code === 'PLAN_VERSION_CONFLICT') return '검토하는 동안 배차가 바뀌었습니다. 최신 배차로 다시 계산한 뒤 승인하세요.'
  if (code === 'IDEMPOTENCY_CONFLICT') return '같은 승인을 다른 내용으로 다시 보냈습니다. 화면을 새로고침한 뒤 확인하세요.'
  if (code === 'RESULT_NOT_COMPUTED') return '실제 계산 결과가 아니라 승인할 수 없습니다.'
  if (code === 'APPROVAL_NOT_IMPLEMENTED') return '이 서버에서는 승인을 처리할 수 없습니다.'
  if (code === 'STORAGE_UNAVAILABLE') return '서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도하세요.'
  if (code === 'WINDOW_UNCONFIRMED' || code === 'INPUT_EXPIRED' || code === 'INPUT_STALE') return '공지가 확정되지 않았거나 계산한 지 오래됐습니다. 최신 내용으로 다시 계산하세요.'
  if (status === 409) return '계산한 뒤 내용이 바뀌었습니다. 최신 내용으로 다시 계산하세요.'
  if (status === 503) return '서버가 지금 승인을 처리할 수 없습니다. 잠시 후 다시 시도하세요.'
  return null
}

/** HTTP 응답을 받은 거절은 입력·서버 상태를 고친 뒤 새 결과를 검토한다. 통신 실패만 같은 요청으로 재시도한다. */
export function approvalRetryAllowed(status: number, code: string | undefined): boolean {
  return (status >= 500 && status !== 503) || (status === 503 && code === 'STORAGE_UNAVAILABLE')
}

/** 방법 전환 후 돌아와도 동일한 승인 요청의 키를 보존한다. 캐시는 App 세션에만 둔다. */
export function approvalIdempotencyKey(cache: Map<string, string>, planId: string, request: ApprovalRequest): string {
  const target = JSON.stringify([planId, request.run_id, request.method, request.expected_version, [...request.acknowledged_job_ids].sort()])
  let key = cache.get(target)
  if (!key) {
    key = `approve-${crypto.randomUUID()}`
    cache.set(target, key)
  }
  return key
}

/** 성공 코드만으로 다른 실행의 응답이나 외부 행동을 승인 성공으로 표시하지 않는다. */
export function approvalResponseMatches(approval: Approval, run: Run, method: MethodResult['method']): boolean {
  if (!approval || typeof approval !== 'object') return false
  return approval.plan_id === run.plan_id && approval.run_id === run.run_id && approval.method === method &&
    approval.version === run.base_plan_version + 1 && typeof approval.approval_id === 'string' && !!approval.approval_id &&
    typeof approval.approved_by === 'string' && !!approval.approved_by &&
    typeof approval.approved_at === 'string' && approval.approved_at.endsWith('Z') && Number.isFinite(Date.parse(approval.approved_at)) &&
    approval.external_actions_performed === false
}

export function currentPlanWarning(plan: Plan | null, approval: Approval, scenarioId: string): string | null {
  if (!plan) return '승인은 됐지만 최신 배차를 불러오지 못했습니다. 새로고침해 확인하세요.'
  if (plan.plan_id !== approval.plan_id) return '다른 배차가 돌아왔습니다. 새로고침해 확인하세요.'
  if (plan.version !== approval.version || plan.scenario_id !== scenarioId || plan.approval_id !== approval.approval_id)
    return '최신 배차가 이번 승인과 다릅니다. 새로고침해 확인하세요.'
  return null
}
