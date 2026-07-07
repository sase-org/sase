---
create_time: 2026-07-06
updated_time: 2026-07-06
status: research
---

# A Dedicated SASE Mobile App: Motivation and Path to TUI Parity

## Question

Should SASE invest in a dedicated native mobile app to break free of the limitations of interacting with SASE through
Telegram, with the goal of replicating as much TUI (`sase ace`) functionality as possible in a mobile-native way? What
already exists, what is the gap to TUI parity, and what is the recommended path?

## Executive Summary

**Yes — and the surprising finding is that most of the hard foundation already exists and has simply never been turned
on.** The "untouched Android repo" is not a stale skeleton: it is a ~11.8k-LOC Kotlin/Jetpack Compose client
(`../sase-android`, 26 commits, all landed 2026-05-06) that implements the complete committed gateway API contract —
pairing (manual + QR), Keystore-encrypted bearer auth, SSE live refresh, notification inbox with plan/HITL/question
action screens, agent list/launch/kill/retry, image-prompt launch, xprompt catalog, beads, self-update, FCM push hints,
and a foreground connected mode — backed by ~6.1k LOC of tests and a fake-gateway harness. Its server counterpart, the
Rust `sase_gateway` crate in `../sase-core` (~12.2k LOC), is equally real: REST + SSE + pairing + push + audit log +
committed contract snapshot. What has never happened is the final step: running the 17-step manual smoke checklist in
`../sase-android/README.md` against a live gateway.

The motivation case rests on four legs:

1. **Telegram is structurally maxed out.** The `sase-telegram` plugin (~6.9k LOC) is majority workaround code:
   MarkdownV2 escaping machinery, 4096-char message splitting, 64-byte callback-data encoding hacks, zero-width-space
   blockquote tricks, and PDF attachments as the escape hatch for anything rich. The code literally appends
   "... (see TUI for full output)" when it hits the ceiling. It also has a real security gap: inbound handling verifies
   no sender identity at all.
2. **The market has validated the product shape.** Anthropic shipped Claude Code Remote Control (Feb 2026), OpenAI
   shipped Codex in the ChatGPT mobile app (May 2026), and an open-source ecosystem (Happy, Happier, and others) has
   formed around exactly this pattern: phone supervises, workstation executes. Mobile supervision of coding agents is
   now table stakes; SASE's self-hosted, tailnet-private version of it is a coherent and differentiated position.
3. **The architecture is already right.** Server-side execution with the phone as a paired remote client matches the
   Rust core backend boundary, the web-client research (`sdd/research/202604/sase_web_client_research.md`), and the
   remote-agents research (`sdd/research/202606/remote_sase_agents_consolidated.md`), which explicitly designates the
   mobile gateway on an always-online tailnet host as Phase 1 of remote SASE.
4. **TUI parity is a tiered target, not a cliff.** The gateway already covers the highest-value TUI workflows
   (approvals, HITL, questions, launch, kill, retry, notifications). The big missing read surfaces — chat transcripts,
   diffs, ChangeSpec detail — are exactly the surfaces where a native mobile renderer beats both Telegram (PDF
   attachments) and the TUI-over-SSH (no ANSI-art constraints, native scrolling, pinch zoom).

Recommended path: **smoke-test the existing MVP first** (days, not weeks — it converts "never tested" into ground
truth), then extend the gateway with read endpoints for transcripts, diffs, and ChangeSpecs, keeping Kotlin/Compose as
the client stack and Tailscale Serve as the transport. Do not rewrite in Flutter/KMP now, and do not attempt on-device
`sase_core` via UniFFI — the core is filesystem/SQLite/Python-CLI coupled by design and the phone should stay a client.

## Current State: The Mobile Stack Already Spans Three Repos

The May 2026 mobile MVP epic (sase-26.x / Epic 6-7, landed ~2026-05-06 per git history of `docs/mobile_gateway.md` and
`src/sase/integrations/`) produced a full vertical slice:

### Rust gateway (`../sase-core/crates/sase_gateway`, ~12.2k src LOC)

