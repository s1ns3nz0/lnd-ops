"""Aggregate non-identifying LND payment and invoice metrics.

LND's paginated REST responses are processed in memory; no payment request,
hash, preimage, or peer identifier is exported as a metric label.
"""

import hashlib
import json
import os
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen


PAGE_SIZE = 1000
WINDOW_SECONDS = 3600
WALLET_STATES = ("NON_EXISTING", "LOCKED", "UNLOCKED", "RPC_ACTIVE", "SERVER_ACTIVE", "WAITING_TO_START")


def backup_metrics(source_path, status_path, now):
    """Describe live SCB and latest verified host-backup record without hashes."""
    source_present = os.path.isfile(source_path) and os.path.getsize(source_path) > 0
    source_size = os.path.getsize(source_path) if source_present else 0
    recorded = False
    current = False
    age = 0
    try:
        with open(status_path, encoding="utf-8") as status_file:
            epoch, plain_hash, cipher_hash, backup_format = status_file.read().split()
        epoch = int(epoch)
        valid_record = (
            epoch > 0 and len(plain_hash) == 64 and len(cipher_hash) == 64
            and backup_format == "gpg-symmetric-v1"
        )
        recorded = valid_record
        age = max(0, now - epoch) if valid_record else 0
        if source_present and valid_record:
            with open(source_path, "rb") as source_file:
                current = hashlib.sha256(source_file.read()).hexdigest() == plain_hash
    except (OSError, ValueError):
        pass
    lines = [
        "# HELP lnd_ops_scb_source_present Static channel backup exists in the LND data volume.",
        "# TYPE lnd_ops_scb_source_present gauge",
        f"lnd_ops_scb_source_present {int(source_present)}",
        "# HELP lnd_ops_scb_source_size_bytes Static channel backup size in bytes.",
        "# TYPE lnd_ops_scb_source_size_bytes gauge",
        f"lnd_ops_scb_source_size_bytes {source_size}",
        "# HELP lnd_ops_scb_backup_recorded Latest encrypted host-backup success record is present.",
        "# TYPE lnd_ops_scb_backup_recorded gauge",
        f"lnd_ops_scb_backup_recorded {int(recorded)}",
        "# HELP lnd_ops_scb_backup_current Latest encrypted host-backup plaintext hash matches the live SCB.",
        "# TYPE lnd_ops_scb_backup_current gauge",
        f"lnd_ops_scb_backup_current {int(current)}",
        "# HELP lnd_ops_scb_backup_age_seconds Age of the latest encrypted host-backup success record.",
        "# TYPE lnd_ops_scb_backup_age_seconds gauge",
        f"lnd_ops_scb_backup_age_seconds {age}",
    ]
    return "\n".join(lines) + "\n"


def certificate_metrics(cert_path):
    """Expose only the LND TLS certificate expiry timestamp."""
    decoded = ssl._ssl._test_decode_cert(cert_path)
    expiry = int(ssl.cert_time_to_seconds(decoded["notAfter"]))
    return "\n".join([
        "# HELP lnd_ops_tls_certificate_expiry_timestamp_seconds LND TLS certificate expiry as a Unix timestamp.",
        "# TYPE lnd_ops_tls_certificate_expiry_timestamp_seconds gauge",
        f"lnd_ops_tls_certificate_expiry_timestamp_seconds {expiry}",
    ]) + "\n"


def read_wallet_state(base_url, context):
    """Read LND's unauthenticated state endpoint without a macaroon."""
    with urlopen(f"{base_url}/v1/state", context=context, timeout=10) as response:
        state = json.load(response).get("state")
    if state not in WALLET_STATES:
        raise ValueError("unrecognized LND wallet state")
    return state


def wallet_state_metrics(state):
    """Emit a fixed one-hot state set, with no wallet identity or secrets."""
    lines = ["# HELP lnd_ops_wallet_state LND wallet and RPC state (one active state).",
             "# TYPE lnd_ops_wallet_state gauge"]
    lines.extend(f'lnd_ops_wallet_state{{state="{name}"}} {int(name == state)}' for name in WALLET_STATES)
    return "\n".join(lines) + "\n"


