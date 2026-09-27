"""Journal one approved payment; ambiguous outcomes are reconciled, never resent."""
import base64
import json
import re
import shlex
import subprocess
import time
import uuid

from router_proof import plan, validate
from router_model import channel_id
from router_rpc import call, require_testnet
from router_store import operation_lock, read, write


def invoice_hash(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return value
    try:
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) == 32:
            return decoded.hex()
    except (ValueError, TypeError):
        pass
    raise ValueError("invoice hash를 확인할 수 없습니다")


class Endpoint:
    def __init__(self, alias, lnddir):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", alias):
            raise ValueError("외부 노드는 등록된 SSH 별칭으로 지정하세요")
        if not lnddir.startswith("/") or any(ord(c) < 32 for c in lnddir):
            raise ValueError("외부 LND 데이터 경로는 절대 경로여야 합니다")
        self.alias, self.lnddir = alias, lnddir

    def __call__(self, command, *args):
        if command not in ("getinfo", "listchannels", "addinvoice", "decodepayreq", "payinvoice", "trackpayment", "lookupinvoice"):
            raise ValueError("허용되지 않은 외부 검증 작업")
        remote = shlex.join(["lncli", "--network=testnet", "--lnddir=" + self.lnddir, command, *args])
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                                 "-o", "ConnectTimeout=10", "--", self.alias, remote],
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            # RPC stderr can echo the payment request; avoid copying it into
            # monitor logs. Operators can inspect their remote node directly.
            raise RuntimeError(f"외부 {self.alias}의 {command} 작업 실패 (exit {result.returncode})")
        decoder, rest, document = json.JSONDecoder(), result.stdout.strip(), None
        while rest:
            document, position = decoder.raw_decode(rest)
            rest = rest[position:].strip()
        if not isinstance(document, dict):
            raise ValueError("외부 노드의 JSON 응답을 확인할 수 없습니다")
        return document


def preview(payer, receiver, amount_sat, fee_sat, rpc=call):
    info, payer_info, receiver_info = rpc("getinfo"), payer("getinfo"), receiver("getinfo")
    channels = rpc("listchannels").get("channels", [])
    incoming = [c for c in channels if c.get("remote_pubkey") == payer_info["identity_pubkey"] and c.get("active") and not c.get("private")]
    outgoing = [c for c in channels if c.get("remote_pubkey") == receiver_info["identity_pubkey"] and c.get("active") and not c.get("private")]
    if len(incoming) != 1 or len(outgoing) != 1:
        raise ValueError("제어 가능한 송신·수신 peer 각각에 활성 공개 채널 하나가 필요합니다")
    return plan(info, payer_info, receiver_info, channels, channel_id(incoming[0]), channel_id(outgoing[0]), amount_sat, fee_sat)


def save(root, record):
    write(root, "proof-request.json", record)
    write(root, "proof-" + record["request_id"] + ".json", record)


def start(root, approved, payer, receiver, rpc=call):
    with operation_lock(root):
        previous = read(root, "proof-request.json")
        if previous and previous["state"] in ("paying", "uncertain", "verifying"):
            raise ValueError("이전 검증 결제의 결과를 먼저 확인해야 합니다. 재송금하지 않습니다")
        if preview(payer, receiver, approved["amount_sat"], approved["fee_limit_sat"], rpc) != approved:
            raise ValueError("지갑 또는 채널이 바뀌었습니다. 새 요약을 확인하세요")
        record = approved | {"request_id": uuid.uuid4().hex, "started_at": time.time(), "state": "invoice_requested"}
        save(root, record)
        invoice = receiver("addinvoice", f"--amt={record['amount_sat']}", "--expiry=300", "--memo=lndops-router-" + record["request_id"])
        decoded = payer("decodepayreq", invoice["payment_request"])
        payment_hash = decoded.get("payment_hash", "")
        if decoded.get("destination") != record["receiver"] or int(decoded.get("num_msat", -1)) != record["amount_sat"] * 1000 or not re.fullmatch(r"[0-9a-f]{64}", payment_hash):
            raise ValueError("수신 invoice가 승인한 지갑·금액과 다릅니다")
        if invoice_hash(invoice.get("r_hash")) != payment_hash:
            raise ValueError("생성한 invoice와 송신 노드가 해석한 invoice hash가 다릅니다")
        record.update(payment_hash=payment_hash, state="paying")
        save(root, record)  # Must be durable before a funds-moving RPC.
        try:
            payer("payinvoice", "--force", "--json", "--max_parts=1", "--timeout=30s",
                  f"--fee_limit={record['fee_limit_sat']}", f"--outgoing_chan_id={record['incoming']['id']}",
                  "--last_hop=" + record["identity"], invoice["payment_request"])
            record["state"] = "verifying"
        except BaseException:
            record["state"] = "uncertain"
            save(root, record)
            raise
        save(root, record)
    return reconcile(root, payer, receiver, rpc)


def reconcile(root, payer, receiver, rpc=call):
    with operation_lock(root):
        record = read(root, "proof-request.json")
        if not record or record["state"] not in ("paying", "uncertain", "verifying"):
            return record
        for endpoint, key in ((rpc, "identity"), (payer, "payer"), (receiver, "receiver")):
            info = endpoint("getinfo")
            require_testnet(info)
            if info["identity_pubkey"] != record[key]:
                raise ValueError("검증을 시작한 지갑과 현재 지갑이 다릅니다")
        channels = rpc("listchannels").get("channels", [])
        for direction in ("incoming", "outgoing"):
            expected = record[direction]
            if not any(c.get("channel_point") == expected["point"] and channel_id(c) == expected["id"]
                       and c.get("remote_pubkey") == expected["peer"] and not c.get("private") for c in channels):
                raise ValueError("검증 경로의 채널이 바뀌었습니다")
        payment = payer("trackpayment", "--json", record["payment_hash"])
        if payment.get("payment_hash") != record["payment_hash"]:
            raise ValueError("송신 결제 hash가 검증 요청과 다릅니다")
        if payment.get("status") == "FAILED":
            record.update(state="failed", failure_reason=payment.get("failure_reason", "unknown"))
            save(root, record)
            return record
        invoice = receiver("lookupinvoice", record["payment_hash"])
        if invoice_hash(invoice.get("r_hash")) != record["payment_hash"]:
            raise ValueError("수신 invoice hash가 검증 결제와 다릅니다")
        # Bound history to this attempt, and refuse ambiguous matches. Never
        # count an arbitrary old forwarding event as success.
        events = rpc("fwdinghistory", f"--start_time={int(record['started_at'])}", "--max_events=50000").get("forwarding_events", [])
        evidence = validate(record, payment, invoice, events)
        save(root, evidence)
        write(root, "forwarding-proof.json", evidence)
        return evidence
