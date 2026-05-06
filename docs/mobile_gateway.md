# Mobile Gateway

The SASE mobile gateway is a workstation-hosted HTTP gateway for future mobile clients. The phone is only a client: it
pairs with the host, stores a bearer token, calls product-shaped SASE APIs, and subscribes to server-sent events. The
gateway never exposes a generic file, shell, or RPC surface.

The implementation is split across repos:

- `sase` owns user configuration, CLI startup, and lifecycle glue through `sase mobile gateway start`.
- `../sase-core/crates/sase_gateway` owns the Rust HTTP server, wire records, pairing/token storage, audit log, SSE
  event stream, and committed API contract snapshot.

## Start Locally

Install the local checkout first so the Python CLI and sibling Rust binaries are available:

```bash
just install
cargo build -p sase_gateway --manifest-path ../sase-core/Cargo.toml
```

Start the gateway from SASE:

```bash
sase mobile gateway start
```

By default this runs the Rust gateway in the foreground on `127.0.0.1:7629`, waits for `GET /api/v1/health`, creates a
one-time pairing challenge, and prints:

```text
Starting SASE mobile gateway at http://127.0.0.1:7629
Pairing code: 123456
Pairing ID: pair_abc123
Expires at: 2026-05-06T15:00:00Z
Keep this process running while mobile clients connect.
```

Keep that process running while clients connect. Stop it with `Ctrl-C`.

Useful startup overrides:

```bash
sase mobile gateway start -p 7630
sase mobile gateway start -H /tmp/sase-mobile-state
sase mobile gateway start -c "../sase-core/target/debug/sase_gateway"
```

The matching configuration keys live under `mobile_gateway`:

```yaml
mobile_gateway:
  bind_address: "127.0.0.1"
  port: 7629
  state_dir: ""
  allow_non_loopback: false
  command: ""
  startup_timeout_seconds: 10
```

## Pairing Flow

The local host starts pairing with `POST /api/v1/session/pair/start`. The response contains a short-lived one-time code
and a `pairing_id`; it does not contain a long-lived credential. A mobile client finishes pairing by sending the code,
the `pairing_id`, and device metadata to `POST /api/v1/session/pair/finish`.

Example:

```bash
PAIRING_ID="pair_abc123"
PAIRING_CODE="123456"

curl -sS http://127.0.0.1:7629/api/v1/session/pair/finish \
  -H 'Content-Type: application/json' \
  -d "{
    \"schema_version\": 1,
    \"pairing_id\": \"$PAIRING_ID\",
    \"code\": \"$PAIRING_CODE\",
    \"device\": {
      \"display_name\": \"Pixel 9\",
      \"platform\": \"android\",
      \"app_version\": \"0.1.0\"
    }
  }"
```

The finish response returns the bearer token exactly once:

```json
{
  "schema_version": 1,
  "device": {
    "schema_version": 1,
    "device_id": "dev_example",
    "display_name": "Pixel 9",
    "platform": "android",
    "app_version": "0.1.0",
    "paired_at": "2026-05-06T15:00:00Z",
    "last_seen_at": null,
    "revoked_at": null
  },
  "token_type": "bearer",
  "token": "sase_mobile_example"
}
```

Store the token on the client as a secret. Future authenticated requests use:

```bash
TOKEN="sase_mobile_example"

curl -sS http://127.0.0.1:7629/api/v1/session \
  -H "Authorization: Bearer $TOKEN"
```

## Events

Authenticated clients subscribe to `GET /api/v1/events` with `Accept: text/event-stream`:

```bash
curl -N http://127.0.0.1:7629/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: text/event-stream'
```

Events are JSON `EventRecordWire` records carried in SSE `data:` lines. Each event has a stable monotonic string ID such
as `0000000000000001`. Reconnect with `Last-Event-ID` to replay buffered events newer than the last processed ID:

```bash
curl -N http://127.0.0.1:7629/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: text/event-stream' \
  -H 'Last-Event-ID: 0000000000000001'
```

The first implementation keeps the event buffer in memory. After a gateway restart or buffer overflow, clients must
handle a `resync_required` event by fetching full state again.

## Storage And Revocation

Gateway state is stored under `<sase_home>/mobile_gateway/`. With the default SASE home, that is
`~/.sase/mobile_gateway/`.

- Paired devices live in `devices.json`.
- Raw bearer tokens are not written to disk; only SHA-256 token hashes are stored.
- Audit records append to `audit.jsonl` with device ID, endpoint, target ID when available, and outcome. Audit records
  avoid pairing codes and bearer tokens.
- The Rust store includes a revocation primitive so future UI/API work can mark a device revoked. Revoked tokens fail
  authentication.

## Network Exposure

The gateway binds to `127.0.0.1` by default. This is intentional: a local-only bind is the safe desktop development and
same-host test path.

For private remote access, prefer Tailscale Serve or an equivalent private tailnet path that terminates access control
outside the gateway. Keep the gateway bound to loopback when possible, then serve the loopback endpoint through the
private tailnet configuration.

LAN and public-interface binds are explicit opt-in only:

```bash
sase mobile gateway start -b 100.64.0.10 -p 7629 -L
```

Only use `--allow-non-loopback` / `-L` on trusted private networks. Do not expose the gateway directly to the public
internet. The MVP pairing flow uses auditable one-time pairing codes and bearer tokens, not a hardened mTLS or SPAKE2
protocol.

## Contract Snapshot

The committed API contract snapshot for Android/client work lives in the sibling Rust repo:

```text
../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json
```

Regenerate it from the Rust workspace with:

```bash
cd ../sase-core
cargo run -p sase_gateway -- \
  --contract-out crates/sase_gateway/contracts/api_v1/mobile_api_v1.json
```

Keep the JSON snapshot, Rust wire tests, and this document aligned whenever the gateway route or record shape changes.
