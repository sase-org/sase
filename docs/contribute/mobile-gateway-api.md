---
title: Mobile gateway API
description: Host-bridge commands, events, and API contract for the mobile gateway.
---

# Mobile gateway API

This page documents the host-bridge commands, events, and committed API contract.

## Host Bridge CLI Commands

The gateway shells out only to fixed JSON-over-stdin bridge commands. These commands are
intentionally narrow integration surfaces for the Rust gateway and mobile clients; they
are not general user workflows and they do not accept mobile-supplied shell commands,
cwd values, environment variables, or host paths.

Agent bridge operations:

| Command                                   | Purpose                                                 |
| ----------------------------------------- | ------------------------------------------------------- |
| `sase mobile agent-bridge list-agents`    | Return running agents, with optional recent completions |
| `sase mobile agent-bridge resume-options` | Return copy/share/direct-launch resume prompt options   |
| `sase mobile agent-bridge launch-text`    | Launch a text prompt in home or known-project context   |
| `sase mobile agent-bridge launch-image`   | Store an uploaded image and launch an image prompt      |
| `sase mobile agent-bridge kill-agent`     | Kill an agent by exact name                             |
| `sase mobile agent-bridge retry-agent`    | Retry an agent by name, timestamp, or mobile context    |
| `sase mobile agent-bridge fork-agent`     | Fork a named agent with an instruction (`#fork:<name>`) |

A `kill-agent` request with `retain_for_retry: true` (used by remote fleet stops) skips
the dismissal record, so the stopped row stays visible and retryable; kill markers,
claims, and notification dismissal still happen.

Helper bridge operations:

| Command                                     | Purpose                                                            |
| ------------------------------------------- | ------------------------------------------------------------------ |
| `sase mobile helper-bridge changespec-tags` | List active Patch prompt tags; the operation name is legacy-stable |
| `sase mobile helper-bridge macro-catalog`   | Return the mobile-safe structured macro catalog                    |
| `sase mobile helper-bridge beads-list`      | List every non-closed bead, snoozed ones included                  |
| `sase mobile helper-bridge beads-show`      | Inspect one bead by ID                                             |
| `sase mobile helper-bridge update-start`    | Start the configured SASE update worker                            |
| `sase mobile helper-bridge update-status`   | Poll structured update worker status                               |

Both `beads-list` and `beads-show` payloads expose canonical `patch_name` and
`patch_bug_id` fields and also dual-write `changespec_name` and `changespec_bug_id` for
compatibility with older clients. New clients should prefer the Patch-named fields.

Notification bridge operations:

| Command                                           | Purpose                                       |
| ------------------------------------------------- | --------------------------------------------- |
| `sase mobile notification-bridge gate-action`     | Execute selected option IDs for any gate kind |
| `sase mobile notification-bridge question-action` | Execute a complete specialized question form  |

Both commands read a schema-versioned request from stdin and write one action result to
stdout. Gate action requests contain only a pending-action prefix,
`selected_option_ids`, and optional feedback.

## Hardening Test Commands

CI-friendly smoke slices for the three-repo mobile gateway surface:

```bash
# Android fake gateway, push hint, and background wake regressions.
(cd ../sase-android && ./gradlew testDebugUnitTest --tests org.sase.mobile.testing.BackgroundHardeningSmokeTest)
(cd ../sase-android && ./gradlew testDebugUnitTest --tests org.sase.mobile.testing.FakeGatewayTest)

# Optional local emulator/device coverage.
(cd ../sase-android && ./gradlew connectedDebugAndroidTest)

# Rust push subscription, test provider, and temporary listener smoke coverage.
(cd ../sase-core && cargo test -p sase_gateway push_subscription)
(cd ../sase-core && cargo test -p sase_gateway test_push_provider_records_hint_attempts)
(cd ../sase-core && cargo test -p sase_gateway listener_smoke_exercises_pairing_auth_and_session)

# Python gateway config/argv bridge coverage.
.venv/bin/pytest tests/test_mobile_gateway.py
```

Pairing challenges are issued only by the owner-local CLI into the gateway state root.
`POST /api/v1/session/pair/start` is gone; smoke the remaining unauthenticated surface
with health plus `POST /api/v1/session/pair/finish` after `sase mobile gateway pair`.
Restart an upgraded gateway before that CLI will issue. Existing paired-device tokens
stay valid.

## Events

Authenticated clients subscribe to `GET /api/v1/events` with
`Accept: text/event-stream`:

```bash
curl -N http://127.0.0.1:7629/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: text/event-stream'
```

Events are JSON `EventRecordWire` records carried in SSE `data:` lines. Each event has a
stable monotonic string ID such as `0000000000000001`. Reconnect with `Last-Event-ID` to
replay buffered events newer than the last processed ID:

