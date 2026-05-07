---
create_time: 2026-05-06 09:56:05
status: done
prompt: sdd/prompts/202605/sase_mobile_mvp_legend.md
legend_bead_id: sase-26
tier: legend
epic_count: 7
---
# SASE Mobile MVP Legend Plan

## Product Goal

Build an MVP Android app for SASE that reaches practical Telegram integration parity by controlling the user's
workstation-hosted SASE runtime. The phone is a client, not a replacement host. It should let a paired Android device
receive actionable SASE notifications, approve or answer blocked agents, launch and manage agents, inspect workflow
helpers, and start SASE updates without needing Telegram as the transport.

This plan is intentionally legend-sized. Each epic below should later be converted into its own executable epic plan
with phase beads. The first useful MVP milestone is not "every screen is polished"; it is:

- Pair an Android device with a local SASE host gateway.
- Receive plan, HITL, question, workflow, launch, kill, error, image, and generic notifications.
- Act on plan, HITL, and question notifications from Android.
- Launch text and image agents from Android.
- List, kill, retry, resume, and wait on agents.
- Use ChangeSpec, xprompt, bead, and update helper flows from Android.

## Architectural Decision

Adopt the architecture recommended by `sdd/research/202605/android_mobile_rust_core_api.md`:

- Add a workstation host gateway as the primary API.
- Use `../sase-core/crates/sase_core` for stable wire records and deterministic shared behavior.
- Bridge host-owned side effects through this repo's existing Python modules and CLI paths until those behaviors are
  intentionally migrated to Rust.
- Build Android as a Kotlin + Jetpack Compose client over REST + JSON command endpoints and an SSE event stream.
- Treat UniFFI as optional for a narrow mobile helper SDK later, not as the MVP control plane.

The phone must not write arbitrary host files, run arbitrary shell commands, or embed "all of SASE" in the APK. The
gateway exposes product-shaped commands and owns host filesystem/process effects.

## Repository Scope

Expected implementation will touch at least three workspaces:

- `../sase-core`
  - Add gateway/server crates and shared mobile/API wire contracts.
  - Keep pure deterministic behavior in `sase_core`.
- This repo, `sase_101`
  - Add Python bridge modules, CLI/config integration, SASE notification/action adapters, docs, and tests.
  - Keep Textual/TUI-specific behavior out of the gateway contract.
- New Android app repo, defaulting to sibling `../sase-android` unless the human chooses a different repository name.
  - Kotlin/Compose app, networking, pairing, notification handling, and app UI.

## MVP API Shape

Use versioned REST endpoints under `/api/v1` plus SSE for events:

- `GET /health`
- `GET /session`
- `POST /session/pair/start`
- `POST /session/pair/finish`
- `GET /events`
- `GET /notifications`
- `GET /notifications/{id}`
- `POST /notifications/{id}/mark-read`
- `POST /notifications/{id}/dismiss`
- `GET /attachments/{token}`
- `POST /actions/plan/{prefix}/approve`
- `POST /actions/plan/{prefix}/run`
- `POST /actions/plan/{prefix}/reject`
- `POST /actions/plan/{prefix}/epic`
- `POST /actions/plan/{prefix}/legend`
- `POST /actions/plan/{prefix}/feedback`
- `POST /actions/hitl/{prefix}/accept`
- `POST /actions/hitl/{prefix}/reject`
- `POST /actions/hitl/{prefix}/feedback`
- `POST /actions/question/{prefix}/answer`
- `POST /actions/question/{prefix}/custom`
- `GET /agents`
- `GET /agents/resume-options`
- `POST /agents/launch`
- `POST /agents/launch-image`
- `POST /agents/{name}/kill`
- `POST /agents/{name}/retry`
- `GET /changespec-tags`
- `GET /xprompts/catalog`
- `GET /beads`
- `GET /beads/{id}`
- `POST /update/start`
- `GET /update/{job_id}`

