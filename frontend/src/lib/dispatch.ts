// 확정 변경의 전달·응답 상태(R5~R7). 중계망 접수 ≠ 읽음 ≠ 확인 ≠ 수행 가능 ≠ 운송 완료.

export type DeliveryStatus = 'pending' | 'sending' | 'accepted' | 'failed' | 'unknown' | 'expired' | 'unsubscribed' | 'unlinked' | 'superseded'
export type HumanResponse = 'none' | 'acknowledged' | 'can_perform' | 'cannot_perform'

export interface Followup {
  code: string
  job_id: string | null
  explanation?: string
  contact_role?: string
  check_next?: string
  proof_level?: string
}

export interface PlanChange {
  job_id: string
  kind: string
  before: { vehicle_id?: string; pickup_departure_at?: string; gate_arrival_at?: string } | null
  after: { vehicle_id?: string; pickup_departure_at?: string; gate_arrival_at?: string } | null
  instruction: string
  /** 현장 표시 정보(입력에 있을 때만): 컨테이너 번호·화주·상차지 이름·항차·터미널·크기 */
  display?: { container_no?: string | null; booking_no?: string | null; cargo_owner?: string | null; origin_name?: string; terminal_id?: string; voyage_id?: string; size?: string }
}

export interface DispatchPreview {
  plan_id: string
  scenario_id: string
  method: string
  data_mode: string
  approval_id: string
  approved_version: number
  run_id: string
  unassigned_job_ids: string[]
  followups: Followup[]
  limits: string[]
  vehicle_changes: { vehicle_id: string; plate_no?: string | null; changes: PlanChange[]; followups: Followup[]; recipient_id: string | null; recipient_status: string }[]
}

export interface NotificationState {
  notification_id: string
  recipient_id: string | null
  delivery_status: DeliveryStatus
  error_code: string | null
  attempts: number
  accepted_at: string | null
  opened_at: string | null
  response: HumanResponse
  responded_at: string | null
  is_current: boolean
  vehicle_ids: string[]
  needs_followup: boolean
  retry_not_before: string | null
  response_history: { response: HumanResponse; note: string; created_at: string }[]
}

export interface DispatchState {
  dispatch_id: string
  plan_version: number
  is_current: boolean
  notifications: NotificationState[]
  followups: Followup[]
  external_transport_completed: boolean
}

export interface RecipientSummary {
  recipient_id: string
  plan_id: string
  expires_at: string
  revoked: boolean
  vehicle_ids: string[]
  subscription_status: 'active' | 'revoked' | 'expired' | 'missing'
  /** 기사가 동의해 보낸 최근 60분 안의 휴대폰 위치 */
  location?: DriverLocation | null
}

export interface DriverLocation { latitude: number; longitude: number; accuracy_m: number; captured_at: string; received_at: string }

export const DELIVERY_LABEL: Record<DeliveryStatus, string> = {
  pending: '전송 대기',
  sending: '전송 중',
  accepted: '전달됨',
  failed: '전송 실패',
  unknown: '전달 결과 확인 안 됨',
  expired: '알림 연결 만료',
  unsubscribed: '알림 꺼짐(앱에서 확인 가능)',
  unlinked: '휴대폰 미연결',
  superseded: '이전 계획',
}

export const RESPONSE_LABEL: Record<HumanResponse, string> = {
  none: '응답 없음',
  acknowledged: '확인함',
  can_perform: '수행 가능',
  cannot_perform: '수행 곤란(후속 확인 필요)',
}

export const SUBSCRIPTION_LABEL: Record<RecipientSummary['subscription_status'] | 'unlinked', string> = {
  active: '알림 받는 중',
  missing: '연결됨, 알림 꺼짐',
  revoked: '해제됨',
  expired: '만료',
  unlinked: '휴대폰 미연결',
}

export const CHANGE_LABEL: Record<string, string> = {
  reassigned: '차량 변경',
  schedule_changed: '시각·순서 변경',
  removed_from_plan: '배정 보류(운송 취소 아님)',
  newly_assigned: '새로 배정',
}

/**
 * 담당자가 명시적으로 다시 보낼 수 있는지. 확실한 실패·구독 해제·미연결만.
 * 접수(accepted)·불명(unknown)은 중복 수신 위험 때문에 재전송하지 않는다(서버도 차단). 시도 3회 상한.
 */
export function retryBlocker(n: NotificationState, now: number): string | null {
  if (!n.is_current || n.delivery_status === 'superseded') return '이전 계획이라 다시 보내지 않습니다.'
  if (!['failed', 'unsubscribed', 'expired', 'unlinked'].includes(n.delivery_status)) return null
  if (n.attempts >= 3) return '세 번 보냈습니다. 기사에게 직접 연락하세요.'
  if (n.retry_not_before && Date.parse(n.retry_not_before) > now) return '잠시 뒤 다시 보낼 수 있습니다.'
  return ''
}

/** 미연결 알림을 다시 보낼 때 쓸, 그 차량들을 맡은 현재 연결 수신자. 없으면 null(먼저 초대·연결). */
export function linkedRecipientFor(vehicleIds: string[], recipients: RecipientSummary[]): string | null {
  return recipients.find((r) => !r.revoked && r.subscription_status === 'active' && vehicleIds.every((v) => r.vehicle_ids.includes(v)))?.recipient_id ?? null
}

/** 초대 링크. 비밀은 fragment(#)에만 두어 서버 로그·Referer로 나가지 않게 한다. */
export const invitationLink = (origin: string, token: string) => `${origin}/recipient#invite=${encodeURIComponent(token)}`
