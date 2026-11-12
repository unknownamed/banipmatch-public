// 현장 식별자 표기: 번호판처럼 보이는 차량 번호, 확인 숫자를 네모 칸에 넣은 컨테이너 번호(ISO 6346 표기 관례).
import { formatContainer, jobInfo, vehicleName } from '../lib/labels'

/** 부산 90바 1201 → 번호판 모양. 등록 번호가 없으면 내부 ID를 그대로 쓴다. */
export function Plate({ id, plate }: { id?: string; plate?: string | null }) {
  const text = plate ?? (id ? vehicleName(id) : '')
  return <span className="plate">{text}</span>
}

/** BNJU1002036 → BNJU 100203 [6]. 작업 ID만 있으면 등록된 컨테이너 번호를 찾는다. */
export function BoxNo({ jobId, no }: { jobId?: string; no?: string | null }) {
  const raw = no ?? (jobId ? jobInfo(jobId)?.container ?? null : null)
  if (!raw || !/^[A-Z]{4}\d{7}$/.test(raw)) return <span className="boxno">{raw ? formatContainer(raw) : jobId}</span>
  return (
    <span className="boxno">
      {raw.slice(0, 4)} {raw.slice(4, 10)} <span className="boxno-cd">{raw.slice(10)}</span>
    </span>
  )
}