SSE events should carry stable IDs and support `Last-Event-ID` resume. Android should fetch full state after reconnect
instead of trusting push payloads as authoritative.

## Epic 1: Host Gateway Foundation And Pairing

Goal: create a minimal, secure host gateway that Android can pair with and query.

Scope:

- Add a gateway crate in `../sase-core`, likely `crates/sase_gateway`, using `axum`/`tokio`.
- Add shared API wire structs for health, session, device, auth, errors, events, and common pagination/filtering.
- Add a Python launcher/config bridge in this repo so users can start the gateway through SASE rather than manually
  running a Rust binary.
- Bind to `127.0.0.1` by default; require explicit config for LAN or tailnet binds.
- Implement pairing with one-time codes and long-lived per-device tokens. Keep the first version simple and auditable;
  do not expose any unauthenticated mutating endpoint.
- Add basic audit logging for device, endpoint, target ID, and outcome.
- Generate or hand-maintain OpenAPI/JSON contract snapshots for Android.

Suggested phase split:

1. Rust gateway crate and typed error/response/event contract.
2. Pairing/session/token storage and authenticated request middleware.
3. Python CLI/config integration and gateway lifecycle management.
4. SSE event skeleton with heartbeat, resume IDs, and test client coverage.
5. Documentation and local setup path, with Tailscale Serve as the recommended private remote access option.

Definition of done:

- A desktop user can start the gateway from SASE.
- An authenticated client can pair, call health/session, and subscribe to events.
- Contract tests cover auth success/failure, token revocation, bind-address defaults, and SSE reconnect.

## Epic 2: Notification Inbox, Pending Actions, And Attachments

Goal: expose Telegram-equivalent outbound notification behavior through the gateway.

Scope:

- Reuse Rust notification-store reads where available.
- Add shared Rust wire models for mobile notification cards, action state, pending action identity, stale state, and
  attachment manifests.
- Migrate or mirror Telegram's pending action concepts into host-generic storage so Telegram and mobile can eventually
  share action matching semantics.
- Implement notification list/detail endpoints with unread, silent, dismissed, high-water, and actionability metadata.
- Implement plan/HITL/question action endpoints by translating mobile choices into the same response files SASE already
  consumes:
  - `plan_response.json`
  - `hitl_response.json`
  - `question_response.json`
- Detect actions already handled elsewhere by checking response files and notification/action state before writing.
- Expose authenticated attachment downloads with short-lived tokens and manifest metadata for plan files, PDFs, diffs,
  images, digest files, and generic documents.

Suggested phase split:

1. Notification card and pending-action wire model in Rust with JSON snapshots.
2. Gateway read-only notification list/detail and SSE notification events.
3. Pending action storage, stale cleanup, and external-handled detection.
4. Plan/HITL/question mutating endpoints with response-file intent planning in Rust and host writes in Python.
5. Attachment manifest and download-token support.

Definition of done:

- Android or a curl client can see all notification types described in the Telegram docs.
- Plan approve/run/reject/epic/legend/feedback, HITL accept/reject/feedback, and question option/custom responses
  unblock the same agents that the TUI and Telegram flows unblock.
- Duplicate, stale, and already-handled actions return deterministic API errors instead of overwriting state.

## Epic 3: Agent Lifecycle, Launch, Retry, And Image Input

Goal: expose the Telegram agent-management and launch surface through host-shaped gateway commands.

Scope:

- Add agent list endpoints backed by existing running-agent and artifact scan logic.
- Add launch endpoints that call existing host launch code, preserving xprompt expansion, VCS directives, multi-model
  directives, auto-naming, and project context behavior.
- Preserve or replace Telegram `#workflow@ref` shorthand with a host-normalized helper that Android can call before
  launch.
- Add image upload and launch support. Images must be stored on the host, and prompts must reference the saved host
  path.
- Add kill and retry endpoints using existing agent-running APIs.
- Add resume/wait prompt generation endpoints so Android can offer native copy/share actions or direct launch
  follow-ups.
- Store enough launch context for retry after a kill, even if a pending action entry was lost.

