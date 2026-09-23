# Regtest exercise (Mac Lima or Windows WSL 2)

This exercise uses disposable regtest bitcoin only. Run `ops/bootstrap`, `ops/deploy regtest`, and `ops/verify regtest` first. Exit code `10` from verify means the infrastructure is ready but a wallet must be created or unlocked. The operator must create both wallets interactively and record each seed offline. Never put a seed, password, macaroon, or wallet database in this repository or a shell transcript.

Set `KUBECONFIG` to the path printed by `ops/bootstrap` in your shell. The commands below use `kubectl` against that cluster. Use a separate seed and password for each LND node. Set the uppercase address, public key, and payment request variables from each preceding command's output before running the next command.

## Create wallets

```sh
kubectl -n lnd-regtest exec -it lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest create
kubectl -n lnd-regtest exec -it lnd-1-0 -- lncli --lnddir=/data/.lnd --network=regtest create
ops/verify regtest
```

If the Pods restart later, use `lncli ... unlock` interactively. Do not pass wallet passwords as command arguments.

After both wallets are unlocked, `ops/exercise-regtest` can create a disposable Bitcoin mining wallet, fund `lnd-0`, open a channel to `lnd-1`, and make 10,000 sat payments in both directions. A new one-sided channel does not immediately give `lnd-1` spendable outbound liquidity because of its channel reserve, so the script first sends a one-time 50,000 sat liquidity-seeding payment when the remote balance is below 30,000 sats. The equal 10,000 sat forward and reverse payments then leave the post-seed balance unchanged across normal reruns. It verifies both outgoing payments, both settled invoices, and the 10 sat fee limit, giving each node real send, receive, inbound-liquidity, and outbound-liquidity observations for monitoring. It prints only public node and channel identifiers and can be rerun without opening another channel. It exits `10` before mutating Bitcoin or channels when a wallet is missing. The commands below show the first direction individually if you prefer to run them manually. The automated success path remains untested until the wallets are created.

```sh
ops/exercise-regtest
ops/verify regtest
```

## Fund and open a channel

Create a Bitcoin Core mining wallet and mine 101 blocks to mature its coinbase output:

```sh
kubectl -n lnd-regtest exec bitcoin-0 -- bitcoin-cli -regtest -rpcuser=regtest -rpcpassword=local-regtest-only createwallet miner
kubectl -n lnd-regtest exec bitcoin-0 -- bitcoin-cli -regtest -rpcuser=regtest -rpcpassword=local-regtest-only getnewaddress
kubectl -n lnd-regtest exec bitcoin-0 -- bitcoin-cli -regtest -rpcuser=regtest -rpcpassword=local-regtest-only generatetoaddress 101 "$MINER_ADDRESS"
```

Get an address from `lnd-0`, send regtest bitcoin to it, and mine confirmations:

```sh
kubectl -n lnd-regtest exec lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest newaddress p2wkh
kubectl -n lnd-regtest exec bitcoin-0 -- bitcoin-cli -regtest -rpcuser=regtest -rpcpassword=local-regtest-only sendtoaddress "$LND_0_ADDRESS" 0.02
kubectl -n lnd-regtest exec bitcoin-0 -- bitcoin-cli -regtest -rpcuser=regtest -rpcpassword=local-regtest-only generatetoaddress 6 "$MINER_ADDRESS"
kubectl -n lnd-regtest exec lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest walletbalance
```

Get `lnd-1`'s `identity_pubkey` from `getinfo`, then connect and open a channel from `lnd-0`:

```sh
kubectl -n lnd-regtest exec lnd-1-0 -- lncli --lnddir=/data/.lnd --network=regtest getinfo
kubectl -n lnd-regtest exec lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest connect "$LND_1_PUBKEY@lnd-1:9735"
kubectl -n lnd-regtest exec lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest openchannel --node_key "$LND_1_PUBKEY" --local_amt 1000000
kubectl -n lnd-regtest exec bitcoin-0 -- bitcoin-cli -regtest -rpcuser=regtest -rpcpassword=local-regtest-only generatetoaddress 6 "$MINER_ADDRESS"
kubectl -n lnd-regtest exec lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest listchannels
```

Create a 10,000 sat invoice on `lnd-1`, pay it from `lnd-0`, and check the result on both sides. The automated script first seeds remote liquidity if required, then creates another 10,000 sat invoice on `lnd-0` and pays it from `lnd-1` to prove the reverse direction:

```sh
kubectl -n lnd-regtest exec lnd-1-0 -- lncli --lnddir=/data/.lnd --network=regtest addinvoice --amt 10000
kubectl -n lnd-regtest exec lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest payinvoice --pay_req "$PAYMENT_REQUEST"
kubectl -n lnd-regtest exec lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest listpayments
kubectl -n lnd-regtest exec lnd-1-0 -- lncli --lnddir=/data/.lnd --network=regtest listinvoices
```

