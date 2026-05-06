---
create_time: 2026-05-06 16:08:33
bead_id: sase-26.5
tier: epic
legend_bead_id: sase-26
status: wip
prompt: sdd/prompts/202605/mobile_gateway_epic_5.md
---
# Plan: Mobile MVP Epic 5 - Android App Foundation

## Context

Epic 5 from `sdd/legends/202605/sase_mobile_mvp_legend.md` creates the Android application foundation for the SASE
mobile MVP. Earlier gateway epics define the host control plane; this epic should make the phone a reliable
authenticated client of that host, not a second SASE runtime.

The current workspace state matters:

- `../sase-android` already exists as `git@github.com:sase-org/sase-android.git`, but it is effectively empty: only an
  empty `README.md` is present after the initial commit.
- `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json` is the canonical mobile API contract snapshot.
- `../sase-core/crates/sase_gateway/README.md` and this repo's `docs/mobile_gateway.md` document the gateway response
  shape, pairing flow, bearer-token auth, SSE reconnect behavior, and route set.
- Epics 2-4 may still be maturing while Android starts. Android must be able to proceed against checked fixtures and a
  fake gateway, then switch to the real host as endpoints land.

The Android app should use Kotlin, Jetpack Compose, Material 3, kotlinx serialization, OkHttp or Ktor, coroutine Flows,
and a small local cache. This plan chooses OkHttp for REST and SSE because the existing gateway is plain HTTP plus
server-sent events, and OkHttp keeps the MVP dependency surface small. If the implementing agent finds a strong local
reason to use Ktor instead, it may do so, but it must keep the same repository boundaries and tests.

## Goal

Deliver an Android app foundation in `../sase-android` that can:

- build and test from a clean checkout;
- pair with a SASE gateway by manual code and QR payload;
- store paired-host metadata and bearer tokens using Android Keystore-backed storage;
- call the versioned `/api/v1` REST contract and map gateway errors deterministically;
- subscribe to `/api/v1/events`, reconnect with `Last-Event-ID`, and refresh full state after reconnect/resync;
- cache session and notification state locally enough to survive app restart;
- render the first usable Compose screens: inbox list, notification detail, and settings/paired host;
- run against mocked gateway fixtures before every host endpoint is complete.

## Non-Goals

- Plan/HITL/question action UX. Epic 6 owns mobile action controls and mutation flows.
- Agent launch, kill, retry, image launch, helper pickers, and update screens. Epic 6 owns those user flows.
- Android background push delivery, foreground service behavior, notification permission UX, packaging, and release
  hardening. Epic 7 owns those.
- Embedding Rust `sase_core` or running agents on the phone.
- Arbitrary host file access, shell access, or Android-controlled gateway command execution.
- iOS or Kotlin Multiplatform support.

## Android Architecture

Use a conventional single-app Android architecture:

- `:app` Android application module with package `org.sase.mobile` unless the human chooses a different ID before Phase
  1 starts.
- Kotlin, Compose, Material 3, Navigation Compose, kotlinx serialization, coroutines, OkHttp, Room or DataStore-backed
  small cache, and a Keystore-backed token store.
- Clear package boundaries:
  - `data.api` for DTOs, REST client, SSE client, and gateway error mapping;
  - `data.session` for host/session/token persistence;
  - `data.notifications` for notification repository and cache;
  - `domain` for app-facing models where DTOs should not leak directly into UI;
  - `ui.settings`, `ui.inbox`, `ui.notification`, and shared `ui.components`;
  - `testing` fixtures and fake gateway utilities.
- Prefer handwritten Kotlin DTOs checked against the JSON contract snapshot for MVP. Generated OpenAPI clients can be
  revisited later if the host contract becomes large enough to justify build complexity.
- Keep gateway state authoritative. The local cache is for startup continuity and offline display, not conflict-prone
  offline mutation.

## Cross-Phase Rules

- Start every phase with `git status --short` in each repo it will touch and preserve unrelated dirty changes.
- Most phases should touch only `../sase-android`. Touch this repo only for plan/docs links if a final integration phase
  needs them.
- Do not modify `../sase-core` from this epic except to read the committed contract snapshot. Contract changes belong to
  gateway epics.
