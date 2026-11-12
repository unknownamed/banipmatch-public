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
    <h3>화물차 도로 이동 시간</h3>
    <p className="small muted">{road ? STATUS[road.status] : '아직 수신 결과가 없습니다.'}{road?.received_at && <> · {kstDateTime(road.received_at)} 조회</>} · 지역 대표 지점 기준(실시간 교통 미반영)</p>
    {road?.status === 'rate_limited' && <p className="warn">호출을 중단했습니다. {road.retry_after_seconds != null && <>서버 안내 대기 {road.retry_after_seconds}초. </>}모의 값으로 바꾸지 않습니다.</p>}
    {!!road?.cells.length && <div className="table-scroll"><table className="grid small"><caption className="small muted">행에서 출발해 열로 도착 · 분 / km</caption><thead><tr><th>출발 / 도착</th>{road.points.map((p,i)=><th key={i}>{p.label}</th>)}</tr></thead><tbody>{road.points.map((p,i)=><tr key={i}><th>{p.label}</th>{road.points.map((_,j)=>{
      const c=road.cells.find(x=>x.origin===i && x.destination===j)
      return <td key={j}>{c?.duration_seconds == null || c?.distance_meters == null ? <span className="warn">자료 없음</span> : i===j ? <span className="muted">—</span> : <><b>{Math.round(c.duration_seconds/60)}분</b> <span className="muted">{(c.distance_meters/1000).toFixed(1)}km</span></>}</td>
    })}</tr>)}</tbody></table></div>}
    {!!road?.points.length && <details className="tech-info"><summary>조회 좌표</summary>{road.points.map((p,i)=><p className="small" key={i}>{p.label}: 경도 {p.longitude}, 위도 {p.latitude}<br/>가까운 도로까지 보정: 출발 {p.source_snap_m == null ? '미확인' : `${p.source_snap_m.toFixed(1)}m`} / 도착 {p.destination_snap_m == null ? '미확인' : `${p.destination_snap_m.toFixed(1)}m`}</p>)}</details>}
    <p className="small muted">© <a href="https://openrouteservice.org/" target="_blank" rel="noreferrer">openrouteservice by HeiGIT</a> | Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer">CC-BY-SA 4.0</a></p>
  </section>
}
