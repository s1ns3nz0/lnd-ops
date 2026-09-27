"""Persistent local observations; no traffic requirement or financial actions."""
import math
import time

from router_store import write


def age(stamp, now):
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp > now or stamp <= 0:
        return None
    return now - stamp


def status(record, now=None):
    """Read heartbeat and observation freshness separately; never restart anything."""
    now = time.time() if now is None else now
    if not isinstance(record, dict) or record.get('schema') != 'lnd-ops/router-monitor/v1':
        return {'state': 'missing', 'monitor_alive': False, 'ready': False,
                'message': '감시 기록이 없습니다', 'external_reachability': 'unverified'}
    heartbeat_age = age(record.get('heartbeat_at'), now)
    alive = record.get('running') is True and heartbeat_age is not None and heartbeat_age <= 15
    observed = record.get('current') if isinstance(record.get('current'), dict) else {}
    observation_age = age(observed.get('checked_at'), now)
    fresh = alive and observation_age is not None and observation_age <= 30 and observed.get('code') != 'query_error'
    ready = fresh and observed.get('ready') is True
    external = fresh and observed.get('external_reachability') == 'operator_attested' and \
        type(observed.get('external_expires_at')) in (int, float) and math.isfinite(observed['external_expires_at']) and observed['external_expires_at'] > now
    state = 'stopped' if record.get('running') is False else 'heartbeat_stale' if not alive else 'observation_stale' if not fresh else 'ready' if ready else 'pending'
    messages = {'stopped': '감시가 종료되었습니다', 'heartbeat_stale': '감시 생존 시각이 오래됐거나 잘못되었습니다',
                'observation_stale': '노드 상태를 새로 확인해야 합니다', 'ready': '현재 라우팅 준비 상태입니다',
                'pending': observed.get('message', '노드 운영 조건을 확인해야 합니다')}
    return {'state': state, 'monitor_alive': alive, 'ready': ready, 'heartbeat_age_seconds': heartbeat_age,
            'observation_age_seconds': observation_age, 'probe_in_progress': record.get('probe_in_progress') is True,
            'external_reachability': 'operator_attested' if external else 'unverified',
            'message': messages[state], 'alert': record.get('alert'), 'code': observed.get('code')}


class Observations:
    def __init__(self, threshold=120):
        self.threshold = threshold
        self.current = self.last_good = None
        self.condition = None
        self.since = None
        self.alerted = False
        self.observation_received_at = None
        self.stale_since = None
        self.stale_alerted = False

    def accept(self, result, now=None):
        now = time.monotonic() if now is None else now
        events = []
        previous = self.current
        self.current = result
        self.observation_received_at = time.time()
        if result["code"] != "query_error":
            self.last_good = result
        # A ready but unproven node is not an operational outage. Completion
        # evidence is still separately required by the verifier.
        condition = None if result.get("ready") is True and result['code'] != 'query_error' else result["code"]
        if condition != self.condition:
            if self.alerted:
                events.append({"event": "recovered" if condition is None else "condition_changed",
                               "previous": self.condition, "code": result["code"]})
            self.condition, self.since, self.alerted = condition, now, False
        if condition is not None and self.since is None:
            self.since = now
        if condition is not None and not self.alerted and now - self.since >= self.threshold:
            self.alerted = True
            events.append({"event": "alert", "code": condition, "duration_seconds": int(now - self.since)})
        if previous is None or previous.get("code") != result["code"]:
            events.insert(0, {"event": "status", "code": result["code"], "message": result.get("message", "")})
        return events

    def check_freshness(self, now=None, wall_now=None):
        """A live daemon must not hide a hung/slow probe behind its heartbeat."""
        now = time.monotonic() if now is None else now
        wall_now = time.time() if wall_now is None else wall_now
        observed_age = age((self.current or {}).get('checked_at'), wall_now)
        fresh = observed_age is not None and observed_age <= 30 and self.current.get('code') != 'query_error'
        if fresh:
            events = [{'event': 'observation_resumed', 'code': self.current['code']}] if self.stale_since is not None else []
            self.stale_since, self.stale_alerted = None, False
            return events
        if self.stale_since is None:
            self.stale_since = now
            return [{'event': 'observation_stale'}]
        if not self.stale_alerted and now - self.stale_since >= self.threshold:
            self.stale_alerted = True
            return [{'event': 'observation_alert', 'duration_seconds': int(now - self.stale_since)}]
        return []

    def save(self, root, running=True, probing=False):
        write(root, "monitor.json", {"schema": "lnd-ops/router-monitor/v1", "running": running,
              "heartbeat_at": time.time(), "probe_in_progress": probing,
              "observation_received_at": self.observation_received_at,
              "current": self.current, "last_successful": self.last_good,
              "alert": self.condition if self.alerted else None,
              "observation_alert": self.stale_alerted})
