// 확정된 변경을 기사에게 문자·카톡으로 붙여넣을 안내문으로 만든다.
// 자동 발송하지 않는다. 담당자가 복사해 자신의 연락 수단으로 보낸다(웹 푸시를 받지 못하는 기사용).
import { jobInfo, jobName, vehicleName, vehicleShort } from './labels'
import { kstTime } from './time'

type Slot = { vehicle_id?: string; pickup_departure_at?: string; gate_arrival_at?: string } | null
export type ChangeLine = { job_id: string; kind: string; before: Slot; after: Slot }

export function driverMessage(vehicleId: string, changes: ChangeLine[], version: number) {
  const mine = changes.filter(c => c.after?.vehicle_id === vehicleId)
  const removed = changes.filter(c => c.before?.vehicle_id === vehicleId && c.after?.vehicle_id !== vehicleId)
  const lines = [`[반입맞춤 배차 변경 v${version}] ${vehicleName(vehicleId)}`]
  if (mine.length) {
    lines.push('', '■ 수행할 작업')
    mine.forEach((c, i) => {
      const info = jobInfo(c.job_id)
      lines.push(`${i + 1}) ${jobName(c.job_id)}${info ? ` · ${info.size} · ${info.owner ?? ''}` : ''}`.trimEnd())
      lines.push(`   ${info?.origin ?? '상차지'} ${kstTime(c.after!.pickup_departure_at ?? null)} 출발 → ${info?.terminal ?? ''} 게이트 ${kstTime(c.after!.gate_arrival_at ?? null)} 도착${info ? ` (항차 ${info.voyage})` : ''}`)
      if (c.before?.vehicle_id && c.before.vehicle_id !== vehicleId) lines.push(`   ※ ${vehicleShort(c.before.vehicle_id)} 차량에서 넘어온 작업`)
      else if (c.before) lines.push(`   ※ 출발 시각 변경: ${kstTime(c.before.pickup_departure_at ?? null)} → ${kstTime(c.after!.pickup_departure_at ?? null)}`)
    })
  }
  if (removed.length) {
    lines.push('', '■ 취소된 작업(다른 차량 배정 또는 보류)')
    removed.forEach(c => lines.push(`- ${jobName(c.job_id)}${c.after?.vehicle_id ? ` → ${vehicleShort(c.after.vehicle_id)} 차량` : ' → 보류(담당자 확인 중)'}`))
  }
  lines.push('', '확인하셨으면 "확인", 수행이 어려우면 "곤란"으로 회신 부탁드립니다.')
  return lines.join('\n')
}
