# Mobile Gateway

The SASE mobile gateway is a workstation-hosted HTTP gateway for future mobile clients. The phone is only a client: it
pairs with the host, stores a bearer token, calls product-shaped SASE APIs, and subscribes to server-sent events. The
gateway never exposes a generic file, shell, or RPC surface.

The implementation is split across repos:

- `sase` owns user configuration, CLI startup, and lifecycle glue through `sase mobile gateway start`.
- `sase.integrations.mobile_notifications` is the stable Python facade used by the gateway host bridge to project local
  notifications, build attachment manifests, and execute plan/HITL/question actions. The sibling
  `_mobile_notification_*` modules are internal implementation details.
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

## Notifications, Actions, And Attachments

All notification, action, and attachment routes require the paired device bearer token:

```bash
BASE_URL="http://127.0.0.1:7629"
TOKEN="sase_mobile_example"
AUTH_HEADER="Authorization: Bearer $TOKEN"
```

List unread, non-silent notifications newest first:

```bash
curl -sS "$BASE_URL/api/v1/notifications?unread=true&limit=25" \
  -H "$AUTH_HEADER"
```

Include dismissed or silent rows only when a client is rebuilding local state:

```bash
curl -sS "$BASE_URL/api/v1/notifications?include_dismissed=true&include_silent=true" \
  -H "$AUTH_HEADER"
```

Inspect a plan approval notification before acting on it:

```bash
NOTIFICATION_ID="abcdef12-plan"

curl -sS "$BASE_URL/api/v1/notifications/$NOTIFICATION_ID" \
  -H "$AUTH_HEADER"
```

Detail responses include full notes, action state, and attachment manifests. Download tokens are minted only in detail
responses, are bound to the authenticated device, expire after a short TTL, and must still pass path and size checks at
download time.

Mark a notification read or dismiss it without taking its pending action:

```bash
curl -sS -X POST "$BASE_URL/api/v1/notifications/$NOTIFICATION_ID/mark-read" \
  -H "$AUTH_HEADER"

curl -sS -X POST "$BASE_URL/api/v1/notifications/$NOTIFICATION_ID/dismiss" \
  -H "$AUTH_HEADER"
```

Both routes mutate only notification state and return `notification_id`, `read`, `dismissed`, and `changed`. Repeating a
route is idempotent: `changed` is `false` when the requested state was already set. Successful state mutations audit the
device and publish `notifications_changed` so clients can refresh list/detail state.

Plan approval actions use the notification ID or any unique pending-action prefix:

```bash
PREFIX="abcdef12"

curl -sS -X POST "$BASE_URL/api/v1/actions/plan/$PREFIX/approve" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"commit_plan":true,"run_coder":false}'

curl -sS -X POST "$BASE_URL/api/v1/actions/plan/$PREFIX/run" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"coder_prompt":"Focus on tests"}'

curl -sS -X POST "$BASE_URL/api/v1/actions/plan/$PREFIX/reject" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"feedback":"Please narrow the scope"}'

curl -sS -X POST "$BASE_URL/api/v1/actions/plan/$PREFIX/feedback" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"feedback":"Revise the rollout section"}'
```

Epic and legend approvals use the same route shape:

```bash
curl -sS -X POST "$BASE_URL/api/v1/actions/plan/$PREFIX/epic" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1}'

curl -sS -X POST "$BASE_URL/api/v1/actions/plan/$PREFIX/legend" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1}'
```

HITL prompts can be accepted, rejected, or returned with feedback:

```bash
HITL_PREFIX="hitl0001"

curl -sS -X POST "$BASE_URL/api/v1/actions/hitl/$HITL_PREFIX/accept" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1}'

curl -sS -X POST "$BASE_URL/api/v1/actions/hitl/$HITL_PREFIX/reject" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1}'

curl -sS -X POST "$BASE_URL/api/v1/actions/hitl/$HITL_PREFIX/feedback" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"feedback":"Use a smaller change"}'
```

Question prompts support stable option IDs, option indices, labels, and custom free text:

```bash
QUESTION_PREFIX="quest001"

curl -sS -X POST "$BASE_URL/api/v1/actions/question/$QUESTION_PREFIX/answer" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"selected_option_id":"safe","global_note":"Use the durable path"}'

curl -sS -X POST "$BASE_URL/api/v1/actions/question/$QUESTION_PREFIX/answer" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"selected_option_index":1}'

curl -sS -X POST "$BASE_URL/api/v1/actions/question/$QUESTION_PREFIX/custom" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"custom_answer":"Use SQLite","global_note":"Small local DB"}'
```

Download an attachment by using a token from a notification detail response:

