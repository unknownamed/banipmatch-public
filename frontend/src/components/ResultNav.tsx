// 점검 결과 화면이 길어서 위에 붙는 구역 이동 줄을 둔다(요약 → 변경 → 비교 → 지도 → 확정 → 기사 전달).
// 지금 보고 있는 구역을 표시하고, 아직 화면에 없는 구역(예: 승인 전의 기사 전달)은 숨긴다.
import { useEffect, useState } from 'react'

const SECTIONS = [
  ['요약', '.action-summary'],
  ['마감 변경', '.card.evidence'],
  ['조정안 비교', '.comparison'],
  ['차량 지도', '.dispatch-map'],
  ['확정', '.side'],
  ['기사 전달', '.card.dispatch'],
] as const

/** 위에 붙는 가로 메뉴 막대(중간 폭·휴대폰)가 있으면 그 높이만큼 아래에 붙는다. 넓은 화면의 왼쪽 메뉴는 해당 없음. */
function stickyBarHeight(): number {
  const bar = document.querySelector<HTMLElement>('.appbar')
  if (!bar) return 0
  const r = bar.getBoundingClientRect()
  const sticky = getComputedStyle(bar).position === 'sticky'
  return sticky && r.width > window.innerWidth * 0.8 && r.top <= 0 + 1 ? Math.floor(r.bottom) : 0 // 소수점 틈으로 아래 글자가 비치지 않게 내림
}

/** brief: 바꿀 것이 없는 결과에서는 확정·기사 전달 구역이 없다. */
export function ResultNav({ brief = false }: { brief?: boolean }) {
  const [top, setTop] = useState(0)
  const [active, setActive] = useState<string | null>(null)
  const [present, setPresent] = useState<string[] | null>(null)
  useEffect(() => {
    const update = () => {
      const offset = stickyBarHeight()
      setTop(offset)
      const found = SECTIONS.filter(([, sel]) => document.querySelector(sel)).map(([, sel]) => sel)
      setPresent((prev) => (prev && prev.join() === found.join() ? prev : found))
      let current: string | null = found[0] ?? null
      for (const sel of found) if (document.querySelector(sel)!.getBoundingClientRect().top - (offset + 90) <= 0) current = sel
      // 맨 아래까지 내렸으면 마지막 구역
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4 && found.length) current = found[found.length - 1]
      setActive(current)
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    // 결과 도착·승인 뒤에 구역이 새로 생긴다.
    const timer = window.setInterval(update, 1500)
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
      window.clearInterval(timer)
    }
  }, [])
  const go = (sel: string, button: HTMLButtonElement) => {
    button.blur()
    const el = document.querySelector(sel)
    if (!el) return
    const y = el.getBoundingClientRect().top + window.scrollY - top - 64
    window.scrollTo({ top: y, behavior: 'smooth' })
  }
  const shown = SECTIONS.filter(([, sel]) => (!brief || (sel !== '.side' && sel !== '.card.dispatch')) && (!present || present.includes(sel)))
  return (
    <nav className="result-nav" aria-label="결과 구역" style={top ? { top } : undefined}>
      {shown.map(([label, sel]) => (
        <button key={sel} type="button" className="rn-link" aria-current={active === sel ? 'true' : undefined} onClick={(e) => go(sel, e.currentTarget)}>
          {brief && sel === '.comparison' ? '차량별 일정' : label}
        </button>
      ))}
    </nav>
  )
}
