"""Wait for the testnet wallet state RPC without reading wallet credentials."""
import json
import subprocess
import sys
import time

from router_rpc import call, environment


def current_container(deadline, clock=time.monotonic, run=subprocess.run):
    """Wait for the desired revision's LND container, not locked-wallet sidecars."""
    def get(kind, name):
        remaining = deadline - clock()
        if remaining <= 0:
            raise RuntimeError("LND container wait expired")
        result = run(["kubectl", "-n", "lnd-testnet", "get", kind, name, "-o", "json"],
                     env=environment(), text=True, capture_output=True, timeout=min(10, remaining))
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip() or "Kubernetes 조회 실패")
        return json.loads(result.stdout)

    workload = get("statefulset", "lnd-0")
    status = workload.get("status", {})
    generation = workload.get("metadata", {}).get("generation")
    if generation is None or status.get("observedGeneration", -1) < generation:
        return False
    revision = status.get("updateRevision")
    pod = get("pod", "lnd-0-0")
    metadata = pod.get("metadata", {})
    if not revision or metadata.get("deletionTimestamp") or metadata.get("labels", {}).get("controller-revision-hash") != revision:
        return False
    return any(c.get("name") == "lnd" and "running" in c.get("state", {})
               for c in pod.get("status", {}).get("containerStatuses", []))


def wait_for_state(timeout=120, rpc=call, clock=time.monotonic, sleep=time.sleep,
                   container_ready=current_container):
    deadline = clock() + timeout
    detail = "LND is starting"
    while clock() < deadline:
        try:
            if container_ready(deadline, clock=clock):
                remaining = deadline - clock()
                if remaining <= 0:
                    break
                result = rpc("state", timeout=min(10, remaining))
                state = result.get("state") if isinstance(result, dict) else None
                if state in ("NON_EXISTING", "LOCKED", "SERVER_ACTIVE"):
                    return state
                detail = f"wallet state: {state or 'unknown'}"
            else:
                detail = "LND 컨테이너에 새 설정 적용 중"
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError, subprocess.SubprocessError) as exc:
            detail = str(exc)
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(2, remaining))
    raise RuntimeError(f"LND 지갑 상태 조회 대기 시간이 지났습니다: {detail}")


def main():
    try:
        print(wait_for_state())
        return 0
    except RuntimeError as exc:
        print(f"보류: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    sys.exit(main())
