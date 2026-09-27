"""Bounded, journaled channel opens. A lost RPC response never authorizes retry."""
import re
import time
import uuid

from router_rpc import call, require_testnet
from router_store import operation_lock, read, write


def outpoint(utxo):
    point = utxo["outpoint"]
    if isinstance(point, str):
        match = re.fullmatch(r"([0-9a-f]{64}):(\d+)", point)
        if not match:
            raise ValueError("invalid UTXO outpoint")
        txid, index = match[1], int(match[2])
    else:
        txid, index = point["txid_str"], int(point["output_index"])
    if not re.fullmatch(r"[0-9a-f]{64}", txid):
        raise ValueError("invalid UTXO txid")
    if index < 0 or index > 0xffffffff:
        raise ValueError("invalid UTXO index")
    return f"{txid}:{index}"


def funding_selection(utxos, amount_sat, rate, fee_cap):
    """Upper-bound a standard single-funded tx, rather than promise an exact fee.

    Only fixed standard segwit inputs are accepted. 200 vB/input + 1000 vB
    overhead exceeds P2WPKH, nested P2WPKH, P2TR key-path and two outputs.
    Another 1000 sat covers discarded dust change. No PSBT, fee bump or extra
    input selection is authorized by this request.
    """
    selected, total = [], 0
    for utxo in sorted(utxos, key=lambda item: int(item["amount_sat"]), reverse=True):
        script = utxo.get("pk_script", "")
        address_type = utxo.get("address_type")
        if type(address_type) is int:
            address_type = {0: "WITNESS_PUBKEY_HASH", 1: "NESTED_PUBKEY_HASH", 4: "TAPROOT_PUBKEY"}.get(address_type)
        pattern = {"WITNESS_PUBKEY_HASH": r"0014[0-9a-f]{40}",
                   "TAPROOT_PUBKEY": r"5120[0-9a-f]{64}",
                   "NESTED_PUBKEY_HASH": r"a914[0-9a-f]{40}87"}.get(address_type)
        if pattern is None or not re.fullmatch(pattern, script):
            continue
        if int(utxo.get("confirmations", 0)) < 1:
            continue
        selected.append(outpoint(utxo))
        total += int(utxo["amount_sat"])
        upper_fee = rate * (1000 + 200 * len(selected)) + 1000
        if upper_fee > fee_cap:
            break
        if total >= amount_sat + upper_fee:
            return {"utxos": selected, "input_sat": total, "fee_upper_bound_sat": upper_fee}
    raise ValueError("확인된 표준 UTXO와 수수료 상한으로 채널을 열 수 없습니다. 금액·예산을 조정하세요")


def preview(peer, amount_sat, sat_per_vbyte, fee_cap_sat, total_cap_sat, rpc=call):
    if not re.fullmatch(r"0[23][0-9a-f]{64}", peer):
        raise ValueError("peer 공개키 형식이 잘못되었습니다")
    if any(type(value) is not int or value <= 0 for value in (amount_sat, sat_per_vbyte, fee_cap_sat, total_cap_sat)):
        raise ValueError("채널 금액·수수료율·예산은 양의 정수여야 합니다")
    info = rpc("getinfo")
    require_testnet(info)
    if peer == info["identity_pubkey"]:
        raise ValueError("자기 노드에 채널을 열 수 없습니다")
    channels = rpc("listchannels").get("channels", [])
    pending = rpc("pendingchannels")
    pending_open = [item["channel"] for item in pending.get("pending_open_channels", [])]
    if any(c.get("remote_pubkey") == peer for c in channels) or any(c.get("remote_node_pub") == peer for c in pending_open):
        raise ValueError("이 peer의 기존 또는 개설 대기 채널이 있습니다. 새로 요청하지 않습니다")
    if not any(p.get("pub_key") == peer for p in rpc("listpeers").get("peers", [])):
        raise ValueError("선택한 peer에 먼저 연결해야 합니다")
    # Count all channel capacity, including remote-funded/private/pending capacity:
    # deliberately stricter than only counting our own journal's opens.
    committed = sum(int(c["capacity"]) for c in channels + pending_open)
    if committed + amount_sat > total_cap_sat:
        raise ValueError("기존·대기 채널을 포함한 전체 채널 예산을 초과합니다")
    wallet = rpc("walletbalance")
    balance = int(wallet.get("confirmed_balance", 0))
    reserved = int(wallet.get("reserved_balance_anchor_chan", 0))
    locked = int(wallet.get("locked_balance", 0))
    if balance - reserved - locked < amount_sat + fee_cap_sat:
        raise ValueError("예약금·잠긴 잔액·수수료 예산을 제외한 확정 잔액이 부족합니다")
    selection = funding_selection(rpc("listunspent", "--min_confs=1").get("utxos", []), amount_sat, sat_per_vbyte, fee_cap_sat)
    return {"schema": "lnd-ops/router-open/v1", "identity": info["identity_pubkey"], "peer": peer,
            "amount_sat": amount_sat, "sat_per_vbyte": sat_per_vbyte, "fee_cap_sat": fee_cap_sat,
            "total_cap_sat": total_cap_sat, "committed_sat": committed,
            "confirmed_sat": balance, "reserved_sat": reserved, "locked_sat": locked, **selection}


