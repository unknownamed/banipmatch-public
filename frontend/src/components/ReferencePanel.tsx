import { useState } from 'react'
import fixture from '../fixtures/reference-preview.synthetic.json'
import { BLOCKER_LABEL, KIND_LABEL, display, type ReferenceView } from '../lib/reference'
import { kstDateTime } from '../lib/time'
import { LiveReference } from './LiveReference'

type Source = 'live' | 'replay' | 'mock'
const cases = fixture.cases as unknown as { id: string; label: string; view: ReferenceView }[]

/**
 * #32 실제·재생·모의 자료 구분 화면. 사용자가 자료 종류를 직접 고르며, 실패해도 다른 종류로 자동 전환하지 않는다.
 * 실제 수신 결과는 인증된 /v2/references/current에서 읽는다. 과거 재생과 모의 예제는 구분한다.
 */
export function ReferencePanel() {
  const [source, setSource] = useState<Source>('live')
  const [caseId, setCaseId] = useState(cases[0].id)
  const picked = cases.find((c) => c.id === caseId)!

  return (
    <main>
      <section className="card reference" aria-labelledby="ref-title">
        <h2 id="ref-title">실제 자료 수신 현황</h2>
        <p className="small muted">
          외부 기관에서 받은 최신 자료입니다. 배차 계산에는 확정된 반입 시간만 쓰고, 이 자료는 판단을 돕는 참고 정보로 보여 줍니다.
        </p>
        <div className="tabs" role="radiogroup" aria-label="자료 종류">
          {([['live', '최근 수신'], ['mock', '상태별 예시']] as const).map(([id, label]) => (
            <button key={id} type="button" role="radio" aria-checked={source === id} aria-selected={source === id} onClick={() => setSource(id)}>{label}</button>
          ))}
        </div>

        {source === 'live' ? <LiveReference /> : source !== 'mock' ? (
          <p className="warn small" role="status">
            과거 저장 자료 재생은 아직 연결되지 않았습니다. 마지막 실제 수신 자료는 첫 번째 탭에서 확인할 수 있습니다. 모의 자료로 대신 채우지 않습니다.
          </p>
        ) : (
          <>
            <p className="small muted" role="note">정상·부분 응답·조회 실패 같은 상황에서 화면이 어떻게 보이는지 보여 주는 예시입니다(실제 수신 아님).</p>
            <label className="small">
              모의 상태{' '}
              <select value={caseId} onChange={(e) => setCaseId(e.target.value)}>
                {cases.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </label>
            <ReferenceStatus view={picked.view} />
          </>
        )}
      </section>
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
