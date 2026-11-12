"""Bounded ORS Matrix reference fetch; never changes dispatch input or logs a key."""
from datetime import datetime, timezone
import json
import math
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = 'https://api.heigit.org/openrouteservice/v2/matrix/driving-hgv'
POINTS = (
    ('부산신항 부두 부근(근사)', 128.8180, 35.0760),
    ('녹산산업단지 부근(근사)', 128.8600, 35.0900),
    ('부산 사상 부근(근사)', 128.9800, 35.1520),
)
MAX_BYTES = 1_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_matrix(key, payload):
    request = Request(ENDPOINT, data=json.dumps(payload).encode('utf-8'),
                      headers={'Authorization': key, 'Content-Type': 'application/json',
                               'User-Agent': 'BanipmatchStudentReference/1.0'})
    try:
        with build_opener(NoRedirect).open(request, timeout=15) as response:
            body = response.read(MAX_BYTES + 1)
            return response.status, body, response.headers.get('Retry-After')
    except HTTPError as exc:
        # Provider errors can echo headers; never retain their bodies or exception text.
        return exc.code, b'', exc.headers.get('Retry-After')
    except Exception:
        return 503, b'', None


def _number(value):
    if value is None:
        return None
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError('invalid metric')
    return float(value)


def collect_ors(key, transport=request_matrix):
    result = dict(source='openrouteservice', kind='reference', profile='driving-hgv',
                  status='key_missing', received_at=None, http_status=None,
                  retry_after_seconds=None, points=[], cells=[],
                  engine_conversion='blocked', approval_eligible=False,
                  automatic_mock_fallback=False, coordinates_are_approximate=True,
                  realtime_traffic=False, truck_access_verified=False)
    if not key:
        return result
    payload = {'locations': [[lon, lat] for _, lon, lat in POINTS],
               'metrics': ['duration', 'distance'], 'units': 'm'}
    try:
        status, body, retry_after = transport(key, payload)
    except Exception:
        status, body, retry_after = 503, b'', None
    result.update(http_status=status, received_at=datetime.now(timezone.utc).isoformat())
    if status != 200:
        result['status'] = ('auth_error' if status in (401, 403) else
                            'rate_limited' if status == 429 else 'http_error')
        if status == 429 and isinstance(retry_after, str) and retry_after.isascii() and retry_after.isdecimal():
            result['retry_after_seconds'] = min(int(retry_after[:9]), 86400)
        return result
    try:
        if not isinstance(body, bytes) or len(body) > MAX_BYTES or key.encode() in body:
            raise ValueError('invalid response')
        raw = json.loads(body)
        matrices = [raw['durations'], raw['distances']]
        n = len(POINTS)
        for matrix in matrices:
            if not isinstance(matrix, list) or len(matrix) != n:
                raise ValueError('invalid matrix shape')
            for row in matrix:
                if not isinstance(row, list) or len(row) != n:
                    raise ValueError('invalid matrix shape')
                for cell in row:
                    _number(cell)
        # Retain source/destination snap distances separately; missing is not zero.
        sources, destinations = raw['sources'], raw['destinations']
        if len(sources) != n or len(destinations) != n:
            raise ValueError('invalid locations')
        points = [dict(label=label, longitude=lon, latitude=lat,
                       source_snap_m=_number(sources[i].get('snapped_distance')),
                       destination_snap_m=_number(destinations[i].get('snapped_distance')))
                  for i, (label, lon, lat) in enumerate(POINTS)]
        cells = [dict(origin=i, destination=j, duration_seconds=_number(matrices[0][i][j]),
                      distance_meters=_number(matrices[1][i][j]))
                 for i in range(n) for j in range(n)]
        result.update(points=points, cells=cells,
                      status='partial' if any(c['duration_seconds'] is None or c['distance_meters'] is None
                                              for c in cells) else 'received')
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        result['status'] = 'invalid_response'
    return result