def reconcile(root, rpc=call):
    record = read(root, "open-request.json")
    if not record or record["state"] not in ("submitting", "uncertain", "broadcast", "closing"):
        return record
    info = rpc("getinfo")
    require_testnet(info)
    if info["identity_pubkey"] != record["identity"]:
        raise ValueError("요청을 기록한 지갑 identity가 현재 지갑과 다릅니다")
    channels = rpc("listchannels").get("channels", [])
    pending = rpc("pendingchannels")
    point = record.get("channel_point")

    def matches(channel, peer_field):
        identified = channel.get('channel_point') == point if point else channel.get('memo') == record['memo']
        return identified and channel.get(peer_field) == record['peer'] and int(channel.get('capacity', 0)) == record['amount_sat']

    candidates = [("active" if c.get('active') else "confirmed", c)
                  for c in channels if matches(c, 'remote_pubkey')]
    for group in ('pending_open_channels', 'pending_closing_channels', 'pending_force_closing_channels', 'waiting_close_channels'):
        for item in pending.get(group, []):
            channel = item['channel']
            if matches(channel, 'remote_node_pub'):
                candidates.append(('broadcast' if group == 'pending_open_channels' else 'closing', channel))
    if len(candidates) == 1:
        state, channel = candidates[0]
        funding_point = channel.get('channel_point', '')
        if not re.fullmatch(r'[0-9a-f]{64}:\d+', funding_point):
            raise ValueError('관측한 funding 채널 식별자가 잘못되었습니다')
        record.update(state=state, channel_point=funding_point, reconciled_at=time.time())
    elif not candidates and point:
        # A memo is not available in ChannelCloseSummary. Never identify a
        # closed channel by peer/capacity alone when the funding point is lost.
        closed = [c for c in rpc('closedchannels').get('channels', []) if matches(c, 'remote_pubkey')]
        if len(closed) == 1 and int(closed[0].get('close_height', 0)) > 0 and re.fullmatch(
                r'[0-9a-f]{64}', closed[0].get('closing_tx_hash', '')) and closed[0].get('close_type') in (
                    'COOPERATIVE_CLOSE', 'LOCAL_FORCE_CLOSE', 'REMOTE_FORCE_CLOSE', 'BREACH_CLOSE', 0, 1, 2, 3):
            record.update(state='closed', closing_txid=closed[0]['closing_tx_hash'],
                          close_height=int(closed[0]['close_height']), reconciled_at=time.time())
        else:
            record.update(state='uncertain', reconciled_at=time.time())
    else:
        record.update(state='uncertain', reconciled_at=time.time())
    if record['state'] == 'uncertain':
        # Read the wallet transaction view as well; lack of pending is not
        # evidence that the remote funding attempt failed.
        transactions = rpc("listchaintxns").get("transactions", [])
        record.update(state="uncertain", reconciled_at=time.time(),
                      observed_txids=[item["tx_hash"] for item in transactions if int(item.get("time_stamp", 0)) >= int(record["submitted_at"])])
    write(root, "open-request.json", record)
    write(root, f"open-{record['request_id']}.json", record)
    return record


def submit(root, approved, rpc=call):
    with operation_lock(root):
        previous = reconcile(root, rpc)
        if previous and previous["state"] in ("submitting", "uncertain", "broadcast", "closing"):
            raise ValueError("이전 개설 요청을 확인 중입니다. 중복 개설을 차단했습니다")
        current = preview(approved["peer"], approved["amount_sat"], approved["sat_per_vbyte"],
                          approved["fee_cap_sat"], approved["total_cap_sat"], rpc)
        if current != approved:
            raise ValueError("잔액·입력·채널 상태가 바뀌었습니다. 새 요약을 확인하고 다시 승인하세요")
        request_id = uuid.uuid4().hex
        record = current | {"request_id": request_id, "memo": "lndops-router-" + request_id,
                            "state": "submitting", "submitted_at": time.time()}
        write(root, "open-request.json", record)
        write(root, f"open-{request_id}.json", record)
        try:
            result = rpc("openchannel", f"--node_key={record['peer']}", f"--local_amt={record['amount_sat']}",
                         f"--sat_per_vbyte={record['sat_per_vbyte']}", "--min_confs=1", "--push_amt=0",
                         f"--memo={record['memo']}", *[f"--utxo={point}" for point in record["utxos"]])
            txid = result["funding_txid"]
            index = int(result["output_index"])
            if not re.fullmatch(r"[0-9a-f]{64}", txid) or index < 0:
                raise ValueError("funding 응답 형식을 확인할 수 없습니다")
            record.update(state="broadcast", channel_point=f"{txid}:{index}")
        except BaseException:
            record.update(state="uncertain")
            write(root, "open-request.json", record)
            write(root, f"open-{request_id}.json", record)
            raise
        write(root, "open-request.json", record)
        write(root, f"open-{request_id}.json", record)
        return record
