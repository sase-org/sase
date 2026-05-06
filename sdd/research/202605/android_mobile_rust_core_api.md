# Android Mobile App over SASE Rust Core

Date: 2026-05-06

## Question

What should it look like to use SASE's Rust core as the API for a new Android mobile app, with an MVP that supports
everything the current Telegram integration can do?

## Executive Summary

The Android app should not try to embed "all of SASE" on the phone. The current Telegram integration is valuable
because it remotely controls the user's desktop SASE host: it reads the host's notification store, writes response files
that unblock local agents, launches and kills local agent processes, resolves local project workspaces, sends local
attachments, and runs the local update worker. Most of that behavior is not in `sase_core` today and cannot be made
useful on Android without access to the workstation's filesystem, processes, VCS credentials, installed LLM runtimes,
and SASE plugin environment.

The right shape is:

1. Add a SASE host gateway on the workstation.
2. Back that gateway with `sase_core` for shared data operations and stable wire records.
3. Bridge host-owned behavior through the existing Python facades/CLI until those pieces intentionally move to Rust.
4. Build the Android app as a Kotlin/Compose client over the gateway API.
5. Use UniFFI only for a small optional mobile SDK of pure local helpers and shared DTO validation, not as the primary
   control plane.

This preserves the architectural direction from the Rust migration research: `sase_core` stays the shared deterministic
backend, while UI shells and transports stay thin.

## Current SASE Shape

### Rust Core

The sibling repo `../sase-core` has a pure Rust crate at `crates/sase_core` and a PyO3 binding crate at
`crates/sase_core_py`. The pure crate deliberately has no PyO3 dependency, which keeps it reusable by future UniFFI,
WASM, or server crates.

The current pure Rust surface already covers many mobile-relevant read/decision primitives:

- ChangeSpec parsing.
- Query tokenizing/parsing/evaluation and persistent query/corpus handles in the PyO3 layer.
- Agent artifact scanning and artifact index operations.
- Notification store append/read/update/rewrite.
- Bead storage/read/mutation/CLI-compatible helpers.
- Status transition planning and line updates.
- Git-query parsing helpers.
- Agent launch planning, timestamp allocation, and workspace claim planning.

But it does not own the whole product runtime. Python still owns xprompt loading/expansion, plugin discovery, LLM/VCS
providers, actual agent subprocess launching, process liveness/kill, activity state, PDF conversion, update worker
orchestration, and several UI-adjacent composition layers.

### Telegram Integration

The Telegram plugin lives in `../sase-telegram` and is a separate chop-based integration. Its behavior is split into:

- Outbound chop: idle-gated notification delivery, high-water mark tracking, exclusive lock, rate limit, formatting,
  attachments, and pending action persistence.
- Inbound chop: Telegram update offset tracking, callback handling, two-step feedback, slash command handling, image
  download, agent launch, project context, and update-completion delivery.

Important files:

- `../sase-telegram/docs/architecture.md`
- `../sase-telegram/docs/inbound.md`
- `../sase-telegram/docs/outbound.md`
- `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`
- `../sase-telegram/src/sase_telegram/scripts/sase_tg_outbound.py`
- `../sase-telegram/src/sase_telegram/formatting.py`
- `../sase-telegram/src/sase_telegram/inbound.py`
- `../sase-telegram/src/sase_telegram/outbound.py`

## Telegram Parity Target

"Everything Telegram can do" is more than notifications. The Android MVP should cover these user-visible capabilities.

### Outbound / Host to Phone

- Deliver unread, non-silent notifications when the TUI says the user is idle.
- Preserve high-water mark semantics so successfully delivered notifications are not resent.
- Rate-limit delivery.
- Render notification types:
  - Plan approval.
  - HITL request.
  - User question.
  - Workflow complete.
  - Agent launched.
  - Agent killed.
  - Error digest.
  - Image generated.
  - Generic notifications.
- Preserve large-content behavior: inline short content, collapsible/preview medium content, attachment fallback for
  long content.
- Send attachments:
  - Plan files.
  - Markdown rendered as PDF when useful.
  - Diff files, ideally embedded into response PDFs when paired with chat/response markdown.
  - Images inline.
  - Existing PDFs/documents as files.
- Persist actionable notifications as pending actions so future phone actions can be matched reliably.
- Remove or disable stale pending actions.
- Detect actions already handled elsewhere, such as the TUI approving a plan after the mobile notification was sent.

