// 화면 표시 이름: 현장에서 쓰는 컨테이너 번호·차량 번호판을 먼저 보여 준다.
// 내부 식별자(job_id·vehicle_id)는 계산·연결용 키로 남고, 표시 이름이 없으면 그대로 쓴다.
import type { Snapshot } from '../api/types'

type JobInfo = { container: string | null; booking: string | null; owner: string | null }
const jobs = new Map<string, JobInfo>()
const plates = new Map<string, string>()

/** 입력을 불러올 때 한 번 호출한다. 같은 입력이면 다시 불러도 결과가 같다. */
export function registerLabels(s: Pick<Snapshot, 'jobs' | 'vehicles'> | null | undefined) {
  if (!s) return
  for (const j of s.jobs) jobs.set(j.job_id, { container: j.container_no ?? null, booking: j.booking_no ?? null, owner: j.cargo_owner ?? null })
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
