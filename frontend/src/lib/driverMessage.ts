// 확정된 변경을 기사에게 문자·카톡으로 붙여넣을 안내문으로 만든다.
// 자동 발송하지 않는다. 담당자가 복사해 자신의 연락 수단으로 보낸다(웹 푸시를 받지 못하는 기사용).
import { jobInfo, jobName, vehicleName, vehicleShort } from './labels'
import { kstTime } from './time'

type Slot = { vehicle_id?: string; pickup_departure_at?: string; gate_arrival_at?: string } | null
export type ChangeLine = { job_id: string; kind: string; before: Slot; after: Slot }

export function driverMessage(vehicleId: string, changes: ChangeLine[], _version?: number) {
  const mine = changes.filter(c => c.after?.vehicle_id === vehicleId)
  const removed = changes.filter(c => c.before?.vehicle_id === vehicleId && c.after?.vehicle_id !== vehicleId)
  const lines = [`[반입맞춤 배차 변경] ${vehicleName(vehicleId)}`]
  if (mine.length) {
    lines.push('', '■ 수행할 작업')
    mine.forEach((c, i) => {
      const info = jobInfo(c.job_id)
      lines.push(`${i + 1}) ${[jobName(c.job_id), info?.size, info?.owner].filter(Boolean).join(', ')}`)
      lines.push(`   ${info?.origin ?? '상차지'} ${kstTime(c.after!.pickup_departure_at ?? null)} 출발 → ${info?.terminal ?? ''} 게이트 ${kstTime(c.after!.gate_arrival_at ?? null)} 도착${info ? ` (항차 ${info.voyage})` : ''}`)
      if (c.before?.vehicle_id && c.before.vehicle_id !== vehicleId) lines.push(`   ※ ${vehicleShort(c.before.vehicle_id)} 차량에서 넘어온 작업`)
      else if (c.before) lines.push(`   ※ 출발 시각 변경: ${kstTime(c.before.pickup_departure_at ?? null)} → ${kstTime(c.after!.pickup_departure_at ?? null)}`)
    })
  }
  if (removed.length) {
    lines.push('', '■ 빠진 작업(다른 차량 배정 또는 미배정)')
    removed.forEach(c => lines.push(`- ${jobName(c.job_id)}${c.after?.vehicle_id ? ` → ${vehicleShort(c.after.vehicle_id)} 차량` : ' → 미배정(담당자 확인 중)'}`))
  }
  lines.push('', '확인하셨으면 "확인", 수행이 어려우면 "곤란"으로 회신 부탁드립니다.')
  return lines.join('\n')
}

/** 한 번 복사로 보내는 메시지: 바뀐 배차 안내문 + 알림 연결 방법 + 연결 링크(맨 끝). */
export function inviteMessage(notice: string, link: string, expiresAt: string) {
  const body = notice.split('\n').filter((l) => !l.startsWith('확인하셨으면')).join('\n').trimEnd()
  return [
    body,
    '',
    '■ 휴대폰 알림 연결(처음 한 번)',
    `아래 링크를 누르고 "연결하고 알림 받기"를 누르면 앞으로 바뀌는 배차를 알림으로 받고 바로 응답할 수 있습니다. (${kstTime(expiresAt)}까지, 한 번만 사용)`,
    '아이폰은 Safari에서 열어 화면 안내를 따라 주세요. 연결이 어려우면 이 메시지에 "확인" 또는 "곤란"으로 회신해 주세요.',
    link,
  ].join('\n')
}
