// 홈 오른쪽 '지금 신항': 담당자가 신경 쓰는 HJNC 반입 마감 임박 항차와, 그 모선의 도착 예정(입항 모선 지도와 같은 모의 자료).
import { useMemo } from 'react'
import { VESSELS, fleetAt, formatDuration } from '../lib/vesselApproach'
import { Icon } from './Icon'
import { demoAnchor } from '../lib/shift'

const hm = (d: Date) => d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' })

export function NowPanel() {
  const now = useMemo(() => new Date(), [])
  // 항차 시각은 모의 기준시각(30분 경계)에 붙어 있다. 남은 시간은 지금 시각 기준.
  const base = useMemo(() => demoAnchor(now.getTime()), [now])
  const elapsed = (now.getTime() - base.getTime()) / 60000
  const at = (min: number) => hm(new Date(base.getTime() + min * 60000))
  const upcoming = VESSELS.filter(v => v.terminal === 'HJNC' && v.cutoffMin !== null && v.cutoffMin > elapsed)
    .sort((a, b) => a.cutoffMin! - b.cutoffMin!).slice(0, 3)
  const inbound = fleetAt(0).filter(v => v.status === 'underway' && !v.vessel.outbound).length
  return (
    <aside className="card now-panel" aria-label="지금 신항 상황">
      <div className="now-head">
        <h2>지금 신항</h2>
        <span className="now-clock"><span className="vm-live" aria-hidden="true" />{hm(now)}</span>
      </div>
      <p className="now-sub">HJNC 반입 마감이 가까운 항차</p>
      <ol className="now-list">
        {upcoming.map(v => (
          <li key={v.id}>
            <span className="now-ship"><Icon name="clock" size={16} /></span>
            <span className="now-main"><b>{v.voyage}</b><span className="muted small">{v.name}</span></span>
            <span className="now-eta"><b>{at(v.cutoffMin!)}</b><span className="muted small">{formatDuration(v.cutoffMin! - elapsed)} 남음</span></span>
            {v.offshoreEtaMin !== undefined && <span className="now-cut small muted">모선 접안 예정 {at(v.offshoreEtaMin)}</span>}
          </li>
        ))}
      </ol>
      <p className="now-foot small"><Icon name="ship" size={14} /> 지금 신항으로 들어오는 모선 {inbound}척</p>
      <div className="now-links">
        <a href="?view=map">입항 모선 지도 <Icon name="arrow" size={13} /></a>
        <a href="?view=reference">터미널 일정 <Icon name="arrow" size={13} /></a>
      </div>
    </aside>
  )
}
