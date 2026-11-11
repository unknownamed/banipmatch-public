// 수신자 화면 모의 연결(?demo=1). 서버·네트워크·푸시를 쓰지 않고 이 탭의 메모리에서만 동작한다.
// 화면 확인·발표 캡처용이며 실제 수신·응답 기록이 아니다. 초대 수락만 하면 바로 연결된 상태가 된다.
import type { RecipientClient, RecipientNotification, RecipientSession } from './recipient'

const at = (minutes: number) => new Date(Date.UTC(2026, 10, 11, 4, 0) + minutes * 60000).toISOString().replace('.000Z', 'Z')

export function createDemoRecipientClient(): RecipientClient {
  let session: RecipientSession | null = null
  const notifications: RecipientNotification[] = [
    {
      notification_id: 'N-DEMO-2', delivery_status: 'accepted', created_at: at(35), opened_at: null, response: 'none', responded_at: null,
      is_current: true, vehicle_ids: ['T1'], response_history: [],
      payload: {
        plan_version: 2, data_mode: 'simulated',
        vehicle_changes: [{
          vehicle_id: 'T1',
          changes: [
            { job_id: 'J1', kind: 'reassigned', before: { vehicle_id: 'T1', pickup_departure_at: at(102), gate_arrival_at: at(132) }, after: null, after_outside_scope: true, instruction: '담당자가 확정한 모의 변경 내용입니다. 수행 가능 여부를 응답하세요. 실제 운송/예약 변경을 뜻하지 않습니다.' },
            { job_id: 'J2', kind: 'reassigned', before: null, before_outside_scope: true, after: { vehicle_id: 'T1', pickup_departure_at: at(102), gate_arrival_at: at(132) }, instruction: '담당자가 확정한 모의 변경 내용입니다. 수행 가능 여부를 응답하세요. 실제 운송/예약 변경을 뜻하지 않습니다.' },
          ],
        }],
      },
    },
    {
      notification_id: 'N-DEMO-1', delivery_status: 'superseded', created_at: at(10), opened_at: at(12), response: 'none', responded_at: null,
      is_current: false, vehicle_ids: ['T1'], response_history: [], payload: null,
    },
  ]
  const find = (id: string) => {
    const n = notifications.find((x) => x.notification_id === id)
    if (!n) throw new Error('모의 알림 없음')
    return n
  }
  const copy = <T,>(v: T): T => structuredClone(v)

  return {
    restore: async () => {
      if (!session) throw new Error('모의: 아직 연결 전')
      return copy(session)
    },
    claim: async () => (session = { recipient_id: 'demo-recipient', vehicle_ids: ['T1'], expires_at: at(24 * 60), csrf_token: 'demo', subscription_status: 'missing', data_mode: 'simulated' }),
    leave: async () => ((session = null), { revoked: true }),
    pushConfig: async () => ({ configured: false, application_server_key: null }),
    subscribe: async () => ({ subscription_status: 'missing' }),
    unsubscribe: async () => ({ subscription_status: 'missing' }),
    inbox: async () => ({ notifications: copy(notifications) }),
    notification: async (id) => copy(find(id)),
    opened: async (id) => {
      const n = find(id)
      n.opened_at ??= new Date().toISOString()
      return copy(n)
    },
    respond: async (id, response, note) => {
      const n = find(id)
      if (!n.is_current) throw new Error('이전 계획에는 응답할 수 없습니다(모의).')
      const now = new Date().toISOString()
      Object.assign(n, { response, responded_at: now })
      n.response_history.push({ response, note, created_at: now })
      return copy(n)
    },
  }
}