- Keep API DTOs versioned and serialization-tested against fixtures derived from
  `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`.
- Never log bearer tokens, pairing codes, QR payload secrets, or attachment tokens.
- Treat all gateway errors as structured `ApiErrorWire`; do not parse human error text.
- Add tests in the same phase as behavior. Later agents should not have to backfill basic safety coverage.
- Use stable Android Gradle Plugin, Kotlin, Compose BOM, and library versions available in the local Android SDK/Gradle
  environment at implementation time. Pin them in a version catalog.
- Each implementation phase should run the strongest available Android verification gate. The target gate is
  `./gradlew testDebugUnitTest lintDebug assembleDebug`; run `./gradlew connectedDebugAndroidTest` when an emulator or
  device is available. If the Android SDK is unavailable, the agent must say exactly which command failed and why.

## Phase 1: Android Repo Scaffold, Build, And CI Baseline

Owner: one agent. Write scope: `../sase-android` only.

Purpose: turn the empty Android repo into a buildable, testable Kotlin/Compose app with a clean project shape.

Concrete work:

- Add a standard Gradle Android application project:
  - Gradle wrapper;
  - `settings.gradle.kts`;
  - root `build.gradle.kts`;
  - `gradle/libs.versions.toml`;
  - `app/build.gradle.kts`;
  - Android manifest and minimal app entry point.
- Configure Kotlin, Compose, Material 3, Navigation Compose, kotlinx serialization, coroutines, OkHttp, Room or
  DataStore dependencies, AndroidX test dependencies, and lint.
- Use package/application ID `org.sase.mobile` unless the repo or user has already chosen another package ID.
- Add a minimal Compose shell with a top-level `SaseMobileApp` and placeholder navigation destinations for inbox,
  notification detail, and settings. Keep the first screen an app surface, not a marketing page.
- Add baseline unit tests and a simple Compose UI test or instrumentation smoke if the local Android environment can run
  it.
- Add GitHub Actions or the repo's chosen CI equivalent for assemble, unit tests, and lint. Do not require secrets or
  release signing.
- Write `README.md` with local setup, build/test commands, gateway dependency, and current MVP scope.

Acceptance:

- `../sase-android` builds a debug APK.
- `./gradlew testDebugUnitTest lintDebug assembleDebug` passes, or the final response clearly names missing local SDK
  prerequisites.
- The repo has a stable package/module layout that later phase agents can extend without re-scaffolding.

## Phase 2: Gateway Contract Snapshot, Kotlin DTOs, And Mock Fixtures

Owner: one agent. Write scope: `../sase-android` only.

Purpose: make Android development independent of live host endpoint availability while staying checked against the
gateway contract.

Concrete work:

- Vendor or copy the current gateway contract snapshot into the Android repo under a stable path such as
  `app/src/test/resources/contracts/mobile_api_v1.json`.
- Add a small contract metadata loader that checks:
  - `schema_version`;
  - `base_path == "/api/v1"`;
  - expected route method/path pairs for health, pairing, session, events, notifications, and attachments;
  - response-shape assumptions, especially direct success records and `ApiErrorWire` errors.
- Implement Kotlin serialization DTOs for the Epic 5 surface:
  - health;
  - pairing start/finish;
  - session/device;
  - API error;
  - event record and event payloads needed for heartbeat, resync, session, notifications changed, agents changed, and
    helper/update changed;
  - notification list/detail, action state summary, and attachment manifest fields needed for inbox/detail display.
- Add JSON fixtures for representative gateway responses:
  - successful health/session/pairing;
  - unauthorized, not found, stale/resync, and bridge unavailable errors;
  - empty inbox;
  - mixed notification inbox with plan, HITL, question, workflow, error digest, image, and generic notification cards;
  - notification detail with notes, action state, and attachments;
  - SSE heartbeat, notification-changed, and resync-required events.
- Add DTO round-trip and fixture parse tests. These tests should fail loudly if field names, enum tags, null behavior,
  or required routes drift.
- Add a reusable fake gateway or MockWebServer fixture harness for later repository and UI tests.

Acceptance:

- Android has typed models for all data needed by pairing, session, events, inbox, detail, and settings.
- Unit tests parse all committed fixtures and verify the checked contract still includes the routes Epic 5 relies on.
- Later UI phases can run entirely against fake gateway fixtures.

## Phase 3: REST API Client, Auth, And Gateway Error Mapping

Owner: one agent. Write scope: `../sase-android` only.

Purpose: provide the app's typed HTTP layer before session and UI code depend on it.

Concrete work:

- Implement a `GatewayApiClient` over OkHttp and kotlinx serialization:
  - base URL validation and normalization;
  - JSON content type handling;
  - bearer auth injection when a token is available;
  - request timeout and connection timeout defaults appropriate for a local or tailnet host;
  - typed success decoding;
  - structured `ApiErrorWire` decoding for non-2xx responses;
  - deterministic transport error mapping for DNS, connection refused, timeout, TLS/cleartext policy, and invalid JSON.
- Implement typed methods for:
  - `GET /health`;
  - `POST /session/pair/start`;
  - `POST /session/pair/finish`;
  - `GET /session`;
  - `GET /notifications`;
  - `GET /notifications/{id}`;
  - `POST /notifications/{id}/mark-read`;
  - `POST /notifications/{id}/dismiss`.
- Keep action mutation endpoints out of UI workflows for this epic, but DTO/client definitions may exist if they are
  already required by detail state fixtures.
- Add query parameter builders for notification filters: unread, include dismissed, include silent, limit, and
  newer-than/high-water where supported by the contract.
- Add MockWebServer tests for auth header behavior, pair start/finish, session, notification list/detail, typed errors,
  malformed JSON, network failure, and base URL normalization.

Acceptance:

- Android can call every REST endpoint needed for pairing, session validation, inbox, detail, and notification
  read/dismiss state.
- Raw HTTP and JSON failures are represented as app-level errors the UI can render without inspecting exceptions.
- Tests prove bearer tokens are sent only to the configured gateway base URL and are not logged.

## Phase 4: Pairing, Keystore-Backed Session Storage, Host Management, And Settings UI

Owner: one agent. Write scope: `../sase-android` only.

Purpose: let a user pair the app with a gateway, persist the session across restart, and inspect/manage the paired host.

Concrete work:

- Implement persistent host/session storage:
  - host label and normalized base URL;
  - device ID/display name returned by the gateway;
  - paired timestamp and last successful session check;
  - bearer token stored through Android Keystore-backed encryption;
  - non-secret settings through DataStore or the chosen local persistence layer.
- Implement a session repository that can:
  - validate a saved session with `GET /session`;
  - clear/re-pair a host;
  - expose connection/session state as a Flow;
  - handle auth expired/revoked, gateway unavailable, and host URL changes.
- Implement manual pairing UX:
  - host URL input;
  - pairing ID and one-time code input;
  - device display name defaulted from Android device/app metadata where safe;
  - progress, success, and structured failure states.
- Implement QR pairing UX:
  - define and document the QR payload shape consumed by Android;
  - support scanning through CameraX plus a barcode scanner library, or a simpler platform-supported scanner if the
    Android environment already provides one;
  - request camera permission only for scanning;
  - parse QR payloads into host URL, pairing ID, and code without accepting arbitrary commands or paths.
- Build the Settings/Paired Host screen:
  - show host URL, device label, connection/session status, and last sync;
  - provide re-check session and forget host actions;
  - expose clear error states for disconnected host, invalid URL, auth expired, and pairing expired/rejected.
- Add unit tests for storage, session repository transitions, QR payload parsing, manual pairing success/failure, and
  token clearing. Add UI tests for settings/pairing flows using fake repositories where practical.

Acceptance:

- The app can pair manually and by QR payload, restart, and retain a valid session.
- Forgetting a host clears the bearer token and cached session metadata.
- Token storage is Keystore-backed and secrets are excluded from logs, screenshots, and plain test fixtures.

## Phase 5: SSE Client, Reconnect Policy, State Repository, And Local Cache

Owner: one agent. Write scope: `../sase-android` only.

Purpose: make Android track live gateway state while treating REST refreshes as authoritative after reconnects.

Concrete work:

- Implement an SSE client over OkHttp:
  - authenticated `GET /events`;
  - `Accept: text/event-stream`;
  - event ID tracking;
  - `Last-Event-ID` reconnect support;
  - heartbeat handling;
  - structured parsing of `EventRecordWire`;
  - backoff with jitter for transient failures;
  - explicit stopped/logged-out state when the host is forgotten or auth expires.
- Implement a small local cache, preferably Room for notifications plus DataStore for sync cursors:
  - notification cards;
  - detail cache for recently opened rows;
  - read/dismissed state returned by the host;
  - last event ID and last full refresh timestamp;
  - session summary.
- Implement a notification repository that:
  - performs full refresh on app start, after successful pairing, after reconnect, and after `resync_required`;
  - performs incremental list refresh after `notifications_changed`;
  - keeps cached data visible while marking it stale/offline;
  - exposes UI-ready Flows for inbox list, detail, connection state, and refresh state.
- Add notification mark-read and dismiss repository operations using the Phase 3 client. Keep action responses out of
  scope.
- Add fake gateway and fake SSE tests for heartbeat, reconnect with Last-Event-ID, resync-required, auth failure,
  connection refused, stale cache display, mark-read/dismiss, and full-state refresh after reconnect.

Acceptance:

- The repository survives app restart with cached session/inbox state and refreshes from the host when reachable.
- SSE reconnect behavior follows the gateway contract: events wake the repository, but REST fetches are authoritative.
- Unit tests cover repository state transitions and cache behavior.

## Phase 6: Inbox And Notification Detail Compose UI

Owner: one agent. Write scope: `../sase-android` only.

Purpose: build the first usable SASE mobile screens on top of the repository and fixtures.

Concrete work:

- Implement app navigation for:
  - inbox list;
  - notification detail;
  - settings/paired host.
- Build an Inbox screen that supports:
  - connection/session status in a compact, non-intrusive app bar or status row;
  - unread/actionable/dismissed visual states;
  - priority and notification-kind affordances;
  - empty, loading, refreshing, stale/offline, and error states;
  - pull-to-refresh or an explicit refresh button;
  - filter affordances for unread and include dismissed/silent if the repository exposes them cleanly.
- Build a Notification Detail screen that supports:
  - title, timestamp, source/kind, priority/action state, and notes content;
  - attachment metadata rows without downloading arbitrary files in this epic;
  - read/dismiss actions;
  - stale/already-handled/unsupported action-state messaging;
  - no plan/HITL/question action buttons yet beyond non-mutating state display.
- Build Compose previews backed by the fixture data from Phase 2.
- Add UI tests that cover the main navigation paths, empty inbox, mixed inbox, detail rendering, read/dismiss actions,
  stale/offline state, and settings link.
- Follow the frontend guidance for a utilitarian operational tool: dense but readable rows, predictable navigation,
  restrained styling, icons for repeated actions, and no marketing/hero surface.

Acceptance:

- A paired user can open the app, see live or cached notification data, inspect a notification, mark it read or dismiss
  it, and reach host settings.
- Preview fixtures cover all notification kinds listed in the legend so Epic 6 can add action controls without
  redesigning detail layout.
- Text fits on small and large Android viewports without overlapping or relying on viewport-scaled typography.

## Phase 7: Android Smoke Harness, Documentation, And Final Integration Gate

Owner: one final integration/land agent after Phases 1-6 are merged.

Purpose: verify the Android foundation end to end and leave a clean base for Epic 6.

Concrete work:

- Add or finalize a fake gateway test application/harness that can:
  - serve health, pairing, session, notifications, detail, and events;
  - emit heartbeat, notifications-changed, and resync-required SSE events;
  - validate auth headers and pairing payloads.
- Add an instrumentation smoke path using MockWebServer or a local fake gateway:
  - launch the app with no paired host;
  - pair via test data;
  - show the inbox;
  - open detail;
  - mark read or dismiss;
  - simulate SSE reconnect/resync;
  - verify settings can forget the host.
- Add a manual real-host smoke checklist in `README.md`:
  - start `sase mobile gateway start`;
  - finish pairing;
  - fetch session/inbox;
  - restart the app and verify session restoration;
  - trigger a notification-state refresh;
  - document known limitations.
