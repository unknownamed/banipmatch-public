import { useEffect, useMemo, useState } from 'react'
import { createV2Client } from '../api/v2'
import type { ReferenceView } from '../lib/reference'
import { kstDateTime } from '../lib/time'
import { ReferenceStatus } from './ReferencePanel'

interface Weather {
  kind: 'sea' | 'warning'; status: string; received_at: string | null; http_status: number | null
  report: null | { row_count: number; future_observation_rows: number; station_mismatch_rows: number
    observations: { station_id: string; observed_at_utc: string; wh_m_original: string; ws_m_s_original: string; gust_m_s_original: string; missing_or_invalid_nonnegative_fields: string[] }[]
    selected_records: { region_name: string; kind: string; level: string; command: string; published_at_utc: string; effective_time_original_kst: string }[] }
}
interface LiveData { checked_at: string; hjnc: ReferenceView; weather: Weather[]; ais: null | {
  status: string; finished_at: string; max_seconds: number; subscription_confirmed: boolean; valid_position_events: number; unique_position_mmsi_count: number; connection_closed: boolean
} }

export function LiveReference() {
  const client = useMemo(() => createV2Client(), [])
  const [data, setData] = useState<LiveData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  async function load() {
    setLoading(true); setError(null)
    try { await client.session(); setData(await client.get<LiveData>('/v2/references/current')) }
    catch (e) { setError(e instanceof Error ? e.message : '자료를 읽지 못했습니다.'); setData(null) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [client])
  return <>
    <p className="small muted">서버에서 마지막으로 실제 수신한 자료입니다. 자동 실시간 갱신이나 확정된 반입시간 변경을 뜻하지 않습니다. 조회 버튼은 서버에 보관된 수신 결과를 다시 읽습니다.</p>
    <button type="button" className="secondary" disabled={loading} onClick={load}>{loading ? '불러오는 중…' : '수신 결과 새로 읽기'}</button>
    {error && <p className="warn" role="alert">실제 자료 조회 실패: {error} 모의 자료로 전환하지 않았습니다.</p>}
    {data && <>
      <ReferenceStatus view={data.hjnc} />
      <p className="small"><a href="https://www.hjnc.co.kr/esvc/vessel/berthScheduleT" target="_blank" rel="noreferrer">출처: HJNC 공개 선석배정현황</a> · 원문 시간대·전체 범위·변경 확인은 별도입니다.</p>
      <h3>기상청 · 부산 신항 인근 참고 관측</h3>
      <p className="small muted">거제도 부이(22104)는 터미널 내부 관측이 아닙니다. 기상과 지연이 동시에 나타나도 지연 원인으로 확정하지 않습니다. 1시간 이상 지난 관측은 과거 자료로 봅니다.</p>
      {data.weather.map(w => <div className="card" key={w.kind}>
        <h4>{w.kind === 'sea' ? '해양 관측' : '기상특보 조회'}</h4>
        <p className="small">{w.status === 'sample_received' ? '실제 수신' : w.status === 'empty_framed_response' ? '정상 응답 · 자료 0건(특보 없음의 증거는 아님)' : `조회 확인 필요: ${w.status}`} · HTTP {w.http_status ?? '—'} · 수신 {w.received_at ? kstDateTime(w.received_at) : '없음'}</p>
        {!!w.report?.station_mismatch_rows && <p className="warn">요청 지점과 다른 관측입니다.</p>}
        {!!w.report?.future_observation_rows && <p className="warn">수신 시각 이후 관측이 포함되어 현재 판단 근거로 쓸 수 없습니다.</p>}
        {w.report?.observations.map((o,i) => <p key={i}>관측 {kstDateTime(o.observed_at_utc)}{Date.now()-Date.parse(o.observed_at_utc)>3600000 && <b className="warn"> · 오래된 관측</b>}<br/>유의파고 {o.missing_or_invalid_nonnegative_fields.includes('WH') ? '미확인' : o.wh_m_original + ' m'} · 풍속 {o.missing_or_invalid_nonnegative_fields.includes('WS') ? '미확인' : o.ws_m_s_original + ' m/s'} · 순간풍속 {o.missing_or_invalid_nonnegative_fields.includes('WS_GST') ? '미확인' : o.gust_m_s_original + ' m/s'}</p>)}
        {w.report?.selected_records.map((r,i) => <p key={i}>{r.region_name} · {r.kind} {r.level} · {r.command}<br/>발표 {kstDateTime(r.published_at_utc)} · 발효 원문(KST) {r.effective_time_original_kst}</p>)}
      </div>)}
      <p className="small"><a href="https://apihub.kma.go.kr/" target="_blank" rel="noreferrer">자료: 기상청 API허브</a> · 관측·발표·발효·수신 시각을 구분합니다. 배차 계산에는 넣지 않았습니다.</p>
      <h3>AIS · 부산 제한 수신 시험</h3>
      {data.ais ? <p className="small">{data.ais.subscription_confirmed ? '구독 응답 확인' : '구독 확인 안 됨'} · {data.ais.max_seconds}초 동안 위치 {data.ais.valid_position_events}건 / 선박 {data.ais.unique_position_mmsi_count}척 · 상태 {data.ais.status}<br/>시험 종료 {kstDateTime(data.ais.finished_at)} · {data.ais.connection_closed ? '연결 종료 확인' : '종료 확인 필요'}<br/>무수신은 부산에 선박이 없다는 뜻이 아닙니다. 지도에서 모의 재생을 별도로 선택할 수 있습니다.</p> : <p>실제 AIS 시험 기록이 아직 없습니다.</p>}
    </>}
  </>
}
