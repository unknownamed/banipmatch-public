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
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  map: 'M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14',
  plus: 'M12 5v14M5 12h14',
  ship: 'M3 16h18l-2.5 5h-13L3 16zM5 16V9h14v7M9 9V5h6v4',
  box: 'M3 7.5 12 3l9 4.5v9L12 21l-9-4.5v-9zM3 7.5l9 4.5 9-4.5M12 12v9',
  edit: 'M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4',
  octagon: 'M8 3h8l5 5v8l-5 5H8l-5-5V8l5-5zM12 8v5M12 16h.01',
  arrow: 'M5 12h14M13 6l6 6-6 6',
} as const

export function Icon({ name, size = 13 }: { name: keyof typeof PATHS; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  )
}