### Inbound / Phone to Host

- Plan actions:
  - Approve/tale.
  - Approve and run coder without committing the plan.
  - Reject.
  - Create epic.
  - Create legend.
  - Feedback/revision request.
- HITL actions:
  - Accept.
  - Reject.
  - Feedback.
- User question actions:
  - Select one of the provided options.
  - Send custom answer text.
- Two-step flows:
  - Tap Feedback/Custom.
  - Send text response.
  - Write the correct response JSON file.
- Agent launch:
  - Launch from free-form text.
  - Preserve Telegram-specific `#workflow@ref` shorthand parity, or replace it with an Android-native picker.
  - Reconstruct or preserve code blocks from mobile input.
  - Support xprompt expansion.
  - Support multi-model directives.
  - Auto-name agents.
  - Return launch confirmation with resume/wait/kill/retry affordances.
- Image launch:
  - Accept camera/gallery images and image documents.
  - Store/download them on the host, not only on the phone.
  - Launch an agent with a prompt pointing at the saved host path.
- Agent management:
  - List running agents.
  - Kill named agents.
  - Retry using original prompt.
  - Generate resume/wait prompt text.
  - Show running/done resume choices.
- ChangeSpec helpers:
  - List active ChangeSpec workflow tags.
  - Filter by project.
  - Copy or insert tags into launch prompts.
- Xprompt helpers:
  - Generate/show/send xprompt catalog output equivalent to `/xprompts`.
- Beads:
  - List active beads across known projects.
  - Show bead details.
  - Preserve project-context resolution from recent launch prompts.
- Update:
  - Start the detached SASE update worker.
  - Show immediate acknowledgement.
  - Deliver completion/failure result later.

## Why an Embedded Android-Only Core Is Not Enough

An embedded Android `sase_core` library can parse/query/format local data if that data is already on the phone. It
cannot by itself do the core Telegram-equivalent jobs:

- It cannot read `~/.sase/notifications/notifications.jsonl` on the workstation unless a host process exposes it.
- It cannot write `plan_response.json`, `hitl_response.json`, or `question_response.json` into the agent artifact
  directories on the workstation.
- It cannot kill local agent processes running on the workstation.
- It cannot launch agents with the user's installed LLM CLIs, local workspace clones, VCS provider plugins, and SASE
  config.
- It cannot safely attach local plan/diff/chat/PDF files without a host broker.

So "Rust core as API" should mean a host API whose request/response contract is defined in Rust and backed by
`sase_core`, not "put `sase_core` in the APK and skip the workstation."

## Android / Rust Integration Findings

### UniFFI

UniFFI is a good fit for generating Kotlin bindings for Rust libraries. The current UniFFI guide says it generates
foreign-language bindings for Rust crates and has full support for Kotlin, Swift, and Python. It can use proc macros or
an IDL, and the Kotlin binding has Android-specific configuration such as `android = true`, `package_name`, and
`cdylib_name`. Its Gradle integration guide still documents a manual `uniffi-bindgen generate ... --language kotlin`
task and a JNA dependency.

Sources:

- https://mozilla.github.io/uniffi-rs/latest/bindings.html
- https://mozilla.github.io/uniffi-rs/latest/kotlin/configuration.html
- https://mozilla.github.io/uniffi-rs/latest/kotlin/gradle.html
- https://mozilla.github.io/uniffi-rs/0.29/

Implication for SASE:

- Use UniFFI for a narrow `sase_mobile_core` crate if we want shared local helpers in the app.
- Keep the API coarse-grained. Large per-row FFI crossings have already burned SASE once in query evaluation; use
  batch operations or JSON blobs where that is simpler.
- Do not expose the whole existing PyO3-shaped binding one function at a time. Design a mobile-specific facade.

### Android Rust Build

Rust supports Android targets through the Android NDK. The Rust 1.68 update moved Android platform support to NDK r25,
and current `rustc` platform support docs state Rust supports the most recent LTS Android NDK. `cargo-ndk` remains the
practical build helper for producing Android libraries from Cargo projects.

Sources:

- https://blog.rust-lang.org/2023/01/09/android-ndk-update-r25/
- https://doc.rust-lang.org/rustc/platform-support/android.html
- https://github.com/bbqsrc/cargo-ndk

Implication for SASE:

- Add a new `cdylib` crate rather than reusing `sase_core_py`.
- Target the normal Android ABIs: `arm64-v8a` first, then `armeabi-v7a`, `x86_64`, and `x86` if emulator/old-device
  support matters.