- axum HTTP server, default bind `127.0.0.1:7629`, non-loopback binds refused unless `--allow-non-loopback`.
- **Pairing/auth**: one-time pairing code → bearer token (only SHA-256 hashes stored in `devices.json`); audit log
  (`audit.jsonl`); device revocation primitive.
- **SSE event stream** (`GET /api/v1/events`): `agents_changed` / `notifications_changed` / `helpers_changed` /
  `heartbeat` / `resync_required`, with monotonic IDs and `Last-Event-ID` replay from an in-memory ring buffer.
- **Push**: transport-agnostic subscription model; FCM HTTP v1 provider plus a test provider. Hint-only payloads
  (IDs, categories, short safe text — never tokens, prompts, or paths); client always re-fetches authenticated state.
- **Routes**: notifications list/detail/mark-read/dismiss; attachment downloads with device-bound short-TTL tokens and
  path/size/symlink guards; plan approve/run/reject/epic/legend/feedback; HITL accept/reject/feedback; question
  answer/custom; agents list/resume-options/launch/launch-image/kill/retry; changespec-tags; xprompt catalog; beads
  list/show; update start/status.
- **Committed machine-readable contract**: `crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`.
- **Host bridge**: the gateway shells out to fixed `sase mobile agent-bridge` / `helper-bridge` JSON-over-stdin
  commands for launch/kill/retry and helper reads. It never accepts mobile-supplied shell, cwd, env, or host paths.

### Python bridge facades (this repo)

`src/sase/integrations/mobile_gateway.py`, `mobile_agents.py`, `mobile_notifications.py`, `mobile_helpers.py`
(~5.3k LOC across `src/sase/integrations/`), CLI glue in `src/sase/main/parser_mobile.py`, config under the
`mobile_gateway:` key in `src/sase/default_config.yml`. Critically, mobile actions write the **same response JSON
files** the TUI writes (`src/sase/plan_approval_actions.py`, `launch_approval_actions.py`), so mobile approvals are
first-class, not a bolt-on.

### Android client (`../sase-android`, canonical checkout `~/projects/github/sase-org/sase-android`)

- Kotlin 2.1.10, Jetpack Compose Material 3, single module, `org.sase.mobile`, minSdk 26 / target+compileSdk 35.
- Bottom-nav shell: **Inbox, Launch, Agents, Settings**, plus NotificationDetail, Helpers, and Update routes.
- Hand-written OkHttp client (`GatewayApiClient.kt`, 758 lines) covering the entire `mobile_api_v1` contract; SSE
  client with backoff+jitter reconnect; Keystore AES/GCM-encrypted token vault; CameraX + ML Kit QR pairing;
  FCM messaging service; foreground connected-mode service; action-draft persistence.
- ~30 unit-test files (MockWebServer + route-based `FakeGateway`), 9 Compose instrumentation tests, JSON contract
  fixtures, GitHub Actions CI running `testDebugUnitTest lintDebug assembleDebug`.
- **No TODO/stub markers, no hardcoded endpoints, auth fully implemented.** Known-limitations section documents the
  real gaps: never run against a live gateway, FCM needs a local `google-services.json`, release signing/minification
  deferred, hand-written client (codegen intentionally deferred).

**Toolchain staleness is mild, not fatal**: the pinned early-2025 stack (AGP 8.8.2, Gradle 8.11.1, Compose BOM
2025.02.00, SDK 35) is internally consistent and should still build via its wrapper; a bump to current AGP/Kotlin/SDK 36
is routine maintenance, not a rewrite.

### Operational runbook already written

`docs/mobile_gateway.md` and `docs/mobile_mvp_runbook.md` cover install, pairing, push configuration, **Tailscale Serve
as the recommended private remote path** (gateway stays on loopback; Serve proxies it inside the tailnet; Funnel and
public tunnels explicitly rejected), a lost-phone/LAN-attacker/push-leak threat model, and rollback. For the athena
home-server deployment this maps directly onto the remote-agents research's "Role A: always-online server as execution
host" — the phone submits and observes; agents execute on athena.

## Why Telegram Cannot Get There

