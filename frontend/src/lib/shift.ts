// 모의 예제를 시연 시각으로 옮긴다.
// 기준시각(as_of)을 지금 직전의 10분 경계로 옮기고, 그 차이만큼 `*_at`·`as_of`·`input_valid_until` 시각을 모두 같은 양 이동한다.
// 10분 단위로 옮기므로 반입 마감·모선 접안이 01:01 같은 어색한 분이 아니라 10분 단위로 놓인다.
// 예제의 첫 출발은 기준 10분 뒤라, 기준과 지금의 차이(최대 9분) 때문에 승인 전 작업이 이미 출발한 것처럼 보이지 않는다.
// 원본의 반입 시작이 KST 자정이면(터미널 관행: 접안일 3일 전 00:00) 이동 후에도 같은 규칙으로 자정에 맞춘다.
// 미확인(null) 값은 그대로 둔다(채우지 않음). 실제 자료는 옮기지 않는다.
import type { Snapshot } from '../api/types'

/** 모의 상황의 기준시각: 지금 직전의 10분 경계. 배차 예제·입항 모선·지금 신항이 모두 같은 기준을 쓴다. */
export function demoAnchor(now = Date.now()): Date {
  return new Date(Math.floor(now / SLOT) * SLOT)
}

export function shiftSnapshot(source: Snapshot, anchor: Date): Snapshot {
  if (source.data_mode !== 'simulated') throw new Error('모의 입력만 시연 시각으로 옮길 수 있습니다.')
  const delta = Math.floor(anchor.getTime() / SLOT) * SLOT - Date.parse(source.as_of)
  const shift = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(shift)
    if (node && typeof node === 'object')
      return Object.fromEntries(
        Object.entries(node).map(([k, v]) => [
          k,
          typeof v === 'string' && (k.endsWith('_at') || k === 'as_of' || k === 'input_valid_until')
            ? new Date(Date.parse(v) + delta).toISOString().replace('.000Z', 'Z')
            : shift(v),
        ]),
      )
    return node
  }
  const out = shift(source) as Snapshot
  out.windows = out.windows.map((w, i) => {
    const original = source.windows[i]
    if (!original || !w.opens_at || !w.closes_at || !isKstMidnight(original.opens_at)) return w
    const berthDay = kstMidnight(Date.parse(w.closes_at) + BERTH_AFTER_CLOSE)
    return { ...w, opens_at: iso(berthDay - 3 * DAY) }
  })
  return out
}

const MIN = 60_000
const SLOT = 10 * MIN
const DAY = 24 * 60 * MIN
const KST = 9 * 60 * MIN
const BERTH_AFTER_CLOSE = 10 * 60 * MIN
const kstMidnight = (t: number) => Math.floor((t + KST) / DAY) * DAY - KST
const isKstMidnight = (v: string | null | undefined) => !!v && kstMidnight(Date.parse(v)) === Date.parse(v)
const iso = (t: number) => new Date(t).toISOString().replace('.000Z', 'Z')