```bash
ATTACHMENT_TOKEN="att_example"

curl -sS "$BASE_URL/api/v1/attachments/$ATTACHMENT_TOKEN" \
  -H "$AUTH_HEADER" \
  -o attachment.bin
```

Mutating notification state and action routes audit device ID, endpoint, target notification/prefix, and outcome.
Duplicate, stale, ambiguous, already-handled, unsupported, and missing-target cases return typed `ApiErrorWire` records
and do not overwrite existing response files.

## Agents

Agent lifecycle routes also require the paired device bearer token. They call fixed host bridge operations, not
mobile-supplied commands, cwd values, or environment variables.

List running agents:

```bash
curl -sS "$BASE_URL/api/v1/agents" \
  -H "$AUTH_HEADER"
```

Include recent completed/failed agents, filter by status or known project, and cap the response:

```bash
curl -sS "$BASE_URL/api/v1/agents?include_recent=true&project=sase&status=running&limit=25" \
  -H "$AUTH_HEADER"
```

Fetch copy/share/direct-launch resume and wait prompt options:

```bash
curl -sS "$BASE_URL/api/v1/agents/resume-options" \
  -H "$AUTH_HEADER"
```

Launch a text agent:

```bash
curl -sS -X POST "$BASE_URL/api/v1/agents/launch" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"prompt":"Summarize the current failures","name":"mobile.summary"}'
```

Launch in a known SASE project context by passing the project name, not a path. The bridge resolves only
`<sase_home>/projects/<project>/<project>.gp` and uses that file's `WORKSPACE_DIR` when it needs a project cwd:

```bash
curl -sS -X POST "$BASE_URL/api/v1/agents/launch" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"project":"sase","prompt":"Run the focused mobile gateway tests","name":"mobile.sase"}'
```

For home-mode launches, omit `project` or pass `"home"`. For VCS-ref launches, include the normal SASE prompt syntax
such as `#gh:12345` or legacy `#gh@12345`; the bridge normalizes legacy `@` refs before launch and persists a
product-shaped context ID such as `project:sase:gh:12345`. Android must never send host paths as project context.

Launch an image agent with base64 image bytes. The host stores the image under SASE-owned gateway state and injects the
absolute saved path into the agent prompt:

```bash
IMAGE_B64="$(base64 -w0 screenshot.png)"
IMAGE_BYTES="$(wc -c < screenshot.png)"

curl -sS -X POST "$BASE_URL/api/v1/agents/launch-image" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d "{
    \"schema_version\": 1,
    \"prompt\": \"Review this screenshot\",
    \"name\": \"mobile.image\",
    \"original_filename\": \"screenshot.png\",
    \"content_type\": \"image/png\",
    \"byte_length\": $IMAGE_BYTES,
    \"base64_image\": \"$IMAGE_B64\"
  }"
```

Kill an agent by exact name:

```bash
AGENT_NAME="mobile.summary"

curl -sS -X POST "$BASE_URL/api/v1/agents/$AGENT_NAME/kill" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"reason":"mobile"}'
```

Retry an agent by exact name, artifact timestamp, or durable mobile context:

```bash
curl -sS -X POST "$BASE_URL/api/v1/agents/$AGENT_NAME/retry" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1}'
```

Successful launch, image launch, kill, and retry routes audit the paired device and publish `agents_changed` SSE events
with a reason and agent name when available. Mobile launch context is appended to
`<sase_home>/mobile_gateway/agent_launch_contexts.jsonl`; mobile kill context is stored under
`<sase_home>/mobile_gateway/agent_kill_contexts/`; and the last known product-shaped project context per device is
stored under `<sase_home>/mobile_gateway/device_project_contexts/`.

## Storage And Revocation

Gateway state is stored under `<sase_home>/mobile_gateway/`. With the default SASE home, that is
`~/.sase/mobile_gateway/`.

- Paired devices live in `devices.json`.
- Mobile agent launch, kill, upload, and per-device project context state also lives under this directory.
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

## Known MVP Limitations

- Notification reads are authoritative REST reads from the host JSONL store. Successful gateway state/action mutations
  publish `notifications_changed` SSE events, but passive file watching is intentionally out of the MVP.
- Attachment downloads are capped by the gateway's configured max attachment bytes. Oversized, missing, directory,
  traversal, symlinked, or unknown-risk files appear in manifests without download tokens.
- Telegram remains supported through the shared pending-action compatibility path. If an older Telegram install has only
  legacy pending-action JSON, mobile can read it, but Telegram is not yet required to use the shared store as its only
  source of truth.
- Agent project context is intentionally an MVP metadata and known-project cwd selector. It does not expose arbitrary
  host directory selection, and clients must use SASE prompt syntax for VCS refs rather than sending raw repo paths.
