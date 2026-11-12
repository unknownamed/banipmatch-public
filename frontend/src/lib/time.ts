// 전송·저장은 UTC Z, 화면은 한국 시각(Asia/Seoul)으로만 바꿔 보여준다.

const timeFmt = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

const dateTimeFmt = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** null(미확인)은 '미확인'으로 표시하고 다른 값으로 채우지 않는다. */
export function kstTime(utc: string | null | undefined): string {
  if (!utc) return '미확인'
  const d = new Date(utc)
  if (Number.isNaN(d.getTime())) return `형식 오류(${utc})`
  return timeFmt.format(d)
}

export function kstDateTime(utc: string | null | undefined): string {
  if (!utc) return '미확인'
  const d = new Date(utc)
  if (Number.isNaN(d.getTime())) return `형식 오류(${utc})`
  return `${dateTimeFmt.format(d)} KST`
}

/** 같은 날이 아닐 때만 날짜를 붙인다(예: 전날 23:50 UTC → 08:50 KST). */
export function kstTimeWithDay(utc: string | null | undefined, refUtc: string): string {
  if (!utc) return '미확인'
  return dayKey(utc) === dayKey(refUtc) ? kstTime(utc) : dateTimeFmt.format(new Date(utc))
}

const dayFmt = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' })
const dayKey = (utc: string) => dayFmt.format(new Date(utc))

/** 서버 설명문 안의 UTC 시각(2026-11-12T09:34:00Z)을 화면 기준 KST 시각(18:34)으로 바꾼다. 다른 글자는 그대로 둔다. */
export function humanizeTimes(text: string): string {
  return text.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z/g, (iso) => kstTime(iso))
}
