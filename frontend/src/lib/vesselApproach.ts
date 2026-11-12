// 부산항 신항 입항 선박 모의 재생 — 위치·남은 항로·도착 추정 계산.
// 선박·항차·속력·반입 마감은 모두 모의다. 항로 경유점은 OSM 해상 표지(부표) 위치를 참고해 그린 설명용 선이며
// 공식 항로 고시·도선 경로가 아니다. 도착 추정은 '남은 항로 ÷ 현재 속력'뿐이고 조류·감속·도선·선석 대기를 반영하지 않는다.
// 반입 마감은 터미널 공지(모의) 값이며 이 추정으로 바뀌지 않는다(설계 원칙: ETA 변화 ≠ 반입 마감 변경).

export type LatLon = { lat: number; lon: number }

export const SOURCES = {
  seamark: 'OpenStreetMap 해상 표지(seamark) · Overpass 조회 2026-11-12 · © OpenStreetMap contributors, ODbL',
  places: '카카오 장소 검색(터미널 대표 좌표) · 조회 2026-11-12',
} as const

// 주항로 표지 — OSM seamark 원좌표(이름은 OSM 표기). 색은 한국(IALA B): 좌현 녹색, 우현 적색.
export type Buoy = LatLon & { name: string; side: 'port' | 'starboard' | 'safe' | 'center' }
export const BUOYS: Buoy[] = [
  { name: 'Busan New Port No 1', side: 'port', lat: 34.97308, lon: 128.79603 },
  { name: 'Busan New Port No 2', side: 'starboard', lat: 34.98314, lon: 128.81961 },
  { name: 'Busan New Port No 3', side: 'port', lat: 34.98136, lon: 128.79353 },
  { name: 'Busansin Hang No 5', side: 'port', lat: 34.99028, lon: 128.79067 },
  { name: 'Busansin Hang No 9', side: 'port', lat: 35.00636, lon: 128.78608 },
  { name: 'NEW PORT CENTER C', side: 'center', lat: 35.024, lon: 128.78856 },
  { name: 'Busan New Port No.15', side: 'port', lat: 35.02961, lon: 128.75536 },
  { name: 'Busan New Port No D', side: 'safe', lat: 35.03589, lon: 128.75792 },
  { name: 'Busan New Port No E', side: 'safe', lat: 35.04161, lon: 128.73886 },
  { name: 'Busan New Port No 18', side: 'starboard', lat: 35.04539, lon: 128.75272 },
  { name: 'Busan New Port No 107', side: 'port', lat: 35.05406, lon: 128.77742 },
  { name: 'Busan New Port No 109', side: 'port', lat: 35.0585, lon: 128.77969 },
  { name: 'V NEWPORT SAFE 2', side: 'safe', lat: 35.06042, lon: 128.78442 },
]

export type TerminalId = 'HJNC' | 'DGT' | 'PNIT' | 'HPNT' | 'BNCT'
export type Terminal = LatLon & { id: TerminalId; name: string; target: boolean }
// 대표 좌표는 카카오 장소 검색 결과(사무동·시설 대표점)이며 선석 위치가 아니다.
export const TERMINALS: Terminal[] = [
  { id: 'HJNC', name: '한진부산컨테이너터미널', target: true, lat: 35.08137, lon: 128.78431 },
  { id: 'DGT', name: '동원글로벌터미널', target: false, lat: 35.07793, lon: 128.76994 },
  { id: 'PNIT', name: '부산신항국제터미널', target: false, lat: 35.08177, lon: 128.83368 },
  { id: 'HPNT', name: 'HMM PSA 신항만', target: false, lat: 35.07061, lon: 128.83299 },
  { id: 'BNCT', name: '비엔씨티', target: false, lat: 35.06445, lon: 128.81903 },
]

