"""Read recent settled forwards on this node; no payer access or payments."""


def observe(rpc, channels, now):
    start = max(0, int(now) - 86400)
    response = rpc('fwdinghistory', f'--start_time={start}',
                   f'--end_time={int(now)}', '--max_events=50000')
    public = {str(c['id']): c for c in channels if not c.get('private') and c.get('id')}
    matched = []
    recent = []
    known = {str(c["id"]): c for c in channels if c.get("id")}
    for event in response.get('forwarding_events', []):
        incoming = public.get(str(event.get('chan_id_in')))
        outgoing = public.get(str(event.get('chan_id_out')))
        try:
            stamp = int(event['timestamp_ns']) / 1_000_000_000
            amount_in, amount_out, fee = (int(event[k]) for k in ('amt_in_msat', 'amt_out_msat', 'fee_msat'))
        except (KeyError, TypeError, ValueError):
            continue
        if start <= stamp <= now and amount_out > 0 and fee >= 0 and amount_in == amount_out + fee:
            recent.append({'timestamp': stamp, 'amount_msat': amount_out, 'fee_msat': fee,
                           'incoming_channel': str(event.get('chan_id_in', '?')),
                           'outgoing_channel': str(event.get('chan_id_out', '?')),
                           'incoming_peer': known.get(str(event.get('chan_id_in')), {}).get('peer'),
                           'outgoing_peer': known.get(str(event.get('chan_id_out')), {}).get('peer')})
            if incoming and outgoing and incoming['id'] != outgoing['id'] and incoming.get('peer') != outgoing.get('peer'):
                matched.append((stamp, fee))
    recent.sort(key=lambda item: item['timestamp'], reverse=True)
    return {'forwarding_recent': recent[:5],
            'forwarding_history_count': len(recent),
            'forwarding_history_fee_msat': sum(item['fee_msat'] for item in recent),
            'forwarding_observed_count': len(matched),
            'forwarding_observed_at': max((stamp for stamp, _ in matched), default=None),
            'forwarding_observed_fee_msat': sum(fee for _, fee in matched),
            'forwarding_window_start': start,
            'forwarding_window_capped': len(response.get('forwarding_events', [])) >= 50000}