- Review the copied contract snapshot against `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json` and
  refresh Android fixtures if the host contract has moved.
- Run final verification:
  - `./gradlew testDebugUnitTest lintDebug assembleDebug`;
  - `./gradlew connectedDebugAndroidTest` if an emulator/device is available;
  - any CI workflow locally reproducible without secrets.
- Record known limitations for Epic 6 and Epic 7:
  - no action mutation UI yet;
  - no agent/helper screens yet;
  - no background push/foreground service yet;
  - attachment download/viewing is metadata-only unless implemented incidentally for fixtures;
  - generated client is intentionally deferred.

Acceptance:

- The app foundation is usable against a fake gateway and can be manually smoke-tested against a real local SASE
  gateway.
- Restart persistence, session validation, inbox refresh, SSE reconnect/resync, and read/dismiss flows are covered by
  automated tests where practical.
- `../sase-android` has clear README instructions for the next agent and for a human running the MVP locally.

## Suggested Phase Dependencies

- Phase 1 is the root dependency for every later phase.
- Phase 2 depends on Phase 1 and on the available gateway contract snapshot from Epic 1. It can use the current snapshot
  even while Epics 2-4 continue to fill endpoint behavior.
- Phase 3 depends on Phase 2.
- Phase 4 depends on Phase 3.
- Phase 5 depends on Phases 3 and 4.
- Phase 6 depends on Phases 2 and 5. It may begin UI work against fixtures after Phase 2, but final live repository
  integration depends on Phase 5.
- Phase 7 depends on Phases 1-6.

## Suggested Phase Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_mobile_gateway_epic_5.md`: scaffold the `../sase-android` Kotlin/Compose Android app
> with Gradle wrapper, Material 3, baseline navigation placeholders, CI/lint/test setup, README, and a passing debug
> build. Do not implement gateway networking yet.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_mobile_gateway_epic_5.md`: copy the mobile gateway contract snapshot into
> `../sase-android`, add Kotlin serialization DTOs and representative fixtures for pairing/session/events/notifications,
> and add contract/fixture parse tests plus a fake gateway test harness.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_mobile_gateway_epic_5.md`: add the typed Android gateway REST client with bearer
> auth, structured `ApiErrorWire` mapping, health/pairing/session/notification endpoints, and MockWebServer tests.

Phase 4 prompt:

> Implement Phase 4 from `sase_plan_mobile_gateway_epic_5.md`: add Keystore-backed token/session storage, manual and QR
> pairing flows, host/session repository behavior, and the Settings/Paired Host UI in `../sase-android`.

Phase 5 prompt:

> Implement Phase 5 from `sase_plan_mobile_gateway_epic_5.md`: add the authenticated SSE client, reconnect with
> `Last-Event-ID`, authoritative full-state refresh behavior, local notification cache, and repository state-transition
> tests.

Phase 6 prompt:

> Implement Phase 6 from `sase_plan_mobile_gateway_epic_5.md`: build the Compose inbox and notification detail screens
> over the repository and fixture previews, including loading/offline/stale/error states and read/dismiss controls.

Phase 7 prompt:

> Implement Phase 7 from `sase_plan_mobile_gateway_epic_5.md`: add the Android fake-gateway smoke harness,
> instrumentation smoke path, real-host manual checklist, final contract fixture refresh, and the Android verification
> gate.

## Final Definition Of Done

- `../sase-android` is a buildable Kotlin/Compose Android app with pinned Gradle/library versions and CI-ready checks.
- The app can pair with a SASE gateway by manual code and QR payload.
- The bearer token is stored with Android Keystore-backed protection and survives app restart until the user forgets the
  host.
- The app validates the saved session, shows connection status, subscribes to gateway SSE, reconnects with
  `Last-Event-ID`, and refreshes full state after reconnect/resync.
- The app displays live or cached notification inbox data from the host and can render notification detail.
- Unit tests cover API serialization, REST error mapping, session storage, repository state transitions, and cache/SSE
  behavior.
- Compose previews and UI/instrumentation smoke coverage exist for inbox, detail, and settings.
- Mocks and fixtures are good enough for Epic 6 agents to add action, agent, and helper UX without waiting on a live
  gateway for every test.
