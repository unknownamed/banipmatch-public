// 단색 선 아이콘. 오픈소스 Lucide(ISC 라이선스)를 쓰고, 이름은 화면에서 쓰는 업무 뜻으로 묶는다.
// 뜻은 옆 글자가 전하므로 화면 낭독기에서는 숨긴다.
import {
  Anchor, ArrowDown, ArrowLeftRight, ArrowRight, ArrowUp, Bell, CalendarClock, Check, CircleCheck, Clock, Container,
  Inbox, Info, LayoutGrid, Lock, Map, OctagonAlert, Package, PencilLine, Plus, Route, Search, Ship, TriangleAlert, Truck, Waves, Wind, CloudSun,
  type LucideIcon,
} from 'lucide-react'

const ICONS = {
  lock: Lock,
  warning: TriangleAlert,
  up: ArrowUp,
  down: ArrowDown,
  clock: Clock,
  swap: ArrowLeftRight,
  truck: Truck,
  check: Check,
  checkCircle: CircleCheck,
  grid: LayoutGrid,
  map: Map,
  plus: Plus,
  ship: Ship,
  box: Package,
  container: Container,
  edit: PencilLine,
  octagon: OctagonAlert,
  arrow: ArrowRight,
  bell: Bell,
  inbox: Inbox,
  anchor: Anchor,
  schedule: CalendarClock,
  route: Route,
  info: Info,
  search: Search,
  waves: Waves,
  wind: Wind,
  weather: CloudSun,
} satisfies Record<string, LucideIcon>

export type IconName = keyof typeof ICONS

export function Icon({ name, size = 13 }: { name: IconName; size?: number }) {
  const C = ICONS[name]
  return <C className="icon" size={size} strokeWidth={1.9} aria-hidden="true" />
}
