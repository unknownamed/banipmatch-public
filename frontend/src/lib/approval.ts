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
    reasons.push('설명용 예시 결과(illustrative_fixture)입니다. 실제 계산이 아니므로 승인할 수 없습니다.')
  if (result.method === 'B0') reasons.push('B0는 원안 진단이며 승인 대상(B1~B3)이 아닙니다.')
  if (!['HEURISTIC', 'OPTIMAL', 'FEASIBLE'].includes(result.solution_status))
    reasons.push(`승인 가능한 해 상태가 아닙니다(${result.solution_status}).`)
  if (run.status !== 'completed') reasons.push(`실행 상태가 completed가 아닙니다(${run.status}).`)
  if (!result.approval_eligible) reasons.push('서버가 승인 가능(approval_eligible)으로 표시하지 않았습니다.')
  if (result.validation_status !== 'passed')
    reasons.push(`독립 일정 검사를 통과하지 않았습니다(validation_status=${result.validation_status}).`)
  if (!activeScenarioId || run.scenario_id !== activeScenarioId)
    reasons.push(`이 결과의 입력(${run.scenario_id})이 현재 입력(${activeScenarioId})과 다릅니다.`)
  if (!run.methods.includes(result.method)) reasons.push('현재 실행에서 요청한 방법의 결과가 아닙니다.')
  if (context) {
    const { snapshot, results, runId } = context
    if (run.run_id !== runId || results.run_id !== runId || results.scenario_id !== activeScenarioId)
      reasons.push('화면에서 요청한 실행·입력과 결과가 다릅니다.')
    if (snapshot.plan_id !== run.plan_id || snapshot.base_plan_version !== run.base_plan_version || results.base_plan_version !== run.base_plan_version)
      reasons.push('입력·실행·결과의 계획 또는 기준 버전이 다릅니다.')
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
  if (code === 'PLAN_VERSION_CONFLICT') return '검토하는 동안 계획이 바뀌었습니다. 최신 계획과 입력으로 다시 계산한 뒤 승인하세요.'
  if (code === 'IDEMPOTENCY_CONFLICT') return '같은 요청 키로 다른 내용을 보냈습니다. 화면을 새로고침한 뒤 요청 내용을 확인하세요.'
  if (code === 'RESULT_NOT_COMPUTED') return '설명용 예시 결과는 승인할 수 없습니다.'
  if (code === 'APPROVAL_NOT_IMPLEMENTED') return '현재 서버의 승인 기능은 미구현입니다. 내부 계획이 승인된 것으로 처리하지 않습니다.'
  if (code === 'STORAGE_UNAVAILABLE') return '서버 저장소를 사용할 수 없습니다. 복구 후 같은 요청으로 다시 확인하세요.'
  if (code === 'WINDOW_UNCONFIRMED' || code === 'INPUT_EXPIRED' || code === 'INPUT_STALE') return '필수 근거의 확인 상태나 유효기간이 충족되지 않았습니다. 변경 근거를 확인하고 최신 입력으로 다시 계산하세요.'
  if (status === 409) return '이 결과의 입력이나 계획이 현재 서버 상태와 다릅니다. 최신 입력으로 다시 계산하세요.'
  if (status === 503) return '서버가 승인을 처리할 수 없습니다. 오류 코드와 확인 상태를 확인하세요. 원인을 유효기간 문제로 단정하지 않습니다.'
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
  if (!plan) return '승인 응답은 받았지만 서버 현재 계획을 조회하지 못했습니다. 현재 계획을 다시 확인하세요.'
  if (plan.plan_id !== approval.plan_id) return '서버가 다른 계획을 반환했습니다. 현재 계획 확인이 필요합니다.'
  if (plan.version !== approval.version || plan.scenario_id !== scenarioId || plan.approval_id !== approval.approval_id)
    return `서버 현재 계획(v${plan.version}, 입력 ${plan.scenario_id})이 이번 승인과 다릅니다. 최신 계획을 확인하세요.`
  return null
}