- Keep Android-linked dependencies conservative. `sase_core` currently depends on filesystem, SQLite, regex, chrono,
  and serde. That is plausible, but the mobile facade should avoid pulling host-only behavior into the APK.

### Android Background Delivery

Android background execution rules make a Telegram-style "poll every five seconds forever from the app" the wrong
mobile design. Android's background-work docs direct developers to choose between asynchronous work, WorkManager,
foreground services, and alternatives depending on user visibility and task urgency. Foreground services are intended
for user-noticeable work and have restrictions. Firebase Cloud Messaging is the standard way to receive push messages;
Firebase's Android docs describe `FirebaseMessagingService` for receiving messages and note that notification messages
in the background go to the system tray.

Sources:

- https://developer.android.com/develop/background-work
- https://developer.android.com/develop/background-work/services/fgs
- https://firebase.google.com/docs/cloud-messaging/android/client
- https://firebase.google.com/docs/cloud-messaging/android/receive-messages

Implication for SASE:

- Foreground app: maintain a WebSocket/SSE connection to the host gateway.
- Background app: receive FCM notification/data payloads as wake-up hints, then fetch current state when opened.
- Do not build the MVP around phone-side periodic polling.

## API Shape

The host gateway should expose product-level commands, not raw file writes. The phone should never need to know whether
a plan response is stored as `plan_response.json` or whether a bead lookup shells out to `sase bead show`.

Suggested high-level API:

```text
GET  /api/health
GET  /api/session
POST /api/session:pair

GET  /api/events
GET  /api/notifications?include_dismissed=false
GET  /api/notifications/{id}
POST /api/notifications/{id}:mark-read
POST /api/notifications/{id}:dismiss
POST /api/notifications/{id}:snooze

POST /api/actions/plan/{prefix}:approve
POST /api/actions/plan/{prefix}:run
POST /api/actions/plan/{prefix}:reject
POST /api/actions/plan/{prefix}:epic
POST /api/actions/plan/{prefix}:legend
POST /api/actions/plan/{prefix}:feedback

POST /api/actions/hitl/{prefix}:accept
POST /api/actions/hitl/{prefix}:reject
POST /api/actions/hitl/{prefix}:feedback

POST /api/actions/question/{prefix}:answer
POST /api/actions/question/{prefix}:custom

GET  /api/agents?state=running
GET  /api/agents/resume-options
POST /api/agents:launch
POST /api/agents:launch-image
POST /api/agents/{name}:kill
POST /api/agents/{name}:retry

GET  /api/changespec-tags?project=...
GET  /api/xprompts/catalog
GET  /api/beads?project=...
GET  /api/beads/{id}?project=...
POST /api/update:start
GET  /api/update/{job_id}
```

The gateway can implement these endpoints using a mix of:

- Direct Rust `sase_core` calls for notification snapshots, bead reads/mutations where already ported, status planning,
  agent artifact scan/index, and query helpers.
- Existing Python modules or `sase` CLI subprocesses for xprompt expansion, agent launch, running-agent kill/list,
  update worker launch, PDF rendering, and plugin-owned behavior.

This mirrors the web-client research recommendation: a Rust `axum` server is the long-term backbone, but command-shaped
side effects can bridge to Python host logic until the Rust port earns its way in.

## Connectivity Options

### Option A: Android Embeds `sase_core` Only

Pros:

- Lowest server work.
- Useful for local parsing/querying if SASE data is synced to the phone.
- Simple offline demos.

Cons:

- Does not meet Telegram parity.
- Cannot launch/kill agents on the workstation.
- Cannot handle pending approval response files on the host.
- Creates a second source of truth for state if data is copied to the phone.

Assessment: not viable for the requested MVP.

### Option B: Host Gateway on LAN/VPN, Android Client Connects Directly

Pros:

- Directly maps to the real SASE host.
- Avoids a hosted multi-tenant service.
- Easy to secure for a personal MVP with pairing, short-lived tokens, and a private network such as Tailscale/WireGuard.
- Works well with WebSocket/SSE while the app is open.

Cons:

- Requires phone-to-host reachability.
- Background notifications still need either FCM or user-visible foreground service.
- Remote access setup becomes part of the product experience.

Assessment: best MVP if this is a personal/internal SASE app.

### Option C: Hosted Relay

Pros:

- Closest network shape to Telegram: host and phone both make outbound connections to a cloud service.
- Works off LAN without a VPN.
- Enables push, command queueing, and multi-device support.

Cons:

- Introduces user accounts, cloud security, data retention, relay availability, and hosted ops.
- Raises the blast radius for prompts, file paths, agent summaries, and attachments.
- More infrastructure before the mobile product is proven.

Assessment: possible later, but too much for the first MVP unless remote-anywhere access without VPN is non-negotiable.

### Option D: Keep Telegram as Transport, Add Android Mini-App/WebView

Pros:

- Keeps Telegram's solved delivery/pairing/network problem.
- Faster path to richer UI if Telegram Mini Apps are acceptable.

Cons:

- Not a standalone Android app.
- Still inherits Telegram bot privacy and formatting constraints.

Assessment: good fallback or stepping stone, but it does not satisfy the stated Android-app direction.

## Host Gateway Design

Recommended first host component:

```text
../sase-core/
  crates/sase_core/          # existing pure domain/data crate
  crates/sase_gateway/       # new axum/tokio host API binary or library

sase_100/
  src/sase/integrations/mobile_gateway.py  # optional Python bridge/launcher
  src/sase/main/mobile_handler.py          # starts/locates gateway
```

Core properties:

- Bind to `127.0.0.1` by default; allow explicit LAN/VPN bind only through config.
- Pair the phone by QR code with a one-time code and host public key/fingerprint.
- Use HTTPS if binding beyond loopback. For a private VPN MVP, pinned self-signed certs are acceptable.
- Use scoped bearer/session tokens.
- Use explicit command endpoints. No "run arbitrary shell command" endpoint.
- Log all mutating actions with actor/device, endpoint, notification/agent/bead id, and outcome.
- Validate `Origin`/`Host` for browser clients, and use token auth for mobile clients.
- Expose event stream by SSE or WebSocket.
- Keep attachments behind authenticated URLs with short TTLs.

Implementation order:

1. Read-only health/state:
   - health, notifications, running agents, recent/done agents, pending actions.
2. Mutating pending-action parity:
   - plan/HITL/question responses.
3. Agent commands:
   - launch, launch image, list, kill, retry, resume/wait prompt generation.
4. Helpers:
   - changes, beads, xprompts catalog, update worker.
5. Push/background:
   - FCM device registration and notification hints.

## Android App Design

Recommended app stack:

- Kotlin + Jetpack Compose.
- OkHttp/Ktor for HTTPS/WebSocket.
- Room or simple encrypted local cache for recent notifications/actions.
- Android Keystore for pairing tokens.
- FCM for background notification hints.
- Optional `sase_mobile_core` UniFFI AAR for shared DTO validation and pure helper functions.

First screens:

- Inbox: active notifications, grouped by action type/status.
- Action detail: plan/HITL/question detail with native controls.
- Agents: running agents with list/kill/retry/resume/wait controls.
- Launch: prompt input, project/workflow picker, image attach.
- Beads/Changes: compact pickers for bead details and workflow tags.
- Settings: paired host, connection status, notification delivery mode.

Avoid copying Telegram UI too literally. Android can use native sheets, lists, pickers, file previews, and persistent
state instead of encoded callback buttons and copy-text hacks.

## What Should Move Into Rust Core First

To make the gateway cleaner and reduce Python bridge calls, the next Rust/core candidates for mobile parity are:

1. Notification-to-action wire model.
   - Today Telegram stores `pending_actions.json` with plugin-specific shapes. A shared `PendingActionWire` would let
     Telegram, Android, and future web clients use the same matching and stale-cleanup logic.
2. Action response planning.
   - Convert callback/text choices into response-file write intents in Rust:
     `PlanActionChoice -> plan_response.json payload`, `HitlActionChoice -> hitl_response.json payload`,
     `QuestionActionChoice -> question_response.json payload`.
   - The host gateway still performs the write, but Rust owns the shared semantics.
3. Agent launch request normalization.
   - Move Telegram's `#workflow@ref` normalization or replace it with a more general mobile-safe prompt-normalization
     helper.
   - Keep actual xprompt expansion/launch in Python until the plugin/config story is ready.
4. Bead read/show/list APIs.
   - Much of bead storage is already in Rust. Prefer direct Rust calls for mobile bead list/show rather than shelling
     out to `sase bead`.
5. Attachment manifest generation.
   - Build a shared manifest of notification attachments with kind, display name, size, MIME-ish type, render strategy,
     and safe download token.

