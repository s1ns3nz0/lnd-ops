# Validation and authority

Run the relevant project test or check after a change. Required checks must run
on Linux, be vendor-neutral, and avoid local-only runtime assumptions.

For a new application or deployable artifact, test in a maintained Linux
Docker image appropriate to its runtime, pinned by digest when available.
Testing does not authorize an image push or deployment.

After code, configuration, or user-visible behavior changes, use a short
Paperthin `sip` and an independent `shower` review. Address material findings;
include the outcome in the handoff summary.

Publishing, merging, deploying, changing secrets, accessing production, or
contacting third parties requires explicit authorization for that task.
