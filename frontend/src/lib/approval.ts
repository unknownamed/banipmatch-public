// 승인 버튼을 열지 판단하는 화면 쪽 조건. 최종 판단은 서버(안선효)가 다시 한다.
// 여기서는 "서버에 보내도 거절될 것이 확실한 경우"를 미리 막고 이유를 보여준다.
import type { MethodResult, Run } from '../api/types'

export interface ApprovalGate {
  allowed: boolean
  reasons: string[]
}

export function approvalGate(run: Run | null, result: MethodResult | undefined, activeScenarioId: string | null): ApprovalGate {
  const reasons: string[] = []
  if (!run || !result) return { allowed: false, reasons: ['계산 결과가 아직 없습니다.'] }
  if (result.result_origin === 'illustrative_fixture')
    reasons.push('설명용 예시 결과(illustrative_fixture)입니다. 실제 계산이 아니므로 승인할 수 없습니다.')
  if (result.method === 'B0') reasons.push('B0는 원안 진단이며 승인 대상(B1~B3)이 아닙니다.')
  if (run.status !== 'completed') reasons.push(`실행 상태가 completed가 아닙니다(${run.status}).`)
  if (!result.approval_eligible) reasons.push('서버가 승인 가능(approval_eligible)으로 표시하지 않았습니다.')
  if (result.validation_status !== 'passed')
    reasons.push(`독립 일정 검사를 통과하지 않았습니다(validation_status=${result.validation_status}).`)
  if (activeScenarioId && run.scenario_id !== activeScenarioId)
    reasons.push(`이 결과의 입력(${run.scenario_id})이 현재 입력(${activeScenarioId})과 다릅니다.`)
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
  if (status === 409) return '이 결과의 입력이나 계획이 현재 서버 상태와 다릅니다. 최신 입력으로 다시 계산하세요.'
  if (status === 503) return '필수 근거의 확인 상태나 유효기간이 충족되지 않았습니다. 반입시간 변경 확인과 입력 유효기간을 다시 확인하세요.'
  return null
}
