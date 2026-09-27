"""Separate current Router observations from historical, scoped recovery proof."""
from datetime import datetime, timezone
import json
import math
import subprocess
import time
import textwrap

from router_rpc import environment
from router_store import read
from router_recovery import historical
from router_address_recovery import historical as address_history


def infrastructure():
    command = ["kubectl", "-n", "lnd-testnet", "get", "statefulset/lnd-0", "pod/lnd-0-0",
               "persistentvolumeclaim/data-lnd-0-0", "service/lnd-router-p2p",
               "--ignore-not-found", "-o", "json"]
    try:
        result = subprocess.run(command, env=environment(), capture_output=True, text=True, timeout=20, check=True)
        payload = json.loads(result.stdout)
        items = payload.get("items", [payload])
        kinds = {item["kind"]: item for item in items}
        required = ("StatefulSet", "Pod", "PersistentVolumeClaim", "Service")
        missing = [kind for kind in required if kind not in kinds]
        return {"state": "missing" if missing else "present", "missing": missing,
                "pod_ready": any(c.get("type") == "Ready" and c.get("status") == "True"
                                 for c in kinds.get("Pod", {}).get("status", {}).get("conditions", [])),
                "pvc_bound": kinds.get("PersistentVolumeClaim", {}).get("status", {}).get("phase") == "Bound",
                "checked_at": time.time()}
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        return {"state": "unknown", "checked_at": time.time()}


def pod_recovery(evidence, current, now):
    """Historical proof is applicable only to the same identity/channel set."""
    active = [c for c in current.get("channels", []) if c.get("active") and not c.get("private")]
    comparable = bool(current.get("identity")) and current.get("code") != "query_error" and all(
        isinstance(c.get("point"), str) and bool(c["point"]) and isinstance(c.get("peer"), str) and bool(c["peer"]) for c in active)
    points = sorted(c["point"] for c in active) if comparable else []
    peers = sorted({c["peer"] for c in active}) if comparable else []
    candidates = []
    invalid = 0
    for path in evidence.glob("testnet-reconnect-*.json"):
        try:
            record = read(evidence, path.name)
            if record["schema"] != "lnd-ops/testnet-reconnect/v1" or record["result"] != "pass":
                raise ValueError("not a passing reconnect record")
            before, after = record["before"], record["after"]
            prepared = datetime.fromisoformat(record["prepared_at"].replace("Z", "+00:00"))
            verified = datetime.fromisoformat(record["verified_at"].replace("Z", "+00:00"))
            if prepared.tzinfo is None or verified.tzinfo is None or not 0 <= prepared.timestamp() <= verified.timestamp() <= now:
                raise ValueError("invalid recovery time")
            if not before["pod_uid"] or not after["pod_uid"] or before["pod_uid"] == after["pod_uid"]:
                raise ValueError("restart not proved")
            if not before["node_key"] or not before["channel_points"] or not before["peer_pubkeys"]:
                raise ValueError("empty recovery baseline")
            for field in ("channel_points", "peer_pubkeys"):
                if not isinstance(before[field], list) or not all(isinstance(value, str) and value for value in before[field]):
                    raise ValueError("invalid recovery baseline list")
            for field in ("node_key", "channel_points", "peer_pubkeys"):
                if before[field] != after[field]:
                    raise ValueError("recovery changed identity or channels")
            elapsed = record["elapsed_seconds"]
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("invalid elapsed time")
            if abs(elapsed - (verified - prepared).total_seconds()) > 2:
                raise ValueError("elapsed time contradicts the observation window")
            applicable = (comparable and after["node_key"] == current.get("identity")
                          and sorted(after["channel_points"]) == points and sorted(after["peer_pubkeys"]) == peers)
            candidates.append({"state": "current_unavailable" if not comparable else "verified_history" if applicable else "different_current_state",
                               "history_valid": True, "matches_current": applicable if comparable else None,
                               "verified_at": verified.timestamp(), "elapsed_seconds": elapsed,
                               "record": path.name, "scope": "pod_restart"})
        except (ValueError, TypeError, KeyError, OSError):
            invalid += 1
    latest = max(candidates, key=lambda item: item["verified_at"], default={"state": "unverified", "scope": "pod_restart"})
    return latest | {"invalid_records": invalid}


