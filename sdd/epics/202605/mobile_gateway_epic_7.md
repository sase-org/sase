---
bead_id: sase-26.7
legend_bead_id: sase-26
tier: epic
create_time: 2026-05-06 19:59:08
status: done
prompt: sdd/prompts/202605/mobile_gateway_epic_7.md
---

# Plan: Mobile MVP Epic 7 - Background Delivery, Packaging, And End-To-End Hardening

## Context

Epic 7 from `sdd/legends/202605/sase_mobile_mvp_legend.md` is the hardening layer for the SASE Android MVP. Epics 1-6
establish the host gateway, Android pairing/session state, foreground SSE/cache behavior, notification actions, agent
launch/lifecycle flows, helper pickers, update UI, and fake-gateway coverage. This epic should make those foreground
flows reliable when the app is backgrounded, packageable for private/internal use, and explicit about the security
posture of exposing a workstation-hosted SASE runtime to a phone.

Current repository state:

- `../sase-android` is the primary app repo. It already has Kotlin/Compose screens for inbox/detail/launch/agents/
  helpers/update/settings, Keystore-backed token storage, `NotificationRepository` with SSE reconnect and full-state
  refresh, a route-based fake gateway, connected smoke tests, and a README that explicitly lists background delivery,
  foreground service behavior, notification permission UX, packaging, security review, and release hardening as Epic 7
  work.
- `../sase-core` owns `crates/sase_gateway`, the gateway HTTP/SSE contract, auth/pairing storage, audit logging, event
  emission, notification/action/agent/helper/update endpoints, and the checked
  `crates/sase_gateway/contracts/api_v1/mobile_api_v1.json` snapshot.
- This repo owns the Python SASE shell and gateway launcher/config bridge under
  `src/sase/integrations/mobile_gateway.py` and `src/sase/main/parser_mobile.py`, plus the SDD plan/prompt/bead
  artifacts.
- The Android manifest currently grants camera and internet permissions only. It has no Android 13+ `POST_NOTIFICATIONS`
  permission, no foreground service declaration, no Firebase/UnifiedPush dependency, no push receiver, and no
  release-packaging or Tailscale setup docs beyond the foreground manual smoke checklist.

The product bar for Epic 7 is: a paired user can opt into background/foreground delivery, receive hint-only mobile
notifications while away from the app, open the app to authoritative host state, run the primary approval/launch/kill
flows through regression coverage, and follow a documented private distribution and remote-access runbook.

## Goal

Deliver background delivery and hardening for the Android MVP:

- Runtime notification permission handling for Android API 33+.
- Android local notification channels/rendering/deep links for SASE notification hints.
- A foreground connected mode that keeps the gateway event stream alive under Android platform rules.
- A transport-agnostic push-hint contract, with FCM as the first private/internal APK provider and no secrets or prompt
  bodies in push payloads.
- Host event-to-push bridge behavior with audit logging, provider configuration, disabled/noop/test modes, and fake HTTP
  coverage.
- End-to-end fake-gateway and real-host smoke coverage for background open-to-current-state and the primary
  approval/launch/kill paths.
- Packaging docs for direct APK/internal distribution and remote access docs centered on Tailscale Serve.
- A threat-model review for lost phones, LAN attackers, public tunnels, attachment-token leakage, and accidental
  arbitrary-command expansion.

## Non-Goals

- Hosted multi-tenant relay service, custom public push relay, or iOS support.
- Running SASE locally on Android or embedding the full Rust core in the APK.
- Sending secrets, bearer tokens, pairing codes, full prompts, response text, attachment contents, or host paths in push
  payloads.
- Arbitrary shell execution, arbitrary host file browsing, live terminal streaming, or generic RPC.
- Replacing Telegram immediately; Telegram remains a fallback while mobile hardening matures.
- Full Play Store production release automation. This epic should support direct APK/internal distribution; Play Store
  production policy work can be a follow-up.

## Cross-Phase Rules

- Start every phase with `git status --short` in each repo it will touch and preserve unrelated dirty changes.
- Keep push payloads as hints only. The app must fetch authoritative detail from the authenticated gateway after wake,
  notification tap, reconnect, or app open.
- Keep deterministic wire records in `../sase-core`; use this repo for Python launcher/config glue and docs; keep
  Android app lifecycle/UI/platform behavior in `../sase-android`.
- Do not add runtime-specific Claude/Gemini/Codex behavior. Mobile commands remain product-shaped gateway commands.
- Every new `sase` CLI/config option in this repo needs a short flag when applicable.
- Do not commit FCM service-account credentials, `google-services.json` secrets, signing keys, keystores, or local
  Tailscale hostnames. Provide samples/templates and documented local paths instead.