Suggested phase split:

1. Read-only agent list/resume-options endpoint with rich agent descriptions.
2. Text launch endpoint using existing Python launch facade and normalized mobile launch requests.
3. Image upload and image launch endpoint with host-side storage and validation.
4. Kill/retry endpoints with consistent result wire records and audit logging.
5. Project-context persistence for launch, retry, and later bead/helper commands.

Definition of done:

- A paired client can launch one or more agents, receive launch confirmation, list them, kill one by name, and retry it.
- Image launch stores the image on the host and starts an agent with a valid local path reference.
- Multi-model launch requests retain current SASE behavior.

## Epic 4: Workflow Helper APIs

Goal: replace Telegram slash commands with native mobile helper endpoints.

Scope:

- Add ChangeSpec tag listing with project filtering and terminal-status exclusion.
- Add xprompt catalog endpoint. The first version may return structured entries and an optional generated PDF path; it
  does not need to reproduce Telegram PDF-first UX.
- Add bead list/show endpoints across known projects, preserving Telegram's project-context resolution and project
  override behavior.
- Add update worker start/status endpoints backed by `src/sase/integrations/chat_install.py`.
- Standardize command-result wire records so Android can render partial success, skipped entries, and failures without
  parsing human text.

Suggested phase split:

1. ChangeSpec workflow-tag endpoint with project filter tests.
2. Xprompt catalog endpoint and optional attachment/PDF integration.
3. Bead list/show endpoint across known projects with remembered project context.
4. Update start/status endpoints and completion events.
5. Cross-helper result model and docs.

Definition of done:

- Android can present native pickers for ChangeSpec tags, xprompts, and beads.
- Android can start a SASE update and later receive completion/failure status.
- No helper endpoint shells out when an existing structured API is available; shelling out is explicitly contained where
  no better host API exists yet.

## Epic 5: Android App Foundation

Goal: create the Android app skeleton and core networking/session layer.

Scope:

- Create the Android project in `../sase-android` unless a different app repo is chosen.
- Use Kotlin, Jetpack Compose, Material 3, OkHttp or Ktor, kotlinx serialization, and a small local cache.
- Implement pairing by QR/manual code, token storage in Android Keystore-backed storage, connection status, and host
  management.
- Implement the API client, SSE client, reconnect logic, and full-state refresh after reconnect.
- Build the first usable screens:
  - Inbox list.
  - Notification detail.
  - Settings/paired host.
- Add mocked gateway fixtures so Android UI work can proceed before every host endpoint is complete.

Suggested phase split:

1. Android repo scaffold, Gradle setup, CI/lint/test baseline.
2. API models/client generated from or checked against the gateway contract.
3. Pairing/session storage and settings UI.
4. SSE/reconnect/state repository and local cache.
5. Inbox/detail Compose UI with preview fixtures and instrumentation smoke tests.

Definition of done:

- The app can pair with the gateway, survive restart with its session intact, show connection status, and render live
  notification data from the host.
- Unit tests cover API serialization and repository state transitions.

## Epic 6: Android Action, Agent, And Helper UX

Goal: make Android functionally useful for all Telegram-parity interactions.

Scope:

- Add native controls for plan, HITL, and question action flows.
- Add two-step feedback/custom-answer UX with draft preservation and failure retry.
- Add Agents screen with list, kill, retry, resume/wait actions, and launch result affordances.
- Add Launch screen with prompt editor, code-friendly input, project/workflow helpers, and image attach from camera or
  gallery.
- Add helper pickers for ChangeSpec tags, xprompts, and beads.
- Add update screen/status affordance.

Suggested phase split:

1. Plan/HITL/question action detail controls and mutation result handling.
2. Feedback/custom two-step flows with drafts, retries, and stale-action refresh.
3. Agents screen and kill/retry/resume/wait UX.
4. Launch screen with text prompt, helpers, and multi-model directive preservation.
5. Image attach/launch and Android content URI handling.
6. ChangeSpec, xprompt, bead, and update helper screens.