def report(current, construction, evidence, now=None, recovery_root=None):
    now = time.time() if now is None else now
    recovery = {"pod_restart": pod_recovery(evidence, current, now),
                "mac_reboot": {"state": "unverified"}, "windows_reboot": {"state": "unverified"},
                "address_change": {"state": "unverified"}}
    if recovery_root is not None:
        for kind in ('mac', 'windows'):
            recovery[kind + '_reboot'] = historical(recovery_root, kind, current, now)
            recovery[kind + '_address_change'] = address_history(recovery_root, kind, current, now)
        recovery['address_change'] = {'state': 'verified_history' if all(
            recovery[kind + '_address_change']['state'] == 'verified_history' for kind in ('mac', 'windows')) else 'unverified'}
    requirements = {
        'resources_not_ready': construction.get('state') == 'present' and construction.get('pod_ready') is True and construction.get('pvc_bound') is True,
        'router_not_complete': current.get('complete') is True and current.get('ready') is True and current.get('code') == 'complete',
        'external_observation_expired': current.get('external_reachability') == 'operator_attested' and current.get('external_expires_at', 0) > now,
        'router_observation_stale': type(current.get('checked_at')) in (int, float) and 0 <= now - current['checked_at'] <= 30,
    }
    for key in ('pod_restart', 'mac_reboot', 'windows_reboot', 'address_change'):
        requirements[key + '_not_verified'] = recovery[key]['state'] == 'verified_history'
    missing = [reason for reason, passed in requirements.items() if not passed]
    return {"schema": "lnd-ops/router-report/v1", "generated_at": now,
            "construction": construction,
            "readiness": {"state": "unknown" if current.get("code") == "query_error" else "ready" if current.get("ready") else "pending",
                          "reason": current.get("message", "조회 결과 없음"),
                          "checked_at": current.get("checked_at"), "code": current.get("code")},
            "forwarding": {"state": current.get("forwarding_proof", "unverified"),
                           "verified_at": current.get("proof_verified_at")},
            "external_p2p": {"state": current.get("external_reachability", "unverified")},
            "recovery": recovery,
            "complete": not missing, "incomplete_reasons": missing}


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if value is not None else "기록 없음"


def render(value):
    construction = value["construction"]
    resource = {"present": "필수 리소스 있음", "missing": "리소스 부족", "unknown": "조회 실패"}[construction["state"]]
    ready = {"ready": "준비됨", "pending": "조건 미충족", "unknown": "조회 실패"}[value["readiness"]["state"]]
    proof = value["forwarding"]
    pod = value["recovery"]["pod_restart"]
    lines = ["=" * 56, "  ROUTER · 운영 상태와 검증 이력", "=" * 56,
             f"  구축       {resource}",
             f"  Pod Ready  {'예' if construction.get('pod_ready') else '미확인'} / PVC Bound  {'예' if construction.get('pvc_bound') else '미확인'}",
             f"  현재 준비  {ready}",
             f"  조회 시각  {timestamp(value['readiness']['checked_at'])}",
             f"  실경유     {'현재 구성의 성공 이력 있음' if proof['state'] == 'verified' else '미검증'}",
             f"  검증 시각  {timestamp(proof['verified_at'])}",
             f"  외부 P2P   {'확인 (운영자 외부 실행)' if value['external_p2p']['state'] == 'operator_attested' else '미검증'}",
             "-" * 56,
             "  Pod 재시작 " + {"verified_history": "현재 구성과 일치하는 복구 이력 있음",
                                  "different_current_state": "과거 이력은 있으나 현재 구성과 다름",
                                  "current_unavailable": "과거 이력 있음 / 현재 구성 대조 불가",
                                  "unverified": "미검증"}[pod["state"]]]
    if pod.get("verified_at") is not None:
        lines += [f"  복구 시각  {timestamp(pod['verified_at'])}", f"  소요 시간  {pod['elapsed_seconds']}초 (준비·수동 unlock 포함)"]
    descriptions = {'unverified': '미검증', 'verified_history': '현재 지갑·채널과 일치하는 이력',
                    'different_current_state': '현재와 다른 지갑·채널의 이력', 'current_unavailable': '현재 구성 대조 불가',
                    'invalid_record': '유효하지 않은 기록'}
    for kind, label in (('mac', 'Mac'), ('windows', 'Windows')):
        item = value['recovery'][kind + '_reboot']
        lines.append(f"  {label} 재부팅  " + descriptions[item['state']])
        if item.get('verified_at') is not None:
            lines.append("    " + timestamp(item['verified_at']))
    for kind, label in (('mac', 'Mac'), ('windows', 'Windows')):
        item = value['recovery'].get(kind + '_address_change', {'state': 'unverified'})
        lines.append(f"  {label} 주소 변경  " + descriptions[item['state']])
        if item.get('verified_at') is not None:
            lines.append("    " + timestamp(item['verified_at']))
    lines += [
              "-" * 56, "  과거 성공 이력은 현재 가용성을 보장하지 않습니다.",
              "  이 조회는 Phase 완료 기록을 생성하지 않습니다."]
    reason = " ".join(str(value['readiness']['reason']).split())
    lines.extend(textwrap.wrap("  현재 상태: " + reason, width=26, subsequent_indent="    "))
    return "\n".join(lines)
