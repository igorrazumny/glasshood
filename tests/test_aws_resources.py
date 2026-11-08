from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.collectors import aws_resources as aws


@pytest.fixture(autouse=True)
def clean():
    aws._credentials.clear()


def test_identity_exchange_is_cached_and_scoped(monkeypatch):
    import boto3
    calls = []
    sts = Mock()
    sts.assume_role_with_web_identity.return_value = {'Credentials': {
        'AccessKeyId': 'synthetic-id', 'SecretAccessKey': 'synthetic-secret', 'SessionToken': 'synthetic-session',
        'Expiration': datetime.now(timezone.utc) + timedelta(hours=1)}}
    def factory(service, **kwargs):
        calls.append((service, kwargs))
        return sts if service == 'sts' else Mock()
    monkeypatch.setattr(boto3, 'client', factory)
    identity = Mock(return_value='synthetic-azure-token')
    monkeypatch.setattr(aws, 'token', identity)
    config = {'role_arn': 'test-role', 'region': 'us-east-2', 'audience': 'test-audience'}
    aws.client('ecs', config); aws.client('logs', config)
    assert sts.assume_role_with_web_identity.call_count == 1
    assert identity.call_args.args == ('test-audience',)
    assert calls[-1][1]['aws_session_token'] == 'synthetic-session'
    aws.client('ecs', {**config, 'role_arn': 'other-role'})
    assert sts.assume_role_with_web_identity.call_count == 2


def test_missing_azure_identity_never_uses_local_credentials(monkeypatch):
    import boto3
    monkeypatch.setattr(aws, 'token', Mock(side_effect=RuntimeError('no managed identity')))
    factory = Mock(); monkeypatch.setattr(boto3, 'client', factory)
    with pytest.raises(RuntimeError):
        aws.client('ecs', {'role_arn': 'r', 'region': 'x', 'audience': 'a'})
    factory.assert_not_called()


@pytest.mark.parametrize('running,pending,desired,expected', [(1, 0, 1, 'healthy'), (0, 0, 1, 'error'),
                                                           (1, 1, 2, 'degraded'), (0, 0, 0, 'idle')])
def test_service_counts(running, pending, desired, expected):
    c = Mock()
    c.describe_services.return_value = {'services': [{'status': 'ACTIVE', 'runningCount': running,
        'pendingCount': pending, 'desiredCount': desired}]}
    result = aws.box({'type': 'aws_ecs_service', 'cluster': 'c', 'service': 's'}, lambda *_: c)
    assert result['status'] == expected


def test_missing_service_or_failed_read_is_not_healthy():
    c = Mock(); c.describe_services.return_value = {'services': [], 'failures': [{'reason': 'MISSING'}]}
    probe = {'type': 'aws_ecs_service', 'cluster': 'c', 'service': 's'}
    assert aws.box(probe, lambda *_: c)['status'] == 'not checked'
    c.describe_services.side_effect = RuntimeError('sensitive response content')
    result = aws.box(probe, lambda *_: c)
    assert result['status'] == 'not checked'
    assert 'sensitive' not in result['check_description']


@pytest.mark.parametrize('states,expected', [([], 'error'), (['healthy'], 'healthy'),
    (['healthy', 'unhealthy'], 'degraded'), (['initial'], 'error'), ([None], 'not checked')])
def test_target_health(states, expected):
    c = Mock(); c.describe_target_health.return_value = {'TargetHealthDescriptions': [
        {'TargetHealth': {'State': s}} for s in states]}
    assert aws.box({'type': 'aws_target_group', 'arn': 'tg'}, lambda *_: c)['status'] == expected


def test_logs_read_backwards_across_empty_pages_and_streams():
    c = Mock()
    c.describe_log_streams.side_effect = [{'logStreams': [{'logStreamName': 'a'}], 'nextToken': 'more'},
                                        {'logStreams': [{'logStreamName': 'b'}]}]
    c.get_log_events.side_effect = [
        {'events': [], 'nextBackwardToken': 'next'},
        {'events': [{'timestamp': 1000, 'message': 'ERROR old'}], 'nextBackwardToken': 'next'},
        {'events': [{'timestamp': 3000, 'message': '{"level":"warning","message":"new"}'}], 'nextBackwardToken': 'end'},
        {'events': [], 'nextBackwardToken': 'end'}]
    rows = aws.query_logs({'log_group': '/ecs/test'}, 1, 2, lambda *_: c)
    assert [r['severity'] for r in rows] == ['WARNING', 'ERROR']
    assert c.get_log_events.call_args_list[1].kwargs['nextToken'] == 'next'
    assert all(not call.kwargs['startFromHead'] for call in c.get_log_events.call_args_list)
    assert all('endTime' in call.kwargs for call in c.get_log_events.call_args_list)


