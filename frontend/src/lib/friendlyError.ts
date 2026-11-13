// 서버 오류 코드를 담당자·기사가 바로 알아듣는 안내로 바꾼다. 서버의 개발용 설명 문장은 화면에 그대로 보이지 않게 한다.
import { ApiRequestError } from '../api/client'

const MESSAGE: Record<string, string> = {
  RECIPIENT_LIMIT: '연결할 수 있는 기사 수를 넘었습니다. 쓰지 않는 연결을 해제한 뒤 다시 해 주세요.',
  RECIPIENT_ALREADY_LINKED: '이 차량에는 이미 연결된 휴대폰이 있습니다. 연결 해제 후 다시 해 주세요.',
  RECIPIENT_REQUIRED: '연결이 끊겼거나 링크가 올바르지 않습니다. 담당자에게 새 링크를 요청하세요.',
  RECIPIENT_UNLINKED: '연결되지 않은 차량이 있습니다. 연결 상태를 먼저 확인하세요.',
  RECIPIENT_CHANGED: '그사이 연결된 휴대폰이 바뀌었습니다. 새로고침 후 다시 확인하세요.',
  INVITATION_USED: '이미 사용한 링크입니다. 담당자에게 새 링크를 요청하세요.',
  INVITATION_EXPIRED: '링크 유효 시간(30분)이 지났습니다. 담당자에게 새 링크를 요청하세요.',
  SESSION_REQUIRED: '작업 시간이 지났습니다. 새로고침해 처음부터 다시 시작해 주세요.',
  SESSION_EXPIRED: '작업 시간이 지났습니다. 새로고침해 처음부터 다시 시작해 주세요.',
  CSRF_FAILED: '화면이 오래되었습니다. 새로고침 후 다시 시도해 주세요.',
  PUSH_TEST_NOT_AUTHORIZED: '알림 사용 코드로 알림 기능을 먼저 켜 주세요.',
  TEAM_CODE_INVALID: '코드가 맞지 않습니다.',
  RATE_LIMITED: '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
  QUEUE_FULL: '처리 중인 작업이 많습니다. 잠시 후 다시 시도해 주세요.',
  PUSH_RATE_LIMITED: '알림을 잠시 보낼 수 없습니다. 1분 뒤 다시 보내 주세요.',
  DISPATCH_LIMIT: '이 작업에서 보낼 수 있는 알림 횟수를 넘었습니다. 새로 점검해 주세요.',
  DELIVERY_UNCERTAIN: '이미 전달됐을 수 있어 다시 보내지 않았습니다. 기사 응답을 먼저 확인하세요.',
  DELIVERY_NOT_RETRYABLE: '지금은 다시 보낼 수 없는 상태입니다.',
  NOTIFICATION_SUPERSEDED: '새 배차가 나와 이전 알림에는 응답할 수 없습니다.',
  SUBSCRIPTION_INVALID: '이 브라우저의 알림은 연결할 수 없습니다. Chrome이나 Safari(아이폰은 홈 화면 앱)로 다시 열어 주세요.',
  SUBSCRIPTION_REQUIRED: '알림이 꺼져 있습니다. 알림 허용을 눌러 주세요.',
  SUBSCRIPTION_ALREADY_LINKED: '이 휴대폰은 다른 차량에 연결돼 있습니다. 그 연결을 해제한 뒤 다시 해 주세요.',
  PLAN_VERSION_CONFLICT: '그사이 배차가 바뀌었습니다. 새로고침 후 다시 확인해 주세요.',
  LOCATION_STALE: '위치를 다시 확인하지 못했습니다. 잠시 후 다시 보냅니다.',
  INVALID_LOCATION: '위치를 다시 확인하지 못했습니다. 잠시 후 다시 보냅니다.',
  RESPONSE_LIMIT: '이 알림에는 응답을 더 남길 수 없습니다.',
  RESPONSE_TRANSITION: '수행 가능 또는 수행 곤란 중 하나로 답해 주세요.',
}

export function friendlyError(e: unknown): string {
  if (e instanceof ApiRequestError) {
    const code = e.body?.code
    if (code && MESSAGE[code]) return MESSAGE[code]
    return '처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'
  }
  if (e instanceof TypeError) return '서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.'
  return e instanceof Error && /[가-힣]/.test(e.message) ? e.message : '처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'
}
