# File: src/collectors/aws_resources.py
# Purpose: Read AWS service state and CloudWatch logs using Azure workload identity.
# Role, audience, region and resource identifiers come only from the landscape.

import json
import re
import threading
import time
from datetime import datetime, timezone

from src.collectors.azure_resources import token

_lock = threading.Lock()
_credentials = {}


def client(service: str, config: dict):
    """Exchange our Azure identity for short-lived AWS credentials; never use local keys."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    role, region, audience = (config[k] for k in ('role_arn', 'region', 'audience'))
    if not all((role, region, audience)):
        raise ValueError('AWS role, region and identity audience are required')
    key = (role, region, audience)
    options = dict(connect_timeout=5, read_timeout=20, retries={'mode': 'standard', 'total_max_attempts': 3})
    with _lock:
        credentials = _credentials.get(key)
        if not credentials or credentials['Expiration'].timestamp() <= time.time() + 120:
            identity = token(audience)  # missing Azure identity fails before any AWS credential lookup
            sts = boto3.client('sts', region_name=region, config=Config(signature_version=UNSIGNED, **options))
            credentials = sts.assume_role_with_web_identity(
                RoleArn=role, RoleSessionName='glasshood-readonly', WebIdentityToken=identity,
                DurationSeconds=3600)['Credentials']
            _credentials[key] = credentials
        return boto3.client(service, region_name=region, config=Config(**options),
                            aws_access_key_id=credentials['AccessKeyId'],
                            aws_secret_access_key=credentials['SecretAccessKey'],
                            aws_session_token=credentials['SessionToken'])


def _one(response, field):
    rows = response.get(field) or []
    if response.get('failures') or len(rows) != 1:
        raise ValueError('AWS did not return the requested resource')
    return rows[0]


def read(probe: dict, make_client=None) -> tuple:
    """Return (status, explanation, figures), with no write operations."""
    get = make_client or client
    kind = probe['type']
    if kind == 'aws_ecs_service':
        service = _one(get('ecs', probe).describe_services(
            cluster=probe['cluster'], services=[probe['service']]), 'services')
        desired, running, pending = (service.get(k) for k in ('desiredCount', 'runningCount', 'pendingCount'))
        if any(v is None for v in (desired, running, pending)):
            raise ValueError('AWS returned no task counts')
        figures = {'desired_tasks': desired, 'running_tasks': running, 'pending_tasks': pending}
        failed = any(d.get('rolloutState') == 'FAILED' for d in service.get('deployments') or [])
        if service.get('status') != 'ACTIVE' or (desired > 0 and running == 0):
            return 'error', f'Service unavailable: {running} of {desired} tasks running', figures
        if desired == 0:
            return 'idle', 'Service is configured with no running tasks', figures
        if running < desired or pending or failed:
            return 'degraded', f'{running} of {desired} tasks running; {pending} pending' + ('; deployment failed' if failed else ''), figures
        return 'healthy', f'{running} of {desired} tasks running', figures
    if kind == 'aws_load_balancer':
        lb = _one(get('elbv2', probe).describe_load_balancers(LoadBalancerArns=[probe['arn']]), 'LoadBalancers')
        state = (lb.get('State') or {}).get('Code')
        if not state:
            raise ValueError('AWS returned no load balancer state')
        status = 'healthy' if state == 'active' else 'error' if state == 'failed' else 'degraded'
        return status, f'Load balancer state: {state}', {'state': state}
    if kind == 'aws_target_group':
        rows = get('elbv2', probe).describe_target_health(TargetGroupArn=probe['arn']).get('TargetHealthDescriptions')
        if rows is None:
            raise ValueError('AWS returned no target health')
        states = [(r.get('TargetHealth') or {}).get('State') for r in rows]
        if any(s is None for s in states):
            raise ValueError('AWS returned an unknown target state')
        healthy = states.count('healthy')
        figures = {'targets': len(rows), 'healthy_targets': healthy}
        status = 'healthy' if rows and healthy == len(rows) else 'degraded' if healthy else 'error'
        return status, f'{healthy} of {len(rows)} application targets pass the load balancer health check', figures
    if kind == 'aws_log_group':
        rows = get('logs', probe).describe_log_groups(logGroupNamePrefix=probe['log_group']).get('logGroups') or []
        group = next((r for r in rows if r.get('logGroupName') == probe['log_group']), None)
        if group is None:
            raise ValueError('AWS did not return the requested log group')
        return 'healthy', 'CloudWatch log group is readable', {'stored_bytes': group.get('storedBytes')}
    raise ValueError('Unknown AWS probe type')


def box(probe: dict, make_client=None) -> dict:
    try:
        status, explanation, figures = read(probe, make_client)
    except Exception as exc:
        # SDK errors may contain request details; do not expose identities or tokens.
        status, figures = 'not checked', {}
        explanation = f'GlassHood could not read this AWS resource ({type(exc).__name__})'
    return {'status': status, 'metrics': figures, 'check_description': explanation}


def _line(event: dict) -> dict:
    message = str(event.get('message') or '')
    severity = 'INFO'
    try:
        payload = json.loads(message)
        if isinstance(payload, dict):
            severity = str(payload.get('level') or payload.get('severity') or severity).upper()
    except (ValueError, TypeError):
        match = re.search(r'\b(CRITICAL|ERROR|WARNING|WARN|DEBUG|INFO)\b', message, re.I)
        if match:
            severity = match.group(1).upper()
    if severity == 'WARN':
        severity = 'WARNING'
    return {'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000, timezone.utc).isoformat(),
            'severity': severity, 'message': message}


def query_logs(config: dict, since_hours: float, max_entries: int, make_client=None, end_ms: int = None) -> list:
    """Newest lines across the configured group's streams, including quiet older streams.

    Read backwards within each stream so a busy stream cannot hide its latest lines.
    Empty pages are not EOF; AWS ends backwards pagination by repeating the token.
    `end_ms` reads the lines before that moment instead of before now (REQ-GHA-032 clause 13).
    """
    logs = (make_client or client)('logs', config)
    end = int(time.time() * 1000) if end_ms is None else int(end_ms)
    start = end - int(since_hours * 3600 * 1000)
    group = config['log_group']
    streams, token_value, seen = [], None, set()
    while True:
        args = {'logGroupName': group}
        if config.get('stream_prefix'):
            args['logStreamNamePrefix'] = config['stream_prefix']
        if token_value:
            args['nextToken'] = token_value
        page = logs.describe_log_streams(**args)
        streams.extend(s['logStreamName'] for s in page.get('logStreams') or [])
        token_value = page.get('nextToken')
        if not token_value:
            break
        if token_value in seen:
            raise RuntimeError('AWS log stream pagination did not advance')
        seen.add(token_value)
    events = []
    for stream in streams:
        token_value, rows, seen = None, [], set()
        while len(rows) < max_entries:
            args = dict(logGroupName=group, logStreamName=stream, startTime=start, endTime=end,
                        startFromHead=False, limit=max_entries - len(rows))
            if token_value:
                args['nextToken'] = token_value
            page = logs.get_log_events(**args)
            rows.extend(page.get('events') or [])
            next_token = page.get('nextBackwardToken')
            if not next_token or next_token == token_value:
                break
            if next_token in seen:
                raise RuntimeError('AWS log pagination did not advance')
            seen.add(next_token)
            token_value = next_token
        events.extend(rows)
    return [_line(e) for e in sorted(events, key=lambda e: e['timestamp'], reverse=True)[:max_entries]]
