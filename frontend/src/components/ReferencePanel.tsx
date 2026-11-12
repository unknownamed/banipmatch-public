import { BLOCKER_LABEL, KIND_LABEL, display, type ReferenceView } from '../lib/reference'
import { kstDateTime } from '../lib/time'
import { LiveReference } from './LiveReference'


/**
 * #32 실제·재생·모의 자료 구분 화면. 사용자가 자료 종류를 직접 고르며, 실패해도 다른 종류로 자동 전환하지 않는다.
 * 실제 수신 결과는 인증된 /v2/references/current에서 읽는다. 과거 재생과 모의 예제는 구분한다.
 */
export function ReferencePanel() {
  return (
    <main className="timeline-view">
      <header className="page-head top">
        <div>
          <h1>터미널 일정</h1>
          <p className="muted">항차별 반입 시작·마감과 모선 접안 예정</p>
        </div>
      </header>
      <LiveReference />
    </main>
  )
}

export function ReferenceStatus({ view: v }: { view: ReferenceView }) {
  const d = display(v)
  return (
    <div className="ref-status">
      <p className={`ref-headline tone-${d.tone}`} role="status">
        <span className="badge mode-simulated">{KIND_LABEL[v.kind]}</span> {d.headline}
      </p>
      <dl className="ref-meta small">
        <div><dt>최근 시도</dt><dd>{v.last_attempt ? `${kstDateTime(v.last_attempt.at)} · ${v.last_attempt.attempts}회` : '없음'}</dd></div>
        <div><dt>최근 성공 수신</dt><dd>{v.last_success ? `${kstDateTime(v.last_success.received_at)} · ${v.last_success.row_count}행` : '없음'}</dd></div>
        <div><dt>신선도 판단 시각</dt><dd>{kstDateTime(v.checked_at)}</dd></div>
      </dl>

      {d.sample && (
        <>
          {d.sample.status === 'partial' && (
            <p className="warn small">
              부분 응답 · 제공자 표기 {d.sample.reported_count ?? '미표기'}건 · 수신 행 {d.sample.row_count}건 · 표시 가능 {d.sample.items.length}건 · 제외 {d.sample.excluded_rows}건. 표시 가능한 행만 참고로 보여줍니다.
            </p>
          )}
          {d.sample.items.length ? (
            <table className="grid small">
              <caption className="small muted">
                {d.sampleIsPrevious ? '이전 수신 표본' : '이번 조회 표본'} · 수신 {kstDateTime(d.sample.received_at)} · 시각은 원문 그대로(시간대 미확인)
              </caption>
              <thead><tr><th scope="col">항차</th><th scope="col">반입 시작</th><th scope="col">반입 마감</th><th scope="col">접안 예정(ETB)</th><th scope="col">자료</th></tr></thead>
              <tbody>
                {d.sample.items.map((it, i) => (
                  <tr key={`${it.values.VOY_NO}:${i}`}>
                    <td>{it.values.VOY_NO}</td>
                    <td>{it.values.YARD_OPEN}</td>
                    <td>{it.values.YARD_CLOSE}</td>
                    <td>{it.values.ETB}</td>
                    <td>{KIND_LABEL[it.provenance.kind]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            // 정상 0건은 status=empty일 때만. 부분 응답에서 모두 제외된 경우와 구분한다.
            <p className="small">
              {d.sample.status === 'empty'
                ? '제공자가 정상 응답으로 0건을 보냈습니다. 이전 자료를 대신 보여주지 않습니다.'
                : '받은 행이 필드 누락 등으로 모두 제외돼 표시할 행이 없습니다. 정상 0건이 아닙니다.'}
            </p>
          )}
        </>
      )}
      <details className="tech-info">
        <summary>자료 사용 조건</summary>
        {d.sample && d.sample.blockers.length > 0 && (
          <ul className="small muted ref-blockers">
            {d.sample.blockers.map((b) => <li key={b}>{BLOCKER_LABEL[b] ?? b}</li>)}
          </ul>
        )}
        <p className="small muted">
          배차 계산 입력으로 변환: {v.engine_conversion === 'blocked' ? '하지 않음' : v.engine_conversion} · 승인 근거로 사용: {v.approval_eligible ? '가능' : '불가'} · 조회 실패 시 예시 자료로 대체: {v.automatic_mock_fallback ? '있음' : '없음'}
        </p>
      </details>
    </div>
  )
}
