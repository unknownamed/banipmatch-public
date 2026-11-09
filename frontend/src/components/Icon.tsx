// 이모지 대신 쓰는 단색 선 아이콘(currentColor, 선 두께 1.75 통일). 뜻은 옆 글자가 전하므로 화면 낭독기에서는 숨긴다.
const PATHS = {
  lock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4',
  warning: 'M12 3 2 21h20L12 3zM12 10v5M12 18h.01',
  up: 'M12 19V5M5 12l7-7 7 7',
  down: 'M12 5v14M5 12l7 7 7-7',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  swap: 'M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7',
  truck: 'M2 6h11v10H2zM13 10h4l4 4v2h-8M6.5 19a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM17.5 19a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z',
  check: 'M5 12l5 5 9-10',
} as const

export function Icon({ name, size = 13 }: { name: keyof typeof PATHS; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  )
}