// 설명용 항로(경유점). 표지 사이 중앙을 지나도록 그렸고 마지막 점은 터미널 앞 수면의 근사 위치다.
const OFFSHORE: LatLon[] = [
  { lat: 34.62, lon: 128.98 }, // 대한해협 쪽 외해(설명용)
  { lat: 34.8, lon: 128.86 },
  { lat: 34.9, lon: 128.82 },
]
const SOUTH_APPROACH: LatLon[] = [
  ...OFFSHORE,
  { lat: 34.952, lon: 128.806 }, // 외해 대기·진입 구역(설명용)
  { lat: 34.973, lon: 128.801 }, // No.1 부근
  { lat: 34.99, lon: 128.796 }, // No.5 부근
  { lat: 35.006, lon: 128.791 }, // No.9 부근
  { lat: 35.024, lon: 128.7886 }, // CENTER C
  { lat: 35.042, lon: 128.783 },
  { lat: 35.056, lon: 128.7825 }, // No.107·109 동측
  { lat: 35.0604, lon: 128.7844 }, // SAFE 2
]
const WEST_APPROACH: LatLon[] = [
  { lat: 35.038, lon: 128.69 }, // 서측 진입(설명용)
  { lat: 35.0416, lon: 128.7389 }, // No E
  { lat: 35.04, lon: 128.7565 }, // No D·No 18 사이
  { lat: 35.05, lon: 128.772 },
  { lat: 35.0604, lon: 128.7844 }, // SAFE 2
]
const BERTH_APPROACH: Record<TerminalId, LatLon[]> = {
  HJNC: [{ lat: 35.0675, lon: 128.7865 }, { lat: 35.0735, lon: 128.7868 }],
  DGT: [{ lat: 35.066, lon: 128.778 }, { lat: 35.0715, lon: 128.7715 }],
  BNCT: [{ lat: 35.0605, lon: 128.796 }, { lat: 35.0592, lon: 128.812 }],
  HPNT: [{ lat: 35.0605, lon: 128.796 }, { lat: 35.0625, lon: 128.818 }, { lat: 35.0665, lon: 128.829 }],
  PNIT: [{ lat: 35.0605, lon: 128.796 }, { lat: 35.0625, lon: 128.818 }, { lat: 35.0715, lon: 128.83 }, { lat: 35.0765, lon: 128.8305 }],
}
export const ANCHORAGE: LatLon = { lat: 34.94, lon: 128.885 } // 외해 묘박 대기(설명용)

export type VesselState = 'underway' | 'anchored' | 'berthed'
export type Vessel = {
  id: string
  name: string | null // null = 선박 이름 미수신
  voyage: string
  terminal: TerminalId
  route: LatLon[]
  startNm: number // 재생 시작 시점에 항로 위에서 이미 지나온 거리
  speedKn: number
  state: VesselState
  cutoffMin: number // 재생 시작 기준 반입 마감(분, 모의 터미널 공지)
  staleAfterMin?: number // 이 시각 이후 위치 갱신 없음
}

const route = (approach: LatLon[], t: TerminalId) => [...approach, ...BERTH_APPROACH[t]]

export const VESSELS: Vessel[] = [
  { id: 'SIM-01', name: 'SIM 한바다', voyage: 'V1', terminal: 'HJNC', route: route(SOUTH_APPROACH, 'HJNC'), startNm: 22.5, speedKn: 11, state: 'underway', cutoffMin: 90 },
  { id: 'SIM-02', name: 'SIM 동백', voyage: 'V2', terminal: 'HJNC', route: route(SOUTH_APPROACH, 'HJNC'), startNm: 9, speedKn: 13, state: 'underway', cutoffMin: 150 },
  { id: 'SIM-07', name: 'SIM 누리', voyage: 'V4', terminal: 'HJNC', route: route(SOUTH_APPROACH, 'HJNC'), startNm: 0, speedKn: 14, state: 'underway', cutoffMin: 210 },
  { id: 'SIM-03', name: 'SIM 가덕', voyage: 'V7', terminal: 'DGT', route: route(WEST_APPROACH, 'DGT'), startNm: 0.6, speedKn: 10, state: 'underway', cutoffMin: 60 },
  { id: 'SIM-04', name: 'SIM 오륙', voyage: 'V9', terminal: 'PNIT', route: [ANCHORAGE], startNm: 0, speedKn: 0, state: 'anchored', cutoffMin: 300 },
  { id: 'SIM-05', name: null, voyage: 'V5', terminal: 'BNCT', route: route(SOUTH_APPROACH, 'BNCT'), startNm: 21, speedKn: 12, state: 'underway', cutoffMin: 30, staleAfterMin: 35 },
  { id: 'SIM-06', name: 'SIM 영도', voyage: 'V3', terminal: 'HJNC', route: route(SOUTH_APPROACH, 'HJNC'), startNm: 99, speedKn: 0, state: 'berthed', cutoffMin: -120 },
]