- Each Android implementation phase should run `./gradlew testDebugUnitTest lintDebug assembleDebug` from
  `../sase-android`; run `./gradlew connectedDebugAndroidTest` when an emulator/device is available.
- Each `../sase-core` implementation phase should run `cargo fmt --all -- --check`,
  `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`.
- If this repo changes outside `sdd/beads/`, run `just install && just check` before handoff.

## Phase 1: Android Notification Permission, Channels, And Local Hint Rendering

Owner: one agent. Write scope: `../sase-android` only.

Purpose: make the app capable of rendering safe local notifications and handling Android 13+ notification permission
without changing host push behavior yet.

Concrete work:

- Add `POST_NOTIFICATIONS` permission and runtime permission request/denied/permanently-denied states for API 33+.
- Add a notification settings surface that shows permission state, provides a request action, and links to system
  settings when Android no longer shows the prompt.
- Add Android notification channels for SASE action hints, agent lifecycle hints, helper/update hints, and foreground
  connection status. Keep channel names stable and user-readable.
- Add a local notification renderer that accepts a sanitized hint model:
  - notification ID or event ID;
  - type/category;
  - short title/body;
  - created timestamp;
  - deep-link target such as inbox, notification detail, agents, or update.
- Add deep-link/intents so tapping a local hint opens the app and triggers a full authenticated refresh before showing
  detail-dependent state.
- Do not render prompt bodies, feedback text, attachment contents, bearer tokens, pairing codes, attachment tokens, or
  raw host paths.
- Add unit tests for permission-state mapping, channel creation idempotence, hint sanitization, and deep-link target
  parsing. Add Compose/instrumentation coverage for the permission/settings surface where practical.

Acceptance:

- On API 33+, the app can request notification permission and clearly represent allowed/denied states.
- With permission granted, a sanitized in-app test hint can render as an Android notification and tap through to the
  correct app route while refreshing from the host.
- With permission denied, the app does not claim background notification delivery is active.

## Phase 2: Foreground Connected Service And Reconnect Policy

Owner: one agent. Write scope: `../sase-android` only.

Purpose: provide an opt-in foreground mode that keeps the SSE connection active when the user wants durable workstation
connectivity without relying only on push.

Concrete work:

- Add a foreground service for connected mode, using the platform service type that best matches remote messaging on the
  target SDK and the required `FOREGROUND_SERVICE*` permissions.
- Move or wrap the existing `NotificationRepository.start()`/`runSseLoop()` behavior so it can be owned by the service
  while the app UI observes shared repository/cache state.
- Add a persistent foreground notification with connection state, host label, last refresh time, and stop action. Keep
  content concise and free of sensitive prompt/host file detail.
- Add Settings controls for foreground connected mode:
  - off;
  - on until stopped;
  - optional start-on-pair/app-start preference if the implementation can support it cleanly.
- Harden reconnect/backoff behavior for long-running background use:
  - bounded exponential backoff with jitter;
  - network unavailable awareness if Android APIs are already available without heavy dependencies;
  - auth-expired/session-removed stop behavior;
  - full refresh after reconnect and after `resync_required`.
- Ensure the service does not keep running when the host is forgotten, token is revoked, or the user stops it.
- Add unit tests for service controller state transitions and reconnect policy. Add instrumentation smoke coverage for
  starting/stopping the service and seeing the foreground notification when practical.

Acceptance:

- A paired user can turn on foreground connected mode, background the app, and keep receiving gateway event refreshes
  through the existing SSE path.
- Android sees an active foreground notification while the mode is running.
- Stopping the mode, forgetting the host, or auth expiration tears down the service and event stream cleanly.

## Phase 3: Push-Hint Wire Contract And Subscription Endpoints

Owner: one agent. Write scope: `../sase-core` primarily, with Android contract snapshot update in `../sase-android` only
if the phase intentionally publishes the new contract there.

Purpose: add a transport-agnostic push registration contract before implementing FCM or host delivery.

Concrete work:

- Add wire models for push subscriptions and hint delivery:
  - provider enum such as `fcm`, `unified_push`, `ntfy`, and `test`;
  - provider device token/endpoint as opaque subscription material;
  - app instance/device metadata;
  - enabled/disabled timestamps;
  - hint categories the device wants;
  - sanitized `PushHintWire` that carries only IDs, category, reason, and short safe display text.
- Add authenticated endpoints under `/api/v1`, for example:
  - `GET /session/push-subscriptions`
  - `POST /session/push-subscriptions`
  - `DELETE /session/push-subscriptions/{id}` Exact paths can change if the agent finds a stronger existing convention,
    but they must remain product-shaped and versioned.
- Store subscriptions under gateway state with atomic writes and no bearer-token leakage. Treat provider tokens as
  sensitive enough to avoid audit logs and debug dumps.
