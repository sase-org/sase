---
title: Mobile gateway
description: Look up pairing, push hints, storage, and private remote access.
---

# Mobile gateway

This page describes how to start, pair, and expose the workstation-hosted mobile
gateway.

The SASE mobile gateway is a workstation-hosted HTTP gateway for paired mobile clients.
The phone is only a client: it pairs with the host, stores a bearer token, calls
product-shaped SASE APIs, and subscribes to server-sent events. The gateway never
exposes a generic file, shell, or RPC surface.

The implementation is split across repos:

- `sase` owns user configuration, CLI startup, and lifecycle glue through
  `sase mobile gateway start`.
- `sase.integrations.mobile_notifications` is the stable Python facade used by the
  gateway host bridge to project local notifications, build attachment manifests, and
  execute generic gate or specialized question actions. The sibling
  `_mobile_notification_*` modules are internal implementation details.
- `sase.integrations.mobile_agents` and `sase.integrations.mobile_helpers` are the
  fixed-operation bridge facades used by the Rust gateway to list/launch/kill/retry/fork
  agents and to expose Patch, macro, bead, and update helpers. The sibling
  `_mobile_agent_*` and `_mobile_helper_*` modules are internal implementation details.
- `../sase-core/crates/sase_gateway` owns the Rust HTTP server, wire records,
  pairing/token storage, audit log, SSE event stream, and committed API contract
  snapshot.
- `../sase-android/README.md` is the Android client handoff for build/test commands,
  fake-gateway coverage, foreground UX smoke checks, and Epic 7 limitations.
- [`docs/contribute/mobile-mvp-runbook.md`](../../contribute/mobile-mvp-runbook.md) is
  the install/operate/security runbook for private APK distribution, Tailscale Serve
  remote access, push payload boundaries, troubleshooting, and rollback.

## Start Locally

Install the local checkout first so the Python CLI and sibling Rust binaries are
available:

```bash
just install-venv
cargo build -p sase_gateway --manifest-path ../sase-core/Cargo.toml
```

`sase mobile gateway start` uses `-c/--command` or `mobile_gateway.command` when one is
set. Otherwise it resolves `sase_gateway` from `PATH`, then from the running Python
environment's `bin/` directory, then from the sibling `../sase-core` debug or release
target. Use `-c /path/to/sase_gateway` only when you need to override that lookup.

Start the gateway from SASE:

```bash
sase mobile gateway start
```

When the effective built-in `gateway` service proc is available and enabled, this
command delegates ownership to the service host. It clears a boot-scoped stop, starts or
nudges the host, and returns instead of holding a foreground process. The gateway is
disabled by default and is enabled per machine in the overlay where it is wanted; enable
it for this machine and start it with:

```bash
sase service proc enable gateway
sase mobile gateway start
sase mobile gateway pair
```

The final command issues a pairing challenge into the gateway's local state root on this
machine. Pass `-H/--state-dir` when the gateway was started with a nondefault root. Use
`sase service proc show gateway`, `sase service proc logs gateway`, and the Services tab
for lifecycle and output. `sase service proc stop gateway` stops it until the next host
boot; `sase service proc disable gateway` changes the durable machine override.

Otherwise, `sase mobile gateway start` retains the foreground path. It runs the Rust
gateway on `127.0.0.1:7629`, waits for `GET /api/v1/health` to advertise
`pairing.issuance = owner_local_v1`, issues a one-time pairing challenge into that
shared state root, and prints:

```text
Starting SASE mobile gateway at http://127.0.0.1:7629
Pairing code: 123456
Pairing ID: pair_abc123
Expires at: 2026-05-06T15:00:00Z
Keep this process running while mobile clients connect.
```

On this fallback path, keep that process running while clients connect and stop it with
`Ctrl-C`. An unavailable, disabled, or unconfigured gateway service proc also falls back
to this path.

Useful startup overrides:

```bash
sase mobile gateway start -p 7630
sase mobile gateway start -H /tmp/sase-mobile-state
sase mobile gateway start -c "../sase-core/target/debug/sase_gateway"
```

`-H` sets the SASE home root passed to the Rust gateway as `--sase-home`; gateway files
are then stored below that root in `mobile_gateway/`. The matching configuration keys
live under `mobile_gateway`:

