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
