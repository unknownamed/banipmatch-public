// 터미널 일정: 배차 담당자가 확인하는 외부 공지(HJNC 항차별 반입 일정)와 판단 참고 정보(해상 기상·도로 이동시간).
// 서버에 보관된 마지막 실제 수신 결과를 보여 준다. 수신 실패 시 예시 자료로 바꾸지 않는다.
import { useEffect, useMemo, useState } from 'react'
import { createV2Client } from '../api/v2'
import { display, type ReferenceView } from '../lib/reference'
import { kstDateTime } from '../lib/time'
import { type RoadData } from './RoadReference'
import { Icon } from './Icon'

interface Weather {
  kind: 'sea' | 'warning'; status: string; received_at: string | null; http_status: number | null; failure?: 'network' | 'provider' | null
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
  const [tlFilter, setTlFilter] = useState<'all' | 'before' | 'open' | 'closed'>('open')
  const [tlQuery, setTlQuery] = useState('')
  // 서버에 받아 둔 최신 일정을 5분마다 다시 읽는다(사람이 누를 필요 없음). 이미 보이는 표는 다시 읽는 동안에도 유지한다.
  async function load(quiet = false) {
    if (!quiet) setLoading(true)
    try { await client.session(); setData(await client.get<LiveData>('/v2/references/current')); setError(null) }
    catch (e) { if (!quiet) { setError(e instanceof Error ? e.message : '자료를 읽지 못했습니다.'); setData(null) } }
    finally { if (!quiet) setLoading(false) }
  }
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(true), 5 * 60_000)
    return () => window.clearInterval(timer)
  }, [client])

  if (error) return <p className="warn" role="alert">터미널 일정을 불러오지 못했습니다: {error}</p>
  if (!data) return <p className="muted" role="status">{loading ? '불러오는 중…' : ''}</p>

  const d = display(data.hjnc)
  const all = [...(d.sample?.items ?? [])].sort((a, b) => String(a.values.YARD_CLOSE).localeCompare(String(b.values.YARD_CLOSE)))
  // 공개 화면의 시각은 KST 문자열이다. 지금과 비교해 반입 전 / 반입 중 / 마감을 표시한다.
  const kstMs = (raw: unknown) => (typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(raw) ? Date.parse(`${raw.slice(0, 10)}T${raw.slice(11, 16)}:00+09:00`) : NaN)
  const stateOf = (v: Record<string, unknown>): 'before' | 'open' | 'closed' => {
    const now = Date.now(), o = kstMs(v.YARD_OPEN), c = kstMs(v.YARD_CLOSE)
    return now >= c ? 'closed' : now >= o ? 'open' : 'before'
  }
  const rows = all.filter((it) => (tlFilter === 'all' || stateOf(it.values) === tlFilter) && (!tlQuery.trim() || String(it.values.VOY_NO).toLowerCase().includes(tlQuery.trim().toLowerCase())))
  const received = d.sample?.received_at ?? data.hjnc.last_success?.received_at ?? null

  return <>
    <section className="card tl-card" aria-labelledby="tl-hjnc">
      <div className="tl-head">
        <div>
          <h3 id="tl-hjnc">HJNC 항차별 반입 일정</h3>
          <p className="small muted">
            <a href="https://www.hjnc.co.kr/esvc/vessel/berthScheduleT" target="_blank" rel="noreferrer">HJNC 공개 선석배정현황</a> 기준
            {received && <>, {kstDateTime(received)} 수신 <span className={`tl-age${(Date.now() - Date.parse(received)) > 6 * 3600000 ? ' stale' : ''}`}>{age(received)}</span></>}
          </p>
        </div>
      </div>
      {all.length > 0 && (
        <div className="toolbar">
          <div className="seg" role="group" aria-label="반입 상태">
            {([['open', '반입 중'], ['before', '반입 전'], ['closed', '마감'], ['all', '전체']] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={tlFilter === id} onClick={() => setTlFilter(id)}>{label}<span className="n">{id === 'all' ? all.length : all.filter((it) => stateOf(it.values) === id).length}</span></button>
            ))}
          </div>
          <label className="search">
            <Icon name="search" size={15} />
            <input type="search" value={tlQuery} onChange={(e) => setTlQuery(e.target.value)} placeholder="항차 검색 (예: OONP)" aria-label="항차 검색" />
          </label>
        </div>
      )}
      {all.length ? (
        <div className="dt-wrap">
          <table className="dt tl-table">
            <thead><tr><th scope="col">항차</th><th scope="col">상태</th><th scope="col">반입 시작</th><th scope="col">반입 마감</th><th scope="col">접안 예정</th></tr></thead>
            <tbody>
              {rows.length === 0 && <tr className="empty-row"><td colSpan={5}>조건에 맞는 항차가 없습니다.</td></tr>}
              {rows.map((it, i) => (
                <tr key={`${it.values.VOY_NO}:${i}`}>
                  <td className="tl-voy">{it.values.VOY_NO}</td>
                  <td>{(() => { const st = stateOf(it.values); return <span className={`st ${st === 'open' ? 'ok' : st === 'closed' ? 'wait' : 'run'}`}>{st === 'open' ? '반입 중' : st === 'closed' ? '마감' : '반입 전'}</span> })()}</td>
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


  </>
}

/** 입항 선박 화면용 한 줄 해상 기상(모선 도착이 늦어질 수 있는 참고). 배차 계산에는 쓰지 않는다. */
export function SeaWeatherLine() {
  const [data, setData] = useState<LiveData | null>(null)
  useEffect(() => {
    const client = createV2Client()
    client.session().then(() => client.get<LiveData>('/v2/references/current')).then(setData, () => setData(null))
  }, [])
  const obs = data?.weather.find(w => w.kind === 'sea')?.report?.observations[0]
  const warn = data?.weather.find(w => w.kind === 'warning')
  // 3시간이 지난 관측은 지금 바다 상태로 보기 어려워 보여 주지 않는다.
  if (!obs || Date.now() - Date.parse(obs.observed_at_utc) > 3 * 3600_000) return null
  const warnText = warn?.status === 'empty_framed_response' ? '특보 없음'
    : warn?.report?.selected_records.length ? warn.report.selected_records.map(r => `${r.kind} ${r.level}`).join(', ')
    : warn?.failure === 'provider' ? '특보 확인 안 됨(기상청 응답 오류)'
    : warn?.failure === 'network' ? '특보 확인 안 됨(연결 실패)' : ''
  const hm = new Date(obs.observed_at_utc).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' })
  return (
    <span className="sea-line" title={`거제도 해양기상부이, ${hm} 관측`}>
      <span className="sea-item"><Icon name="waves" size={15} />파고 <b>{obs.wh_m_original}m</b></span>
      <span className="sea-item"><Icon name="wind" size={15} />풍속 <b>{obs.ws_m_s_original}m/s</b></span>
      {warnText && <span className={`sea-item${warnText === '특보 없음' ? '' : warnText.startsWith('특보 확인 안 됨') ? ' sea-muted' : ' sea-warn'}`}><Icon name="weather" size={15} />{warnText}</span>}
      <span className="sea-age">{hm} 관측</span>
    </span>
  )
}
