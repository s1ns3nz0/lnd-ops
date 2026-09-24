# Repeated outgoing payment failures

## Trigger

`LndOpsRepeatedPaymentFailures` fires after at least three failed outgoing payments appear in the trailing-hour collector window for five minutes.

## Diagnose

1. Confirm wallet, chain, peer, channel, and liquidity health.
2. Compare failed-payment count with HTLC attempts and latency without exposing invoices, hashes, preimages, routes, or peer identifiers.
3. Inspect redacted LND logs for route, timeout, fee-limit, or liquidity errors.
4. Confirm whether failures came from one operator test or a broader handling problem.

## Recover

Do not retry payments automatically. Report the likely cause and obtain explicit operator approval for any new payment or liquidity action. Verify the next approved payment and the collector window afterward.