Record only node public keys, channel points, block heights, payment status, and command outcomes in evidence. Keep both original wallet volumes until the recovery exercise has been verified.

## Preserve the regtest SCB

After the channel appears in `listchannels`, copy and verify **both nodes'** encrypted Static Channel Backups outside K3s. Each wallet has its own seed and SCB:

```sh
ops/backup-scb regtest lnd-0
ops/backup-status regtest lnd-0
ops/backup-scb regtest lnd-1
ops/backup-status regtest lnd-1
```

Each file goes to `~/lnd-ops-backups/regtest/<node>/channel.backup` on Mac or `<WSL-backing-drive>:\lnd-ops-backups\regtest\<node>\channel.backup` on Windows. Keep each seed offline and separate from its file. LND's [recovery guide](https://github.com/lightningnetwork/lnd/blob/master/docs/recovery.md) says seed plus SCB recovery initiates Data Loss Protection and closes the old channel to recover settled funds on-chain; it does not recreate an active channel.

## Isolated seed and SCB recovery exercise

Use only the disposable regtest channel from this runbook. `ops/prepare-regtest-recovery` requires a verified host SCB and one channel from `lnd-0` to `lnd-1`. It creates `lnd-regtest-recovery` with a fresh PVC, stops original `lnd-0`, and copies the host SCB into the new Pod. It leaves the original PVC intact and marks the original namespace so `ops/deploy regtest` refuses to restart that identity. This procedure deliberately causes the channel to close; do not use it for an ordinary redeploy.

```sh
ops/prepare-regtest-recovery --confirm-disposable
kubectl -n lnd-regtest-recovery exec -it lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest create --multi_file=/data/recovery.backup
```

At the interactive prompt, restore **the original `lnd-0` seed** from your offline record. Do not enter the `lnd-1` seed. Keep the seed and password out of shell arguments, repository files, and captured logs. After the wallet finishes opening, get `lnd-1`'s public key from `lncli getinfo`. The recovered node may connect to the peer automatically; if it does not, connect it using the peer's full service name:

```sh
kubectl -n lnd-regtest exec lnd-1-0 -- lncli --lnddir=/data/.lnd --network=regtest getinfo
kubectl -n lnd-regtest-recovery exec lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest connect "$LND_1_PUBKEY@lnd-1.lnd-regtest.svc.cluster.local:9735"
kubectl -n lnd-regtest exec bitcoin-0 -- bitcoin-cli -regtest -rpcuser=regtest -rpcpassword=local-regtest-only -rpcwallet=miner getnewaddress
kubectl -n lnd-regtest exec bitcoin-0 -- bitcoin-cli -regtest -rpcuser=regtest -rpcpassword=local-regtest-only generatetoaddress 6 "$MINER_ADDRESS"
ops/verify-regtest-recovery
```

If verification reports pending closure or sweep, mine further regtest blocks and rerun it after the nodes process them. A passing result requires the recovered public key to equal the original, original `lnd-0` to remain stopped with the same PVC, the host and recovery Pod SCB hashes to match, `lnd-1` to record the channel close, and the recovered on-chain balance to rise above its pre-recovery balance. Keep the original LND PVC stopped even after a pass. The prepare and verification success paths have not yet run with real wallets and an SCB; do not count this documented procedure as stage 2 proof until they do.

After saving secret-free evidence of a passing recovery, keep the original wallet PVC and the recovery evidence. Wallet recreation is not required for MVP redeployment proof. Never restart the original and recovered copies of the same identity concurrently. `ops/reset-recovered-regtest --confirm-disposable` remains available only when the operator deliberately wants to retire the entire disposable regtest exercise after recovery; it is no longer an MVP acceptance step.

To reuse the original wallet, retire the recovered copy first and then resume the preserved original PVC:

```sh
ops/finish-regtest-recovery --preserve-original-wallet
kubectl -n lnd-regtest exec -it lnd-0-0 -- lncli --lnddir=/data/.lnd --network=regtest unlock
ops/verify regtest
```

The finish command refuses to proceed until recovery verification passes, stops and deletes the recovered copy before starting the original identity, and checks that the original PVC UID is unchanged. The original database will observe the already-confirmed channel closure when it synchronizes.

```sh
ops/reset-recovered-regtest --confirm-disposable
ops/deploy regtest
ops/verify regtest
```

If the optional reset is used, it deletes the disposable wallet-bearing PVCs and requires new wallets on the next deployment. Ordinary MVP redeployment instead preserves the existing PVCs and identities.
