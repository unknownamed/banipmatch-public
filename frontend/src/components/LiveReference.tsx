// 터미널 일정: 배차 담당자가 확인하는 외부 공지(HJNC 항차별 반입 일정)와 판단 참고 정보(해상 기상·도로 이동시간).
// 서버에 보관된 마지막 실제 수신 결과를 보여 준다. 수신 실패 시 예시 자료로 바꾸지 않는다.
import { useEffect, useMemo, useState } from 'react'
import { createV2Client } from '../api/v2'
import { display, type ReferenceView } from '../lib/reference'
import { kstDateTime } from '../lib/time'
import { RoadReference, type RoadData } from './RoadReference'
import { Hint } from './Hint'

interface Weather {
  kind: 'sea' | 'warning'; status: string; received_at: string | null; http_status: number | null
  report: null | { row_count: number; future_observation_rows: number; station_mismatch_rows: number
    observations: { station_id: string; observed_at_utc: string; wh_m_original: string; ws_m_s_original: string; gust_m_s_original: string; missing_or_invalid_nonnegative_fields: string[] }[]
    selected_records: { region_name: string; kind: string; level: string; command: string; published_at_utc: string; effective_time_original_kst: string }[] }
}
interface LiveData { checked_at: string; hjnc: ReferenceView; weather: Weather[]; road?: RoadData | null; ais: null | {
  status: string; finished_at: string; max_seconds: number; subscription_confirmed: boolean; valid_position_events: number; unique_position_mmsi_count: number; connection_closed: boolean
} }

