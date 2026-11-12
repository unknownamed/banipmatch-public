// 한 작업의 진행 단계(상차지 이동 → 게이트로 운송 → 게이트 반입 → 복귀). 물류 추적 화면에서 흔히 쓰는 단계 표시.
import type { Phase } from '../lib/fleetPosition'

const STEPS = ['상차', '운송', '반입', '복귀'] as const
const INDEX: Record<Phase, number> = { idle: -1, to_origin: 0, loading_wait: 0, to_gate: 1, at_gate: 2, returning: 3, done: 4 }

export function TripStepper({ phase, late = false, compact = false }: { phase: Phase; late?: boolean; compact?: boolean }) {
  const at = INDEX[phase]
  if (compact)
    return (
      <span className={`trip-bar${late ? ' late' : ''}`} aria-label={`진행 단계: ${at < 0 ? '대기' : at > 3 ? '완료' : STEPS[at]}`}>
        {STEPS.map((s, i) => <i key={s} className={i < at ? 'done' : i === at ? 'now' : ''} />)}
      </span>
    )
  return (
    <ol className={`trip-steps${late ? ' late' : ''}`} aria-label={`진행 단계: ${at < 0 ? '대기' : at > 3 ? '완료' : STEPS[at]}`}>
      {STEPS.map((s, i) => (
        <li key={s} className={i < at ? 'done' : i === at ? 'now' : ''}>
          <span className="dot" aria-hidden="true" />
          <span className="lbl">{s}</span>
        </li>
      ))}
    </ol>
  )
}
