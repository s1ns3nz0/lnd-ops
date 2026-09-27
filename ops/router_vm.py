"""Start only an approved existing Lima instance, with a durable retry budget."""
import hashlib
import json
import math
import os
import pathlib
import re
import stat
import subprocess
import time

from router_store import operation_lock, read, write


def inventory(limactl, name, env=None):
    if not pathlib.Path(limactl).is_absolute() or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
        raise ValueError("Lima 실행 경로 또는 VM 이름이 잘못되었습니다")
    result = subprocess.run([limactl, "list", name, "--json"], env=env, capture_output=True, text=True, timeout=15, check=True)
    items = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if len(items) != 1 or items[0].get("name") != name:
        raise ValueError("승인할 기존 VM 하나를 확인할 수 없습니다. 자동 생성하지 않습니다")
    return items[0]


def fingerprint(item):
    directory = pathlib.Path(item["dir"])
    metadata = directory.lstat()
    if not directory.is_absolute() or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("VM 디렉터리가 현재 사용자 소유의 실제 디렉터리가 아닙니다")
    config = directory / "lima.yaml"
    info = config.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("기존 VM 설정 파일을 확인할 수 없습니다")
    return {"directory": str(directory), "inode": metadata.st_ino, "device": metadata.st_dev,
            "configuration_sha256": hashlib.sha256(config.read_bytes()).hexdigest()}


def approve(root, limactl, name, env=None):
    item = inventory(limactl, name, env)
    if item.get("status") not in ("Running", "Stopped"):
        raise ValueError("VM이 시작/종료 중이거나 상태를 확인할 수 없습니다")
    record = {"schema": "lnd-ops/router-vm/v1", "limactl": limactl, "name": name,
              "fingerprint": fingerprint(item), "approved_at": time.time(),
              "attempts": 0, "next_attempt_at": 0, "state": "approved"}
    with operation_lock(root, "vm-start.lock"):
        write(root, "vm-start.json", record)
    return record


def ensure_started(root, env=None, now=None):
    now = time.time() if now is None else now
    with operation_lock(root, "vm-start.lock"):
        record = read(root, "vm-start.json")
        if not isinstance(record, dict) or record.get("schema") != "lnd-ops/router-vm/v1":
            raise ValueError("승인된 기존 VM 시작 설정이 없습니다")
        if (type(record.get("attempts")) is not int or not 0 <= record["attempts"] <= 3
                or type(record.get("next_attempt_at")) not in (int, float)
                or not math.isfinite(record["next_attempt_at"]) or record["next_attempt_at"] < 0
                or not isinstance(record.get("limactl"), str)
                or not isinstance(record.get("name"), str)
                or not isinstance(record.get("fingerprint"), dict)):
            raise ValueError("VM 시작 승인 기록 형식이 잘못되었습니다")
        item = inventory(record["limactl"], record["name"], env)
        if fingerprint(item) != record["fingerprint"]:
            raise ValueError("승인 이후 VM 디렉터리나 설정이 바뀌었습니다. 자동 시작하지 않습니다")
        if item.get("status") == "Running":
            record.update(state="running", attempts=0, next_attempt_at=0, checked_at=now)
            write(root, "vm-start.json", record)
            return True
        if item.get("status") != "Stopped":
            record.update(state="transitioning", checked_at=now)
            write(root, "vm-start.json", record)
            return False
        if record["attempts"] >= 3:
            record.update(state="needs_review", checked_at=now)
            write(root, "vm-start.json", record)
            return False
        if now < record["next_attempt_at"]:
            return False
        record["attempts"] += 1
        delay = 30 * 2 ** (record["attempts"] - 1)
        record.update(state="starting", next_attempt_at=now + delay, checked_at=now)
        write(root, "vm-start.json", record)
        started = time.monotonic()
        try:
            # NAME comes only from the checked existing inventory. No template,
            # URL, create command, wallet copy or configuration override is used.
            result = subprocess.run([record["limactl"], "start", "--tty=false", "--timeout=2m", record["name"]],
                                    env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=130)
            record.update(state="requested" if result.returncode == 0 else "retry_wait", last_exit=result.returncode)
        except subprocess.TimeoutExpired:
            record.update(state="uncertain")
        except BaseException:
            record.update(state="uncertain")
            record["next_attempt_at"] = now + max(0, time.monotonic() - started) + delay
            write(root, "vm-start.json", record)
            raise
        # Backoff starts after the client finishes, including a timeout. Saving
        # the attempt before spawning also retains the budget after SIGKILL.
        record["next_attempt_at"] = now + max(0, time.monotonic() - started) + delay
        write(root, "vm-start.json", record)
        return False  # Only a subsequent inventory observation proves running.
