// 배차 일정으로 '지금 이 차량이 어디서 무엇을 하는지' 추정한다. 실제 GPS가 아니다.
// 이동 구간은 두 지점 사이를 시간 비율로 직선 보간한다(도로 경로 아님).
// 실제 차량 위치가 연결되면 source='gps'로 대체할 수 있도록 출처를 함께 돌려준다.
import type { Assignment, Snapshot } from '../api/types'
import roadRoutes from '../fixtures/road-routes.osm.json'

// 표시용 실제 도로 경로(OpenStreetMap·OSRM). 같은 위치 쌍이 있으면 직선 대신 도로를 따라 움직인다.
const ROADS = (roadRoutes as unknown as { routes: Record<string, { path: [number, number][] }> }).routes
export const ROAD_ATTRIBUTION = (roadRoutes as { attribution: string }).attribution
export function roadPath(fromId: string, toId: string): Pt[] | null {
  const r = ROADS[`${fromId}>${toId}`]
  return r ? r.path.map(([lat, lon]) => ({ lat, lon })) : null
}
function along(path: Pt[], f: number): Pt {
  if (path.length < 2) return path[0]
  const seg: number[] = []
  let total = 0
  for (let i = 1; i < path.length; i++) { const d = Math.hypot(path[i].lat - path[i - 1].lat, path[i].lon - path[i - 1].lon); seg.push(d); total += d }
  let goal = Math.min(1, Math.max(0, f)) * total
  for (let i = 0; i < seg.length; i++) {
    if (goal <= seg[i] || i === seg.length - 1) { const k = seg[i] ? goal / seg[i] : 0; return { lat: path[i].lat + (path[i + 1].lat - path[i].lat) * k, lon: path[i].lon + (path[i + 1].lon - path[i].lon) * k } }
    goal -= seg[i]
  }
  return path[path.length - 1]
}

export type Pt = { lat: number; lon: number }
export type Phase = 'idle' | 'to_origin' | 'loading_wait' | 'to_gate' | 'at_gate' | 'returning' | 'done'
export const PHASE_LABEL: Record<Phase, string> = {
  idle: '차고지 대기',
  to_origin: '상차지로 이동',
  loading_wait: '상차 대기',
  to_gate: '게이트로 운송 중',
  at_gate: '게이트 반입 중',
  returning: '복귀 중',
  done: '오늘 작업 종료',
}

export type GateStatus = 'ok' | 'tight' | 'late'
export type VehicleNow = {
  vehicleId: string
  pos: Pt | null
  phase: Phase
  jobId: string | null // 지금 수행 중이거나 다음에 할 작업
  from: Pt | null
  to: Pt | null
  gateEta: string | null // 다음(또는 현재) 작업의 게이트 도착 예정 UTC
  cutoff: string | null
  marginMin: number | null // 마감 - (도착 + 여유)
  gate: GateStatus | null
  source: 'plan_inferred'
  path?: Pt[] | null // 지금 달리는 구간의 도로 경로(있으면)
  /** 기사가 동의해 보낸 휴대폰 위치(있으면 pos가 이 값) */
  live?: { captured_at: string; accuracy_m: number }
}

const ms = (iso: string) => Date.parse(iso)
const lerp = (a: Pt, b: Pt, f: number): Pt => ({ lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f })
const frac = (now: number, s: number, e: number) => (e <= s ? 1 : Math.min(1, Math.max(0, (now - s) / (e - s))))

export function locationPoints(s: Snapshot): Map<string, Pt> {
  const m = new Map<string, Pt>()
  for (const l of s.locations ?? []) if (l.latitude != null && l.longitude != null) m.set(l.location_id, { lat: l.latitude, lon: l.longitude })
  return m
}

export function gateStatus(arrival: string, cutoff: string | null, buffer: number): { marginMin: number | null; gate: GateStatus | null } {
  if (!cutoff) return { marginMin: null, gate: null }
  const margin = Math.round((ms(cutoff) - ms(arrival)) / 60000 - buffer)
  return { marginMin: margin, gate: margin < 0 ? 'late' : margin < 20 ? 'tight' : 'ok' }
}

export function vehiclesAt(s: Snapshot, plan: Assignment[], now: number): VehicleNow[] {
  const pts = locationPoints(s)
  const jobs = new Map(s.jobs.map(j => [j.job_id, j]))
  const travel = new Map((s.travel_times ?? []).map(t => [`${t.from_location_id}>${t.to_location_id}`, t.minutes]))
  const cutoffOf = (jid: string) => {
    const j = jobs.get(jid)!
    return s.windows.find(w => w.voyage_id === j.voyage_id && w.terminal_id === j.terminal_id)?.closes_at ?? null
  }
  const buffer = s.policy.buffer_minutes
  return (s.vehicles ?? []).map(v => {
    const mine = plan.filter(a => a.vehicle_id === v.vehicle_id).sort((a, b) => a.sequence - b.sequence)
    const base = { vehicleId: v.vehicle_id, source: 'plan_inferred' as const }
    let location = v.start_location_id
    let freeAt = v.available_at ? ms(v.available_at) : -Infinity
    for (const a of mine) {
      const j = jobs.get(a.job_id)!
      const origin = pts.get(j.origin_id) ?? null, gate = pts.get(j.terminal_id) ?? null, back = pts.get(j.return_location_id) ?? null
      const here = pts.get(location) ?? null
      const dep = ms(a.pickup_departure_at), arr = ms(a.gate_arrival_at), ret = ms(a.return_at)
      const approach = (travel.get(`${location}>${j.origin_id}`) ?? 0) * 60000
      const done = arr + (buffer + (j.service_minutes ?? 0)) * 60000
      const cut = cutoffOf(a.job_id)
      const gs = gateStatus(a.gate_arrival_at, cut, buffer)
      const job = { jobId: a.job_id, gateEta: a.gate_arrival_at, cutoff: cut, ...gs }
      if (now < ret) {
        if (now >= dep && now < arr) { const road = roadPath(j.origin_id, j.terminal_id); const f = frac(now, dep, arr); return { ...base, ...job, phase: 'to_gate' as Phase, pos: road ? along(road, f) : origin && gate && lerp(origin, gate, f), from: origin, to: gate, path: road } }
        if (now >= arr && now < done) return { ...base, ...job, phase: 'at_gate' as Phase, pos: gate, from: null, to: null }
        if (now >= done) { const road = roadPath(j.terminal_id, j.return_location_id); const f = frac(now, done, ret); return { ...base, ...job, phase: 'returning' as Phase, pos: road ? along(road, f) : gate && back && lerp(gate, back, f), from: gate, to: back, path: road } }
        const leave = Math.max(freeAt, dep - approach)
        if (now < leave) return { ...base, ...job, phase: 'idle' as Phase, pos: here, from: null, to: null }
        if (now < leave + approach) { const road = roadPath(location, j.origin_id); const f = frac(now, leave, leave + approach); return { ...base, ...job, phase: 'to_origin' as Phase, pos: road ? along(road, f) : here && origin && lerp(here, origin, f), from: here, to: origin, path: road } }
        return { ...base, ...job, phase: 'loading_wait' as Phase, pos: origin, from: null, to: null }
      }
      location = j.return_location_id
      freeAt = ret
    }
    return { ...base, jobId: null, gateEta: null, cutoff: null, marginMin: null, gate: null, phase: (mine.length ? 'done' : 'idle') as Phase, pos: pts.get(location) ?? null, from: null, to: null }
  })
}
