"""Read recent settled forwards on this node; no payer access or payments."""


def observe(rpc, channels, now):
    start = max(0, int(now) - 86400)
    response = rpc('fwdinghistory', f'--start_time={start}',
                   f'--end_time={int(now)}', '--max_events=50000')
    public = {str(c['id']): c for c in channels if not c.get('private') and c.get('id')}
    matched = []
    for event in response.get('forwarding_events', []):
        incoming = public.get(str(event.get('chan_id_in')))
        outgoing = public.get(str(event.get('chan_id_out')))
        if not incoming or not outgoing or incoming['id'] == outgoing['id'] or incoming.get('peer') == outgoing.get('peer'):
            continue
        try:
            stamp = int(event['timestamp_ns']) / 1_000_000_000
            amount_in, amount_out, fee = (int(event[k]) for k in ('amt_in_msat', 'amt_out_msat', 'fee_msat'))
        except (KeyError, TypeError, ValueError):
            continue
        if start <= stamp <= now and amount_out > 0 and fee >= 0 and amount_in == amount_out + fee:
            matched.append((stamp, fee))
    return {'forwarding_observed_count': len(matched),
            'forwarding_observed_at': max((stamp for stamp, _ in matched), default=None),
            'forwarding_observed_fee_msat': sum(fee for _, fee in matched),
            'forwarding_window_start': start,
            'forwarding_window_capped': len(response.get('forwarding_events', [])) >= 50000}
