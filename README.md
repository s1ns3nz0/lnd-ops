# lnd-ops

Reproducible Lightning node operator portfolio project for Mac arm64 Lima K3s and Windows WSL 2 K3s. Both run the same Helm stack with separate testnet wallets and optional regtest profiles. The [implementation roadmap](docs/implementation-roadmap.md) defines the MVP, multi-platform images, and repeat-deployment contract. The [operator plan](docs/operator-plan.md) records the target architecture, while the [observability plan](docs/observability-plan.md) records dashboards, alerts, and runbook priorities. Installation runbooks will be added with the Helm charts.

## Repository harness

A small, repository-local harness for predictable Codex work. It keeps only
the rules that affect delivery: MVP first, focused discovery, portable tests,
and a short final review.

## Flow

1. Build the smallest testable slice first.
2. Use Graft to find the relevant code and make the change.
3. Run the relevant test or check.
4. For code, configuration, or user-visible behavior, do a short `sip` and
   fresh-context `shower` review.
5. Summarize the result concisely.

`$grill-me` runs before work only when a request can change product design,
security, an external integration, data, irreversible state, or external
state. Uploads, formatting, pushes, and merges do not need it.

## Setup

Requires Node.js 20 or newer.

```sh
npm run harness:init
npm run harness:check
npm test
```

`harness.config.json` is the machine-readable policy. Add project adapter
commands there when the repository has a real stack, then run:

```sh
npm run harness:verify
```

The agent environment provides Graft, `$grill-me`, `sip`, and `shower`; this
template does not install or wrap those skills. `harness:check` validates the
policy, while `harness:verify` also runs the active adapter commands.

Required tests must run on Linux and be vendor-neutral. New applications and
deployable artifacts run their relevant tests in a maintained Linux Docker
image selected for the project's runtime; use a digest when available.
Building or testing an image does not authorize pushing it or deploying.

## Safety

Work stays inside the repository. Publishing, merging, deployment, secret
changes, production access, and third-party contact require explicit task
authorization.
