# Mobile MVP Runbook

This runbook covers the private Android MVP that connects a phone to a workstation-hosted SASE mobile gateway. The phone
is a client only: it stores a paired bearer token, renders notifications, opens fixed SASE workflows, and fetches
authoritative state from the gateway. It does not run agents locally and the gateway does not expose arbitrary shell,
file-browse, or RPC access.

Use this with:

- Android app: `../sase-android`
- Rust gateway: `../sase-core/crates/sase_gateway`
- SASE host CLI: this repo, `sase mobile gateway start`

## Build And Install

### Debug APK

Use a debug APK for local development and manual smoke tests:

```bash
cd ../sase-android
./gradlew testDebugUnitTest lintDebug assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The debug build does not require Firebase project files. If `app/google-services.json` is absent, the app still builds,
but push registration reports an unconfigured provider in Settings.

### Internal APK With FCM

For an internal/direct APK that should receive FCM push hints:

1. Create a Firebase Android app with package `org.sase.mobile`.
2. Place the downloaded Android config at `../sase-android/app/google-services.json`.
3. Keep `google-services.json` local; it is ignored by git.
4. Build the APK:

   ```bash
   cd ../sase-android
   ./gradlew testDebugUnitTest lintDebug assembleDebug
   ```

FCM payloads are hints only. They may contain event IDs, categories, routing IDs, short safe titles, and short safe
bodies. They must not contain bearer tokens, pairing codes, prompt bodies, response text, attachment contents,
attachment tokens, host paths, signing material, or Firebase credentials.

### Signed Release APK

Release signing is configured from local-only Gradle properties, `local.properties`, or environment variables. Do not
commit keystores or signing values.

Required keys:

```text
SASE_ANDROID_RELEASE_STORE_FILE=/absolute/path/to/sase-mobile-upload.jks
SASE_ANDROID_RELEASE_STORE_PASSWORD=...
SASE_ANDROID_RELEASE_KEY_ALIAS=sase-mobile
SASE_ANDROID_RELEASE_KEY_PASSWORD=...
```

Build:

```bash
cd ../sase-android
./gradlew testDebugUnitTest lintDebug assembleRelease
```

The release build currently leaves minification off for private distribution. Revisit minification and keep rules before
any broad public release.

### Versioning And Upgrades

The Android MVP keeps paired-host metadata, bearer tokens, cached inbox state, action drafts, foreground-mode
preference, push registration status, and remembered update jobs in app-private storage. Preserve the application ID
`org.sase.mobile` and increase `versionCode` for upgrades. Users who install a differently signed APK may need to
uninstall first, which deletes local session/cache state and requires re-pairing.

## Host Setup

Install the SASE checkout and build the Rust gateway:

```bash
cd /path/to/sase_100
just install
cargo build -p sase_gateway --manifest-path ../sase-core/Cargo.toml
```

Start the gateway on loopback:

```bash
sase mobile gateway start
```

The command prints a pairing code, pairing ID, and expiration. Keep the process running while mobile clients connect.

For an emulator pointed at host loopback, use `http://10.0.2.2:7629` as the base URL in the Android app. For a physical
device on the same trusted LAN, bind explicitly to a LAN address only when needed:

```bash
sase mobile gateway start -b 192.0.2.10 -L
```

Do not bind to `0.0.0.0` or a public interface unless you have a separate network control that restricts access to your
own device. Pairing and bearer auth protect the product API, but the workstation remains the trust boundary.

## Push Provider

Push delivery is disabled by default:

```yaml
mobile_gateway:
  push_provider: "disabled"
```

Use the test provider for local gateway coverage without sending traffic off the workstation:

```bash
sase mobile gateway start -P test
```

Use FCM only for internal APKs that include Firebase Android configuration:

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

The host passes credential paths or environment-variable names to the Rust gateway, not credential contents on the
process command line. Store service-account files under user-private config directories.

## Private Remote Access

Tailscale Serve is the recommended remote-access path for the MVP because it keeps the gateway on host loopback and
proxies it only inside the tailnet. Tailscale documents Serve as a way to route traffic from tailnet devices to a local
service and notes that Funnel is the public-internet option; do not use Funnel for the mobile MVP. See the official
Serve docs: <https://tailscale.com/docs/features/tailscale-serve> and <https://tailscale.com/kb/1242/tailscale-serve>.

Start SASE on loopback:

```bash
sase mobile gateway start
```

In another terminal, expose that loopback service to your tailnet:

```bash
tailscale serve --bg 127.0.0.1:7629
tailscale serve status
```

Use the reported tailnet HTTPS URL as the Android base URL. Keep Tailscale ACLs limited to the users/devices that should
operate the workstation. Stop serving when finished:

```bash
tailscale serve reset
```

Fallback options:

- Emulator: `http://10.0.2.2:7629` while the gateway binds host loopback.
- Trusted LAN: bind a specific host LAN address with `-L` and pair only on that network.
- USB reverse/tunnel tooling: acceptable for local development, but document the exact command in your local notes.

Avoid:

- Public tunnel services and Tailscale Funnel.
- Committing tailnet hostnames, Firebase service accounts, Android signing keys, or local gateway URLs.
- Exposing the gateway on a shared network without explicit need and a short operating window.

## Manual Smoke

Run the automated gates first:

```bash
(cd ../sase-android && ./gradlew testDebugUnitTest lintDebug assembleDebug)
(cd ../sase-core && cargo test -p sase_gateway push_subscription)
(cd ../sase-core && cargo test -p sase_gateway test_push_provider_records_hint_attempts)
.venv/bin/pytest tests/test_mobile_gateway.py
```

Then smoke the end-to-end path:

1. Start `sase mobile gateway start`.
2. Install the APK and pair from Settings.
3. Verify session check, inbox refresh, and notification detail load.
4. Approve/reject a plan notification, launch a text agent, and kill or retry an agent.
5. Turn on foreground connected mode, background the app, trigger a gateway event, reopen the app, and verify state
   refreshes.
6. For FCM builds, verify push registration in Settings, send a test hint, tap the local notification, and confirm the
   app fetches host state before showing detail-sensitive UI.
7. Forget the host and verify the app returns to the unpaired state.

## Troubleshooting

- Gateway refuses to bind: non-loopback addresses require `-L`; prefer loopback plus Tailscale Serve.
- Emulator cannot connect: use `10.0.2.2`, not `127.0.0.1`, from inside the emulator.
- Physical device cannot connect: verify phone and host are on the same tailnet/LAN and that the displayed base URL
  matches the exposed address.
- Push says unconfigured: check `app/google-services.json` for Android and `mobile_gateway.push_provider`/FCM credential
  config for the host.
- Push arrives but detail is stale: push is only a wake hint; verify the app can reach the authenticated gateway and
  refresh after receipt or tap.
- Auth failures after reinstall or host reset: forget the host in Android Settings and pair again.
- Foreground notification will not appear: verify Android notification permission and that connected mode is enabled.

## Rollback

To roll back mobile access:

1. Stop the gateway process.
2. Stop Tailscale Serve with `tailscale serve reset`.
3. Forget the host in the Android app to revoke local session state and push subscription state.
4. Remove or rotate local FCM service-account credentials if they were exposed.
5. Use Telegram fallback for pending notifications/actions while mobile is disabled.

## Threat Model

### Assets

- Workstation SASE state, notifications, pending action files, agent launch context, and attachment files.
- Mobile bearer token and cached display state.
- Pairing code and pairing ID during their short validity window.
- FCM provider token/service account and Android app `google-services.json`.
- Android signing key.

### Lost Phone

Risk: a paired phone can use its bearer token until the host forgets/revokes that device or the token becomes unusable.

Controls:

- Android stores the token in app-private secure storage.
- Users can forget the host from the app, and host-side session/token storage can be removed.
- Pairing codes are one-time and short-lived.

Operator response:

- Stop the gateway.
- Remove the device/session entry from gateway state or reset the mobile gateway state directory.
- Rotate any FCM device subscription if the host has not already marked it inactive.

### LAN Attacker And Non-Loopback Bind

Risk: binding to LAN or `0.0.0.0` exposes the gateway transport to anyone who can route to the host, increasing online
attack surface even though API routes require auth.

Controls:

- The Python launcher refuses non-loopback binds unless `--allow-non-loopback` / `-L` is passed.
- Product APIs require bearer auth after pairing.
- Helper routes expose fixed operations, not arbitrary commands.

Guidance:

- Prefer loopback plus Tailscale Serve.
- If LAN binding is necessary, bind a specific LAN IP for a short smoke window and stop it afterward.

### Public Tunnels

Risk: public tunnels expose pairing and authenticated routes to the internet and make brute-force, scanner, and logging
risks materially worse.

Controls and guidance:

- Do not use public tunnels or Tailscale Funnel for the MVP.
- Tailscale Serve keeps access inside the tailnet and respects tailnet ACLs.
- Pair only while physically operating both devices.

### Attachment URL And Token Leakage

Risk: attachment download tokens grant temporary access to specific declared files for a paired device.

Controls:

- Tokens are minted only from authenticated detail responses.
- Tokens are bound to the authenticated device, expire after a short TTL, and are not stored in audit logs.
- Download checks reject traversal, symlink crossing, missing or changed files, non-regular files, and oversized files.

Guidance:

- Do not put attachment tokens in push payloads, logs, screenshots, or external issue trackers.
- Treat notification detail screens as potentially sensitive.

### Arbitrary-Command Expansion

Risk: mobile helper or launch surfaces could become a general host command channel.

Controls:

- Gateway routes are product-shaped: notification actions, agent launch/kill/retry, fixed helpers, and update start.
- Helper bridge commands are configured by the host and invoked with fixed operations.
- Mobile clients cannot send cwd values, environment variables, host file paths, shell fragments, or arbitrary bridge
  argv for helper operations.

Guidance:

- Keep new mobile features behind explicit product commands.
- Reject proposals that turn mobile into a generic shell, file browser, or RPC client.

### Push Provider Compromise Or Logs

Risk: FCM or intermediary logs may retain push metadata.

Controls:

- Push records are hints only.
- Provider tokens and service-account credentials are local-only and not audited.
- Delivery failures are best-effort diagnostics; user actions do not depend on push success.

Allowed in FCM payloads:

- Event ID or notification ID.
- Category/reason.
- Safe route hint.
- Short generic title/body.

Never allowed in FCM payloads:

- Bearer tokens, pairing codes, service-account contents, prompt bodies, response text, attachment contents, attachment
  tokens, raw host paths, local tailnet names, or signing material.

### Notification Content Sensitivity

Risk: lock-screen notifications can be read by people near the phone.

Controls:

- Local notification rendering uses sanitized hint models.
- Sensitive content remains behind an authenticated gateway fetch after app open.

Guidance:

- Keep notification text generic for private builds.
- If a future build needs richer text, add an explicit user setting and revisit lock-screen visibility.

## Known Limitations

- The MVP is for private/internal distribution, not Play Store production.
- FCM is the first push provider; UnifiedPush/ntfy remain future provider options behind the transport-agnostic
  subscription model.
- Push diagnostics are mostly in tests/logs and Android Settings state.
- Foreground connected mode improves durability but still follows Android background execution limits.
- Telegram remains the fallback for users who need a mature remote notification path.
- No follow-up beads were created during this close-out; material gaps above should be triaged under the parent epic or
  a future planning pass.
