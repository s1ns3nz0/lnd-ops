# Lightning liquidity below demo target

## Trigger

`LndOpsOutgoingLiquidityLow` or `LndOpsIncomingLiquidityLow` fires when aggregate active-channel liquidity remains below the 10,000 sat demo target for five minutes.

## Diagnose

1. Confirm the wallet is active, chain synchronized, peer connected, and channel active.
2. Compare aggregate and per-channel inbound/outbound bandwidth panels.
3. Inspect recent payments, pending HTLCs, commitment reserves, and channel status.
4. Treat inbound and outbound liquidity as separate constraints.

## Recover

Channel funding, Loop operations, payments, and channel closure are manual fund-moving actions. Present the evidence and obtain operator approval before changing liquidity. After an approved action, verify both target panels and payment handling.
