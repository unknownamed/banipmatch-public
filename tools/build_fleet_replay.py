"""Reproducible AISstream-shaped synthetic Busan replay, never actual vessel tracks."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from tools.demo_aisstream import BASE, Replay, position, static_event, utc, SOURCE, MODEL_SOURCE


def build():
    replay = Replay(fresh_for_seconds=90)
    frames, wire = [], []
    for second in range(0, 601, 10):
        for index in range(12):
            mmsi = 999001001 + index  # Fictional IDs, not reserved/real vessel identities.
            if second == 0 and index != 7:
                static = static_event(999000001)
                static['MetaData'].update(MMSI=mmsi, ShipName=f'SIM-BUSAN-{index+1:02}')
                static['Message']['ShipStaticData'].update(UserID=mmsi, Name=f'SIM-BUSAN-{index+1:02}')
                wire.append({'offset_seconds': second, 'event': static})
                replay.consume(static, utc(BASE))
            if index in (3, 9) and second > 240:
                continue  # Deliberate loss of positional updates; never animate stale data onward.
            event = position(999000001, second)
            body = event['Message']['PositionReport']
            # Keep the display lanes offshore west of Gadeok; not surveyed navigation routes.
            lat = round(35.04 + (index // 4) * .004 + (body['Latitude']-35.035), 6)
            lon = round(128.74 + (index % 4) * .006 + (body['Longitude']-128.745), 6)
            body.update(UserID=mmsi, Latitude=lat, Longitude=lon)
            event['MetaData'].update(MMSI=mmsi, ShipName='' if index == 7 else f'SIM-BUSAN-{index+1:02}', Latitude=lat, Longitude=lon)
            wire.append({'offset_seconds': second, 'event': event})
            replay.consume(event, utc(BASE+timedelta(seconds=second)))
        view = replay.view(BASE+timedelta(seconds=second))
        for ship in view['ships']: ship.pop('track', None)
        frames.append({'second': second, **view})
    return {'kind': 'simulated', 'format_source': SOURCE, 'model_source': MODEL_SOURCE,
            'note': '실제 선박/예약/항로가 아닌 공급자 형식 기반 합성 재생. 직선은 항행 가능한 항로 검증이 아님.',
            'vessel_count': 12, 'duration_seconds': 600, 'wire_event_count': len(wire), 'frames': frames}, wire


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    view, wire = build()
    (root/'frontend/src/fixtures/ais-fleet.synthetic.json').write_text(json.dumps(view, ensure_ascii=False, separators=(',',':'))+'\n', encoding='utf-8')
    out = root/'docs/data/ais-fleet.synthetic.jsonl'
    out.write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in wire), encoding='utf-8')
    print(f'Synthetic only: {view["vessel_count"]} vessels, {len(view["frames"])} frames, {len(wire)} wire events')