```yaml
mobile_gateway:
  bind_address: "127.0.0.1"
  port: 7629
  state_dir: ""
  allow_non_loopback: false
  command: ""
  agent_bridge_command: ""
  helper_bridge_command: ""
  push_provider: "disabled"
  fcm_project_id: ""
  fcm_service_account_json: ""
  fcm_credential_env: ""
  fcm_dry_run: false
  push_timeout_seconds: 5
  push_retry_limit: 1
  startup_timeout_seconds: 10
```

## Push Hints

Push delivery is disabled by default. When enabled, the gateway sends hint-only records
derived from the same event stream used by SSE. Push payloads contain safe IDs,
categories, reasons, and short display text; they do not contain bearer tokens, pairing
codes, prompt bodies, response text, attachment contents, attachment tokens, or host
paths. The mobile client must always fetch authenticated gateway state after a push wake
or notification tap.

Local development can use the test provider, which records attempted delivery without
leaving the process:

```bash
sase mobile gateway start -P test
```

FCM HTTP v1 is configured with non-secret pointers. Use either a service-account JSON
path or an environment variable containing a short-lived bearer token or service-account
JSON:

```bash
export SASE_FCM_CREDENTIAL='...'
sase mobile gateway start \
  -P fcm \
  -F my-firebase-project \
  -E SASE_FCM_CREDENTIAL \
  -D
```

Equivalent config:

```yaml
mobile_gateway:
  push_provider: "fcm"
  fcm_project_id: "my-firebase-project"
  fcm_service_account_json: "~/.config/sase/firebase-service-account.json"
  fcm_credential_env: ""
  fcm_dry_run: false
  push_timeout_seconds: 5
  push_retry_limit: 1
```

Only credential paths or environment-variable names are passed on the gateway command
line. Do not commit service-account JSON, Firebase project secrets,
`google-services.json`, signing keys, or local tailnet hostnames.

After pairing, a mobile client registers its provider token through the authenticated
session routes. `provider_token` is the opaque device/app token from the push provider;
treat it as device credential material and avoid committing or logging real values.

```bash
TOKEN="sase_mobile_example"

curl -sS -X POST http://127.0.0.1:7629/api/v1/session/push-subscriptions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 1,
    "provider": "fcm",
    "provider_token": "opaque-fcm-token",
    "app_instance_id": "pixel-9-app-instance",
    "device_display_name": "Pixel 9",
    "platform": "android",
    "app_version": "0.1.0",
    "hint_categories": ["notifications", "agents", "update"]
  }'
```

Duplicate registrations with the same provider token update the existing subscription.
Clients can list active subscriptions and revoke one by ID:

```bash
curl -sS http://127.0.0.1:7629/api/v1/session/push-subscriptions \
  -H "Authorization: Bearer $TOKEN"

SUBSCRIPTION_ID="sub_example"

curl -sS -X DELETE "http://127.0.0.1:7629/api/v1/session/push-subscriptions/$SUBSCRIPTION_ID" \
  -H "Authorization: Bearer $TOKEN"
```

## Private Remote Access And Packaging

The MVP runbook covers debug APK installation, signed release APKs, Firebase-configured
internal builds, versioning, Tailscale Serve setup, threat model, and rollback steps:

```text
docs/contribute/mobile-mvp-runbook.md
```

Keep the gateway on `127.0.0.1` when using Tailscale Serve. Tailscale proxies the
loopback gateway inside the tailnet, so the SASE process does not need a LAN or public
bind. Use `--allow-non-loopback` / `-L` only for explicit LAN or tailnet address binds
during short smoke windows. Loopback still shares the host with other local accounts:
challenge issuance is an owner-local filesystem operation, so another user on the same
machine cannot mint a pairing code by contacting the HTTP listener.

## Pairing Flow

The owner issues a pairing challenge with `sase mobile gateway pair` (or the foreground
`start` path). The CLI writes the challenge into `<sase_home>/mobile_gateway/pairing/`
as the gateway's OS account, then prints a six-digit code, a `pairing_id`, and a
five-minute expiration. HTTP callers cannot create challenges. `GET /api/v1/health`
advertises `pairing.issuance = owner_local_v1` so the CLI can refuse an old gateway
instead of falling back to unauthenticated issuance.

