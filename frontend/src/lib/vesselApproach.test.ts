import { describe, expect, it } from 'vitest'
import { VESSELS, distanceNm, fleetAt, pointAlong, routeLengthNm, vesselAt, formatDuration, type Vessel } from './vesselApproach'

const line = [{ lat: 35, lon: 128.8 }, { lat: 35.1, lon: 128.8 }] // 정북 6해리

describe('입항 선박 계산', () => {
  it('위도 0.1도는 약 6해리이고 항로 길이는 구간 합이다', () => {
    expect(distanceNm(line[0], line[1])).toBeCloseTo(6.0, 1)
    expect(routeLengthNm([line[0], line[1], line[0]])).toBeCloseTo(12.0, 1)
  })

  it('항로 중간 지점은 지나온 경로와 남은 경로로 나뉘고 진행 방향은 북쪽이다', () => {
    const at = pointAlong(line, 3)
    expect(at.pos.lat).toBeCloseTo(35.05, 2)
    expect(at.heading).toBeCloseTo(0, 0)
    expect(at.passed.at(-1)).toEqual(at.pos)
    expect(at.ahead[0]).toEqual(at.pos)
  })

  it('도착 추정은 남은 항로를 현재 속력으로 나눈 값이다', () => {
    const v: Vessel = { id: 'T', name: 't', voyage: 'V', terminal: 'HJNC', route: line, startNm: 0, speedKn: 12, state: 'underway', cutoffMin: 0 }
    const now = vesselAt(v, 10) // 10분 동안 2해리 이동
    expect(now.remainingNm!).toBeCloseTo(4.0, 1)
    expect(now.etaMin!).toBeCloseTo(10 + 20, 0)
    expect(vesselAt(v, 40).status).toBe('berthed')
  })

  it('속력이 0인 묘박 선박은 도착 시각을 만들지 않는다', () => {
    const v = vesselAt(VESSELS.find(x => x.state === 'anchored')!, 30)
    expect(v.status).toBe('anchored')
    expect(v.etaMin).toBeNull()
  })

  it('위치 갱신이 끊기면 마지막 위치에 멈추고 도착 추정을 내지 않는다', () => {
    const s = VESSELS.find(x => x.staleAfterMin !== undefined)!
    const before = vesselAt(s, s.staleAfterMin!)
    const after = vesselAt(s, s.staleAfterMin! + 20)
    expect(after.status).toBe('stale')
    expect(after.pos).toEqual(before.pos)
    expect(after.etaMin).toBeNull()
    expect(after.positionAgeMin).toBe(20)
  })

  it('대상 터미널(HJNC) 항차가 목록 앞에 오고, 그 안에서 도착이 빠른 순이다', () => {
    const list = fleetAt(0)
    const hj = list.filter(v => v.vessel.terminal === 'HJNC')
    expect(list.slice(0, hj.length).every(v => v.vessel.terminal === 'HJNC')).toBe(true)
    const etas = hj.filter(v => v.etaMin !== null).map(v => v.etaMin!)
    expect(etas).toEqual([...etas].sort((a, b) => a - b))
  })

  it('남은 시간 표기', () => {
    expect(formatDuration(42.4)).toBe('42분')
    expect(formatDuration(135)).toBe('2시간 15분')
  })
})