The `sase-telegram` plugin is a competent *notify-and-tap* remote control, and it proved the demand: plan approvals,
HITL, question answering, text/photo agent launches, kill/retry, and 7 slash commands all work today. But the medium
imposes hard ceilings that no amount of plugin code can lift:

| Constraint | Telegram reality | Evidence in plugin code |
| --- | --- | --- |
| Message size | 4096 chars; plans truncated at 3500 | `formatting.py` `MAX_MESSAGE_LENGTH`, `NOTES_TRUNCATION_THRESHOLD`; literal "... (see TUI for full output)" |
| Rich text | MarkdownV2 with 18 escapable chars; silent plain-text fallback on parse failure | `escape_markdown_v2`, parse-mode fallback in `telegram_client.py` |
| Tables/diffs/code | Tables dumped into monospace blocks; diffs exported as PDF attachments; code blocks downgraded to per-line inline code to survive blockquotes | `markdown_to_telegram_v2`, `_code_blocks_to_inline`, `pdf_convert.py` |
| Interactivity | Inline buttons with a 64-byte callback-data cap → 8-char notification-ID prefixes; copy-text buttons as a clipboard hack | `callback_data.py` (`MAX_CALLBACK_BYTES = 64`), `_notif_prefix` |
| Latency | ~5 s inbound polling tick (short-poll `getUpdates`, offset file) | `sase_tg_inbound.py` main loop |
| Throughput | 1 msg/s per chat, ~30/s global; self-imposed 8 msgs/15 s limiter | `rate_limit.py`; Telegram flood limits |
| Navigation/state | None — discrete messages only; no browsing transcripts, ChangeSpecs, agent trees, or live output | absence by construction |
| Auth | Single global chat ID; **no sender verification on inbound updates** — anyone who finds the bot can launch/kill agents | no `from_user` checks anywhere in `sase_tg_inbound.py` |
| Privacy | Bot traffic is client-server encrypted only; Telegram's servers can read plan/prompt content | `sdd/research/202602/telegram_integration.md` security notes |

The strongest evidence is structural: of ~6.9k source LOC, well over half is escaping machinery, length-budget
juggling, zero-width-space blockquote hacks, backtick-entity reconstruction, media-group reassembly, and PDF
conversion — i.e., fighting the medium rather than delivering features. Each new SASE concept (workflow trees, bead
graphs, live diffs) would add another lossy flattening layer.

A dedicated app inverts every row of that table: no message-size or callback-size limits, native Markdown/diff/code
rendering, real navigation, SSE push instead of 5 s polling, per-device bearer auth with revocation and audit, and
content that never transits a third party's servers (tailnet-only).

Telegram should survive as the documented **fallback** (the runbook already positions it that way) — it is mature,
zero-infrastructure, and useful when the gateway is down.

## The Parity Target: What the TUI Actually Does

The `sase ace` TUI is large: ~150k LOC under `src/sase/ace/tui/`, 3 top-level tabs (Agents, PRs/ChangeSpecs, AXE), a
6-pane Admin Center, ~79 modal screens, and ~130 keybound actions (vocabulary in `src/sase/default_config.yml`).
Chasing 1:1 parity would be a mistake; the right framing is tiers of mobile value.

### Tier 0 — already served by the gateway + Android app today

| TUI capability | Gateway/app status |
| --- | --- |
| Notification inbox (read/dismiss), incl. attachments | ✅ routes + Inbox/Detail screens |
| Plan approval (approve/run/reject/epic/legend/feedback) | ✅ same response files as TUI |
| Launch approval, HITL accept/reject/feedback | ✅ |
| User questions (options, custom answers, notes) | ✅ |
| Agent list w/ status + recent completions | ✅ |
| Launch text agent (home or project context, xprompt syntax, VCS refs) | ✅ |
| Launch image agent (photo → prompt) | ✅ base64 upload route |
| Kill / retry agents | ✅ |
| xprompt catalog browsing (with editor metadata) | ✅ |
| Beads list/show | ✅ |
| SASE self-update | ✅ start/poll |
| Live refresh | ✅ SSE + FCM hints + foreground mode |