const NM = 1852
export function distanceNm(a: LatLon, b: LatLon) {
  const R = 6371008.8, rad = Math.PI / 180
  const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2
  return (2 * R * Math.asin(Math.sqrt(h))) / NM
}
export function bearing(a: LatLon, b: LatLon) {
  const rad = Math.PI / 180
  const y = Math.sin((b.lon - a.lon) * rad) * Math.cos(b.lat * rad)
  const x = Math.cos(a.lat * rad) * Math.sin(b.lat * rad) - Math.sin(a.lat * rad) * Math.cos(b.lat * rad) * Math.cos((b.lon - a.lon) * rad)
  return ((Math.atan2(y, x) / rad) + 360) % 360
}
export function routeLengthNm(r: LatLon[]) {
  let s = 0
  for (let i = 1; i < r.length; i++) s += distanceNm(r[i - 1], r[i])
  return s
}

// 항로 위 travelled 해리 지점의 좌표·진행 방향과 그 지점에서 나눈 지나온/남은 경로.
export function pointAlong(r: LatLon[], travelled: number) {
  if (r.length === 1) return { pos: r[0], heading: 0, passed: [r[0]], ahead: [r[0]] }
  let left = Math.max(0, travelled)
  for (let i = 1; i < r.length; i++) {
    const seg = distanceNm(r[i - 1], r[i])
    if (left <= seg) {
      const f = seg === 0 ? 0 : left / seg
      const pos = { lat: r[i - 1].lat + (r[i].lat - r[i - 1].lat) * f, lon: r[i - 1].lon + (r[i].lon - r[i - 1].lon) * f }
      return { pos, heading: bearing(r[i - 1], r[i]), passed: [...r.slice(0, i), pos], ahead: [pos, ...r.slice(i)] }
    }
    left -= seg
  }
  const n = r.length
  return { pos: r[n - 1], heading: bearing(r[n - 2], r[n - 1]), passed: r, ahead: [r[n - 1]] }
}

export type VesselView = {
  vessel: Vessel
  pos: LatLon
  heading: number
  passed: LatLon[]
  ahead: LatLon[]
  status: 'underway' | 'anchored' | 'berthed' | 'stale'
  remainingNm: number | null
  etaMin: number | null // 재생 시작 기준 도착 추정(분). 산정할 수 없으면 null
  etaNote: string
  positionAgeMin: number
}

// t: 재생 시작 후 경과 분. 위치 갱신이 끊긴 선박은 마지막 위치에 멈추고 이후 이동을 추정하지 않는다.
export function vesselAt(v: Vessel, t: number): VesselView {
  const total = routeLengthNm(v.route)
  const stale = v.staleAfterMin !== undefined && t > v.staleAfterMin
  const seenT = stale ? v.staleAfterMin! : t
  const travelled = Math.min(total, v.startNm + (v.speedKn * seenT) / 60)
  const at = pointAlong(v.route, v.state === 'berthed' ? total : travelled)
  const base = { vessel: v, pos: at.pos, heading: at.heading, passed: at.passed, ahead: at.ahead, positionAgeMin: stale ? t - v.staleAfterMin! : 0 }
  if (v.state === 'berthed') return { ...base, status: 'berthed', remainingNm: 0, etaMin: null, etaNote: '접안 중' }
  if (v.state === 'anchored' || v.speedKn <= 0)
    return { ...base, status: 'anchored', remainingNm: null, etaMin: null, etaNote: '묘박 대기 · 속력 0이라 도착 시각을 산정하지 않음' }
  const remaining = total - travelled
  if (stale) return { ...base, status: 'stale', remainingNm: remaining, etaMin: null, etaNote: `위치 갱신 ${Math.round(t - v.staleAfterMin!)}분 없음 · 이후 이동을 추정하지 않음` }
  if (remaining <= 0.01) return { ...base, status: 'berthed', remainingNm: 0, etaMin: null, etaNote: '터미널 앞 도착(모의)' }
  return { ...base, status: 'underway', remainingNm: remaining, etaMin: t + (remaining / v.speedKn) * 60, etaNote: '남은 항로 ÷ 현재 속력' }
}

export function fleetAt(t: number) {
  const order = { underway: 0, stale: 1, anchored: 2, berthed: 3 } as const
  return VESSELS.map(v => vesselAt(v, t)).sort((a, b) =>
    Number(b.vessel.terminal === 'HJNC') - Number(a.vessel.terminal === 'HJNC') ||
    order[a.status] - order[b.status] || (a.etaMin ?? 1e9) - (b.etaMin ?? 1e9))
}

export function formatDuration(min: number) {
  const m = Math.max(0, Math.round(min))
  return m >= 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${m}분`
}
