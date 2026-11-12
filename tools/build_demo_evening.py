"""시연용 예제 02 '신항 저녁 배차'(모의) 입력을 만든다.

운송사 한 곳의 저녁 배차 규모(트럭 6대·작업 16건·항차 3개·상차지 5곳)를 흉내 낸 모의 자료다.
원래 배차표(baseline)는 변경 전 반입 마감 기준으로 엔진과 같은 일정 규칙
(출발 = max(이전 복귀+이동, 준비, 반입 시작-운송), 도착+여유 ≤ 마감, 복귀 ≤ 근무 종료)으로 계산한다.
V1 반입 마감이 2시간 앞당겨진 확정 변경 뒤, 일부 작업이 마감을 넘기도록 구성했다.
이동시간은 실제 측정값이 아닌 가정값이며 좌표는 화면 표시용 근사 위치다.

사용: python tools/build_demo_evening.py  (frontend/src/fixtures/demo-02-evening.synthetic.json 갱신)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/src/fixtures/demo-02-evening.synthetic.json"
T0 = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)  # 19:00 KST. 화면에서 현재 시각으로 옮긴다.
REF = "fixture:demo_02_evening"
BUFFER = 10


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ev(kind="simulated", ref=REF):
    return dict(kind=kind, source_ref=ref, observed_at=None, received_at=at(0))


LOCATIONS = [
    ("D", "녹산 차고지(모의)", "depot", 35.0890, 128.8600),
    ("O1", "녹산산단 상차지(모의)", "origin", 35.0950, 128.8530),
    ("O2", "사상 공단 상차지(모의)", "origin", 35.1530, 128.9790),
    ("O3", "웅동 물류단지(모의)", "origin", 35.1160, 128.7660),
    ("O4", "김해 안동공단(모의)", "origin", 35.2300, 128.8790),
    ("O5", "장유 상차지(모의)", "origin", 35.1950, 128.8020),
    ("HJNC", "HJNC 게이트(모의)", "terminal", 35.0814, 128.7843),
    ("PNIT", "PNIT 게이트(모의)", "terminal", 35.0818, 128.8337),
]
# 화물차 기준 가정 이동시간(분). 대칭으로 쓴다.
PAIRS = {
    ("D", "O1"): 8, ("D", "O2"): 35, ("D", "O3"): 20, ("D", "O4"): 35, ("D", "O5"): 25, ("D", "HJNC"): 18,
    ("O1", "O2"): 32, ("O1", "O3"): 18, ("O1", "O4"): 33, ("O1", "O5"): 22, ("O1", "HJNC"): 15,
    ("O2", "O3"): 45, ("O2", "O4"): 30, ("O2", "O5"): 35, ("O2", "HJNC"): 40,
    ("O3", "O4"): 40, ("O3", "O5"): 20, ("O3", "HJNC"): 15,
    ("O4", "O5"): 22, ("O4", "HJNC"): 45, ("O5", "HJNC"): 30,
    ("D", "PNIT"): 10, ("O1", "PNIT"): 8, ("O2", "PNIT"): 33, ("O3", "PNIT"): 25, ("O4", "PNIT"): 40, ("O5", "PNIT"): 32, ("HJNC", "PNIT"): 15,
}


def travel(a: str, b: str) -> int:
    return 0 if a == b else PAIRS.get((a, b)) or PAIRS[(b, a)]


# 항차별 반입 마감(분, T0 기준). V1(BH045E)은 변경 전 +240 → 변경 후 +90(2시간 30분 앞당김).
# 반입 마감은 모선 접안 12시간 전(PNC 공지의 '접안 12시간 전 이후 반입 금지' 규칙을 모의 규칙으로 사용),
# 반입 시작은 접안 72시간 전으로 둔다(터미널은 보통 며칠 전부터 반입을 받는다. 예: HPNT 선적 5일 전, 2021).
# 둘 다 터미널·선사마다 다르므로 모의 가정값이다.
CLOSES = {"V1": 90, "V2": 330, "V4": 480, "V7": 300}
V1_PREVIOUS_CLOSE = 240
_OPEN_BEFORE_CLOSE = 72 * 60 - 12 * 60  # 접안 72시간 전 시작 = 마감 60시간 전
WINDOWS = {v: ((V1_PREVIOUS_CLOSE if v == "V1" else c) - _OPEN_BEFORE_CLOSE, c) for v, c in CLOSES.items()}
TERMINAL = {"V1": "HJNC", "V2": "HJNC", "V4": "HJNC", "V7": "PNIT"}

VEHICLES = [  # id, 가용 시작, 장비
    ("T1", -60, ["DRY20", "DRY40"]),
    ("T2", -60, ["DRY20", "DRY40"]),
    ("T3", 0, ["DRY20", "DRY40"]),
    ("T4", 0, ["DRY20"]),
    ("T5", 30, ["DRY20", "DRY40"]),
    ("T6", 60, ["DRY20", "DRY40"]),
    ("T7", 0, ["DRY20", "DRY40"]),
    ("T8", 20, ["DRY20", "DRY40"]),
]
SHIFT_END = 540

# id, 항차, 상차지, 준비(분), 중량, 장비, 상태
JOBS = [
    ("J01", "V1", "O1", -40, 24000, "DRY40", "departed"),
    ("J02", "V1", "O3", -30, 18000, "DRY20", "departed"),
    ("J03", "V1", "O1", 10, 22000, "DRY40", "planned"),
    ("J04", "V1", "O2", 0, 26000, "DRY40", "planned"),
    ("J05", "V1", "O3", 20, 14000, "DRY20", "planned"),
    ("J06", "V1", "O5", 15, 23000, "DRY40", "planned"),
    ("J07", "V1", "O1", 40, 12000, "DRY20", "planned"),
    ("J08", "V1", "O2", 60, 25000, "DRY40", "planned"),
    ("J09", "V2", "O4", 0, 21000, "DRY40", "planned"),
    ("J10", "V2", "O2", 30, 24000, "DRY40", "planned"),
    ("J11", "V2", "O5", 60, 15000, "DRY20", "planned"),
    ("J12", "V2", "O1", 20, 20000, "DRY40", "planned"),
    ("J13", "V2", "O3", 90, 13000, "DRY20", "planned"),
    ("J14", "V4", "O4", 120, 22000, "DRY40", "planned"),
    ("J15", "V4", "O2", 150, 26000, "DRY40", "planned"),
    ("J16", "V4", "O5", 100, 16000, "DRY20", "planned"),
    # 같은 날 PNIT로 가는 다른 항차(반입 시간 변경 없음) — 영향받지 않는 작업이 섞여 있는 실제 배차표를 흉내 낸다
    ("J17", "V7", "O1", 10, 21000, "DRY40", "planned"),
    ("J18", "V7", "O4", 30, 19000, "DRY40", "planned"),
    ("J19", "V7", "O2", 60, 23000, "DRY40", "planned"),
    ("J20", "V7", "O5", 80, 14000, "DRY20", "planned"),
]
# 터미널 체류(게이트 진입·하차·출문) 가정값. 부산신항 체류시간은 혼잡도에 따라 크게 달라 실측 대신 30분으로 둔다.
SERVICE = 30

# 현장에서 쓰는 식별 정보(모두 가상). 항차는 '선박 약어+항차 번호+방향' 형식, 선박은 서비스 이름을 딴 가상 선단.
VOYAGE_CODE = {"V1": "BH045E", "V2": "BO112W", "V4": "BP007E", "V7": "BE221E"}
SHIPPER = {"O1": "가람정밀(주)", "O2": "다온물산(주)", "O3": "한결산업(주)", "O4": "누리화학(주)", "O5": "새벽식품(주)"}
PLATE = {"T1": "부산 90바 1201", "T2": "부산 90바 1207", "T3": "부산 91사 3315", "T4": "경남 87아 2044", "T5": "부산 92바 5520", "T6": "경남 88자 7136", "T7": "부산 93바 4408", "T8": "경남 86사 6620"}


def iso6346(owner: str, serial: int) -> str:
    """ISO 6346 확인 숫자를 붙인 컨테이너 번호(소유자 코드는 가상)."""
    values = {c: v for c, v in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 35, 36, 37, 38])}
    code = owner + f"{serial:06d}"
    total = sum((values[c] if c.isalpha() else int(c)) * (2 ** i) for i, c in enumerate(code))
    return code + str(total % 11 % 10)
# 변경 전 마감 기준으로 짠 원래 배차(준비 순·근거리 위주, V1 우선 고려 없음)
BASELINE = {
    "T1": ["J01", "J09", "J14"],
    "T2": ["J02", "J12", "J16"],
    "T3": ["J04", "J10", "J15"],
    "T4": ["J05", "J11", "J13"],
    "T5": ["J06", "J07"],
    "T6": ["J03", "J08"],
    "T7": ["J17", "J19"],
    "T8": ["J18", "J20"],
}
DEPARTED = {"J01": -15, "J02": -10}  # 이미 출발한 작업의 실제 출발(분)


def departed_return(jid: str) -> int:
    _, voy, origin, *_ = next(j for j in JOBS if j[0] == jid)
    gate = TERMINAL[voy]
    return DEPARTED[jid] + travel(origin, gate) + BUFFER + SERVICE + travel(gate, "D")


# 출발한 작업을 수행 중인 차량은 그 작업 복귀 뒤에 다음 작업이 가능하다(예제 01과 같은 규칙).
AVAILABLE = {v: a for v, a, _ in VEHICLES}
for vid, route in BASELINE.items():
    if route[0] in DEPARTED:
        AVAILABLE[vid] = departed_return(route[0])


def build():
    jobs = {j[0]: j for j in JOBS}
    assignments = []
    for vid, route in BASELINE.items():
        cursor, location = next(v for v in VEHICLES if v[0] == vid)[1], "D"
        for seq, jid in enumerate(route, 1):
            _, voy, origin, ready, *_ = jobs[jid]
            opens, closes = WINDOWS[voy]
            if voy == "V1":
                closes = V1_PREVIOUS_CLOSE
            gate = TERMINAL[voy]
            loaded = travel(origin, gate)
            if jid in DEPARTED:
                dep = DEPARTED[jid]
            else:
                dep = max(cursor + travel(location, origin), ready, opens - loaded)
            arr = dep + loaded
            back = arr + BUFFER + SERVICE + travel(gate, "D")
            assert arr + BUFFER <= closes and back <= SHIFT_END, (jid, arr, closes, back)
            assignments.append(dict(job_id=jid, vehicle_id=vid, sequence=seq, pickup_departure_at=at(dep),
                                    gate_arrival_at=at(arr), return_at=at(back)))
            cursor, location = back, "D"
    snapshot = dict(
        schema_version="0.1.0", scenario_id="S002", plan_id="P002", base_plan_version=1, data_mode="simulated", as_of=at(0),
        locations=[dict(location_id=i, name=n, kind=k, latitude=la, longitude=lo, evidence=ev()) for i, n, k, la, lo in LOCATIONS],
        vehicles=[dict(vehicle_id=v, start_location_id="D", available_at=at(AVAILABLE[v]), shift_end_at=at(SHIFT_END), capacity_kg=30000,
                       equipment_types=eq, evidence=ev(), plate_no=PLATE[v]) for v, a, eq in VEHICLES],
        jobs=[dict(job_id=j, voyage_id=VOYAGE_CODE[voy], origin_id=o, terminal_id=TERMINAL[voy], return_location_id="D", ready_at=at(r),
                   gross_weight_kg=w, equipment_type=e, service_minutes=SERVICE, state=st, frozen=st == "departed",
                   freeze_reason="ALREADY_DEPARTED" if st == "departed" else None, evidence=ev(),
                   container_no=iso6346("BNJU", 100200 + int(j[1:])), booking_no=f"BKG{VOYAGE_CODE[voy]}{int(j[1:]):03d}",
                   cargo_owner=SHIPPER[o]) for j, voy, o, r, w, e, st in JOBS],
        windows=[dict(window_id=f"W-{VOYAGE_CODE[voy]}", voyage_id=VOYAGE_CODE[voy], terminal_id=TERMINAL[voy], opens_at=at(o), closes_at=at(c), verification="confirmed",
                      confirmed_by="demo-dispatcher", confirmed_at=at(-5), evidence=ev()) for voy, (o, c) in WINDOWS.items()],
        travel_times=[dict(from_location_id=a, to_location_id=b, minutes=travel(a, b), evidence=ev("assumed", "fixture:demo_02_travel"))
                      for a, *_ in LOCATIONS for b, *_ in LOCATIONS],
        baseline_assignments=assignments,
        change=dict(change_id="C002", voyage_id=VOYAGE_CODE["V1"], terminal_id="HJNC", previous_opens_at=at(WINDOWS["V1"][0]),
                    previous_closes_at=at(V1_PREVIOUS_CLOSE), new_window_id=f"W-{VOYAGE_CODE['V1']}", verification="confirmed",
                    confirmed_by="demo-dispatcher", confirmed_at=at(-5), evidence=ev()),
        policy=dict(buffer_minutes=BUFFER, time_change_tolerance_minutes=5, input_valid_until=at(180),
                    allow_wait_before_open=False, external_actions_enabled=False),
        baseline_unassigned_job_ids=[],
    )
    return snapshot


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: jobs={len(data['jobs'])} vehicles={len(data['vehicles'])}")
