# SASE Mobile MVP Install and Usage Research

Date: 2026-05-07

## Question

What did the recently completed mobile MVP work ship, and how should a user install and use the new Android app?

## Executive Summary

The mobile MVP is a private Android client for a workstation-hosted SASE gateway. The phone does not run agents or embed
the full SASE runtime. It pairs with the host, stores a bearer token, renders SASE state, and sends product-shaped
requests back to the gateway.

The practical user story is:

1. Build or install the Android APK from `../sase-android`.
2. Build the Rust host gateway from `../sase-core`.
3. Start the gateway from this repo with `sase mobile gateway start`.
4. Pair from Android Settings using the gateway base URL, pairing ID, and one-time code.
5. Use the app for inbox actions, agent launch/lifecycle, helper pickers, update status, foreground connected mode, and
   optional FCM push hints.

For remote physical-device use, the safest MVP path is loopback gateway plus Tailscale Serve. Direct LAN binds require
explicit `-L`, and public tunnels/Funnel are not recommended.

## Evidence Reviewed

- `sase bead show sase-26` showed closed legend `sase-26`, "SASE Mobile MVP Legend", with seven closed child epics.
- Plans reviewed:
  - `sdd/legends/202605/sase_mobile_mvp_legend.md`
  - `sdd/epics/202605/mobile_gateway_epic_1.md`
  - `sdd/epics/202605/mobile_gateway_epic_2.md`
  - `sdd/epics/202605/mobile_gateway_epic_3.md`
  - `sdd/epics/202605/mobile_gateway_epic_4.md`
  - `sdd/epics/202605/mobile_gateway_epic_5.md`
  - `sdd/epics/202605/mobile_gateway_epic_6.md`
  - `sdd/epics/202605/mobile_gateway_epic_7.md`
- User-facing docs reviewed:
  - `docs/mobile_gateway.md`
  - `docs/mobile_mvp_runbook.md`
  - `../sase-android/README.md`
  - `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`
- Related commits sampled:
  - This repo: `1d91c216` mobile gateway CLI, `93b13d7b` gateway docs, `0c7cf0bc` notification API docs,
    `af1f66e8` mobile MVP runbook, `e0c984b1` push config bridge, `9fdb4377` close legend.
  - `../sase-core`: `0b23b35` gateway crate, `61c5dc6` pairing auth, `dd62999` SSE stream, `a0e52cb`
    notification endpoints, `497247f` text launch bridge, `aaf2659` helper bridge, `c8a64ed` push subscription
    contract, `d61edcf` push dispatcher, `c2d34eb` FCM hint key fix.
  - `../sase-android`: `c6cf460` app scaffold, `e91e839` REST client, `b6fa458` pairing/session,
    `b1bde27` inbox/detail UI, `e26588d` text launch, `082cc3f` image launch, `a0d3716` foreground connected mode,
    `dc343c2` FCM registration, `42f2237` APK packaging docs.
- Cross-checked against the runtime CLI surface (`sase mobile --help`, `sase mobile gateway --help`,
  `sase mobile gateway start --help`) and the contract snapshot's `EventPayloadWire`/`ApiErrorWire` records.

## What Shipped

The completed `sase-26` legend covers seven closed epics:

- Host gateway foundation and pairing.
- Notification inbox, pending actions, and attachments.
- Agent lifecycle, launch, retry, and image input.
- Workflow helper APIs.
- Android app foundation.
- Android action, agent, and helper UX.
- Background delivery, packaging, and hardening.

The resulting app surface includes:

- Settings and host pairing.
- Inbox list and notification detail.
- Plan, HITL, and question actions, including feedback/custom-answer draft preservation.
- Text and image agent launch.
- Agent list, kill, retry, resume, and wait flows.
- ChangeSpec tag, xprompt, bead, and update helper screens.
- SSE-backed foreground refresh, foreground connected mode, Android local notification hints, and optional FCM push
  hints.

The gateway API is versioned under `/api/v1`. Public unauthenticated routes are limited to health and pairing:

- `GET /health`
- `POST /session/pair/start`
- `POST /session/pair/finish`

After pairing, the client authenticates with `Authorization: Bearer <token>` for session, events, notifications,
attachments, actions, agents, helper endpoints, update endpoints, and push subscriptions.

## Install Path

### 1. Prepare Android Build Tools

The Android repo expects:

- JDK 21.
- Android SDK command-line tools.
- Android platform `android-35`.
- Android build tools `35.0.0`.
- `ANDROID_HOME` or `ANDROID_SDK_ROOT` when the SDK is not auto-discovered.

### 2. Build and Install a Debug APK

