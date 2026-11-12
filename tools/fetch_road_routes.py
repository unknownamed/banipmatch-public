"""예제 02 위치 사이의 실제 도로 경로(OSRM 공개 서버, OpenStreetMap 자료)를 한 번 받아 저장한다.

화면에서 차량 위치를 직선이 아닌 도로를 따라 그리기 위한 표시용 경로다. 배차 계산(이동시간)에는 쓰지 않는다.
자료: © OpenStreetMap contributors (ODbL), 경로 계산: OSRM.
사용: python tools/fetch_road_routes.py  (frontend/src/fixtures/road-routes.osm.json 갱신)
"""
from __future__ import annotations

import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend/src/fixtures/demo-02-evening.synthetic.json"
OUT = ROOT / "frontend/src/fixtures/road-routes.osm.json"


def main():
    snap = json.loads(SRC.read_text(encoding="utf-8"))
    loc = {l["location_id"]: (l["latitude"], l["longitude"]) for l in snap["locations"]}
    depot = [k for k, l in ((l["location_id"], l) for l in snap["locations"]) if l["kind"] == "depot"]
    origins = [l["location_id"] for l in snap["locations"] if l["kind"] == "origin"]
    gates = [l["location_id"] for l in snap["locations"] if l["kind"] == "terminal"]
    pairs = [(d, o) for d in depot for o in origins] + [(o, g) for o in origins for g in gates] + [(g, d) for g in gates for d in depot]
    routes = {}
    for a, b in pairs:
        (la, lo), (lb, lob) = loc[a], loc[b]
        url = f"https://router.project-osrm.org/route/v1/driving/{lo},{la};{lob},{lb}?overview=full&geometries=geojson"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "route-sample-script"}), timeout=20) as r:
            data = json.load(r)
        coords = data["routes"][0]["geometry"]["coordinates"]
        # 화면 표시에 충분하도록 점을 줄인다(약 40m 이내 점 생략).
        kept, last = [], None
        for x, y in coords:
            if last is None or abs(x - last[0]) + abs(y - last[1]) > 0.0004:
                kept.append([round(y, 5), round(x, 5)])
                last = (x, y)
        if kept[-1] != [round(coords[-1][1], 5), round(coords[-1][0], 5)]:
            kept.append([round(coords[-1][1], 5), round(coords[-1][0], 5)])
        routes[f"{a}>{b}"] = {"km": round(data["routes"][0]["distance"] / 1000, 1), "path": kept}
        print(a, b, routes[f"{a}>{b}"]["km"], "km", len(kept), "pts")
        time.sleep(1.1)  # 공개 서버 이용 정책: 초당 1회 이하
    OUT.write_text(json.dumps({"attribution": "© OpenStreetMap contributors · 경로: OSRM", "note": "표시용 도로 경로. 배차 계산에는 쓰지 않는다.", "routes": routes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
