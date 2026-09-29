# Introduction to Lightning Node Operations

## What is the Lightning Network?

The Lightning Network is a payment network built on top of Bitcoin. It lets people transfer bitcoin through payment channels without recording every payment on the blockchain.

Bitcoin transactions can be broadcast quickly, but confirmation requires inclusion in a block. Blocks arrive roughly every ten minutes on average, and an individual transaction may wait longer.

That delay can be inconvenient when buying coffee or paying for an API request. Lightning allows payments to complete without waiting for a new block each time.

Lightning still uses bitcoin. A **satoshi**, usually shortened to **sat**, is one hundred millionth of a bitcoin:

```text
1 BTC = 100,000,000 sats
```

Sources: [Lightning specification](https://github.com/lightning/bolts/blob/master/00-introduction.md), [How Bitcoin works](https://bitcoin.org/en/how-it-works).

## How do payment channels work?

Think of a restaurant tab: instead of settling every purchase separately, the customer and restaurant keep updating a record.

However, a Lightning channel is **funded in advance**. The participants lock bitcoin into the channel before spending it. There is no promise to find the money at the end of the month.

Imagine Alice and Bob have a shared vault containing 100,000 sats. Their signed agreement specifies how much belongs to each person.

Ignoring fees and reserves, their balances might change like this:

| Channel state | Alice’s balance | Bob’s balance | Total |
|---|---:|---:|---:|
| Before payment | 70,000 sats | 30,000 sats | 100,000 sats |
| Alice pays Bob 10,000 sats | 60,000 sats | 40,000 sats | 100,000 sats |

The bitcoin stays in the channel. What changes is their agreement about how to divide it.

Technically, a funding transaction creates an on-chain output. The participants exchange signed **commitment transactions** describing how that output can be spent.

A UTXO is an unspent Bitcoin transaction output. During ordinary channel payments, the funding UTXO stays unspent. The nodes update signed transactions privately rather than creating a blockchain transaction each time.

Opening a channel and paying through it are therefore different operations:

```text
Open the channel:
    Lock bitcoin on-chain.

Make payments:
    Update signed channel states off-chain.

Close the channel:
    Settle the channel on-chain.
```

Channels can stay open across many payments. There is no monthly settlement requirement.

Sources: [Transaction formats](https://github.com/lightning/bolts/blob/master/03-transactions.md), [Channel lifecycle](https://github.com/lightning/bolts/blob/master/00-introduction.md).

## Why can the participants trust this arrangement?

The arrangement works because each participant has a way to enforce the channel state using Bitcoin transactions.

If both cooperate, they can close the channel together. If one disappears, the other can broadcast a commitment transaction and recover funds through the on-chain process, subject to applicable delays.

But what if Alice broadcasts an old state that gives her more money?

In the penalty-based channel design used here, updating the channel also revokes the previous state. Publishing a revoked state lets the other participant use a penalty mechanism to claim the cheating party’s funds.

Bitcoin does not automatically recognize which channel state is newest. Protection depends on detecting the revoked transaction and responding in time.

That is why blockchain monitoring matters. A watchtower can help monitor for this kind of cheating while a node is offline.

Source: [On-chain handling](https://github.com/lightning/bolts/blob/master/05-onchain.md).

## What makes it a network?

Alice does not need a direct payment channel with everyone she wants to pay. Payments can travel through existing channels:

```text
Alice ── channel ── Bob ── channel ── Carol
```

Bob acts as a **routing node**. He forwards the payment through his channel with Carol and may earn a routing fee.

Simply connecting two nodes as peers does not create a payment channel. A peer connection lets them communicate; a funded channel gives them balances they can transfer.

The next question is: how can Alice pay Carol without trusting Bob to keep his promise?

### HTLCs connect the payments

An **HTLC**, or **Hash Time-Locked Contract**, makes a payment conditional on revealing a secret. Its timeout provides a way to recover funds if the payment cannot complete.

Consider a simple invoice payment:

1. Carol generates a random secret, `X`, called the **payment preimage**.
2. She calculates `H = SHA256(X)`.
3. Her invoice gives Alice `H`, while Carol keeps `X` secret.
4. Alice offers Bob a conditional payment tied to `H`.
5. Bob offers Carol a conditional payment tied to the same `H`.

For an illustrative payment of 100 sats with a 1 sat routing fee:

```text
Alice → Bob:   101 sats, conditional on revealing X
Bob   → Carol: 100 sats, conditional on revealing X

Both conditions check:
SHA256(X) == H
```

After the conditional payments are securely established, Carol reveals `X` to fulfill Bob’s payment. Bob uses that same `X` to fulfill Alice’s payment. He receives 101 sats and pays 100 sats.

The payment offers move toward Carol. The secret moves back toward Alice:

```text
Conditional payments: Alice → Bob → Carol
Payment preimage:     Alice ← Bob ← Carol
```

This is not a hash chain or an identity check. The same hash condition links separate contracts so Bob can obtain his incoming payment when his outgoing payment is fulfilled.

These mechanics belong to the Lightning protocol, which multiple implementations support.

Source: [Conditional payments and forwarding](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md).

### Why are the timeouts different?

Bob needs time to claim his incoming payment after Carol claims hers. Therefore, his outgoing HTLC expires earlier than his incoming HTLC.

For example, using illustrative block heights:

```text
Bob → Carol:   expiry at block 900,000
Alice → Bob:   expiry at block 900,040
```

The gap gives Bob time to respond, including on-chain if necessary. Actual expiry gaps follow routing policies and safety requirements.

HTLC expiry uses Bitcoin block heights. A wallet’s “try this payment for 30 seconds” setting is a separate timeout.

A failed payment can resolve earlier through cooperation. If it requires on-chain resolution, funds may remain locked while the necessary transactions and timelocks complete.

Source: [HTLC timeout requirements](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md).

## What if Bob does not have enough money?

Suppose Carol should receive 100 sats, but Bob can send only 50 sats through his channel with her. That route cannot carry the full payment.

Even if Bob has plenty of bitcoin in his on-chain wallet, those funds are outside the channel. They do not automatically become available for forwarding.

This is why **liquidity is directional and specific to a channel**.

Consider a simplified channel between Alice and Bob:

| State | Alice’s side | Bob’s side | Capacity |
|---|---:|---:|---:|
| Before payment | 7,000 sats | 3,000 sats | 10,000 sats |
| Alice pays Bob 1,000 sats | 6,000 sats | 4,000 sats | 10,000 sats |

From Alice’s perspective, her side provides **outbound liquidity**, while Bob’s side provides **inbound liquidity**.

After paying Bob, Alice has less ability to send through this channel and more ability to receive through it.

These balances are a simplified model. Fees, reserves, pending HTLCs, and channel limits can reduce the amount actually transferable.

Source: [Understanding liquidity](https://docs.lightning.engineering/the-lightning-network/liquidity/understanding-liquidity).

Ordinary payments redistribute the channel’s balance without changing its capacity. Splicing can change capacity where supported, but it is a separate operation.

Lightning Labs provides **Loop** to help move value between on-chain funds and channel balances:

- **Loop Out:** Spend Lightning funds and receive on-chain bitcoin, creating more inbound liquidity.
- **Loop In:** Spend on-chain bitcoin and receive Lightning funds, increasing outbound liquidity.

Swaps involve fees and depend on successful execution. They do not guarantee a usable payment route.

Source: [Lightning Loop](https://github.com/lightninglabs/loop).

## Does every user need to operate a node?

No. Users can access Lightning through different kinds of wallets.

| Wallet arrangement | Who operates the Lightning infrastructure? | What does the user manage? |
|---|---|---|
| Custodial wallet | The provider | An account with the provider |
| Self-custodial mobile wallet | The app may embed node software and use supporting services | Keys and recovery information, depending on the design |
| Wallet connected to a personal node | The user | The node, its wallet, channels, and backups |

A wallet is the interface used to request and manage payments. Node software handles the Lightning protocol. Some applications combine both roles.

**LND**, short for *Lightning Network Daemon*, is one implementation of that node software. **lncli** is a command-line client that sends requests to a running LND instance.

For example:

```text
lncli command
      │
      ▼
Your running LND node
      │
      ▼
Payment channels and other Lightning nodes
```

Installing `lncli` alone does not give you a funded wallet or payment channels.

Source: [LND documentation](https://docs.lightning.engineering/lightning-network-tools/lnd).

## Where does Aperture fit?

Aperture sits in front of a web service and controls access to it. With **L402**, it can require a Lightning payment before allowing a request through.

A simplified flow is:

```text
1. Client requests a paid API.
2. Aperture returns HTTP 402 with an invoice and a macaroon.
3. Client pays the invoice using Lightning.
4. Client retries with the macaroon and payment preimage.
5. Aperture validates them and forwards the authorized request.
```

A macaroon is an authorization token. The payment preimage supplies proof associated with the paid invoice.

In an LND-backed setup, Aperture connects to the service operator’s node using configured connection details and credentials. The customer pays through their own wallet infrastructure.

Aperture therefore belongs to the application layer. LND handles Lightning payments; Aperture uses those payments to control access to a service.

Source: [Aperture documentation](https://github.com/lightninglabs/aperture).

## What does operating a Lightning node involve?

Running a node involves more than starting a container. The operator needs to maintain several things:

- **Blockchain synchronization:** keep the node aware of relevant on-chain activity.
- **Wallet and channel recovery:** protect credentials and maintain appropriate backups.
- **Connectivity:** keep useful peer connections available.
- **Liquidity:** maintain balances in the directions payments need.
- **Monitoring:** distinguish successful payments, forwarding events, failures, and funds still locked in pending payments.

A running node can be healthy and still receive no forwarding traffic. Other senders must choose routes through it, and those routes must have sufficient liquidity.

In this lab, we will use LND to examine those responsibilities directly: deploy a node, fund its wallet, open channels, send payments, observe forwarding, and monitor the results.
