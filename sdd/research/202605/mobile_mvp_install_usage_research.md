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

After pairing, the app stores the bearer token in app-private secure storage. The gateway stores token hashes, not raw
tokens.

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
- Browse xprompt catalog entries.
- List/show beads.
- Start the fixed SASE update worker and poll structured update status.

Helper endpoints are fixed product operations. The phone cannot send shell commands, cwd values, arbitrary host paths,
environment variables, or bridge argv.

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
.venv/bin/pytest tests/test_mobile_gateway.py
```

For this research note, I verified source availability and command shape by running:

```bash
sase bead show sase-26
.venv/bin/sase mobile gateway start --help
git log --date=short --pretty=format:'%h %ad %s' --all --regexp-ignore-case --grep='mobile\|android\|gateway\|sase-26'
git -C ../sase-android log --date=short --pretty=format:'%h %ad %s' --all --regexp-ignore-case --grep='mobile\|android\|gateway\|sase-26\|pair\|push\|fcm\|apk'
git -C ../sase-core log --date=short --pretty=format:'%h %ad %s' --all --regexp-ignore-case --grep='mobile\|android\|gateway\|sase-26\|pair\|push\|fcm'
```