The issuer and the gateway must share the same state root: CLI `-H/--state-dir`, then
`mobile_gateway.state_dir`, then the runtime `SASE_HOME` / `HOME/.sase` default. Pairing
is supported on Linux and macOS, where the store enforces owner-only `0700`/`0600`
objects and rejects symlink, hard-link, wrong-owner, and attacker-writable containing
paths. New pairing is unavailable on platforms without that owner isolation.

A matching ID is consumed on the first finish attempt even when the code is wrong or
expired. Existing paired-device bearer tokens stay valid across this upgrade; this
change does not revoke them. Install the matching `sase-core` wheel and CLI, then
restart an old gateway before relying on the fix.

A mobile client finishes pairing by sending the owner-supplied code, the `pairing_id`,
and device metadata to `POST /api/v1/session/pair/finish`.

Example:

```bash
sase mobile gateway pair

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

Only `GET /api/v1/health` and `POST /api/v1/session/pair/finish` are unauthenticated.
`POST /api/v1/session/pair/start` is gone. All other routes require this bearer token.

## Storage And Revocation

Gateway state is stored under `<sase_home>/mobile_gateway/`. With the default SASE home,
that is `~/.sase/mobile_gateway/`.

- Paired devices live in `devices.json`.
- Mobile agent launch, kill, upload, and per-device project context state also lives
  under this directory.
- Raw bearer tokens are not written to disk; only SHA-256 token hashes are stored.
- Audit records append to `audit.jsonl` with device ID, endpoint, target ID when
  available, and outcome. Audit records avoid pairing codes and bearer tokens.
- The Rust store includes a revocation primitive so future UI/API work can mark a device
  revoked. Revoked tokens fail authentication.

## Network Exposure

The gateway binds to `127.0.0.1` by default. This is intentional: a local-only bind is
the safe desktop development and same-host test path.

For private remote access, prefer Tailscale Serve or an equivalent private tailnet path
that terminates access control outside the gateway. Keep the gateway bound to loopback
when possible, then serve the loopback endpoint through the private tailnet
configuration. The remote-dispatch setup path uses the same loopback-plus-Serve exposure
pattern; see the [Remote Dispatch Runbook](remote-dispatch.md) for target gateway
supervision, bootstrap issuance, and controller enrollment.

LAN and public-interface binds are explicit opt-in only:

```bash
sase mobile gateway start -b 100.64.0.10 -p 7629 -L
```

Only use `--allow-non-loopback` / `-L` on trusted private networks. Do not expose the
gateway directly to the public internet. The MVP pairing flow uses auditable one-time
pairing codes and bearer tokens, not a hardened mTLS or SPAKE2 protocol.

## Known MVP Limitations

- Notification reads are authoritative REST reads from the host JSONL store. Successful
  gateway state/action mutations publish `notifications_changed` SSE events, but passive
  file watching is intentionally out of the MVP.
- Attachment downloads are capped by the gateway's configured max attachment bytes.
  Oversized, missing, directory, traversal, symlinked, or unknown-risk files appear in
  manifests without download tokens.
- Telegram remains supported through the shared pending-action compatibility path. If an
  Telegram installations with only compatibility pending-action JSON can be read, but
  Telegram is not yet required to use the shared store as its only source of truth.
- Agent project context is intentionally an MVP metadata and known-project cwd selector.
  It does not expose arbitrary host directory selection, and clients must use SASE
  prompt syntax for VCS refs rather than sending raw repo paths.
- Workflow helper routes are native helper APIs, not generic command execution. Patch,
  macro, and bead helpers are read-only; macro PDF generation is optional; and update
  completion events are opportunistic while status polling remains authoritative.

## Related

- [Mobile gateway API](../../contribute/mobile-gateway-api.md) — host-bridge commands
  and contract.
- [Remote dispatch](remote-dispatch.md) — enroll a machine and launch with `%dispatch`.
- [Mobile MVP runbook](../../contribute/mobile-mvp-runbook.md) — install and operate.
- [Integrations](index.md) — other integration pages.
