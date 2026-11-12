// 기사가 동의해 보낸 휴대폰 위치. '기사 전달' 칸이 5초마다 받아 오고, 같은 화면의 차량 지도가 이 값을 쓴다.
import { useSyncExternalStore } from 'react'
import type { DriverLocation, RecipientSummary } from './dispatch'

let current = new Map<string, DriverLocation>()
const listeners = new Set<() => void>()

export function publishDriverLocations(rows: Pick<RecipientSummary, 'revoked' | 'vehicle_ids' | 'location'>[]) {
  const next = new Map<string, DriverLocation>()
  for (const r of rows) if (!r.revoked && r.location) for (const v of r.vehicle_ids) next.set(v, r.location)
  const same = next.size === current.size && [...next].every(([k, v]) => current.get(k)?.received_at === v.received_at)
  if (same) return
  current = next
  listeners.forEach((f) => f())
}

export function useDriverLocations(): Map<string, DriverLocation> {
  return useSyncExternalStore((f) => { listeners.add(f); return () => { listeners.delete(f) } }, () => current, () => current)
}
