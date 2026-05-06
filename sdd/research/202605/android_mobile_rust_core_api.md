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

### Kotlin Multiplatform and Compose Multiplatform

Stock UniFFI emits Android-JVM-only Kotlin. If iOS parity ever becomes a goal, two community generators target Kotlin
Multiplatform (KMP) and Compose Multiplatform (CMP) directly so a single Kotlin module can run on JVM, Android, iOS,
and Native:

- **Gobley** — actively maintained KMP fork after the original UniFFI-KMP crate stalled. Embeds Rust into KMP
  projects; supports JVM and Native targets out of the box. https://github.com/gobley/gobley
- **uniffi-kotlin-multiplatform-bindings** (Ubique fork) — published as `uniffi_bindgen_kotlin_multiplatform`.
  https://github.com/UbiqueInnovation/uniffi-kotlin-multiplatform-bindings

Implication for SASE: stock UniFFI is enough for an Android-first MVP. Pick Gobley only when iOS is a committed second
client. Compose Multiplatform on top of either generator works but is unnecessary for a Kotlin/Compose-Android MVP.

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
- **Avoid OpenSSL.** The NDK's bundled OpenSSL is stuck on EOL 1.1.1, and `openssl-sys` cross-compilation is a
  recurring source of CI pain. Prefer `rustls` for any TLS-touching code. https://ospfranco.com/compiling-openssl-in-rust-for-android/
- **Encrypted SQLite:** if the mobile facade needs encrypted local storage, use `sqlcipher-android` (Guardian Project).
  The older `android-database-sqlcipher` is deprecated. https://github.com/sqlcipher/android-database-sqlcipher
- **Gradle integration:** Mozilla's `rust-android-gradle` still works but is Python-based and broke after Python 3.13
  removed `pipes`; the `cargo-ndk-android-gradle` (willir fork) is a more Gradle-native alternative.
  https://github.com/willir/cargo-ndk-android-gradle

### Android Background Delivery

Android background execution rules make a Telegram-style "poll every five seconds forever from the app" the wrong
mobile design. Android's background-work docs direct developers to choose between asynchronous work, WorkManager,
foreground services, and alternatives depending on user visibility and task urgency. Foreground services are intended
for user-noticeable work and have restrictions. Firebase Cloud Messaging is the standard way to receive push messages;
Firebase's Android docs describe `FirebaseMessagingService` for receiving messages and note that notification messages
in the background go to the system tray.

Modern Android specifics that affect this MVP:

- **POST_NOTIFICATIONS (API 33+).** Notifications are off by default on fresh installs; the app must request the
  runtime permission and handle `shouldShowRequestPermissionRationale`.
  https://developer.android.com/develop/ui/views/notifications/notification-permission
- **Foreground service types are required (API 34, Android 14).** Each `<service>` must declare a
  `foregroundServiceType` and the app must hold the matching `FOREGROUND_SERVICE_<TYPE>` permission. The new
  `remoteMessaging` type is the right fit for a "stay connected to my SASE host" service. The `dataSync` type is being
  soft-deprecated and on Android 15 has a hard 6-hour daily cap.
  https://developer.android.com/about/versions/14/changes/fgs-types-required and
  https://developer.android.com/develop/background-work/services/fgs/service-types
- **Starting an FGS from background is forbidden (API 31+)** except for narrow exemptions like `BOOT_COMPLETED`,
  high-priority FCM, or user-visible notification interaction; otherwise the system throws
  `ForegroundServiceStartNotAllowedException`. https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start
- **FCM data-only vs notification messages.** Notification messages default to high priority and bypass Doze; data-only
  messages default to **normal priority** and get batched in Doze. Even high-priority data messages have documented
  delivery delays. https://firebase.google.com/docs/cloud-messaging/android-message-priority
- **Self-hosted push without Google Play Services.** UnifiedPush is the de-facto standard; ntfy.sh is the most popular
  distributor and is fully self-hostable; Gotify and NextPush exist as alternatives. This is interesting for SASE
  because the host already has push-shaped event semantics and we may want to ship via F-Droid alongside Play Store.
  https://unifiedpush.org/users/distributors/ and https://docs.ntfy.sh/subscribe/phone/

Sources:

- https://developer.android.com/develop/background-work
- https://developer.android.com/develop/background-work/services/fgs
- https://firebase.google.com/docs/cloud-messaging/android/client
- https://firebase.google.com/docs/cloud-messaging/android/receive-messages