```bash
curl -N http://127.0.0.1:7629/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: text/event-stream' \
  -H 'Last-Event-ID: 0000000000000001'
```

The first implementation keeps the event buffer in memory. After a gateway restart or
buffer overflow, clients must handle a `resync_required` event by fetching full state
again.

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

Poll incrementally with the activity cursor returned as `next_high_water`:

```bash
curl -sS "$BASE_URL/api/v1/notifications?newer_than=2026-08-01T13:05:00Z%7C7f3c...&limit=25" \
  -H "$AUTH_HEADER"
```

### Notification Activity Cursor

List reads are **current-state** reads: a due snooze is expired atomically inside the
store before the response is projected. Ordering, `limit`, and `newer_than` all use the
activity cursor `(activity_at, id)`, where `activity_at` is `resurfaced_at` when present
and `timestamp` otherwise. Each row carries both `timestamp` (the immutable original
send time, unchanged by a snooze) and `resurfaced_at` (`null` until a snooze expires),
and `next_high_water` is the `"<activity_at>|<id>"` cursor of the newest row in the
page.

Two consequences matter for clients:

- An old notification whose snooze just expired is **new activity**. It appears at the
  top of the first page and it crosses a `newer_than` cursor that was captured before it
  resurfaced, so an incremental poller sees it exactly once.
- The `|<id>` tie-breaker is what prevents two rows sharing an `activity_at` from hiding
  one another. Persist `next_high_water` verbatim. A cursor from the timestamp-only
  rollout format (no `|`) is still parsed and keeps its prior strict comparison, so
  stored cursors do not need a migration step.

