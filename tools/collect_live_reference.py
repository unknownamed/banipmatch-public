"""Operator-only, bounded reference fetch. Secrets/raw bodies/credential URLs are never logged.

Reads only fixed provider endpoints. This is not a background scraper or a calculation input.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

from backend.references import ReferenceReader, SampleResponse
from tools.audit_kma_response import audit_response

ROOT = Path(__file__).resolve().parents[1]
KMA = 'https://apihub.kma.go.kr/api/typ01/url/'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url):
    try:
        with build_opener(NoRedirect).open(Request(url, headers={'User-Agent': 'BanipmatchStudentReference/1.0'}), timeout=15) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                return 502, b''
            return response.status, raw
    except HTTPError as e:
        return e.code, b''  # 제공기관이 보낸 오류 코드
    except Exception:
        return 0, b''  # 우리 쪽 연결 실패·시간 초과(제공기관 응답 없음)


def collect(key: str | None, transport=fetch, *, ors_key=None, ors_transport=None):
    result = {'schema_version': 'reference-display-1', 'kind': 'reference', 'checked_at': now(),
              'engine_conversion': 'blocked', 'approval_eligible': False,
              'automatic_mock_fallback': False, 'weather': []}
    today = datetime.now(timezone(timedelta(hours=9))).date()
    query = urlencode(dict(startDate=str(today), endDate=str(today + timedelta(days=7)),
                           sort='ETB', dateType='', route='', oper='', amount=100, page=1))
    status, raw = transport('https://www.hjnc.co.kr/esvc/vessel/berthScheduleT/data?' + query)
    reader = ReferenceReader('hjnc', kind='reference', sample_permission_ref='public-schedule-manual-student-reference')
    result['hjnc'] = reader.ingest(SampleResponse(raw, now(), status or 503))
    for kind, resource, args in (
            ('sea', 'sea_obs.php', {'stn': '22104', 'help': '1'}),
            ('warning', 'wrn_now_data.php', {'fe': 'f', 'help': '1'})):
        item = {'source': '기상청 API허브', 'kind': kind, 'source_ref': 'https://apihub.kma.go.kr/apiList.do',
                'status': 'key_missing', 'received_at': None, 'http_status': None, 'report': None}
        if key:
            status, raw = transport(KMA + resource + '?' + urlencode({**args, 'authKey': key}))
            # 0은 응답을 받지 못함(연결 실패·시간 초과), 그 밖의 오류 코드는 기상청이 보낸 응답이다.
            item.update(http_status=status or None, received_at=now(),
                        failure='network' if status == 0 else 'provider' if status >= 400 else None)
            try:
                report = audit_response(raw, kind, status or 503, item['received_at'], station='22104',
                    regions=('L1080600', 'L1082700', 'S1311000', 'S1311100', 'S1311110', 'S1311120'))
                item.update(status=report['status'], report=report)
            except Exception:
                item['status'] = 'parse_error'
        result['weather'].append(item)
    from backend.references.ors import collect_ors
    result['road'] = collect_ors(ors_key, **({'transport': ors_transport} if ors_transport else {}))
    result['checked_at'] = now()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kma-key-file', type=Path)
    parser.add_argument('--ors-key-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ais-report', type=Path)
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        if not output.is_relative_to((ROOT / 'local').resolve()):
            raise ValueError('local output only')
        key = args.kma_key_file.read_text(encoding='utf-8-sig').strip() if args.kma_key_file else None
        ors_key = args.ors_key_file.read_text(encoding='utf-8-sig').strip() if args.ors_key_file else None
        ais = None
        if args.ais_report:
            from backend.references.display import AisStatus
            ais = AisStatus.model_validate_json(args.ais_report.read_bytes()).model_dump()
        result = collect(key, ors_key=ors_key)
        if ais is not None:
            result['ais'] = ais
        if any(secret and secret in json.dumps(result, ensure_ascii=False) for secret in (key, ors_key)):
            raise ValueError('credential reflection refused')
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.pending')
        temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(output)
        print(json.dumps({'hjnc': result['hjnc']['last_attempt']['status'],
                          'road': {'status': result['road']['status'], 'http_status': result['road']['http_status']},
                          'weather': [{'kind': x['kind'], 'status': x['status'], 'http_status': x['http_status']} for x in result['weather']]}, ensure_ascii=False))
        return 0
    except Exception:
        print('Reference collection setup failed; no credentials or response bodies printed.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