/** 원문 "2026-11-09 22:00" → "11/09 22:00" (원문 시간대는 바꾸지 않는다) */
const short = (raw: string | undefined) => (raw && /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(raw) ? `${raw.slice(5, 7)}/${raw.slice(8, 10)} ${raw.slice(11, 16)}` : raw ?? '—')
const age = (iso: string | null | undefined) => {
  if (!iso) return null
  const h = (Date.now() - Date.parse(iso)) / 3600000
  return h < 1 ? '1시간 이내' : h < 24 ? `${Math.floor(h)}시간 전` : `${Math.floor(h / 24)}일 전`
}

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

  if (error) return <p className="warn" role="alert">터미널 일정을 불러오지 못했습니다: {error}</p>
  if (!data) return <p className="muted" role="status">{loading ? '불러오는 중…' : ''}</p>

  const d = display(data.hjnc)
  const rows = [...(d.sample?.items ?? [])].sort((a, b) => String(a.values.YARD_CLOSE).localeCompare(String(b.values.YARD_CLOSE)))
  const received = d.sample?.received_at ?? data.hjnc.last_success?.received_at ?? null
  const sea = data.weather.find(w => w.kind === 'sea')
  const warn = data.weather.find(w => w.kind === 'warning')
  const obs = sea?.report?.observations[0]
  const val = (o: NonNullable<typeof obs>, key: string, v: string, unit: string) => (o.missing_or_invalid_nonnegative_fields.includes(key) ? '—' : `${v}${unit}`)

  return <>
    <section className="card tl-card" aria-labelledby="tl-hjnc">
      <div className="tl-head">
        <div>
          <h3 id="tl-hjnc">HJNC 항차별 반입 일정 <Hint text="공개 화면의 시각을 그대로 옮겼습니다. 배차 계산에는 담당자가 확정한 반입 마감만 쓰고, 이 표는 확인용입니다." /></h3>
          <p className="small muted">
            <a href="https://www.hjnc.co.kr/esvc/vessel/berthScheduleT" target="_blank" rel="noreferrer">HJNC 공개 선석배정현황</a> 기준
            {received && <> · 마지막 수신 {kstDateTime(received)} <span className={`tl-age${(Date.now() - Date.parse(received)) > 6 * 3600000 ? ' stale' : ''}`}>{age(received)}</span></>}
          </p>
        </div>
        <button type="button" className="secondary" disabled={loading} onClick={load}>{loading ? '불러오는 중…' : '다시 불러오기'}</button>
      </div>
      {rows.length ? (
        <div className="table-wrap">
          <table className="grid tl-table">
            <thead><tr><th scope="col">항차</th><th scope="col">반입 시작</th><th scope="col">반입 마감</th><th scope="col">접안 예정</th></tr></thead>
            <tbody>
              {rows.map((it, i) => (
                <tr key={`${it.values.VOY_NO}:${i}`}>
                  <td className="tl-voy">{it.values.VOY_NO}</td>
                  <td>{short(it.values.YARD_OPEN)}</td>
                  <td><b>{short(it.values.YARD_CLOSE)}</b></td>
                  <td>{short(it.values.ETB)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">{d.headline}</p>}
    </section>

    <div className="tl-grid">
      <section className="card tl-card" aria-labelledby="tl-sea">
        <h3 id="tl-sea">해상 기상 · 거제도 부이 <Hint text="기상청 API허브 관측입니다. 터미널 내부 관측이 아니며, 기상과 지연이 겹쳐도 지연 원인으로 단정하지 않습니다." /></h3>
        {obs ? (
          <>
            <div className="tl-kpis">
              <div><span>유의파고</span><b>{val(obs, 'WH', obs.wh_m_original, 'm')}</b></div>
              <div><span>풍속</span><b>{val(obs, 'WS', obs.ws_m_s_original, 'm/s')}</b></div>
              <div><span>순간풍속</span><b>{val(obs, 'WS_GST', obs.gust_m_s_original, 'm/s')}</b></div>
            </div>
            <p className="small muted">관측 {kstDateTime(obs.observed_at_utc)} · {age(obs.observed_at_utc)}</p>
          </>
        ) : <p className="muted">관측 자료가 없습니다.</p>}
        <p className="small">
          기상특보: {warn?.status === 'empty_framed_response' ? '해당 지역 발효 기록 없음' : warn?.report?.selected_records.length
            ? warn.report.selected_records.map(r => `${r.region_name} ${r.kind} ${r.level}`).join(', ') : '확인 필요'}
        </p>
      </section>
      <RoadReference road={data.road} />
    </div>

    <details className="tech-info tl-status">
      <summary>데이터 연결 상태</summary>
      <table className="grid small">
        <thead><tr><th>자료</th><th>상태</th><th>마지막 수신</th></tr></thead>
        <tbody>
          <tr><td>HJNC 반입 일정</td><td>{d.headline}</td><td>{received ? kstDateTime(received) : '—'}</td></tr>
          {data.weather.map(w => <tr key={w.kind}><td>{w.kind === 'sea' ? '기상청 해양 관측' : '기상청 특보'}</td><td>{w.status === 'sample_received' ? '수신' : w.status === 'empty_framed_response' ? '정상 응답(0건)' : w.status} · HTTP {w.http_status ?? '—'}</td><td>{w.received_at ? kstDateTime(w.received_at) : '—'}</td></tr>)}
          <tr><td>도로 이동시간(ORS)</td><td>{data.road?.status ?? '없음'}</td><td>{data.road?.received_at ? kstDateTime(data.road.received_at) : '—'}</td></tr>
          <tr><td>AIS 선박 위치</td><td>{data.ais ? `${data.ais.max_seconds}초 시험 · 위치 ${data.ais.valid_position_events}건(부산 제한 구역)` : '기록 없음'}</td><td>{data.ais ? kstDateTime(data.ais.finished_at) : '—'}</td></tr>
        </tbody>
      </table>
      <p className="small muted">자동 반복 수집은 하지 않습니다. 제공기관 이용 조건을 확인한 범위에서 받은 결과만 보관합니다. AIS 무수신은 선박이 없다는 뜻이 아닙니다.</p>
    </details>
  </>
}