Implication for SASE:

- Foreground app: maintain a WebSocket/SSE connection to the host gateway, run as a `remoteMessaging` foreground
  service while connected, request `POST_NOTIFICATIONS` early.
- Background app: receive FCM (or UnifiedPush) data payloads as wake-up hints, then fetch current state when the user
  opens the app. Avoid relying on data-only message timing for anything urgent.
- Do not build the MVP around phone-side periodic polling.
- Pick a push transport early. FCM is the default, but if F-Droid distribution or Google-free devices are part of the
  audience, design the gateway to support UnifiedPush from day one.

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

### Wire Format Choice

REST + JSON is the right MVP default, but worth grounding the trade-off:

- **gRPC** is roughly 5–7× more compact and noticeably faster on the wire, but adds ~3–4 MB of APK weight, requires
  generated stubs on both sides, and on mobile **gRPC-Web does not support bidirectional streaming**. Debuggability is
  worse: opaque proto frames in tcpdump vs. readable JSON in any HTTP client.
  https://grpc.io/blog/mobile-benchmarks/
- **Cap'n Proto / MessagePack** are interesting for binary sizes but lose the "any HTTP client can debug it" property
  and add codegen complexity for marginal gain on a personal-MVP scale.
- **REST + JSON** keeps OkHttp/Retrofit caching, browser/curl debuggability, and matches the wire shape `sase_core`
  already produces via `serde_json`.

For SASE, REST + JSON for commands plus SSE/WebSocket for events. If a future endpoint needs to stream large per-row
data (e.g. live agent stdout), revisit gRPC server-streaming or NDJSON over a single HTTP/2 stream rather than
re-encoding every endpoint.

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

Concrete remote-access options for this option, in increasing order of exposure:

1. **Tailscale Serve** — auto-provisioned HTTPS exposed only to the user's tailnet; ideal for a private SASE host
   accessed from a paired phone also on the tailnet. https://tailscale.com/docs/features/tailscale-serve
2. **Tailscale Funnel** — same auto-HTTPS but reachable from the public internet on fixed ports (443/8443/10000); free
   for personal use. Picks up the "remote anywhere without a VPN" use case at the cost of a publicly addressable
   endpoint. https://tailscale.com/docs/features/tailscale-funnel
3. **Cloudflare Tunnel** — outbound-only connection to Cloudflare with auto-HTTPS and Zero Trust integration; no port
   forwarding, no VPN client on the phone. Good if the user already has Cloudflare DNS for a domain.
4. **headscale** — self-hosted Tailscale control plane in Go, paired with the official Tailscale clients. Useful if
   we want a fully self-hosted control plane without depending on Tailscale Inc.

Recommendation for the MVP: Tailscale Serve. Funnel and Cloudflare Tunnel become reasonable upgrades when a user
demands phone access from a network where the tailnet is unreachable.

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

## Reference Architectures

Three shipping projects already pair a Rust core with an Android client. Useful as templates and as proofs that the
boundary works in production:

- **Bitwarden.** Rust `bitwarden_core`, UniFFI Kotlin bindings published as a separate artifact, Android app uses
  Retrofit alongside SDK calls in a multi-module Gradle setup. Closest analog to the proposed SASE shape.
  https://contributing.bitwarden.com/architecture/sdk/ and https://github.com/bitwarden/sdk-internal
- **Matrix Rust SDK / Element X Android.** Three-layer pattern: pure-Kotlin façade → Rust-backed implementation with
  mappers → `org.matrix.rustcomponents.sdk` UniFFI bindings from `matrix-sdk-ffi`. Strong template if the SASE Android
  app eventually grows a Kotlin façade interface for offline/online swapping.
  https://deepwiki.com/element-hq/element-x-android/3-matrix-integration
- **Signal libsignal.** Pure-Rust core but a hand-tuned JNI bridge instead of UniFFI; codegens Java declarations from
  Rust. Worth knowing as evidence that UniFFI is not the only option, but its hand-tuning is overkill for a SASE-sized
  surface. https://github.com/signalapp/libsignal
- **Tauri 2.0 mobile.** Stable since late 2024. Android plugins are Kotlin classes whose `@Command`-annotated methods
  are callable from Rust/JS. Interesting if we ever decide to share the gateway client UI with a desktop Tauri build.
  https://v2.tauri.app/blog/tauri-20/