def test_logs_do_not_hide_permission_failure_as_empty():
    c = Mock(); c.describe_log_streams.side_effect = RuntimeError('denied')
    with pytest.raises(RuntimeError):
        aws.query_logs({'log_group': '/ecs/test'}, 1, 10, lambda *_: c)


def test_manifest_poll_routes_to_aws(monkeypatch):
    from src.collectors import manifest_metrics
    monkeypatch.setattr(aws, 'box', lambda p: {'status': 'not checked', 'check_description': 'read refused', 'metrics': {}})
    result = manifest_metrics._poll_node({'id': 'ecs', 'monitoring': {'probe': {'type': 'aws_ecs_service'}}})
    assert result['node_id'] == 'ecs' and result['status'] == 'not checked'


def test_aws_log_route_uses_trusted_location_and_quiet_fallback(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.routes import logs
    config = {'source': 'aws', 'log_group': '/ecs/trusted', 'region': 'test-region'}
    monkeypatch.setattr(logs, 'verify_token', lambda r: None)
    monkeypatch.setattr(logs, '_resolve_node', lambda n: ('aws_logs', None, config))
    from src.collectors import statuspage
    monkeypatch.setattr(statuspage, 'log_entries', lambda n: None)
    query = Mock(side_effect=[[], [{'timestamp': '2026-11-01', 'message': 'old', 'severity': 'INFO'}]])
    monkeypatch.setattr(aws, 'query_logs', query)
    app = FastAPI(); app.include_router(logs.router)
    result = TestClient(app).get('/api/logs/ecs?log_filter=untrusted&log_project=other').json()
    assert result['window'] == '7d' and result['count'] == 1
    assert query.call_args_list[0].args == (config, 1, 100)
    assert query.call_args_list[1].args == (config, 168, 100)


def test_aws_location_reaches_part_and_system_ai_without_google_reads(monkeypatch):
    from src.analysis import vertex_overview as ov
    from src.api.routes import manifests
    location = {'source': 'aws', 'log_group': '/ecs/test', 'region': 'test-region'}
    manifests_data = [{'product': 'testrobin', 'project_id': '', 'nodes': [
        {'id': 'ecs', 'label': 'Service', 'monitoring': {'logs': [location]}}]}]
    monkeypatch.setattr(manifests, '_load_manifests', lambda: manifests_data)
    query = Mock(return_value=[{'timestamp': '2026-11-08T01:00:00Z', 'severity': 'ERROR', 'message': 'ERROR service failed'}])
    monkeypatch.setattr(aws, 'query_logs', query)
    google = Mock(side_effect=AssertionError('AWS logs reached Google'))
    monkeypatch.setattr(ov, '_read_entries', google)
    topology = {'nodes': [{'id': 'ecs', 'label': 'Service', 'project': 'testrobin', 'status': 'error'}]}
    [(rec, loc)] = list(ov._walk_parts(topology))
    assert loc == location
    assert 'ERROR service failed' in ov._log_lines(loc, 10, 5)[0]
    generated = []
    def generate(prompt, text):
        import json
        generated.append(json.loads(text))
        return {'summary': 'Service has a problem'}
    monkeypatch.setattr(ov, '_generate', generate)
    ov.run_own_systems(topology)
    assert generated[0]['system'] == 'testrobin'
    assert generated[0]['recent_logs']
    google.assert_not_called()


def test_explicit_verification_reads_aws_not_google(monkeypatch):
    from src import manifest_compiler as compiler
    monkeypatch.setattr(aws, 'box', lambda p: {'status': 'healthy', 'check_description': 'running'})
    monkeypatch.setattr(aws, 'query_logs', lambda *a: [{'message': 'line'}])
    result = compiler._verify_node({'id': 'ecs', 'type': 'compute', 'monitoring': {
        'probe': {'type': 'aws_ecs_service'}, 'logs': [{'source': 'aws', 'log_group': '/ecs/test'}]}})
    assert result['probe_result']['ok'] and result['logs_result']['has_data']
