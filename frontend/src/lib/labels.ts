// 화면 표시 이름: 현장에서 쓰는 컨테이너 번호·차량 번호판을 먼저 보여 준다.
// 내부 식별자(job_id·vehicle_id)는 계산·연결용 키로 남고, 표시 이름이 없으면 그대로 쓴다.
import type { Snapshot } from '../api/types'

type JobInfo = { container: string | null; booking: string | null; owner: string | null; origin: string; terminal: string; voyage: string; size: string }
const jobs = new Map<string, JobInfo>()
const plates = new Map<string, string>()

/** 입력을 불러올 때 한 번 호출한다. 같은 입력이면 다시 불러도 결과가 같다. */
export function registerLabels(s: Pick<Snapshot, 'jobs' | 'vehicles' | 'locations'> | null | undefined) {
  if (!s) return
  const place = (id: string) => s.locations?.find(l => l.location_id === id)?.name.replace('(모의)', '').trim() ?? id
  for (const j of s.jobs)
    jobs.set(j.job_id, {
      container: j.container_no ?? null, booking: j.booking_no ?? null, owner: j.cargo_owner ?? null,
      origin: place(j.origin_id), terminal: j.terminal_id, voyage: j.voyage_id,
      size: j.equipment_type === 'DRY40' ? '40ft' : j.equipment_type === 'DRY20' ? '20ft' : j.equipment_type,
    })
  for (const v of s.vehicles ?? []) if (v.plate_no) plates.set(v.vehicle_id, v.plate_no)
}

/** BNJU1002036 → BNJU 100203 6 (소유자·일련번호·확인 숫자) */
export function formatContainer(no: string) {
  return /^[A-Z]{4}\d{7}$/.test(no) ? `${no.slice(0, 4)} ${no.slice(4, 10)} ${no.slice(10)}` : no
}

export function jobName(id: string) {
  const c = jobs.get(id)?.container
  return c ? formatContainer(c) : id
}
/** 좁은 자리(타임라인 막대)용: 일련번호 6자리 */
export function jobShort(id: string) {
  const c = jobs.get(id)?.container
  return c ? c.slice(4, 10) : id
}
export function jobInfo(id: string): JobInfo | null {
  return jobs.get(id) ?? null
}
export function hasJobName(id: string) {
  return !!jobs.get(id)?.container
}

export function vehicleName(id: string) {
  return plates.get(id) ?? id
}
/** 현장에서 부르는 방식: 번호판 뒤 4자리 */
export function vehicleShort(id: string | null | undefined) {
  if (!id) return ''
  const p = plates.get(id)
  return p ? p.replace(/\s/g, '').slice(-4) : id
}
export function hasVehicleName(id: string) {
  return plates.has(id)
}

/** 계산 방법을 담당자에게 보이는 이름으로. 코드(B0~B3)는 기술 정보에만 남긴다. */
const PLAN_NAME: Record<string, string> = { B0: '원래 배차', B1: '마감순 재배치안', B2: '전체 재배치안', B3: '최소 변경안' }
export function planName(method: string) {
  return PLAN_NAME[method] ?? method
}

const FIELD_NAME: Record<string, string> = {
  ready_at: '상차 준비 시각', gross_weight_kg: '화물 중량', service_minutes: '터미널 체류 시간', verification: '확정 여부',
  confirmed_by: '확인자', confirmed_at: '확인 시각', available_at: '가용 시작', shift_end_at: '근무 종료', closes_at: '반입 마감', opens_at: '반입 시작',
}
/** 서버 입력 검사 결과의 경로(/jobs/2/ready_at)와 사유(CODE: 설명)를 담당자가 읽는 문장으로. */
export function readableDetail(path: string, reason: string, s: Pick<Snapshot, 'jobs' | 'vehicles' | 'windows'> | null): { what: string; why: string } {
  const why = reason.replace(/^[A-Z_]+:\s*/, '')
  const parts = path.replace(/^\//, '').split(/[/.[\]]+/).filter(Boolean)
  const field = (k?: string) => (k ? FIELD_NAME[k] ?? '' : '')
  if (parts[0] === 'jobs' && s) {
    const j = s.jobs[Number(parts[1])]
    return { what: `${j ? jobName(j.job_id) : '작업'} ${field(parts[2])}`.trim(), why }
  }
  if (parts[0] === 'vehicles' && s) {
    const v = s.vehicles?.[Number(parts[1])]
    return { what: `${v ? vehicleName(v.vehicle_id) : '차량'} ${field(parts[2])}`.trim(), why }
  }
  if (parts[0] === 'windows' && s) {
    const w = s.windows[Number(parts[1])]
    return { what: `${w ? w.voyage_id : '항차'} ${field(parts[2]) || '반입 시간'}`.trim(), why }
  }
  if (parts[0] === 'change') return parts[1] === 'verification' ? { what: '터미널 공지', why: '아직 확정된 공지가 아닙니다.' } : { what: `반입 마감 변경 공지 ${field(parts[1])}`.trim(), why }
  return { what: '입력', why }
}