When a list read expires a due snooze, the gateway publishes a `notifications_changed`
event with `reason: "snooze_expired"` **after** releasing the notification-store lock,
carrying the newest expired row's activity cursor (and its `notification_id` when
exactly one row expired). Connected clients can therefore refresh from one unrelated
read rather than waiting for another action. See the
[notifications reference](../reference/automation/notifications.md#snooze-expiry-and-resurfacing)
for the underlying state and timing contract.

Inspect a plan approval notification before acting on it:

```bash
NOTIFICATION_ID="abcdef12-plan"

curl -sS "$BASE_URL/api/v1/notifications/$NOTIFICATION_ID" \
  -H "$AUTH_HEADER"
```

Detail responses include full notes, action state, and attachment manifests. Every
actionable gate kind projects the same verified `branches` model. A branch contains
`options`; each option includes `id`, `label`, optional `icon`, `default_selected`,
`feedback` (`disabled`, `optional`, or `required`), and `inputs` — the option's declared
input fields, each with `id`, `label`, `type` (`word`, `line`, `text`, `path`, `agent`,
`int`, `bool`, `float`, or `enum`), `required`, `default`, `choices`, `placeholder`,
`help`, `secret`, and `repeatable`, mirroring the fields sase's TUI typed input form
already renders for macro launches. Group branches also include `submit` metadata with
the button label and optional icon. Mobile clients keep selection state locally and
submit option IDs from one branch, feedback, and each selected option's own input value
through the host bridge — never a command, path, cwd, or environment value. Download
tokens are minted only in detail responses, are bound to the authenticated device,
expire after a short TTL, and must still pass path and size checks at download time.

Mark a notification read or dismiss it without taking its pending action:

```bash
curl -sS -X POST "$BASE_URL/api/v1/notifications/$NOTIFICATION_ID/mark-read" \
  -H "$AUTH_HEADER"

curl -sS -X POST "$BASE_URL/api/v1/notifications/$NOTIFICATION_ID/dismiss" \
  -H "$AUTH_HEADER"
```

Both routes mutate only notification state and return `notification_id`, `read`,
`dismissed`, and `changed`. Repeating a route is idempotent: `changed` is `false` when
the requested state was already set. Successful state mutations audit the device and
publish `notifications_changed` so clients can refresh list/detail state.

All gate actions, including plan, epic, HITL, launch, and custom gates, use the
notification ID or any unique pending-action prefix. Submit the selected option IDs
exactly as presented by one branch:

```bash
PREFIX="abcdef12"

curl -sS -X POST "$BASE_URL/api/v1/actions/gate/$PREFIX" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":5,"selected_option_ids":["approve","commit"],"feedback":null}'
```

For a feedback branch, send its option ID and the supplied text:

```bash
curl -sS -X POST "$BASE_URL/api/v1/actions/gate/$PREFIX" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":5,"selected_option_ids":["feedback"],"feedback":"Revise the rollout section"}'
```

When a selected option declares `inputs`, submit its typed value under `option_inputs`,
keyed by option ID. An omitted optional field reaches the command as absent rather than
as its declared default — a default is authoring metadata a form seeds its control from,
never a value the host injects — so send every field the reviewer should be answering
with:

```bash
curl -sS -X POST "$BASE_URL/api/v1/actions/gate/$PREFIX" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":5,"selected_option_ids":["restart"],"feedback":null,"option_inputs":{"restart":{"mode":"quick"}}}'
```

`schema_version` bumped from 4 to 5 to add `option_inputs`; it is an optional field
(`#[serde(default)]` in the Rust wire struct), so an older client that omits it keeps
working exactly as before and every selected option is judged against its own schema
with an empty value.

Two submission shapes the other surfaces have are deliberately absent from this wire:

- **No shared `input`.** A bundle authored before `inputs` existed declares a raw
  `input_schema` and expects one value shared by every selected option. `option_inputs`
  cannot express that, so if such a schema requires a property, the gate must be
  answered from `sase gate answer --input` or sase's TUI raw editor.
- **No `retry`.** A reviewer who submits a group whose commands partly ran gets the
  `partial_attempt` error and cannot resume or restart from the phone. This is a dead
  end, never a silent re-run: use `sase gate answer --resume` / `--restart` or sase's
  TUI.

`tests/gate_conformance/` runs the shared fixture set through this bridge and skips
exactly the cases those two gaps cover, so the limitations stay stated rather than
drifting.

Question prompts support stable option IDs, option indices, labels, and custom free
text:

```bash
QUESTION_PREFIX="quest001"

curl -sS -X POST "$BASE_URL/api/v1/actions/question/$QUESTION_PREFIX/answer" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":4,"selected_option_id":"safe","global_note":"Use the durable path"}'

curl -sS -X POST "$BASE_URL/api/v1/actions/question/$QUESTION_PREFIX/answer" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":4,"selected_option_index":1}'

curl -sS -X POST "$BASE_URL/api/v1/actions/question/$QUESTION_PREFIX/custom" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":4,"custom_answer":"Use SQLite","global_note":"Small local DB"}'
```

Download an attachment by using a token from a notification detail response:

```bash
ATTACHMENT_TOKEN="att_example"

curl -sS "$BASE_URL/api/v1/attachments/$ATTACHMENT_TOKEN" \
  -H "$AUTH_HEADER" \
  -o attachment.bin
```

Mutating notification state and action routes audit device ID, endpoint, target
notification/prefix, and outcome. Duplicate, stale, ambiguous, already-handled,
unsupported, and missing-target cases return typed `ApiErrorWire` records and do not
overwrite existing response files.

## Agents

Agent lifecycle routes also require the paired device bearer token. They call fixed host
bridge operations, not mobile-supplied commands, cwd values, or environment variables.

List running agents:

```bash
curl -sS "$BASE_URL/api/v1/agents" \
  -H "$AUTH_HEADER"
```

Include recent completed/failed agents, filter by status or known project, and cap the
response:

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

Launch responses return `schema_version`, a `primary` slot, and all `slots`. Each
launched slot includes `slot_id`, `status: "launched"`, a short startup message, `name`
(the planned name when SASE knows it, otherwise `null`), and `artifact_dir` (a host path
when SASE can derive the canonical agent artifact directory, otherwise `null`). Clients
should treat a non-null `artifact_dir` as an opaque host path for display, retry
context, and host-bridge follow-up actions; they should not construct paths themselves.

Select a known SASE project context by passing the project name, not a path. The bridge
resolves only `<sase_home>/projects/<project>/<project>.sase` (falling back to legacy
`.gp`) and uses that file's `WORKSPACE_DIR` as the cwd for project-local prompt and
macro resolution. This context does not select a launch workspace by itself, so include
the normal workspace ref (a `+<project>`
[project tag](../reference/macros/reference-syntax.md#project-tags) for a known project)
in the prompt when you want the agent to run in that project:

```bash
curl -sS -X POST "$BASE_URL/api/v1/agents/launch" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"project":"sase","prompt":"+sase Run the focused mobile gateway tests","name":"mobile.sase"}'
```

Project lifecycle still applies. Disabled projects are hidden from broad mobile helper
catalogs. Passing `project` alone neither enables the project nor targets its workspace;
without a workspace ref, a bare prompt follows normal launch behavior and defaults to
`#git:home`. If the prompt contains an explicit known-project VCS ref, SASE re-enables a
disabled project before the claim. Run `sase project enable <project>` on the host first
when you want to make that transition separately.

For home-mode launches, omit `project` or pass `"home"`. For VCS-ref launches, include
the normal SASE prompt syntax such as `#gh:12345` or legacy `#gh@12345`; the bridge
normalizes legacy `@` refs before launch and persists a product-shaped context ID such
as `project:sase:gh:12345`. Android must never send host paths as project context.

Launch an image agent with base64 image bytes. The host stores the image under
SASE-owned gateway state and injects the absolute saved path into the agent prompt:

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

Successful launch, image launch, kill, and retry routes audit the paired device and
publish `agents_changed` SSE events with a reason and agent name when available. For
launched slots SASE can associate with an agent, mobile launch context, including any
returned artifact directory, is appended to
`<sase_home>/mobile_gateway/agent_launch_contexts.jsonl`; mobile kill context is stored
under `<sase_home>/mobile_gateway/agent_kill_contexts/`; and the last known
product-shaped project context per device is stored under
`<sase_home>/mobile_gateway/device_project_contexts/`.

## Workflow Helpers

Workflow helper routes require the paired device bearer token. They return direct JSON
records with a common `result` object containing `status`, `message`, `warnings`,
`skipped`, and `partial_failure_count`. Android should render `partial_success` by
showing the primary payload and surfacing the structured skipped rows; it should not
parse the human message text for control flow.

List active Patch tags for a known project:

```bash
curl -sS "$BASE_URL/api/v1/changespec-tags?project=sase&limit=25" \
  -H "$AUTH_HEADER"
```

Fetch the structured macro catalog for a native picker. Optional PDF generation is
best-effort and requested explicitly:

```bash
curl -sS "$BASE_URL/api/v1/macros/catalog?project=sase&tag=changespec&limit=50" \
  -H "$AUTH_HEADER"

curl -sS "$BASE_URL/api/v1/macros/catalog?project=sase&include_pdf=true" \
  -H "$AUTH_HEADER"
```

Each macro catalog entry includes the display-only `input_signature` plus mobile editor
metadata: `insertion`, `reference_prefix`, `kind`, `definition_path` when a real source
file can be resolved, and an `inputs` array of
`{name, type, required, default_display, position, repeatable, description}` records.
`repeatable` is a boolean and `description` is a string or null. String defaults are not
included: `default_display` is null for every string default, including `""`, and is
also null when the declared default is null. Numbers and booleans still appear as
`default_display` (`3`, `true`, `false`). `required` is true only when the input has no
default at all, so a null `default_display` does not by itself mean the argument is
required. Android should insert `insertion` when present, fall back to `#<name>` for
older gateways, and use `inputs` only for prompt-adjacent argument hints. The raw launch
prompt remains authoritative and is sent unchanged.

List active (`open`, `claimed`, `ready`, or `in_progress`) beads in a project and
inspect one bead:

```bash
curl -sS "$BASE_URL/api/v1/beads?project=sase&status=in_progress&limit=25" \
  -H "$AUTH_HEADER"

BEAD_ID="sase-26.4.6"

curl -sS "$BASE_URL/api/v1/beads/$BEAD_ID?project=sase" \
  -H "$AUTH_HEADER"
```

Omit `project` to use the paired device's remembered project context when present. Pass
`all_projects=true` to force a cross-project bead lookup across known SASE projects.

Start the fixed SASE update worker and poll structured job status:

```bash
curl -sS -X POST "$BASE_URL/api/v1/update/start" \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":1,"request_id":"mobile-update-1"}'

JOB_ID="job_123"

curl -sS "$BASE_URL/api/v1/update/$JOB_ID" \
  -H "$AUTH_HEADER"
```

The helper endpoints are read-only except `POST /api/v1/update/start`. Mobile cannot
provide a shell command, cwd, environment, workspace path, project file path, or
arbitrary bridge argv. The gateway invokes fixed `sase mobile helper-bridge <operation>`
commands; the update worker itself runs the built-in `sase update --json` engine.
Successful update start/status checks publish `helpers_changed` events, but polling
`GET /api/v1/update/{job_id}` is the authoritative completion path for the MVP.

## Contract Snapshot

The committed API contract snapshot for Android/client work lives in the sibling Rust
repo:

```text
../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json
```

Regenerate it from the Rust workspace with:

```bash
cd ../sase-core
cargo run -p sase_gateway -- \
  --contract-out crates/sase_gateway/contracts/api_v1/mobile_api_v1.json
```

Keep the JSON snapshot, Rust wire tests, and this document aligned whenever the gateway
route or record shape changes.

## Related

- [Mobile gateway](../reference/integrations/mobile-gateway.md) — pairing, push, and
  private remote access.
- [Integration APIs](integration-apis.md) — Python helpers for mobile clients.
- [Mobile MVP runbook](mobile-mvp-runbook.md) — install and operate.
