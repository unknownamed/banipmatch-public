import { humanizeTimes } from './time'

/**
 * 엔진 설명문을 담당자가 읽는 문장으로 바꾼다. 엔진 원문(검증 기록에 쓰임)은 그대로 두고 화면에서만 바꾼다.
 * 상차 준비가 늦어 어떤 차량으로도 마감에 못 대는 경우: 계산식 나열 대신 몇 분 늦는지를 말한다.
 */
const READY_LATE = /^준비 (\S+) \+ 터미널까지 운송 (\d+)분 \+ 여유 (\d+)분 = (\S+) > 마감 (\S+?)\.\s/

export function issueText(code: string, explanation: string): string {
  // 탐색에서 남은 작업: 엔진 원문은 증명 범위를 설명하는 기술 문장이라 담당자 말로 바꾼다(찾지 못함 = 불가능 단정 아님).
  if (code === 'SEARCH_LIMIT') return '지금 차량과 근무 시간 안에서는 다른 화물을 마감 안에 넣으면서 이 작업까지 넣는 배차를 찾지 못했습니다.'
  const m = code === 'READY_TOO_LATE' ? READY_LATE.exec(explanation) : null
  if (!m) return humanizeTimes(explanation)
  const [, ready, travel, buffer, earliest, closes] = m
  const late = Math.round((Date.parse(earliest) - Date.parse(closes)) / 60000)
  const t = (iso: string) => humanizeTimes(iso)
  const gap = Number.isFinite(late) && late > 0 ? `${late}분 늦습니다` : '늦습니다'
  return `상차 준비가 ${t(ready)}에 끝나 바로 출발해도 운송 ${travel}분과 게이트 여유 ${buffer}분을 더하면 ${t(earliest)}로, 반입 마감 ${t(closes)}보다 ${gap}. 어느 차량에 배정해도 마감 안에 들어갈 수 없습니다.`
}
