import { kstDateTime } from '../lib/time'

export interface RoadData {
  status: 'key_missing' | 'received' | 'partial' | 'auth_error' | 'rate_limited' | 'http_error' | 'invalid_response'
  received_at: string | null; http_status: number | null; retry_after_seconds: number | null
  points: { label: string; longitude: number; latitude: number; source_snap_m: number | null; destination_snap_m: number | null }[]
  cells: { origin: number; destination: number; duration_seconds: number | null; distance_meters: number | null }[]
}
const STATUS = {key_missing:'아직 연결하지 않음', received:'실제 응답 수신', partial:'일부 경로 값 없음',
  auth_error:'인증 확인 필요', rate_limited:'호출 한도 도달', http_error:'제공기관 연결 실패', invalid_response:'응답 형식 확인 필요'}

export function RoadReference({road}: {road: RoadData | null | undefined}) {
  return <section className="card" aria-label="ORS 실제 도로 시간과 거리">
    <h3>도로 이동시간·거리 · ORS 실제 조회</h3>
    <p className="small muted">부산 공개 지점 3곳의 근사 좌표로 조회한 참고값입니다. 실제 상차지·터미널 게이트를 확인한 값이 아니며, 현재 교통을 반영한 도착시각이나 화물차 통행 보장이 아닙니다. 기존 모의 배차 계산에는 자동으로 넣지 않습니다.</p>
    <p>{road ? STATUS[road.status] : '아직 수신 결과가 없습니다.'}{road?.received_at && <> · 수신 {kstDateTime(road.received_at)}</>}</p>
    {road?.status === 'rate_limited' && <p className="warn">호출을 중단했습니다. {road.retry_after_seconds != null && <>서버 안내 대기 {road.retry_after_seconds}초. </>}모의 값으로 바꾸지 않습니다.</p>}
    {!!road?.cells.length && <div className="table-scroll"><table className="grid small"><caption>행: 출발 · 열: 도착 / 이동시간(분) · 거리(km)</caption><thead><tr><th>출발 / 도착</th>{road.points.map((p,i)=><th key={i}>{p.label}</th>)}</tr></thead><tbody>{road.points.map((p,i)=><tr key={i}><th>{p.label}</th>{road.points.map((_,j)=>{
      const c=road.cells.find(x=>x.origin===i && x.destination===j)
      return <td key={j}>{c?.duration_seconds == null || c?.distance_meters == null ? <span className="warn">자료 없음</span> : <>{(c.duration_seconds/60).toFixed(1)}분 · {(c.distance_meters/1000).toFixed(2)}km</>}</td>
    })}</tr>)}</tbody></table></div>}
    {!!road?.points.length && <details><summary>조회 좌표와 도로 보정 거리</summary>{road.points.map((p,i)=><p className="small" key={i}>{p.label}: 경도 {p.longitude}, 위도 {p.latitude}<br/>가까운 도로까지 보정: 출발 {p.source_snap_m == null ? '미확인' : `${p.source_snap_m.toFixed(1)}m`} / 도착 {p.destination_snap_m == null ? '미확인' : `${p.destination_snap_m.toFixed(1)}m`}</p>)}</details>}
    <p className="small">© <a href="https://openrouteservice.org/" target="_blank" rel="noreferrer">openrouteservice by HeiGIT</a> | Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer">CC-BY-SA 4.0</a> · 초→분, 미터→km로 환산 표시. 왕복 방향은 각각 조회하며 없는 값을 0으로 채우지 않습니다.</p>
  </section>
}
