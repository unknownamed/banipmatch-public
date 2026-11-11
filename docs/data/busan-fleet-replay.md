# 부산 신항 AIS 형식 기반 합성 재생

실제 부산 시험에서는 구독 확인 후45초 동안 위치 메시지0건을 받았다(2026-11-11). 짧은 무수신을 부산 미지원이나 선박 부재로 단정하지 않는다. 실제 선박 위치/항차/지연 원인은 확보하지 못했다.

화면은 [AISstream 공식 문서](https://aisstream.io/documentation)와 [메시지 모델](https://github.com/aisstream/ais-message-models/blob/master/type-definition.yaml)의 `MessageType`, `MetaData`, `Message.PositionReport`, `ShipStaticData` 구조를 따른 합성 자료를 별도로 재생한다. 부산 실응답의 이동 궤적을 복제한 데이터라고 표현하지 않는다.

| 항목 | 구성 |
|---|---|
| 선박 | 가상12척, 실제 MMSI와 연결하지 않는 예시 식별자 |
| 시간 | 10분·10초 간격·61개 화면 상태 |
| 입력 메시지 | 정적11건+위치660건=671건 |
| 자료 공백 | 2척은240초 이후 위치 중단; 90초 초과 시 회색·마지막 좌표 고정 |
| 이름 누락 | 1척은 정적 이름 없이 가상 식별자로 표시 |
| 재생 | 20배속·정지·시각 이동·처음으로; 외부 API 호출 없음 |
| 지도 | Leaflet1.9.4 + OpenStreetMap. 일반 배경이며 위성/실시간 영상이 아님 |

재현: `python -m tools.build_fleet_replay`. 원시 합성 입력은 `docs/data/ais-fleet.synthetic.jsonl`, 화면 투영은 `frontend/src/fixtures/ais-fleet.synthetic.json`이다. 동일 입력의 재현성과 0개 파싱 오류·중단 후 위치 고정은 자동검사한다. 이전 2척짜리 형식/오류 사례는 덮어쓰지 않는다.

가덕도 서쪽 해상에 배치한 설명용 이동이며 항로·수심·항행 가능성을 검증한 경로가 아니다. 실제 ETA/반입마감/지연 원인을 계산하지 않으며 실제 화물차 GPS를 만들어낸 것으로 표시하지 않는다. 서버 계산용 배차는 별도 명시적 모의 입력이다. 현장 좌표·선박-항차 매핑·운송사 GPS가 추가돼야 실제 추적 및 현장 검증이 가능하다.

OSM 출처를 지도에 표시하고 [타일 이용정책](https://operations.osmfoundation.org/policies/tiles/)을 따른다. 대량 선행 다운로드·오프라인 타일 복제는 하지 않는다. 선택 가능한 기존 카카오 일반/위성 지도는 JavaScript 키와 배포 도메인 등록이 있을 때만 작동한다.
