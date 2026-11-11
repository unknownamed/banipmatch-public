import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
if not (ROOT / 'tests/test_workflow_api.py').is_file():
    raise SystemExit('PR61 workflow source is required; see README')
from backend.api.settings import Settings

spec = importlib.util.spec_from_file_location('workflow_helpers', 'tests/test_workflow_api.py')
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)
fixture = json.loads((Path(__file__).parent / 'delivery-cases.json').read_text(encoding='utf-8'))
expected = {c['id']: c['expected'] for c in fixture['cases']}
checked = []
for outcome in ('accepted', 'failed', 'unknown', 'unlinked'):
    with TemporaryDirectory() as name:
        root = Path(name)
        settings = Settings(db_path=root/'demo.sqlite3', demo_enabled=True, demo_token='test-only-not-a-production-token-1234')
        generator = h.workflow.__wrapped__(settings, root)
        workflow = next(generator)
        try:
            manager, snapshot, receiver, body = h.approved_flow(workflow, receiver=outcome != 'unlinked')
            if outcome in ('failed','unknown'):
                workflow[1].outcomes = [{'status':outcome,'error_code':'SYNTHETIC_TEST'}]
            response = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", body, key='synthetic-once')
            state = h.wait_delivery(manager, response.json()['dispatch_id'])
            notice = state['notifications'][0]
            key = 'accepted-unread' if outcome == 'accepted' else outcome
            for field in ('delivery_status','response'):
                assert notice[field] == expected[key][field]
            checked.append(key)
            if outcome == 'accepted':
                assert notice['opened_at'] is None
                calls = len(workflow[1].calls)
                duplicate = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", body, key='synthetic-once')
                assert duplicate.json()['dispatch_id'] == response.json()['dispatch_id']
                assert len(workflow[1].calls) == calls
                checked.append('duplicate-send')
                path = f"/v2/recipient/notifications/{notice['notification_id']}"
                opened = receiver.post(path+'/opened', {}).json()
                assert opened['response'] == expected['opened-only']['response'] and opened['opened_at'] is not None
                checked.append('opened-only')
                for case, value in [('acknowledged','acknowledged'),('can-perform','can_perform'),('cannot-perform','cannot_perform')]:
                    result = receiver.post(path+'/responses', {'response':value}).json()
                    assert result['response'] == expected[case]['response']
                    assert result['response_history']
                    if value == 'cannot_perform':
                        assert result['needs_followup']
                    checked.append(case)
                current = manager.get('/v2/dispatches/'+response.json()['dispatch_id']).json()
                assert not current['external_transport_completed']
            if outcome == 'unknown':
                before = len(workflow[1].calls)
                retry = manager.post(f"/v2/notifications/{notice['notification_id']}/retry", {'confirm_test_send':True})
                assert retry.status_code == expected[key]['http_status'] and retry.json()['code'] == expected[key]['code']
                assert len(workflow[1].calls) == before
        finally:
            generator.close()
report={'pr':61,'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'kind':'simulated','transport':'injected; no provider network', 'real_phone_verified':False,
        'fixture_cases_matched':checked,'remaining_examples':'covered by existing workflow regression or frontend/manual acceptance; not full device verification'}

print(json.dumps(report,ensure_ascii=False))
