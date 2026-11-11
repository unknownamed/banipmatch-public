// 수신자 화면 전용 /v2/recipient 연결. 담당자 세션과 다른 쿠키(경로 /v2/recipient)를 쓰며 담당자 API를 부르지 않는다.
import { readJson } from './client'
import type { DeliveryStatus, HumanResponse, PlanChange } from '../lib/dispatch'

export interface RecipientSession {
  recipient_id: string
  vehicle_ids: string[]
  expires_at: string
  csrf_token: string
  subscription_status: 'active' | 'revoked' | 'expired' | 'missing'
  data_mode: string
}

export interface RecipientChange extends PlanChange {
  before_outside_scope?: boolean
  after_outside_scope?: boolean
}

export interface RecipientNotification {
  notification_id: string
  delivery_status: DeliveryStatus
  created_at: string
  opened_at: string | null
  response: HumanResponse
  responded_at: string | null
  is_current: boolean
  vehicle_ids: string[]
  /** 이전 계획이면 null(상세를 가림). */
  payload: { plan_version: number; data_mode: string; vehicle_changes: { vehicle_id: string; changes: RecipientChange[] }[] } | null
  response_history: { response: HumanResponse; note: string; created_at: string }[]
}

const enc = encodeURIComponent

export function createRecipientClient(base = '') {
  let csrf: string | null = null
  const remember = (s: RecipientSession) => ((csrf = s.csrf_token), s)

  async function write<T>(method: 'POST' | 'DELETE', path: string, body: unknown, key: string): Promise<T> {
    const res = await fetch(`${base}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    return readJson<T>(res)
  }
  const get = <T,>(path: string) => fetch(`${base}${path}`).then(readJson<T>)

  return {
    /** 기존 수신자 쿠키로 복구. 없으면 401 RECIPIENT_REQUIRED. */
    restore: () => get<RecipientSession>('/v2/recipient/session').then(remember),
    /** 초대 비밀을 본문으로 교환. 같은 초대 재시도는 같은 키(claimKey). */
    claim: (invitation_token: string, key: string) =>
      write<RecipientSession>('POST', '/v2/recipient/session', { invitation_token, accept_test_invitation: true }, key).then(remember),
    leave: () => write<{ revoked: boolean }>('DELETE', '/v2/recipient/session', undefined, `leave-${crypto.randomUUID()}`),
    pushConfig: () => get<{ configured: boolean; application_server_key: string | null }>('/v2/recipient/push-config'),
    subscribe: (subscription: PushSubscriptionJSON) =>
      write<{ subscription_status: string }>('POST', '/v2/recipient/subscription', {
        subscription: { endpoint: subscription.endpoint, keys: subscription.keys, expirationTime: null },
        notification_permission: 'granted',
        consent: true,
      }, `subscribe-${crypto.randomUUID()}`),
    unsubscribe: () => write<{ subscription_status: string }>('DELETE', '/v2/recipient/subscription', undefined, `unsubscribe-${crypto.randomUUID()}`),
    inbox: () => get<{ notifications: RecipientNotification[] }>('/v2/recipient/notifications'),
    notification: (id: string) => get<RecipientNotification>(`/v2/recipient/notifications/${enc(id)}`),
    opened: (id: string) => write<RecipientNotification>('POST', `/v2/recipient/notifications/${enc(id)}/opened`, {}, `opened-${id}`),
    respond: (id: string, response: Exclude<HumanResponse, 'none'>, note: string, key: string) =>
      write<RecipientNotification>('POST', `/v2/recipient/notifications/${enc(id)}/responses`, { response, note }, key),
  }
}

export type RecipientClient = ReturnType<typeof createRecipientClient>
