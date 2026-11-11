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
        return e.code, b''
    except Exception:
        return 503, b''


def collect(key: str | None, transport=fetch):
    result = {'schema_version': 'reference-display-1', 'kind': 'reference', 'checked_at': now(),
              'engine_conversion': 'blocked', 'approval_eligible': False,
              'automatic_mock_fallback': False, 'weather': []}
    today = datetime.now(timezone(timedelta(hours=9))).date()
    query = urlencode(dict(startDate=str(today), endDate=str(today + timedelta(days=7)),
                           sort='ETB', dateType='', route='', oper='', amount=100, page=1))
    status, raw = transport('https://www.hjnc.co.kr/esvc/vessel/berthScheduleT/data?' + query)
    reader = ReferenceReader('hjnc', kind='reference', sample_permission_ref='public-schedule-manual-student-reference')
    result['hjnc'] = reader.ingest(SampleResponse(raw, now(), status))
    for kind, resource, args in (
            ('sea', 'sea_obs.php', {'stn': '22104', 'help': '1'}),
            ('warning', 'wrn_now_data.php', {'fe': 'f', 'help': '1'})):
        item = {'source': '기상청 API허브', 'kind': kind, 'source_ref': 'https://apihub.kma.go.kr/apiList.do',
                'status': 'key_missing', 'received_at': None, 'http_status': None, 'report': None}
        if key:
            status, raw = transport(KMA + resource + '?' + urlencode({**args, 'authKey': key}))
            item.update(http_status=status, received_at=now())
            try:
                report = audit_response(raw, kind, status, item['received_at'], station='22104',
                    regions=('L1080600', 'L1082700', 'S1311000', 'S1311100', 'S1311110', 'S1311120'))
                item.update(status=report['status'], report=report)
            except Exception:
                item['status'] = 'parse_error'
        result['weather'].append(item)
    result['checked_at'] = now()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kma-key-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ais-report', type=Path)
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        if not output.is_relative_to((ROOT / 'local').resolve()):
            raise ValueError('local output only')
        key = args.kma_key_file.read_text(encoding='utf-8-sig').strip() if args.kma_key_file else None
        result = collect(key)
        if args.ais_report:
            from backend.references.display import AisStatus
            result['ais'] = AisStatus.model_validate_json(args.ais_report.read_bytes()).model_dump()
        if key and key in json.dumps(result, ensure_ascii=False):
            raise ValueError('credential reflection refused')
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.pending')
        temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(output)
        print(json.dumps({'hjnc': result['hjnc']['last_attempt']['status'],
                          'weather': [{'kind': x['kind'], 'status': x['status'], 'http_status': x['http_status']} for x in result['weather']]}, ensure_ascii=False))
        return 0
    except Exception:
        print('Reference collection setup failed; no credentials or response bodies printed.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