Implication for SASE: the Bitwarden pattern (Rust core + UniFFI Kotlin bindings + REST/JSON network layer) is the
closest reference. Adopt it as the default and revisit the Element X façade pattern only if/when an offline-first
mobile mode is on the roadmap.

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

#### SSE vs WebSocket for the event stream

The event stream from gateway to Android is mostly host→phone. SSE is the better default:

- SSE has **built-in reconnection with `Last-Event-ID`** at the protocol level; `axum` exposes this directly via
  `axum::response::sse::Event::id()`. WebSocket clients must reimplement reconnection and resume-from-id themselves.
  https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
- SSE is plain HTTP/1.1 chunked text, so corporate proxies, Tailscale Funnel, and Cloudflare Tunnel all pass it
  through without special configuration; WebSocket upgrades occasionally get blocked or buffered by middleboxes.
- OkHttp ships an SSE module (`okhttp-sse`) and a WebSocket module; both are fine on Android.
- WebSocket only wins if SASE later needs phone→host realtime payloads (e.g., live agent stdin, voice). For
  command-shaped phone→host calls, plain authenticated POSTs are simpler than reusing the socket.

Recommendation: SSE for events with `Last-Event-ID`-driven resume; bare HTTP POST for commands; revisit WebSocket only
when a true bidirectional stream is needed.

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

### Concrete crypto/auth crates and APIs

- **Pairing handshake.** SPAKE2 over a QR code is the cleanest fit: phone scans a QR with the host's public key
  fingerprint and a one-time code, both sides derive a shared key and exchange long-term device public keys. Rust
  crate: `spake2`. https://github.com/warner/spake2.rs
- **Long-term device identity.** Ed25519/X25519 device keypair stored in the **Android Keystore** with hardware
  attestation. Curve25519 algorithms are supported in Keystore since Android 13 (KeyMint v2); StrongBox is available
  on devices with a discrete secure element. Hardware-backed key attestation roots back to a Google certificate.
  https://source.android.com/docs/security/features/keystore/attestation
- **Channel security.** For LAN/Tailnet binds, mTLS via `axum_mtls` is straightforward. For Tailscale Serve/Funnel
  binds, Tailscale's auto-provisioned Let's Encrypt cert handles TLS and we add bearer/device-token auth on top.
  https://crates.io/crates/axum_mtls
- **Optional: Noise protocol.** If we ever want a session protocol independent of TLS (e.g., over UnifiedPush data
  channels), `snow` is the canonical Rust implementation. https://github.com/mcginty/snow

### Lightweight threat model

- **LAN attacker on the same Wi-Fi.** Mitigated by binding to loopback by default and requiring TLS + bearer token
  even on LAN binds. Pairing must happen out-of-band (QR), not over open HTTP.
- **Lost/stolen phone.** Mitigated by keystore-bound device keys (cannot be exfiltrated), per-device tokens that the
  host can revoke, and a remote-revoke endpoint reachable from the desktop TUI.
- **Compromised mobile app/store.** Mitigated by F-Droid reproducible builds where possible, and by limiting the
  gateway surface to product-shaped commands rather than arbitrary shell.
- **Public Tailscale Funnel exposure.** Mitigated by token auth on every endpoint, short attachment TTLs, and audit
  logging. Funnel should be opt-in, not the default.

## Distribution

For a personal/internal MVP this is unimportant; for any wider rollout it becomes a forcing function on the FCM vs
UnifiedPush question above:

- **Play Store.** Standard channel. Self-hosted-server companion apps are common and not policy-hostile, but Play
  requires Google services and pushes you toward FCM for push.
- **F-Droid.** ~4,000 apps, including many self-hosted-server clients. Reproducible builds are encouraged. F-Droid
  apps typically ship UnifiedPush/ntfy instead of FCM. https://f-droid.org/en/2026/01/23/fdroid-in-2025-strengthening-our-foundations-in-a-changing-mobile-landscape.html
- **Sideload / direct APK.** Easiest for an internal MVP. Google's September 2025 Developer Registration Decree
  threatens the sideload path on certified devices over time, which is worth watching.
  https://f-droid.org/en/2025/09/29/google-developer-registration-decree.html