Use this path for local development and smoke testing:

```bash
cd ../sase-android
./gradlew testDebugUnitTest lintDebug assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The debug APK does not require Firebase. Without `app/google-services.json`, push delivery is shown as unconfigured in
Settings, but the rest of the app can still pair and use the gateway.

### 3. Build an Internal APK with FCM

For push hints:

1. Create a Firebase Android app with package `org.sase.mobile`.
2. Put the downloaded config at `../sase-android/app/google-services.json`.
3. Keep that file local and uncommitted.
4. Build the APK normally with `./gradlew testDebugUnitTest lintDebug assembleDebug`.

Push payloads are hint-only. They may include event IDs, categories, routing IDs, and short safe title/body text. They
must not include bearer tokens, pairing codes, prompt bodies, response text, attachment contents, attachment tokens,
host paths, signing material, Firebase credentials, or tailnet hostnames.

### 4. Build a Signed Release APK

Release signing uses local-only Gradle properties, `local.properties`, or environment variables:

```bash
SASE_ANDROID_RELEASE_STORE_FILE=/absolute/path/to/sase-mobile-upload.jks \
SASE_ANDROID_RELEASE_STORE_PASSWORD=... \
SASE_ANDROID_RELEASE_KEY_ALIAS=sase-mobile \
SASE_ANDROID_RELEASE_KEY_PASSWORD=... \
./gradlew testDebugUnitTest lintDebug assembleRelease
```

The app ID is `org.sase.mobile`. Preserve it and increase `versionCode` for upgrades so paired-host state and app-private
caches survive normal installs. Installing with a different signing key may require uninstalling first, which deletes
local session state and requires re-pairing.

## Host Setup

From this SASE repo:

```bash
just install
cargo build -p sase_gateway --manifest-path ../sase-core/Cargo.toml
sase mobile gateway start
```

The gateway binds to `127.0.0.1:7629` by default, waits for health, creates a pairing challenge, and prints a pairing
code, pairing ID, expiration, and gateway URL. Keep this process running while the phone connects. Stop it with
`Ctrl-C`.

Useful local options:

```bash
sase mobile gateway start -p 7630
sase mobile gateway start -H /tmp/sase-mobile-state
sase mobile gateway start -c "../sase-core/target/debug/sase_gateway"
```

The current CLI help exposes:

```text
-b, --bind-address
-p, --port
-H, --state-dir
-L, --allow-non-loopback
-c, --command
-T, --startup-timeout
-P, --push-provider
-F, --fcm-project-id
-S, --fcm-service-account-json
-E, --fcm-credential-env
-D, --fcm-dry-run
-U, --push-timeout-seconds
-R, --push-retry-limit
```

The default config lives under `mobile_gateway` in `src/sase/default_config.yml` and sets `bind_address:
"127.0.0.1"`, `port: 7629`, `allow_non_loopback: false`, and `push_provider: "disabled"`.

`sase mobile` exposes three subcommands but only `gateway start` is user-facing:

```text
sase mobile gateway start    # start the workstation gateway (this is the one you run)
sase mobile agent-bridge     # internal, invoked by the Rust gateway; SUPPRESSED in --help
sase mobile helper-bridge    # internal, invoked by the Rust gateway; SUPPRESSED in --help
```

The bridge subcommands are not part of the user surface — the Rust gateway invokes them with fixed operation names. Do
not call them by hand.

### Quick health check

Once the gateway is up, you can confirm it is reachable before pairing:

```bash
curl -sS http://127.0.0.1:7629/api/v1/health
```

`GET /api/v1/health` is one of three unauthenticated routes (the others are `POST /api/v1/session/pair/start` and
`POST /api/v1/session/pair/finish`); every other route requires the paired bearer token.

## Network Setup

Use the right Android base URL for the device:

- Android emulator: `http://10.0.2.2:7629`.
- Same trusted LAN: bind a specific host address with `sase mobile gateway start -b <host-lan-ip> -L`.
- Preferred physical-device remote path: keep the gateway on loopback and expose it through Tailscale Serve.

Tailscale Serve flow:

```bash
sase mobile gateway start
tailscale serve --bg 127.0.0.1:7629
tailscale serve status
```

Use the reported tailnet HTTPS URL as the Android base URL. Stop serving with:

```bash
tailscale serve reset
```

Avoid public tunnels and Tailscale Funnel for the MVP. The gateway uses pairing and bearer auth, but the workstation is
still the trust boundary.

## Pairing

Open the Android app, go to Settings, and enter or scan the pairing data:

- Gateway base URL.
- Pairing ID.
- One-time pairing code.
- Optional host label.
- Device display name.