## Security Notes

The Android app is a more powerful remote surface than Telegram because it can present richer controls and may eventually
support remote host access directly. Add SASE-level authorization before exposing it broadly:

- Pair devices explicitly.
- Require authentication on every endpoint.
- Restrict host bind addresses by default.
- Gate dangerous operations: launch, kill, update, write response files.
- Keep an audit log.
- Expire pending actions.
- Avoid sending secrets, full prompts, or large file contents through FCM. Use FCM as a hint and fetch authenticated
  details from the host after app open.
- Do not expose arbitrary filesystem paths except as display text or short-lived attachment downloads.

## Open Questions

- Does the first MVP need to work away from the home LAN without Tailscale/WireGuard? If yes, a relay becomes part of
  the MVP, not a later detail.
- Should Android actions mark notifications read/dismissed, or should they only remove action controls while leaving
  notification-read state to the user?
- Should the host gateway be implemented first in Rust `axum`, or should a Python FastAPI prototype prove product
  behavior before Rust server work?
- Do we want Android image attachments copied to the host via gateway upload, or should the gateway pull them from
  Android through multipart upload only at launch time?
- What exact subset of xprompt catalog rendering is required on phone: list/search only, PDF generation, or full rich
  docs?

## Sources

Local SASE sources:

- `memory/short/rust_core_backend_boundary.md`
- `../sase-core/README.md`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/notification_store_facade.py`
- `src/sase/core/agent_launch_facade.py`
- `src/sase/core/rust.py`
- `../sase-telegram/README.md`
- `../sase-telegram/docs/architecture.md`
- `../sase-telegram/docs/inbound.md`
- `../sase-telegram/docs/outbound.md`
- `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`
- `../sase-telegram/src/sase_telegram/scripts/sase_tg_outbound.py`
- `sdd/research/202604/rust_backend_migration.md`
- `sdd/research/202604/sase_web_client_research.md`
- `sdd/research/202604/rust_core_next_candidates.md`
- `sdd/research/202603/telegram_improvements.md`

External sources:

- UniFFI bindings guide: https://mozilla.github.io/uniffi-rs/latest/bindings.html
- UniFFI Kotlin configuration: https://mozilla.github.io/uniffi-rs/latest/kotlin/configuration.html
- UniFFI Gradle integration: https://mozilla.github.io/uniffi-rs/latest/kotlin/gradle.html
- Rust Android NDK update: https://blog.rust-lang.org/2023/01/09/android-ndk-update-r25/
- Rust Android platform support: https://doc.rust-lang.org/rustc/platform-support/android.html
- cargo-ndk: https://github.com/bbqsrc/cargo-ndk
- Android background work: https://developer.android.com/develop/background-work
- Android foreground services: https://developer.android.com/develop/background-work/services/fgs
- Firebase Cloud Messaging Android setup: https://firebase.google.com/docs/cloud-messaging/android/client
- Firebase Cloud Messaging receive messages: https://firebase.google.com/docs/cloud-messaging/android/receive-messages

## Recommended Solution

Build the Android MVP as a native Kotlin/Compose client for a new SASE host gateway, not as a standalone embedded Rust
runtime.

The first gateway should be local-first and personal-device oriented: bind to loopback by default, support explicit
LAN/VPN bind for mobile, pair devices by QR code, authenticate every call, and expose a command-shaped REST plus
SSE/WebSocket API. Implement it with a Rust `axum` crate in `../sase-core` if we are willing to invest in the long-term
server shape now; otherwise prototype the same API in Python and keep the wire contract Rust-shaped so it can move later.
For mutating operations still owned by Python, bridge through existing Python facades or narrow CLI subprocess calls.

Use `sase_core` directly inside the gateway for notification snapshots/state updates, bead data where available, agent
artifact scans/indexes, status/query helpers, and launch planning. Add shared Rust wire records for pending actions and
mobile action response planning before duplicating Telegram callback semantics in Android. Add a small UniFFI
`sase_mobile_core` only after the gateway contract stabilizes, and keep it limited to pure helper logic and typed DTOs.

For delivery, use WebSocket/SSE while the app is foregrounded and FCM as a background wake-up/notification hint. Do not
poll from Android every few seconds. For the first private MVP, require phone-to-host reachability through LAN or
Tailscale/WireGuard rather than building a hosted relay. Add a relay only if remote-anywhere access without a private
network is a product requirement.