Recommendation: ship as a sideloaded APK during the MVP. Keep the gateway's push transport pluggable (FCM and
UnifiedPush) so neither store nor F-Droid distribution is gated on later refactors.

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
- Gobley (UniFFI for Kotlin Multiplatform): https://github.com/gobley/gobley
- Ubique uniffi-kotlin-multiplatform-bindings: https://github.com/UbiqueInnovation/uniffi-kotlin-multiplatform-bindings
- Rust Android NDK update: https://blog.rust-lang.org/2023/01/09/android-ndk-update-r25/
- Rust Android platform support: https://doc.rust-lang.org/rustc/platform-support/android.html
- cargo-ndk: https://github.com/bbqsrc/cargo-ndk
- cargo-ndk-android-gradle (willir fork): https://github.com/willir/cargo-ndk-android-gradle
- Compiling OpenSSL in Rust for Android (NDK pitfalls): https://ospfranco.com/compiling-openssl-in-rust-for-android/
- sqlcipher-android: https://github.com/sqlcipher/android-database-sqlcipher
- Android background work: https://developer.android.com/develop/background-work
- Android foreground services: https://developer.android.com/develop/background-work/services/fgs
- Android 14 FGS types required: https://developer.android.com/about/versions/14/changes/fgs-types-required
- Android FGS service types: https://developer.android.com/develop/background-work/services/fgs/service-types
- Android FGS background-start restrictions: https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start
- Android POST_NOTIFICATIONS permission: https://developer.android.com/develop/ui/views/notifications/notification-permission
- Firebase Cloud Messaging Android setup: https://firebase.google.com/docs/cloud-messaging/android/client
- Firebase Cloud Messaging receive messages: https://firebase.google.com/docs/cloud-messaging/android/receive-messages
- FCM message priority: https://firebase.google.com/docs/cloud-messaging/android-message-priority
- UnifiedPush distributors: https://unifiedpush.org/users/distributors/
- ntfy.sh Android docs: https://docs.ntfy.sh/subscribe/phone/
- Tailscale Serve: https://tailscale.com/docs/features/tailscale-serve
- Tailscale Funnel: https://tailscale.com/docs/features/tailscale-funnel
- Bitwarden SDK architecture: https://contributing.bitwarden.com/architecture/sdk/
- Bitwarden sdk-internal: https://github.com/bitwarden/sdk-internal
- Element X / Matrix Rust SDK integration: https://deepwiki.com/element-hq/element-x-android/3-matrix-integration
- Signal libsignal: https://github.com/signalapp/libsignal
- Tauri 2.0 (mobile stable): https://v2.tauri.app/blog/tauri-20/
- gRPC mobile benchmarks: https://grpc.io/blog/mobile-benchmarks/
- Server-Sent Events (Last-Event-ID): https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
- SPAKE2 (Rust): https://github.com/warner/spake2.rs
- Snow (Noise protocol, Rust): https://github.com/mcginty/snow
- axum_mtls: https://crates.io/crates/axum_mtls
- Android Keystore attestation: https://source.android.com/docs/security/features/keystore/attestation
- F-Droid 2025 retrospective: https://f-droid.org/en/2026/01/23/fdroid-in-2025-strengthening-our-foundations-in-a-changing-mobile-landscape.html
- Google Developer Registration Decree (F-Droid response): https://f-droid.org/en/2025/09/29/google-developer-registration-decree.html

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

For delivery, use SSE (with `Last-Event-ID` resume) while the app is foregrounded inside a `remoteMessaging`-typed
foreground service, and FCM data messages as a background wake-up hint with state fetched on app open. Avoid
polling. Keep the push transport pluggable so UnifiedPush/ntfy can replace FCM later for F-Droid distribution or
Google-free devices. For the first private MVP, require phone-to-host reachability through Tailscale Serve (private
tailnet auto-HTTPS) rather than building a hosted relay. Promote to Tailscale Funnel or Cloudflare Tunnel only when
remote-anywhere access without a tailnet becomes a real requirement.

Anchor the security boundary at pairing: SPAKE2 over QR for the initial handshake, Ed25519/X25519 device keys held in
the Android Keystore (StrongBox where available) for long-term identity, per-device tokens revocable from the desktop
TUI, and TLS on every bind beyond loopback. Prefer `rustls` over OpenSSL in any Android-linked Rust crate to avoid the
NDK's EOL OpenSSL trap.