The app supports JSON and URI QR payloads. Example JSON payload:

```json
{
  "schema_version": 1,
  "type": "sase_mobile_pair",
  "base_url": "http://127.0.0.1:7629",
  "pairing_id": "pair_abc123",
  "code": "123456",
  "host_label": "workstation"
}
```

The equivalent URI form (accepted by the same Settings screen):

```text
sase://pair?base_url=http%3A%2F%2F127.0.0.1%3A7629&pairing_id=pair_abc123&code=123456&host_label=workstation
```

The pairing parser is intentionally narrow: it accepts only the fields above and rejects arbitrary `command`, `path`,
`query`, or `fragment` data. Pairing codes are one-time and short-lived; if the code expires, restart
`sase mobile gateway start` to mint a new pairing challenge.

After pairing, the app stores the bearer token in app-private secure storage. The gateway stores token hashes, not raw
tokens.

### Manual pairing for testing without a phone

You can drive the pairing flow with `curl` to validate the gateway end-to-end before installing the APK. Use the
`pairing_id` and `code` printed by `sase mobile gateway start`:

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
      \"display_name\": \"laptop-curl\",
      \"platform\": \"android\",
      \"app_version\": \"0.1.0\"
    }
  }"
```

The response returns the bearer token exactly once. Use it for any authenticated probe:

```bash
TOKEN="sase_mobile_example"
curl -sS http://127.0.0.1:7629/api/v1/session -H "Authorization: Bearer $TOKEN"
```

This is useful for diagnosing whether a problem is in the gateway, the network, or the Android client.

## Normal Use

### Inbox and Actions

Use Inbox to refresh notifications and open details. Detail screens can:

- Mark read or dismiss.
- Approve, run, reject, epic, legend, or send feedback for plan notifications.
- Accept, reject, or send feedback for HITL prompts.
- Pick an option or send a custom answer for user questions.
- Download declared attachments through authenticated short-lived tokens.

Duplicate, stale, already-handled, ambiguous, unsupported, and missing-target cases return typed errors. Android should
refresh detail state and preserve drafts after transport or stale-action failures.

### Launch

Use Launch for text or image agent starts. The app should preserve raw SASE prompt syntax such as `%model`, `%runtime`,
`#gh:...`, and xprompt references unless the user explicitly inserts helper text.

Image launch uploads camera/gallery content to the host. The host stores the image under SASE mobile gateway state and
injects the saved host path into the launched agent prompt.

### Agents

Use Agents to list running and recent agents, inspect status, kill a running agent, retry an agent, or use resume/wait
prompts. Launch and retry results are correlated with request IDs where the client supplies them.

### Helpers and Update

Use helper screens to:

- List active ChangeSpec tags.
- Browse xprompt catalog entries (with optional best-effort PDF generation).
- List/show beads.
- Start the fixed SASE update worker and poll structured update status.

Helper endpoints are fixed product operations. The phone cannot send shell commands, cwd values, arbitrary host paths,
environment variables, or bridge argv. The gateway invokes fixed `sase mobile helper-bridge <operation>` commands; the
update worker itself runs only the configured `chat_install.command`.

Project context resolution:

- When a helper or launch request includes `project=<name>`, the bridge resolves only
  `<sase_home>/projects/<name>/<name>.gp` and uses that file's `WORKSPACE_DIR` for any cwd. Mobile cannot supply a
  workspace path directly.
- Omit `project` to use the paired device's remembered project (the last product-shaped context the device used).
- Pass `all_projects=true` on bead lookups to force a cross-project search across known SASE projects.

Helper responses include a common `result` block with `status`, `message`, `warnings`, `skipped`, and
`partial_failure_count`. Android renders `partial_success` by showing the primary payload plus the structured `skipped`
rows; the message string is for humans only and must not be parsed for control flow. `POST /api/v1/update/start` is the
only mutating helper route; everything else is read-only. `helpers_changed` SSE events are best-effort; polling
`GET /api/v1/update/{job_id}` is authoritative for completion.

### Background Delivery

Foreground connected mode keeps the REST/SSE path active while Android permits the foreground service to run. The app
shows a persistent notification while this mode is active.

Optional FCM push registers the app with `POST /api/v1/session/push-subscriptions`. Pushes are wake hints only; after a
push or notification tap, the app must fetch authoritative state from the authenticated gateway.

Host-side FCM example:

```bash
export SASE_FCM_CREDENTIAL='...'
sase mobile gateway start \
  -P fcm \
  -F my-firebase-project \
  -E SASE_FCM_CREDENTIAL \
  -D
```

Local gateway push testing can use:

```bash
sase mobile gateway start -P test
```

The `test` provider records attempted delivery in-process without sending traffic off the workstation; it is the right
choice for verifying the gateway side of push without a Firebase project.

## SSE Events

Authenticated clients subscribe to `GET /api/v1/events` with `Accept: text/event-stream`. The wire records published on
this stream are documented in `EventPayloadWire`:

- `notifications_changed` — a notification's read/dismissed/action state changed.
- `agents_changed` — an agent was launched, killed, retried, or transitioned status.
- `helpers_changed` — a helper-driven action (most often the update worker) progressed.
- `resync_required` — the in-memory event buffer can no longer satisfy the client's `Last-Event-ID`; the client must
  refetch authoritative state.
- `heartbeat` — periodic keepalive carrying a monotonic sequence.
- `session` — the device's session state changed.

Each event has a stable monotonic ID such as `0000000000000001`. Clients reconnect with `Last-Event-ID: <id>` to replay
buffered events newer than the last processed ID. The first MVP keeps the buffer in memory, so a gateway restart or
buffer overflow surfaces a `resync_required` event and the client must refetch full state.

## API Error Codes

Errors arrive as `ApiErrorWire` records with a typed `code`. Useful ones to anticipate when smoke-testing or
troubleshooting:

- `unauthorized` — bearer missing/expired/revoked, or pairing flow not completed.
- `pairing_expired`, `pairing_rejected` — restart `sase mobile gateway start` to mint a new pairing challenge.
- `not_found`, `helper_not_found`, `agent_not_found` — target ID or name does not match host state.
- `agent_not_running` — kill/retry on a terminal agent.
- `conflict_already_handled` — action already taken (e.g. plan already approved on another device).
- `gone_stale` — pending action was superseded; client should refresh detail.
- `ambiguous_prefix` — supplied prefix matches more than one pending action.
- `unsupported_action` — action not valid for that notification kind.
- `attachment_expired` — short-lived download token timed out; re-fetch detail.
- `launch_failed`, `invalid_upload`, `bridge_unavailable` — agent launch or bridge dispatch failed.
- `update_already_running`, `update_job_not_found` — update worker state mismatch.
- `permission_denied`, `internal`, `invalid_request` — generic guardrails.

The Android client maps these to typed UX states (stale refresh, already-handled recovery, draft preservation,
re-pair prompts), which is why detail screens preserve feedback and custom-answer drafts after transient errors.

## Storage And State

Gateway state lives under `<sase_home>/mobile_gateway/` (default `~/.sase/mobile_gateway/`):

- `devices.json` — paired devices, including a `revoked_at` field used by the revocation primitive.
- `audit.jsonl` — append-only audit records with device ID, endpoint, target ID, and outcome. Pairing codes and bearer
  tokens are intentionally excluded.
- `agent_launch_contexts.jsonl` — per-launch mobile context (request IDs, project, name).
- `agent_kill_contexts/` — per-kill records.
- `device_project_contexts/` — last product-shaped project context per device, used when `project` is omitted on
  helper/launch requests.
- Image launch attachments — stored under SASE-owned gateway state; the absolute saved path is injected into the
  launched agent prompt.

Bearer tokens are never written to disk; only SHA-256 hashes are stored. Revoking a device flips `revoked_at` and any
future authenticated request with that token fails with `unauthorized`.

## Telegram Fallback

Telegram remains the supported remote path while the Android MVP is private/internal-only. The shared pending-action
compatibility layer means a notification approved on Android (or vice-versa) is honored across transports. If mobile
access is rolled back (for example by stopping the gateway and `tailscale serve reset`), Telegram is still available for
pending plan/HITL/question actions.

## Known MVP Limitations

- Private/internal APK distribution only — no Play Store release. Release minification is intentionally disabled until a
  broader rollout.
- Notification reads are authoritative REST reads from the host JSONL store. Passive file-watching is intentionally out
  of the MVP; mutations publish `notifications_changed` SSE events instead.
- Attachment downloads are capped by the gateway's max-attachment-bytes setting. Oversized, missing, directory,
  traversal, symlinked, or unknown-risk files appear in manifests without download tokens.
- Image launch enforces an oversize ceiling and rejects payloads above the limit with `invalid_upload`.
- Agent project context is an MVP metadata + known-project cwd selector. It does not expose arbitrary host directory
  selection; clients must use SASE prompt syntax (e.g. `#gh:12345`) for VCS refs.
- Helper routes are native picker APIs, not generic command execution. ChangeSpec, xprompt, and bead helpers are
  read-only; xprompt PDF generation is best-effort and opt-in.