- Extend the contract snapshot and route tests for auth, request validation, duplicate token handling, delete/revoke,
  and transport-agnostic JSON shape.
- Define event-to-hint mapping rules without sending the hints yet:
  - notification changed -> notification ID/category only;
  - agents changed -> agent name only if non-sensitive enough, otherwise category/count;
  - helpers/update -> job/helper IDs only;
  - session/resync -> generic refresh hint.

Acceptance:

- A paired client can register, list, and revoke a push subscription.
- Contract tests prove push subscription endpoints require auth and never return raw secrets beyond the current device's
  own registered opaque token if that is needed by Android token reconciliation.
- The gateway has a deterministic hint model that later delivery providers can consume without redesigning the API.

## Phase 4: Host Push Bridge, FCM Provider, And Python Gateway Config

Owner: one agent. Write scope: `../sase-core` and this repo. Avoid Android app changes except contract snapshot sync if
needed.

Purpose: send hint-only pushes from host gateway events through a configurable provider, with FCM as the first real
transport and test/noop modes for local development.

Concrete work:

- Add a gateway push dispatcher that observes the same event emission paths used by SSE and builds `PushHintWire`
  records from Phase 3 mapping rules.
- Add provider abstraction:
  - `disabled`/noop default;
  - `test` provider that records attempted hints for tests;
  - FCM HTTP v1 provider for private/internal builds.
- Add FCM configuration without committing secrets:
  - Firebase project ID;
  - service-account JSON path or credential environment variable;
  - optional dry-run flag;
  - provider timeout and retry limits.
- Keep push delivery best-effort. Event emission and REST mutations must not fail solely because push delivery is down.
  Delivery failures should be audited and exposed through health/status diagnostics without blocking the user action.
- Extend the Rust gateway CLI/config to accept push provider settings.
- Extend this repo's `sase mobile gateway start` config bridge to pass safe push settings from SASE config/CLI to the
  Rust gateway. New CLI flags need short options where exposed.
- Add tests:
  - event-to-hint mapping for notification/action/agent/helper/update events;
  - provider disabled/noop path;
  - fake FCM HTTP server request shape;
  - no prompt/body/attachment/token leakage in payload JSON;
  - Python argv/config construction and non-secret logging.

Acceptance:

- With push disabled, gateway behavior is unchanged.
- With the test provider, mutating endpoints and synthetic events produce recorded hint-only delivery attempts.
- With FCM config present, the gateway can send an FCM data message whose payload contains only safe IDs/categories and
  enough routing information for Android to refresh authoritative state.

## Phase 5: Android FCM Registration, Push Receiver, And Wake-To-Refresh Flow

Owner: one agent. Write scope: `../sase-android` only.

Purpose: connect Android to the Phase 3/4 push infrastructure and turn received hints into local notifications plus
authoritative refreshes.

Concrete work:

- Add Firebase Messaging dependencies and Gradle/plugin configuration suitable for internal/direct APK builds without
  committing project secrets. Provide a checked sample or documented expected location for `google-services.json`.
- Implement FCM token retrieval/refresh handling and register/revoke the token through the authenticated gateway push
  subscription endpoints.
- Add a `FirebaseMessagingService` that accepts data-only hint payloads, validates/sanitizes category and IDs, and hands
  them to the local notification renderer from Phase 1.
- On push receipt:
  - never trust push as authoritative;
  - schedule or trigger a bounded host refresh when a paired session exists and network conditions allow;
  - render a local notification that opens to the relevant route and refreshes again on tap.
- Handle unpaired/auth-expired states by dropping or showing only a generic "open settings" hint, without persisting
  unusable provider tokens as active subscriptions.
- Add Settings state for push delivery:
  - provider token registered;
  - permission missing;
  - foreground mode running;
  - last push hint received;
  - registration failure/retry.
- Add tests for token registration/revocation, payload sanitization, unpaired/auth-expired behavior, local notification
  dispatch, and tap-to-refresh routing. Use fake messaging inputs for unit tests; do not require real FCM for normal
  test runs.

Acceptance:

- An Android build with Firebase config can register a push subscription with the paired gateway.
- A received hint-only FCM data message results in a safe local notification and a host refresh path.
- Push tokens are revoked or marked inactive when the user forgets the host.

## Phase 6: End-To-End Harness And Smoke Coverage

Owner: one agent. Write scope: `../sase-android`, `../sase-core`, and this repo only where needed for shared test
fixtures/docs.

Purpose: prove the hardened MVP behavior across fake gateway, temporary real gateway, and emulator/device smoke paths.

Concrete work:

- Expand the Android fake gateway harness to cover:
  - push subscription endpoints;
  - hint payload fixtures;
  - notification tap/open refresh;
  - foreground service start/stop and reconnect/resync paths;
  - approval, launch, and kill flows after background wake.
- Add at least one real-host smoke scenario using a temporary `sase_gateway` listener where practical:
  - pair;
  - register test push provider subscription;
  - seed or trigger a notification/action event;
  - verify Android/fake client can refresh current state after hint/reconnect.
- Add CI-friendly commands for:
  - Android unit/fake-gateway hardening tests;
  - optional connected emulator tests;
  - Rust gateway push/subscription tests;
  - Python gateway config tests.
- If full emulator automation is too brittle for CI, document a manual connected smoke checklist and keep a stable
  instrumentation test that developers can run locally.
- Add regression coverage for the primary MVP flows after reconnect/background wake:
  - approve or reject a plan notification;
  - launch a text agent;
  - kill or retry an agent.

Acceptance:

- Automated tests cover the background hint -> app open -> authoritative refresh loop without requiring real FCM
  credentials.
- At least one smoke path exercises a real gateway binary/server, not only MockWebServer fixtures.
- The primary approval/launch/kill flows have regression coverage after reconnect or background wake.

## Phase 7: Packaging, Remote Access Runbook, And Threat-Model Review

Owner: one agent. Write scope: documentation and release config across `../sase-android`, `../sase-core`, and this repo.

Purpose: make the MVP installable and operable by a real user while documenting the security boundaries clearly.

Concrete work:

- Add Android packaging docs for:
  - debug APK;
  - signed release APK;
  - internal distribution build with Firebase config;
  - what files/secrets are local-only;
  - versioning and upgrade expectations for app data/session cache.
- Add or tighten Gradle release configuration where safe:
  - signing config via environment variables or local properties only;
  - minification/proguard choice documented;
  - reproducible `assembleRelease` instructions.
- Add host setup docs for:
  - starting `sase mobile gateway start`;
  - enabling push provider config;
  - Tailscale Serve as the recommended private remote-access option;
  - emulator `10.0.2.2` and physical-device tailnet/LAN setup;
  - what not to expose publicly.
- Add a threat model document that explicitly covers:
  - lost phone and token revocation/host forgetting;
  - LAN attacker and non-loopback bind opt-in;
  - public tunnel exposure;
  - attachment URL/token leakage and TTL behavior;
  - accidental arbitrary-command expansion;
  - push provider compromise or logs;
  - notification content sensitivity.
- Add an MVP runbook with known limitations, troubleshooting, and rollback to Telegram fallback.
- Update README references in the three repos so future phase agents and users can find the runbook.

Acceptance:

- A developer can build/install the MVP APK, configure the host gateway for private remote access, and understand how to
  enable or leave disabled push delivery.
- The runbook clearly states which data may leave the workstation via FCM and which data never should.
- The threat model results in follow-up beads for any material gaps not solved inside Epic 7.

## Dependency Order

- Phase 1 should land before Phases 2 and 5 because both foreground service and FCM receiver paths need channels,
  permission state, and local hint rendering.
- Phase 3 should land before Phases 4 and 5 because both host delivery and Android registration need the subscription
  contract.
- Phase 2 can run in parallel with Phase 3 after Phase 1 is reviewed.
- Phase 4 and Phase 5 should be sequential unless Phase 5 works against a contract snapshot and fake provider fixtures
  from Phase 3.
- Phase 6 depends on Phases 1-5.
- Phase 7 can start drafting docs earlier, but final acceptance should happen after Phase 6 evidence is available.

## Open Decisions

- Confirm FCM is acceptable for the first private/internal APK. If not, replace Phase 4/5 FCM specifics with UnifiedPush
  or ntfy while preserving the Phase 3 transport-agnostic contract.
- Decide whether foreground connected mode should auto-start after pairing or remain explicitly user-controlled for the
  MVP. The safer default is explicit opt-in.
- Decide whether the gateway should expose a user-facing push diagnostics endpoint in this epic or leave diagnostics in
  logs/tests until a settings UI needs it.
- Decide whether release minification should stay off for private builds or be enabled with keep rules before wider
  distribution.

## Definition Of Done

- Backgrounded Android users can receive a hint-only notification and open the app to current host state.
- Foreground connected mode is stable, visible to Android as a foreground service, and cleanly stoppable.
- Push subscriptions and host delivery are authenticated, transport-agnostic, auditable, and free of prompt/secret/file
  content.
- The MVP has automated fake-gateway coverage and at least one real-host smoke path for approval, launch, kill, and
  wake-to-refresh behavior.
- Packaging, Tailscale remote access, known limitations, and threat model docs are written and linked from the relevant
  READMEs.