Definition of done:

- A user can complete every Telegram user-visible command from Android without memorizing slash commands.
- Error states are actionable: stale action, disconnected host, auth expired, launch failure, and upload failure each
  produce a clear recovery path.

## Epic 7: Background Delivery, Packaging, And End-To-End Hardening

Goal: make the MVP reliable enough to use away from the workstation.

Scope:

- Implement Android notification permission handling for API 33+.
- Add foreground connected mode using Android's remote-messaging foreground service type where appropriate.
- Add push-hint infrastructure. Prefer FCM for the Play/internal APK path, but keep gateway payloads transport-agnostic
  so UnifiedPush/ntfy can be added without redesigning the host API.
- Push payloads must be hints only: no secrets, full prompts, or large file contents. The app fetches details from the
  authenticated gateway after wake/open.
- Add e2e tests with a fake or temporary host gateway and Android emulator smoke coverage where practical.
- Add packaging docs for direct APK/internal distribution and remote access docs for Tailscale Serve.
- Threat-model review: lost phone, LAN attacker, public tunnel exposure, attachment URL leakage, and accidental
  arbitrary-command expansion.

Suggested phase split:

1. Android runtime notification permission and local notification rendering.
2. Foreground connection service and reconnect/backoff policy.
3. Push-hint registration and host event-to-push bridge.
4. E2E harness with fake gateway plus at least one real-host smoke scenario.
5. Security review, packaging docs, and MVP runbook.

Definition of done:

- When the app is backgrounded, the user can receive a notification hint and open the app to current host state.
- Foreground connected mode is stable and visible to Android as required by platform rules.
- The MVP has a documented setup path, known limitations, and regression tests for the primary approval/launch/kill
  flows.

## Dependency Order

Recommended execution waves:

1. Epic 1 first. It establishes the host gateway, auth, API conventions, and Android contract.
2. Epics 2 and 3 can run in parallel after Epic 1's contract skeleton exists.
3. Epic 4 can run in parallel with late Epic 2/Epic 3 work once common result/error models are stable.
4. Epic 5 can start as soon as Epic 1 publishes API snapshots, using mocks while host endpoints mature.
5. Epic 6 depends on Epics 2, 3, 4, and 5.
6. Epic 7 should start after the app can perform foreground flows, but push-hint contract design should be reviewed
   before Epic 2 finalizes event payloads.

## Cross-Cutting Requirements

- All mutating host endpoints require authentication and audit logging.
- Every CLI-facing option introduced in this repo still needs a short form when applicable.
- New deterministic backend behavior belongs in `../sase-core/crates/sase_core`; Python stays a thin host bridge where
  Rust is ready and remains the owner where plugin/runtime behavior is still Python-only.
- Do not introduce runtime-specific Claude/Gemini/Codex special cases.
- Prefer structured APIs over parsing human CLI output. When parsing is unavoidable, contain it behind a bridge module
  and replace it in a later phase.
- Keep REST JSON contracts snapshot-tested so Android and host agents can work independently.
- Avoid OpenSSL on the Android path; prefer Rustls/Tailscale TLS where TLS work is needed.

## Non-Goals For The MVP

- Hosted multi-tenant relay service.
- iOS support.
- Fully offline mobile SASE runtime.
- Arbitrary remote shell execution.
- Full live terminal/stdout streaming from agents.
- Replacing Telegram immediately; Telegram remains a working fallback while mobile matures.

## Open Decisions For The Epic-Planners

- Final Android repository name and package ID. Default proposal: `../sase-android` and `org.sase.mobile`.
- Whether FCM is acceptable for the first private build or whether UnifiedPush/ntfy is required from day one.
- Whether pairing should start with simple QR token bootstrap or SPAKE2/device-key exchange immediately.
- Whether generated OpenAPI clients are worth the build complexity for the first Android repo, or whether checked JSON
  snapshots plus handwritten Kotlin models are faster for MVP.
