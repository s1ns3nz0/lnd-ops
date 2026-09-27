"""Match one approved external payment to current Router channels and forwarding."""
import re
import time

from router_model import channel_id
from router_rpc import require_testnet


def plan(router_info, payer_info, receiver_info, channels, incoming, outgoing, amount_sat, fee_sat):
    for info in (router_info, payer_info, receiver_info):
        require_testnet(info)
    identities = [info["identity_pubkey"] for info in (router_info, payer_info, receiver_info)]
    if len(set(identities)) != 3:
        raise ValueError("송신·Router·수신 노드의 지갑은 서로 달라야 합니다")
    if type(amount_sat) is not int or not 1 <= amount_sat <= 100 or type(fee_sat) is not int or not 0 <= fee_sat <= 100:
        raise ValueError("검증 금액은 1~100 sat, 수수료 상한은 0~100 sat여야 합니다")
    selected = []
    for scid, peer in ((incoming, identities[1]), (outgoing, identities[2])):
        matches = [c for c in channels if channel_id(c) == str(scid) and c.get("remote_pubkey") == peer
                   and c.get("active") and not c.get("private")]
        if len(matches) != 1:
            raise ValueError("이번 검증에는 제어 가능한 송신·수신 peer와의 활성 공개 채널이 필요합니다")
        selected.append({"id": str(scid), "point": matches[0]["channel_point"], "peer": peer})
    if selected[0]["id"] == selected[1]["id"]:
        raise ValueError("서로 다른 입·출력 채널이 필요합니다")
    return {"schema": "lnd-ops/router-proof/v1", "identity": identities[0], "payer": identities[1],
            "receiver": identities[2], "incoming": selected[0], "outgoing": selected[1],
            "amount_sat": amount_sat, "fee_limit_sat": fee_sat}


def validate(record, payment, invoice, events, now=None):
    """No preimage or invoice string is retained in the resulting evidence."""
    now = time.time() if now is None else now
    expected_hash = record["payment_hash"]
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("검증 결제 hash가 잘못되었습니다")
    if payment.get("payment_hash") != expected_hash or payment.get("status") != "SUCCEEDED":
        raise ValueError("승인한 결제의 송신 성공을 확인하지 못했습니다")
    amount_msat = record["amount_sat"] * 1000
    if int(payment.get("value_msat", -1)) != amount_msat:
        raise ValueError("송신 금액이 승인한 금액과 다릅니다")
    if invoice.get("state") != "SETTLED" or int(invoice.get("amt_paid_msat", -1)) != amount_msat:
        raise ValueError("별도 수신 노드의 정확한 수취 금액을 확인하지 못했습니다")
    # CLI lookupinvoice can return r_hash as base64; the caller queries the
    # recorded hash and separately checks endpoint identity before this method.
    fee = int(payment.get("fee_msat", -1))
    if not 0 <= fee <= record["fee_limit_sat"] * 1000:
        raise ValueError("송신 수수료가 승인 상한을 벗어났습니다")
    successful = [item for item in payment.get("htlcs", []) if item.get("status") == "SUCCEEDED"]
    if len(successful) != 1:
        raise ValueError("단일 경유 경로 검증에는 성공 HTLC 하나가 필요합니다")
    attempt = successful[0]
    started_ns = int(record["started_at"] * 1_000_000_000)
    attempt_ns = int(attempt.get("attempt_time_ns", 0))
    settled_ns = int(attempt.get("resolve_time_ns", 0))
    if not started_ns <= attempt_ns <= settled_ns <= int(now * 1_000_000_000):
        raise ValueError("결제가 이번 검증 시간 범위에 속하지 않습니다. 송신·Router·실행 호스트의 시간 동기화를 확인하세요")
    hops = attempt.get("route", {}).get("hops", [])
    if len(hops) != 2 or hops[0].get("pub_key") != record["identity"] or hops[1].get("pub_key") != record["receiver"]:
        raise ValueError("별도 송신 노드에서 Router를 경유해 수신한 경로가 아닙니다")
    if str(hops[0].get("chan_id")) != record["incoming"]["id"] or str(hops[1].get("chan_id")) != record["outgoing"]["id"]:
        raise ValueError("승인한 입·출력 채널과 실제 경로가 다릅니다")
    if int(hops[0].get("amt_to_forward_msat", -1)) != amount_msat or int(hops[1].get("amt_to_forward_msat", -1)) != amount_msat:
        raise ValueError("경유 경로의 전달 금액이 다릅니다")
    if int(hops[0].get("fee_msat", -1)) != fee or int(hops[1].get("fee_msat", -1)) != 0:
        raise ValueError("경유 수수료와 송신 수수료가 일치하지 않습니다")
    # Timestamp_ns is router-local, as is started_at. External clocks may be
    # skewed; requiring both to fit is conservative and never fabricates proof.
    matches = [event for event in events
               if str(event.get("chan_id_in")) == record["incoming"]["id"]
               and str(event.get("chan_id_out")) == record["outgoing"]["id"]
               and int(event.get("amt_in_msat", -1)) == amount_msat + fee
               and int(event.get("amt_out_msat", -1)) == amount_msat
               and int(event.get("fee_msat", -1)) == fee
               and started_ns <= int(event.get("timestamp_ns", 0)) <= int(now * 1_000_000_000)]
    if len(matches) != 1:
        raise ValueError("이번 결제와 일치하는 로컬 경유 기록 하나를 확인하지 못했습니다")
    return record | {"state": "complete", "verified_at": now, "fee_msat": fee,
                     "forwarded_at_ns": str(matches[0]["timestamp_ns"])}


def current_evidence(record, identity, channels):
    if not record or record.get("schema") != "lnd-ops/router-proof/v1" or record.get("state") != "complete":
        return False
    if record.get("identity") != identity:
        return False
    for direction in ("incoming", "outgoing"):
        expected = record.get(direction, {})
        if not any(c.get("point") == expected.get("point") and c.get("id") == expected.get("id")
                   and c.get("peer") == expected.get("peer") and not c.get("private") for c in channels):
            return False
    return True