This is already more than Telegram does, with none of Telegram's ceilings.

### Tier 1 — the high-value gaps (new gateway read endpoints + app screens)

These are the surfaces that make the app a *supervision workbench* rather than a pager, and each is mobile-native
friendly:

1. **Chat transcript / agent output viewer** — the TUI's `AgentPromptPanel` renders chat content, thinking, tool uses,
   skill uses, commits, deltas, workflow steps from on-disk agent artifacts. The gateway has no transcript endpoint
   today; `sase_core`'s `agent_scan` already indexes the artifacts, so a paginated
   `GET /api/v1/agents/{name}/transcript` is mostly plumbing. This is the single biggest win: "what is my agent
   actually doing/saying?" is the question a phone user asks most.
2. **Diff viewing** — the TUI file panel's live diffs; Telegram ships these as PDFs. A native mobile diff renderer
   (syntax highlighting, horizontal scroll, font scaling) is strictly better than both. Needs a
   `GET /api/v1/agents/{name}/diff` (or per-ChangeSpec diff) endpoint via a fixed bridge op.
3. **ChangeSpec list/detail** — only `changespec-tags` exists today. The full parser and query engine already live in
   Rust (`sase_core::parser`, `query`), so list/detail/grouping endpoints are core-native (no Python bridge needed).
   Detail sections (commits, hooks, comments, mentors) map naturally to collapsible mobile cards.
4. **Status transitions + small command set** — `sase_core::status` has the validated transition planner; expose
   command-shaped `POST /api/v1/changespecs/{name}:transition` mirroring the web-client research's endpoint design.
5. **Saved queries / search** — the Rust query engine is pure and portable; a query bar with saved queries replicates
   the TUI's `/` + `0-9` workflow.

### Tier 2 — nice-to-have on mobile

- Workflow/agent-family tree view (root/child entries, attempt history) — a native tree/timeline beats the TUI's
  fold-glyph encoding.
- Live transcript streaming (extend SSE with a per-agent topic) rather than refresh-on-change.
- Prompt history / prompt stash; mentor review summaries; hook history.
- AXE daemon dashboard (read-only status + restart button).

### Explicitly not mobile targets

Admin Center config editing, keyboard-first navigation emulation, tmux workspace attach, editor integration, repro
bundles, and the long tail of the 79 modals. These are workstation workflows; replicating them would burn effort where
mobile adds no leverage. (Precedent: OpenAI and Anthropic both ship *remote controls*, not mobile IDEs.)

### Mobile-native advantages to lean into

Capabilities no terminal or chat client can match, several already implemented:

- **Lock-screen approval cards** via push → tap → biometric-gated approve (FCM plumbing exists; approval routes exist).
- **Share-sheet integration**: share any screenshot/photo from the phone straight into `launch-image` (route exists;
  Android share-target intent is a small addition).
- **QR pairing** (implemented) — better than copying bot tokens.
- **Offline inbox cache** with authoritative refetch (implemented pattern).
- Home-screen widgets (running/asking agent counts), voice-dictated prompts, and wearable notification actions as
  future candy.

## External Validation: The Landscape in Mid-2026

The "supervise your coding agent from your phone" category went mainstream between February and May 2026:

- **Anthropic — Claude Code Remote Control** (Feb 2026): phone/web as a live window onto a Claude Code session running
  on the workstation; outbound-only HTTPS bridge, QR pairing, approval cards; Max-tier research preview. See
  [VentureBeat](https://venturebeat.com/orchestration/anthropic-just-released-a-mobile-version-of-claude-code-called-remote)
  and [Help Net Security](https://www.helpnetsecurity.com/2026/02/25/anthropic-remote-control-claude-code-feature/).
- **OpenAI — Codex in the ChatGPT mobile app** (May 14, 2026): monitor, approve commands, review diffs, steer threads,
  dispatch tasks; QR-paired to the desktop worker (macOS-only worker at launch). See
  [OpenAI](https://openai.com/index/work-with-codex-from-anywhere/) and
  [TechCrunch](https://techcrunch.com/2026/05/14/openai-says-codex-is-coming-to-your-phone/).
- **Open-source third-party clients**: [Happy](https://github.com/slopus/happy) and its fork
  [Happier](https://github.com/happier-dev/happier) — end-to-end-encrypted mobile/web clients for Claude Code, Codex,
  OpenCode et al., with push notifications, device switching, and zero-knowledge relay servers. A broader tool roundup:
  [CodePick's 2026 mobile AI coding tools guide](https://codepick.dev/en/guides/mobile-ai-coding-tools-2026/).

Three lessons for SASE:

1. **The interaction model is converged and matches SASE's gateway exactly**: workstation executes, phone pairs (QR),
   observes (stream), and approves (cards). SASE built this shape independently in May 2026 — the design is validated.
2. **Everyone treats it as a remote control, not a mobile IDE.** Tier scoping above is consistent with the entire
   field.
3. **SASE's differentiator is self-hosting and breadth.** Happy/Codex/Claude relays route through third-party servers;
   SASE's tailnet-only gateway keeps prompts, plans, and diffs entirely on-net. And none of the commercial offerings
   have SASE's domain objects (ChangeSpecs, beads, xprompts, workflows, mentors) — a dedicated app is the only way
   those ever get a mobile surface.

## Architecture Direction

### Keep: server-side execution, product-shaped API, tailnet transport

The sase-core assessment confirms the phone must remain a client: `sase_core` assumes local filesystem + SQLite
(~22 modules use `std::fs`), and the gateway delegates launch/kill/helpers to the Python `sase` CLI via fixed bridge
commands. Compiling the core for the phone (UniFFI) is only viable for the pure subset (parsers, query engine, status
planner, wire types) — potentially useful later for offline query highlighting or prompt linting, but it cannot carry
the product. UniFFI remains a stated aspiration in `sase-core` with zero implementation; leave it that way for now.

Remote access: run the gateway on athena (always-online), keep it loopback-bound, expose via **Tailscale Serve**
exactly as the runbook prescribes. This is Phase 1/Role A of the remote-agents research, so mobile work and remote-
agents work compound rather than compete.

### Converge, don't fork: `sase_gateway` vs. the future `sase-server`

The web-client research (202604) proposes a `sase_server` crate (axum, REST/OpenAPI, SSE) for the browser SPA. The
mobile gateway is *already* that shape (axum, REST, SSE, versioned contract, command-shaped mutations). Building both
independently would create two divergent API surfaces over the same domain. Recommendation: treat `sase_gateway` as the
seed of the shared frontend server. Concretely:

- New read endpoints (transcripts, diffs, ChangeSpec list/detail, queries) should be specified once and serve both the
  Android app and a future web SPA.
- Adopt the web research's contract discipline for the gateway: snapshot-gated schema in CI (the contract snapshot
  already exists), additive-only v1 changes, `/api/v1/` prefixing (already done).
- Prefer core-native Rust handlers where the logic already lives in `sase_core` (ChangeSpecs, queries, status), and
  fixed Python bridge ops where host logic still owns behavior (launch, diffs against workspaces) — the same
  "Option C" split the web research recommends.

### Client stack: keep Kotlin/Compose; defer cross-platform

| Option | Assessment |
| --- | --- |
| **Keep Kotlin + Jetpack Compose (current)** | ✅ Recommended. ~11.8k LOC of working, tested code exists; single-user Android-first reality (Pixel); full native capability (Keystore, FCM, CameraX, foreground services, share sheet). Cost: Android-only. |
| Kotlin Multiplatform + Compose Multiplatform | Best *future* path to iOS if ever needed — CMP for iOS went stable in May 2025 and the existing Kotlin domain/data layer would largely move into `shared/`. Not worth the migration churn until an iOS device matters. See [JetBrains CMP](https://kotlinlang.org/compose-multiplatform/) and [KMP-vs-Flutter guidance](https://kotlinlang.org/docs/multiplatform/kotlin-multiplatform-flutter.html). |
| Flutter / React Native | Would discard the existing client for no capability gain; adds a second UI toolchain foreign to the stack. |
| PWA / wrapped web client | Zero-cost byproduct once the web SPA exists (responsive layout + installable PWA), but weaker push, no Keystore/biometrics/share-sheet depth. Complement, not substitute. |
| On-device Rust core (UniFFI) | Rejected for now, per above. |

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| The May 2026 stack was generated in one day and never ran end-to-end; unknown-unknowns may lurk | Phase 0 smoke test before any new feature work; fix-forward from real failures |
| Contract drift between the hand-written Kotlin client and the gateway | Contract snapshot already committed + fixture tests on both sides; consider codegen from `mobile_api_v1.json` once the surface grows (README already flags this as deferred) |
| Android toolchain staleness (AGP 8.8.2 / SDK 35 vs. mid-2026 SDK 36 era) | One-time bump PR; CI already pins and installs its own SDK so the build is reproducible meanwhile |
| FCM dependency (Firebase account, `google-services.json`) for push | Acceptable for a personal build; the subscription model is transport-agnostic — UnifiedPush/ntfy is the documented future option if de-Googling matters; foreground connected mode works with zero push infra today |
| Maintenance burden of a third frontend (TUI, web, mobile) | Contract-first convergence (one server, one schema); keep mobile scoped to Tiers 0–1; Uniform Agent Runtimes rule keeps the product surface stable across runtimes |
| Pairing/auth is bearer-token, not hardened mTLS/SPAKE2 | Tailnet-only exposure (Serve, ACLs) is the compensating control per the threat model; revisit only if exposure model changes |
| Gateway event buffer is in-memory (`resync_required` after restart) | Already handled client-side by authoritative refetch; durable event log only if it proves annoying in practice |
| Scope creep toward "TUI on a phone" | Hold the line at the tier table; new mobile features must be product commands, never generic shell/file access (threat model's arbitrary-command-expansion rule) |

## Staged Roadmap

**Phase 0 — Resurrect and smoke (days).** Build `sase_gateway`, run `sase mobile gateway start`, build the debug APK
(after an opportunistic toolchain bump if the pinned stack fights the current machine), pair, and execute the README's
17-step manual smoke checklist. Then `tailscale serve` from athena and repeat from off-LAN. Outcome: ground truth on
what actually works, a triaged defect list, and (likely) a usable notifications-and-approvals app immediately.

**Phase 1 — Daily driver for approvals (1–2 weeks of fixes/polish).** Enable FCM (or live with foreground mode),
migrate plan/HITL/question handling off Telegram day-to-day, keep Telegram as fallback. Add the share-sheet intent for
image launches. Success metric: a week where the TUI is never opened *just to approve something*.

**Phase 2 — Supervision read surfaces (the parity core).** Gateway endpoints + screens for agent transcripts, diffs,
and ChangeSpec list/detail; saved queries. Rust-core-native where possible, fixed bridge ops otherwise; every endpoint
specified in the shared v1 contract with the future web client in mind.

**Phase 3 — Live and structural.** Per-agent SSE transcript streaming, workflow/family tree view, status-transition
commands, prompt history/stash. Demote Telegram to documented-fallback-only.

**Phase 4 — Reach (optional).** KMP/CMP restructuring if iOS becomes real; PWA convergence with the web client;
UniFFI pure-core helpers on-device if offline features emerge.

## Recommended Solution

Commit to the dedicated mobile app as the primary remote interface for SASE, built as a thin, mobile-native supervision
client over the existing `sase_gateway` — not as a TUI port. The decisive facts: the three-repo mobile MVP already
implements the hardest 60% (auth, pairing, push, SSE, approvals, launch/kill/retry) and needs validation rather than
construction; Telegram is provably at its structural ceiling with over half its plugin code fighting the medium and an
unauthenticated inbound surface; and the Feb–May 2026 wave of Claude Code Remote Control, Codex mobile, and the
Happy/Happier ecosystem confirms both the demand and the exact architecture SASE already chose. Execute Phase 0
immediately — the cheapest possible next step is also the most informative — then grow the gateway toward Tier 1 read
surfaces (transcripts, diffs, ChangeSpecs) as the single shared contract that the Android app and the future web client
both consume.

## Sources

Local:

- `docs/mobile_gateway.md`, `docs/mobile_mvp_runbook.md` (gateway API, runbook, threat model)
- `src/sase/integrations/mobile_gateway.py`, `mobile_agents.py`, `mobile_notifications.py`, `mobile_helpers.py`
- `src/sase/default_config.yml` (mobile_gateway config; TUI action vocabulary)
- `src/sase/ace/tui/` (app shell `app.py`, tabs, widgets, modals — parity inventory)
- `src/sase/plan_approval_actions.py`, `src/sase/launch_approval_actions.py` (shared TUI/mobile response writers)
- `../sase-core/crates/sase_gateway/` (routes, server, storage, push, host_bridge, wire;
  `contracts/api_v1/mobile_api_v1.json`)
- `../sase-core/crates/sase_core/` (parser, query, status, agent_scan, notifications, bead, host_bridge)
- `../sase-android/` (README with scope/limitations/smoke checklist; `app/src/main/java/org/sase/mobile/`)
- `../sase-telegram/src/sase_telegram/` (formatting.py, telegram_client.py, callback_data.py, rate_limit.py,
  scripts/sase_tg_inbound.py, scripts/sase_tg_outbound.py)
- `sdd/research/202604/sase_web_client_research.md` (server/API/contract direction)
- `sdd/research/202604/rust_backend_migration.md` (Phase 9 server direction)
- `sdd/research/202606/remote_sase_agents_consolidated.md` (Role A execution host, Tailscale Serve)
- `sdd/research/202602/telegram_integration.md` (original Telegram trade-offs)

External:

- Claude Code Remote Control: [VentureBeat](https://venturebeat.com/orchestration/anthropic-just-released-a-mobile-version-of-claude-code-called-remote),
  [Help Net Security](https://www.helpnetsecurity.com/2026/02/25/anthropic-remote-control-claude-code-feature/),
  [TechRadar](https://www.techradar.com/pro/anthropic-reveals-remote-control-a-mobile-version-of-claude-code-to-keep-you-productive-on-the-move),
  [ZBuild setup guide](https://www.zbuild.io/resources/news/claude-code-remote-control-mobile-terminal-handoff-guide-2026)
- Codex mobile: [OpenAI — Work with Codex from anywhere](https://openai.com/index/work-with-codex-from-anywhere/),
  [TechCrunch](https://techcrunch.com/2026/05/14/openai-says-codex-is-coming-to-your-phone/),
  [Memeburn](https://memeburn.com/openai-codex-mobile-app-now-available-on-ios-and-android/)
- Third-party mobile agent clients: [Happy (slopus/happy)](https://github.com/slopus/happy),
  [Happier](https://github.com/happier-dev/happier), [happy.engineering features](https://happy.engineering/docs/features/),
  [CodePick mobile AI coding tools 2026](https://codepick.dev/en/guides/mobile-ai-coding-tools-2026/),
  [Nimbalyst](https://nimbalyst.com/blog/the-first-real-mobile-app-for-codex-and-claude-code/)
- Telegram Bot API constraints: [Bot API reference](https://core.telegram.org/bots/api),
  [message length limit tracker](https://bugs.telegram.org/c/1423),
  [rate limits explained](https://botnamefinder.com/blog/telegram-bot-rate-limits-explained)
- Cross-platform stacks: [Compose Multiplatform](https://kotlinlang.org/compose-multiplatform/),
  [KMP vs Flutter (JetBrains)](https://kotlinlang.org/docs/multiplatform/kotlin-multiplatform-flutter.html),
  [Shorebird: Flutter vs KMP 2026](https://shorebird.dev/blog/flutter-vs-kotlin-multiplatform)
- Rust-on-mobile bindings: [mozilla/uniffi-rs](https://github.com/mozilla/uniffi-rs),
  [Running Rust on Android with UniFFI](https://sal.dev/android/intro-rust-android-uniffi/)
- Private remote access: [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve),
  [Tailscale for self-hosted services (XDA)](https://www.xda-developers.com/tailscale-guide/)