- FCM is the first push provider; UnifiedPush/ntfy remain future provider options behind the transport-agnostic
  subscription model. Push diagnostics primarily live in tests/logs and the Android Settings push card.
- Foreground connected mode improves durability but still follows Android background execution limits; lower-power
  delivery still depends on push.
- The Android API client is hand-written against the checked contract snapshot; generated client adoption is
  intentionally deferred.

## Smoke Checklist

After installing:

1. Start `sase mobile gateway start`.
2. Install the APK.
3. Pair from Android Settings.
4. Check session from Settings.
5. Refresh Inbox and open a notification detail.
6. Perform a plan/HITL/question action if a pending notification exists.
7. Launch a text agent.
8. Launch an image agent from camera/gallery or emulator content.
9. Open Agents, then kill or retry an agent where safe.
10. Use Helpers for ChangeSpec tags, xprompts, and beads.
11. Start Update and poll status.
12. Enable foreground connected mode, background the app, trigger a host event, and verify refresh after reopening.
13. For FCM builds, verify push registration, tap a local hint notification, and confirm host state refresh.
14. Forget the host and confirm the app returns to an unpaired state.

## Troubleshooting

- Gateway refuses to bind: non-loopback addresses require `-L`; prefer loopback plus Tailscale Serve.
- Emulator cannot connect: use `10.0.2.2`, not `127.0.0.1`, inside the emulator.
- Physical device cannot connect: verify the phone and host share the same tailnet/LAN and the app base URL matches the
  exposed address.
- Push says unconfigured: check Android `app/google-services.json` and host `mobile_gateway.push_provider`/FCM config.
- Push arrives but detail is stale: push is only a hint; verify the app can reach the gateway and refresh after receipt
  or tap.
- Auth fails after reinstall or host reset: forget the host in Android Settings and pair again.
- Foreground notification does not appear: verify Android notification permission and foreground connected mode.

## Security Notes

- The phone is a client only. It does not run agents locally.
- The gateway exposes product-shaped commands, not arbitrary shell, file browsing, or RPC.
- Use loopback by default.
- Prefer Tailscale Serve for private remote access.
- Avoid public tunnels and Tailscale Funnel for the MVP.
- Do not commit `google-services.json`, Firebase service accounts, Android signing keys, keystores, local gateway URLs,
  or tailnet hostnames.
- Treat attachment tokens and notification detail screens as sensitive.
- Stop the gateway and reset Tailscale Serve when mobile access is not needed.

## Verification Commands

Automated gates called out by the docs:

```bash
(cd ../sase-android && ./gradlew testDebugUnitTest lintDebug assembleDebug)
(cd ../sase-android && ./gradlew connectedDebugAndroidTest)
(cd ../sase-core && cargo test -p sase_gateway push_subscription)
(cd ../sase-core && cargo test -p sase_gateway test_push_provider_records_hint_attempts)
(cd ../sase-core && cargo test -p sase_gateway listener_smoke_exercises_pairing_auth_and_session)
.venv/bin/pytest tests/test_mobile_gateway.py
```

Targeted CI-friendly hardening subsets (faster than the full unit suite):

```bash
(cd ../sase-android && ./gradlew testDebugUnitTest --tests org.sase.mobile.testing.BackgroundHardeningSmokeTest)
(cd ../sase-android && ./gradlew testDebugUnitTest --tests org.sase.mobile.testing.FakeGatewayTest)
(cd ../sase-android && ./gradlew testDebugUnitTest --tests 'org.sase.mobile.data.notifications.push.*')
```

The Android repo also ships a route-based fake-gateway harness (`GatewayApiClientTest`, `ActionRepositoryTest`,
`AgentRepositoryTest`, `HelperRepositoryTest`, `UpdateRepositoryTest`) that covers contract-shaped requests, stale and
already-handled errors, draft preservation, and `agents_changed`/`helpers_changed` refresh paths without a real
workstation gateway — useful for app development when the Rust gateway is not running.

For this research note, I verified source availability and command shape by running:

```bash
sase bead show sase-26
.venv/bin/sase mobile gateway start --help
git log --date=short --pretty=format:'%h %ad %s' --all --regexp-ignore-case --grep='mobile\|android\|gateway\|sase-26'
git -C ../sase-android log --date=short --pretty=format:'%h %ad %s' --all --regexp-ignore-case --grep='mobile\|android\|gateway\|sase-26\|pair\|push\|fcm\|apk'
git -C ../sase-core log --date=short --pretty=format:'%h %ad %s' --all --regexp-ignore-case --grep='mobile\|android\|gateway\|sase-26\|pair\|push\|fcm'
```
