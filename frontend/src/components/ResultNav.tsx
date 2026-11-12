// 점검 결과 화면이 길어서 위에 붙는 구역 이동 줄을 둔다(요약 → 변경 → 비교 → 지도 → 확정 → 기사 전달).
const SECTIONS = [
  ['요약', '.action-summary'],
  ['마감 변경', '.card.evidence'],
  ['조정안 비교', '.comparison'],
  ['차량 지도', '.dispatch-map'],
  ['확정', '.side'],
  ['기사 전달', '.card.dispatch'],
] as const

/** brief: 바꿀 것이 없는 결과에서는 확정·기사 전달 구역이 없다. */
export function ResultNav({ brief = false }: { brief?: boolean }) {
  const go = (sel: string) => {
    const el = document.querySelector(sel)
    if (!el) return
    const y = el.getBoundingClientRect().top + window.scrollY - 64
    window.scrollTo({ top: y, behavior: 'smooth' })
  }
  return (
    <nav className="result-nav" aria-label="결과 구역">
      {SECTIONS.filter(([, sel]) => !brief || (sel !== '.side' && sel !== '.card.dispatch')).map(([label, sel]) => (
        <button key={sel} type="button" className="rn-link" onClick={() => go(sel)}>{brief && sel === '.comparison' ? '차량별 일정' : label}</button>
      ))}
    </nav>
  )
}