def read_pages(base_url, path, collection, offset_key, macaroon, context):
    """Read an entire forward-paginated LND collection."""
    offset = 0
    seen = set()
    while True:
        if offset in seen:
            raise ValueError(f"repeated {collection} pagination offset")
        seen.add(offset)
        params = {"index_offset": offset}
        if collection == "payments":
            params.update(max_payments=PAGE_SIZE, paginate_forwards="true", include_incomplete="true", omit_hops="true")
        else:
            params.update(num_max_invoices=PAGE_SIZE, reversed="false")
        request = Request(f"{base_url}{path}?{urlencode(params)}", headers={"Grpc-Metadata-macaroon": macaroon})
        with urlopen(request, context=context, timeout=10) as response:
            payload = json.load(response)
        items = payload.get(collection, [])
        yield from items
        if len(items) < PAGE_SIZE:
            return
        next_offset = int(payload[offset_key])
        if next_offset <= offset:
            raise ValueError(f"non-advancing {collection} pagination offset")
        offset = next_offset


def aggregate(payments, invoices, now):
    """Return Prometheus text for the trailing hour, without sensitive labels."""
    since = now - WINDOW_SECONDS
    counts = {state: 0 for state in ("SUCCEEDED", "FAILED", "IN_FLIGHT")}
    fee_sat = 0
    latency_sum = 0.0
    latency_count = 0
    for payment in payments:
        created_ns = int(payment.get("creation_time_ns", 0))
        if not (since <= created_ns / 1_000_000_000 <= now):
            continue
        state = payment.get("status")
        if state not in counts:
            continue
        counts[state] += 1
        if state == "SUCCEEDED":
            fee_sat += int(payment.get("fee_sat", 0))
            resolved_ns = max((int(htlc.get("resolve_time_ns", 0)) for htlc in payment.get("htlcs", [])), default=0)
            if resolved_ns >= created_ns and resolved_ns > 0:
                latency_sum += (resolved_ns - created_ns) / 1_000_000_000
                latency_count += 1

    settled = 0
    for invoice in invoices:
        state = invoice.get("state")
        if state == "SETTLED" and since <= int(invoice.get("settle_date", 0)) <= now:
            settled += 1

    lines = ["# HELP lnd_ops_outgoing_payments_1h Payments created in the trailing hour by current status.",
             "# TYPE lnd_ops_outgoing_payments_1h gauge"]
    lines.extend(f'lnd_ops_outgoing_payments_1h{{status="{state}"}} {count}' for state, count in counts.items())
    lines += ["# TYPE lnd_ops_outgoing_fee_sat_1h gauge", f"lnd_ops_outgoing_fee_sat_1h {fee_sat}",
              "# TYPE lnd_ops_outgoing_latency_seconds_sum_1h gauge", f"lnd_ops_outgoing_latency_seconds_sum_1h {latency_sum:.6f}",
              "# TYPE lnd_ops_outgoing_latency_samples_1h gauge", f"lnd_ops_outgoing_latency_samples_1h {latency_count}",
              "# TYPE lnd_ops_received_invoices_1h gauge", f'lnd_ops_received_invoices_1h{{state="SETTLED"}} {settled}']
    return "\n".join(lines) + "\n"


def main():
    cert = os.environ["LND_TLS_CERT"]
    macaroon_path = os.environ["LND_READONLY_MACAROON"]
    scb_source = os.environ["LND_SCB_SOURCE"]
    backup_status = os.environ["LND_BACKUP_STATUS"]
    base_url = os.environ.get("LND_REST_URL", "https://127.0.0.1:8080")
    context = ssl.create_default_context(cafile=cert)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/metrics", "/wallet-state"):
                self.send_error(404)
                return
            try:
                if self.path == "/wallet-state":
                    body = wallet_state_metrics(read_wallet_state(base_url, context)).encode()
                else:
                    with open(macaroon_path, "rb") as file:
                        macaroon = file.read().hex()
                    now = int(time.time())
                    payments = read_pages(base_url, "/v1/payments", "payments", "last_index_offset", macaroon, context)
                    invoices = read_pages(base_url, "/v1/invoices", "invoices", "last_index_offset", macaroon, context)
                    body = (
                        aggregate(payments, invoices, now)
                        + backup_metrics(scb_source, backup_status, now)
                        + certificate_metrics(cert)
                    ).encode()
            except (OSError, ValueError, KeyError, TimeoutError, URLError) as error:
                self.log_error("collection failed: %s", error)
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(("0.0.0.0", 9093), Handler).serve_forever()


if __name__ == "__main__":
    main()
