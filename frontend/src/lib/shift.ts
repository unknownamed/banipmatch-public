// 모의 예제를 시연 시각으로 옮긴다. 서버 tools.demo_engine_api.prepare_snapshot과 같은 규칙:
// 기준시각(as_of)과 지금(분 단위)의 차이만큼 `*_at`·`as_of`·`input_valid_until` 시각을 모두 같은 양 이동한다.
// 미확인(null) 값은 그대로 둔다(채우지 않음). 실제 자료는 옮기지 않는다.
import type { Snapshot } from '../api/types'

export function shiftSnapshot(source: Snapshot, anchor: Date): Snapshot {
  if (source.data_mode !== 'simulated') throw new Error('모의 입력만 시연 시각으로 옮길 수 있습니다.')
  const delta = Math.floor(anchor.getTime() / 60000) * 60000 - Date.parse(source.as_of)
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
  return shift(source) as Snapshot
}
