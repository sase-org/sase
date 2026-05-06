# SASE Mobile App vs Telegram Integration Value

Date: 2026-05-06

## Question

SASE already has a strong Telegram integration. How much additional value would a dedicated mobile app provide, and
what would have to be true for the app to justify its build and maintenance cost?

## Executive Summary

A native mobile app is not worth building if it is only "Telegram, but in a different app." Telegram already gives SASE a
free, proven, mobile-native notification/action channel with inline buttons, file/image delivery, command handling,
agent launch, image launch, bead/xprompt/update helpers, and mature push delivery.

The app is worth building if it becomes a **private, stateful SASE control plane**:

- A real inbox and agent dashboard, not a chronological chat stream.
- Product-shaped controls for plan/HITL/question flows, launch, kill, retry, resume, beads, xprompts, ChangeSpecs, and
  updates.
- Local-host authenticated access where full prompt text, paths, diffs, and attachments do not transit Telegram's
  servers.
- Rich mobile affordances: draft preservation, stale-action refresh, filtering, search, attachment viewers, camera/gallery
  image launch, host/session status, and per-device revocation.
- A stable gateway API that can later serve Android, web, editor, or other clients.

Recommendation: keep Telegram as the default remote notification fallback, and continue the mobile work only as an
incremental control-plane effort. The first app milestone should prove value in foreground use before investing heavily
in push delivery or app-store polish.

## Current SASE Baseline

The current Telegram integration is already broad. Repo docs show it:

- Sends unread, non-silent notifications through outbound chops, gated by user idle state.
- Saves actionable plan/HITL/question notifications as pending actions.
- Handles inline keyboard callbacks, two-step feedback/custom-answer flows, and stale action cleanup.
- Supports `/kill`, `/resume`, `/xprompts`, `/bead`, and `/update`.
- Downloads photos or image documents to the host and launches agents with prompts that reference the saved host path.
- Preserves launch context, VCS refs, project context, retry prompts, and rich agent descriptions.

Relevant internal references:

- `../sase-telegram/docs/architecture.md`
- `../sase-telegram/docs/inbound.md`
- `../sase-telegram/docs/outbound.md`
- `sdd/research/202603/telegram_improvements.md`
- `sdd/research/202605/android_mobile_rust_core_api.md`
- `docs/mobile_gateway.md`
- `sdd/legends/202605/sase_mobile_mvp_legend.md`

The May 2026 mobile plan has the right architecture: the phone is a client, not a SASE runtime. The host gateway owns
local filesystem/process side effects, exposes versioned product APIs, binds to loopback by default, supports pairing,
stores only token hashes, audits mutating calls, streams events over SSE, and recommends private remote access such as
Tailscale Serve rather than direct public exposure.

## What Telegram Already Does Well

Telegram is a high-leverage solution for SASE's existing problem: "tell me when agents need me and let me unblock them
from a phone."

Strengths:

- **Very low setup and distribution cost.** No app build, app store, signing, release pipeline, or mobile UI maintenance.
- **Mature push path.** Telegram already handles mobile push delivery, app lifecycle, notification UX, chat history, and
  cross-device sync.
- **Good interaction primitives.** The Bot API supports inline keyboards and callback queries; SASE uses this for plan,
  HITL, question, kill, retry, bead, and similar actions.
- **Files and images are built in.** The bot can send documents/photos and receive image uploads for image-agent launch.
- **No host gateway exposure.** The workstation polls Telegram and sends messages outward, so SASE avoids running a
  remotely reachable local HTTP API for Telegram use.
- **Free enough for personal SASE.** Official Telegram bot limits allow about 30 broadcast messages per second before
  paid-broadcast mechanics matter, far above normal single-user SASE traffic.

Sources: [Telegram Bot API](https://core.telegram.org/bots/api), [Telegram Bots FAQ](https://core.telegram.org/bots/faq),
[Telegram Mini Apps](https://core.telegram.org/bots/webapps).

## Telegram Constraints That Matter for SASE

The constraints are not fatal, but they explain where a native app can create real value.

| Constraint | Why it matters for SASE | Native app advantage |
|---|---|---|
| Chat stream as primary UI | Parallel agents, plans, beads, and questions become interleaved messages. | Dedicated inbox, filters, tabs, status views, detail screens, and state refresh. |
| Callback payload is small | Telegram `callback_data` is limited to 1-64 bytes, so SASE must persist pending action context and route by short IDs. | App can send typed JSON requests to stable endpoints. |
| Bot file limits | Official Bot API `getFile` currently downloads files up to 20 MB through Telegram's hosted API. | Host gateway can expose size-capped local attachments without Telegram's file pipeline. |
| Formatting is transport-specific | MarkdownV2 escaping, split messages, PDFs, and fallback formatting add complexity. | App can render Markdown, code, diffs, images, PDFs, and structured metadata directly. |
| No bot secret chats | Telegram Secret Chats are the E2E path; bot conversations are not that model. | App can keep sensitive content between paired device and host/tailnet, with push hints carrying no secrets. |
| Commands are text-first | Slash/dot commands are efficient for power users but not discoverable for all workflows. | Native controls remove command memorization and can validate inputs before mutation. |
| Telegram account dependency | Users must have and trust Telegram. | SASE can offer a first-party path independent of a messaging account. |

Sources: [Telegram Bot API](https://core.telegram.org/bots/api), [Telegram FAQ](https://telegram.org/faq).

## Concrete Telegram Limits Worth Naming

Beyond the table, several specific Telegram numbers shape SASE behavior and should inform the "is Telegram enough?" question:

- **Text message size: 4096 UTF-8 characters** per `sendMessage`. Long plans, diffs, and prompts must be split, paginated, or sent as documents — every split is a chance for MarkdownV2 escaping or fenced-block reflow to break.
- **`callback_data`: 1-64 bytes** per inline button — already covered above; restated here because it is the single most distorting Telegram constraint on SASE's action design.
- **Inline keyboards:** practical layout limits of roughly 8 buttons per row and a small number of rows before the keyboard becomes unusable on phones. SASE plan/HITL/question keyboards already feel that ceiling.
- **Bot API file download: 20 MB** through the public Bot API (already in table). A self-hosted Bot API server can lift this to 2 GB but is operational work the SASE Telegram path avoids.
- **Bot API send:** ~50 MB documents, ~10 MB photos via the public Bot API. Larger artifacts (long PDFs, big screenshots, log bundles) must be summarized, truncated, or shipped through a non-Telegram path.
- **Rate limits:** ~30 messages/second to different users globally, ~1 message/second to the same chat, ~20 messages/minute to the same group. Wave-based epics where many phases finish near-simultaneously can hit per-chat limits and cause delivery skew.
- **MarkdownV2 reserved characters:** `_*[]()~\`>#+-=|{}.!` all require exact escaping. Mistakes manifest as failed sends, not soft fallbacks.

The combined effect: Telegram is fine for compact, structured, button-driven interactions; it is awkward for content-rich review (long plans, big diffs, dense logs) and for keyboards that have outgrown their button budget. The gateway can simply not have those limits.

Sources: [Telegram Bot API limits](https://core.telegram.org/bots/api#sendmessage), [Telegram Bots FAQ rate limits](https://core.telegram.org/bots/faq#how-can-i-message-all-of-my-bot-39s-subscribers-at-once), [MarkdownV2 style](https://core.telegram.org/bots/api#markdownv2-style).

## Telegram Reliability, Outages, and Jurisdiction

The original analysis assumed Telegram is "always there." In practice, three failure modes affect SASE directly:

- **Outages happen.** Telegram has had multi-hour partial outages and regional incidents over the years. Whenever SASE's only mobile path is Telegram, those outages stall HITL/plan/question loops and there is no in-band fallback.
- **Government blocking is real.** Russia blocked Telegram 2018-2020; Iran, Pakistan, China, and Belarus have blocked or restricted it at various times. A SASE user traveling to or living in those jurisdictions loses Telegram entirely. A tailnet-mediated mobile app is more resilient: tailnet traffic uses ordinary internet routing or DERP relays and is not specifically targeted by Telegram blocks.
- **Bot/account continuity risk.** If a Telegram account is suspended, banned, rate-limited at BotFather, or the bot token is revoked, the SASE bot becomes unreachable until restored.
- **Server-side data residency.** Bot conversations are cloud chats stored in Telegram's infrastructure (DCs in Amsterdam, Miami, Singapore, depending on user). Bots cannot use Secret Chats, so messages are not E2E encrypted and Telegram operators can in principle read content. For SASE prompts, diffs, and paths, this is a real (if low-likelihood) confidentiality cost.

Self-hosted gateway shifts the failure modes rather than removing them:

- It depends on the workstation being on, the tailnet being healthy, and the phone having any network path. None is 100%.
- A silent gateway crash can be worse than a noisy Telegram outage because the user has no chat history to confirm what was actually sent or handled.
- Tailnet-only access means the gateway is unreachable from networks where Tailscale itself is blocked (some restrictive corporate or hotel networks).

Practical implication: even after the app exists, Telegram or another always-on transport is worth keeping as a notification-only fallback for "your workstation or tailnet is down" alerting.

Sources: [Telegram Privacy Policy](https://telegram.org/privacy), [Russia ends ban on Telegram (BBC, 2020)](https://www.bbc.com/news/technology-53077202), [Tailscale architecture](https://tailscale.com/kb/1151/what-is-tailscale).

## Native App Value Proposition

### 1. Private Host Control Plane

This is the strongest reason to build the app. SASE prompts, plan text, diffs, paths, screenshots, and error digests can
be sensitive. Telegram is appropriate for many notifications, but it necessarily places bot-visible message content into
Telegram's cloud chat path. A mobile gateway can instead keep full content on the user's workstation and phone, using
push notifications only as "wake/open and fetch state" hints.

The repo's current gateway design supports this direction:

- Bearer tokens returned once at pairing.
- Token hashes on disk, not raw tokens.
- Device records and future revocation.
- Audit records for mutating device actions.
- Attachment download tokens minted from detail responses, bound to the authenticated device, and short-lived.
- Product-shaped endpoints instead of arbitrary shell/file/RPC access.

This is not free. The app introduces a new local service exposure risk. The gateway must remain loopback-first and use
private tailnet exposure for remote access. Tailscale Serve can route private tailnet traffic to a local service, while
Funnel is explicitly for broader internet exposure and should not be the MVP recommendation.

Sources: [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve),
[Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel).

### 2. Stateful Inbox and Agent Dashboard

Telegram is good at "message plus buttons." It is poor at "current state of a distributed local workflow system."

A real app can show:

- Pending actions grouped by type, agent, bead, or project.
- Read/dismissed/silent state without scanning chat history.
- Stale/already-handled action state after TUI or Telegram handles the same item.
- Running, done, failed, killed, retryable, and resumable agents in a single list.
- Agent detail with prompt, model/provider, duration, workspace/project context, artifacts, logs, and next actions.
- Bead and ChangeSpec pickers that insert structured launch context rather than asking users to remember syntax.

This is the primary UX gap in Telegram. If the mobile app does not deliver this stateful dashboard, its value will be
thin.

### 3. Better High-Context Review

SASE review tasks are often dense: plans, implementation notes, diffs, PDFs, screenshots, failure logs, and generated
images. Telegram can attach files and format messages, but it is still a chat renderer.

A native app can provide:

- Scroll-position-preserving plan review.
- Diff-aware display.
- Markdown/code rendering without Telegram MarkdownV2 conversion.
- In-app PDF/image viewers.
- "Approve and run coder" forms with explicit toggles and editable prompts.
- Draft feedback that survives app backgrounding.
- Retry after network failure without losing text.

This is a meaningful upgrade for plan/HITL/question workflows.

### 4. Structured Launch UX

Telegram's "send text to launch" flow is powerful, but it relies on syntax memory. An app can keep the raw prompt editor
while adding structured controls:

- Project picker.
- VCS ref picker.
- ChangeSpec tag picker.
- Xprompt catalog picker.
- Bead picker.
- Multi-model selector.
- Camera/gallery image attach.
- Name validation and collision handling.
- Launch preview showing the normalized request before it touches the host.

This is likely where a mobile app can beat Telegram for frequent use.

### 5. Shared API for Future Clients

The host gateway is useful even if the Android app is not immediately a daily driver. The same API can serve:

- Web dashboard.
- Desktop menubar/tray app.
- Editor integrations.
- CLI automation.
- A future iOS client.
- A Telegram Mini App or web client.

The gateway should be treated as the durable investment; Android is the first consumer.

### 6. Mobile-Native Affordances Telegram Cannot Match

Several phone-OS capabilities are unavailable or awkward inside a Telegram bot conversation:

- **Biometric guard for high-impact actions.** Fingerprint or face unlock can confirm "kill all running agents", "force-merge", or "run coder on a dirty workspace". Telegram has no per-action biometric step.
- **OS share sheet integration.** A user can share a stack trace, screenshot, photo, or URL from any app directly into "Launch SASE agent with this prompt", which is much smoother than copying into Telegram.
- **Voice input.** Phone keyboards already dictate; a native UI can additionally record audio for a Whisper-style transcription pipeline if the gateway exposes it.
- **Widgets, Quick Settings tiles, and Live Activities.** Android home-screen widgets and Quick Settings tiles can show pending action count and one-tap "answer top question". iOS Live Activities and Lock Screen widgets are the analog. Telegram has chat shortcuts but nothing SASE-shaped.
- **Local Do Not Disturb integration.** Notifications respect device focus modes natively; Telegram has its own DND that can drift from system state.
- **Per-device, per-action revocation.** A lost phone revokes one device token without affecting Telegram or other devices.
- **OS-managed credential storage.** Android Keystore and iOS Keychain hold device keys; Telegram bot tokens currently live in user-readable config files.

These features are also the ones most likely to make the user actively prefer the app over Telegram once both work.

## Native App Costs and Risks

### Background Delivery Is Harder Than Telegram

Telegram already solved push delivery. A SASE app must solve it itself.

On Android 13+ the app needs the `POST_NOTIFICATIONS` runtime permission for non-exempt notifications. Foreground
connected mode must be visible to the user and respect modern foreground-service rules. FCM can wake an app with high
priority messages, but Google explicitly frames those as limited processing windows for user-visible interactions, not
as a general long-running background sync channel.

Implication: the MVP should separate foreground value from background delivery. Build the inbox/control plane first.
Then add push hints that contain no secrets and only tell the app to fetch current state from the host.

Sources: [Android notification permission](https://developer.android.com/develop/ui/views/notifications/notification-permission),
[Android foreground services](https://developer.android.com/develop/background-work/services/fgs),
[FCM Android message priority](https://firebase.google.com/docs/cloud-messaging/android-message-priority).

### Distribution and Maintenance Are Real

Even Android-only has maintenance overhead:

- Google Play has a one-time developer registration fee.
- Google Play target SDK requirements advance; current Play requirements require Android 15/API 35 or higher for new
  app submissions and updates starting 2025-08-31.
- If iOS enters scope later, Apple Developer Program membership is a recurring annual cost and App Review adds policy
  work.
- Native app code adds security, release, QA, UI regression, emulator/device testing, dependency updates, and support
  burden.

Sources: [Play Console registration](https://support.google.com/googleplay/android-developer/answer/6112435),
[Google Play target API requirements](https://developer.android.com/google/play/requirements/target-sdk),
[Apple Developer Program](https://developer.apple.com/programs/).

### The Gateway Expands the Attack Surface

Telegram's current architecture mostly avoids inbound access to the workstation: the bot/plugin polls Telegram and
writes local response files. A mobile gateway must accept authenticated HTTP requests.

Minimum non-negotiables:

- Loopback bind by default.
- Explicit opt-in for LAN/tailnet binds.
- No public internet exposure as the normal path.
- No arbitrary path, shell, environment, or RPC endpoints.
- Per-device tokens, audit logging, revocation, and rate limits.
- Typed errors for stale/ambiguous/already-handled actions.
- Attachment path, symlink, size, and token checks.
- Push payloads as hints only.

The existing gateway docs already align with this. Do not weaken that architecture to chase convenience.

### Connectivity Reality on Mobile Networks

A subtle but important question the previous analysis under-emphasized: from where can the user actually reach the gateway?

- **Loopback bind:** unreachable from any phone, ever.
- **LAN bind:** reachable only when the phone is on the same WiFi as the workstation. Public WiFi, cellular, and most office/guest networks fail.
- **Tailscale Serve over MagicDNS:** reachable from anywhere the phone has a network and Tailscale is running, including cellular. This is the realistic remote-access path.
- **Tailscale Funnel:** publicly reachable but a broader-than-necessary attack surface for a personal control plane; SASE should not default to it.

Practical consequences:

- The gateway is not "always reachable like Telegram." It is reachable when the workstation, tailnet, and phone Tailscale agent are all healthy.
- Tailscale on Android/iOS has measurable but acceptable battery cost (idle DERP keepalives), which is fine for users who already run Tailscale, but is a real install for users who do not.
- During gateway unreachability the app should degrade gracefully: show stale state with timestamps, queue actions, retry on reconnect, and never present "this might have happened" as fact.
- This is the strongest argument for a hybrid model: native app over tailnet for control-plane work, Telegram (or another always-on transport) as a notification-only fallback for "the workstation/tailnet is down" alerting.

Sources: [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve), [Tailscale on mobile](https://tailscale.com/kb/1023/troubleshooting), [DERP relays](https://tailscale.com/kb/1232/derp-servers).

### iOS-Specific Considerations

The current MVP plan is Android-only, but several iOS realities should be named so the gateway design does not paint itself into a corner:

- **APNs is not FCM.** Apple Push Notification service does not support reliable silent data-only wake-ups equivalent to FCM high-priority data messages. iOS background fetch is opportunistic and the OS can throttle it heavily.
- **No UnifiedPush equivalent on iOS.** Independent open-source iOS apps cannot bypass APNs.
- **TestFlight is the only side-loading-equivalent path.** Builds expire every 90 days and tester counts are bounded — awkward for a personal tool that should "just work".
- **Apple Developer Program is $99/year** versus Google Play's one-time $25. Over three years iOS membership is roughly 12× the cost.
- **App Review can be judgmental.** A "control plane for arbitrary code execution on the user's other device" can hit guideline ambiguity and require careful framing.
- **Background networking is more constrained on iOS** than on Android. A persistent SSE channel is less viable; "push hint plus foreground fetch" is essentially mandatory.

This makes a Telegram Mini App or a tailnet-served PWA disproportionately attractive for iOS even if Android gets a native client.

Sources: [APNs overview](https://developer.apple.com/documentation/usernotifications), [Background tasks on iOS](https://developer.apple.com/documentation/backgroundtasks), [App Store Review Guidelines](https://developer.apple.com/app-store/review/guidelines/), [TestFlight](https://developer.apple.com/testflight/).

## Telegram Mini App as an Intermediate Option

Telegram Mini Apps are worth considering before over-investing in native UI. They are web apps launched inside Telegram,
with seamless Telegram authorization and recent support for persistent device storage and secure storage. A Mini App
could provide a richer dashboard while keeping Telegram as the distribution and notification shell.

This could be attractive if the main uncertainty is UI value:

- Build the stateful inbox/agent dashboard as a web app.
- Launch it from Telegram.
- Reuse the host gateway API.
- Avoid Android project setup and app-store distribution at first.

Limitations:

- Still depends on Telegram.
- Still inherits Telegram account/platform trust concerns.
- Still needs hosted web assets or a reachable local/tailnet web path.
- Does not provide the same first-party app identity, OS integration, or independent notification channel as native.

Source: [Telegram Mini Apps](https://core.telegram.org/bots/webapps).

## Alternative Notification Transports

The choice is not binary between "Telegram" and "custom native app." Several transports sit between those poles and may shift the value calculation:

- **ntfy.sh (open source, self-hostable).** HTTP POST publishes a message; mobile apps subscribe to topics. Topic name is a shared secret; optional E2E encryption. Excellent for "notification only, no in-band actions"; trades simplicity for absent action UI.
- **Gotify.** Self-hosted with an Android client (no first-party iOS); token-based. Similar profile to ntfy with a heavier server.
- **UnifiedPush.** Distributor model, Android-focused; lets a SASE app receive push without Google Play Services. Useful for FCM-free distribution but not a Telegram replacement on its own.
- **Matrix bot (Element / Beeper / Cinny).** Federated chat with E2E encryption available in private rooms and a real bot SDK. Better privacy story than Telegram, more setup cost.
- **Signal.** No real public bot API. Not a viable SASE channel today.
- **Discord/Slack webhooks.** Action UI is limited; team-chat aesthetic is wrong for a personal tool, but trivial to wire up as an additional channel.
- **Email + IMAP push.** Universal, works on every device; reply-by-email is plausible for HITL but interaction round-trip is slow.
- **Tasker / iOS Shortcuts + generic webhook.** Can build very custom flows on top of ntfy/Gotify/email for power users who do not want a SASE-specific app.

For SASE specifically, a self-hosted ntfy.sh (or even public ntfy with per-user random topic names) is worth keeping in mind as a Telegram alternative for notification-only delivery. It pairs cleanly with the gateway: gateway emits a content-free push hint, the app or any other client fetches state from the gateway when the user opens it.

Sources: [ntfy.sh](https://ntfy.sh/), [Gotify](https://gotify.net/), [UnifiedPush](https://unifiedpush.org/), [Matrix Bot SDK](https://github.com/turt2live/matrix-bot-sdk).

## Onboarding and Setup Cost

Setup friction is a hidden but decisive variable; it tends to dominate "do I keep using this?" for personal tools.

| Path | First-time setup | Per-device add | Recovery if device lost |
|---|---|---|---|
| Telegram bot | BotFather to create bot, copy token. SASE: install plugin, paste token, message bot, capture chat ID, restart chops. | Sign in to Telegram on the new device. | Sign in elsewhere; revoke old session in Telegram. |
| Native app + gateway | Install gateway, run `sase mobile gateway start`, install APK or Play app, scan pairing QR; optionally enable Tailscale on phone for cellular reach. | Re-pair from gateway, scan a fresh QR. | Revoke the device token from gateway; re-pair on replacement. |
| Telegram Mini App | If the bot already exists, tap "Open App" in chat. Otherwise BotFather setup as above. | Sign in to Telegram on the new device. | Sign in elsewhere. |
| ntfy.sh / Gotify | Install app, paste server URL or use public host, subscribe to a topic. SASE: configure HTTP push of notifications. | Repeat install + subscribe. | None; the topic name is the secret, so rotate it. |

Telegram has the lowest per-device friction because it inherits Telegram's account model. Gateway-based paths are heavier on first setup but offer per-device tokens, which is meaningfully better for revocation and audit. Mini App is the lowest-friction non-Telegram-replacing UI upgrade.

## Multi-Device and Offline Semantics

Telegram solves a problem for SASE almost incidentally: multi-device read-state sync, offline queueing, and reconnection semantics. The mobile gateway must reproduce this explicitly:

- **Read state across devices.** When the user dismisses a question on the phone, the TUI and any other paired device must reflect that. The gateway needs an authoritative server-side notion of "handled" with per-device dismissal and timestamps.
- **Stale-action detection in real multi-client use.** A pending action can be handled by Telegram, the TUI, or another phone. The existing gateway design has stale-action types; they must be exercised in real multi-client traffic, not left as a single-client assumption.
- **Offline action queuing.** The app must queue user actions while disconnected and replay them with idempotency keys. Replaying "kill agent X" twice should be safe.
- **Event replay on reconnect.** SSE drops happen. The app should track the last-seen event ID and request a replay window from the gateway, not silently re-fetch everything (which masks gaps).
- **Push catch-up.** A push that arrives while the app is offline should still be reconciled when the app next opens, not lost.

These semantics are not glamorous and are not where mobile dev attention naturally flows, but they are the difference between "feels like Telegram" and "feels broken."

## Prior Art: Mobile Companion Apps

Several existing products almost exactly match the SASE gateway-plus-mobile shape and are worth treating as design references:

- **Home Assistant Companion.** Self-hosted Home Assistant server on the user's network plus iOS/Android companion apps that pair via QR or URL, talk over LAN or Nabu Casa cloud relay, and use FCM/APNs for hint-style push. The action surface is a structured dashboard. SASE's gateway+app shape is essentially the same architecture.
- **Tailscale mobile.** The mobile app's primary job is to manage and join a tailnet. The SASE app naturally inherits its pairing-via-QR + per-device key + revocation pattern.
- **GitHub Mobile.** Pure cloud-backed, but a strong UX reference for "approve/review/comment from the phone." Notification inbox, PR detail, review-and-merge flow are directly relevant to plan/HITL UI.
- **Linear, Sentry, Vercel mobile apps.** Same dashboard-and-action archetype, generally well-received by power users for triage, weak for deep work.
- **Codespaces and Replit mobile.** Closer to SASE's "real work happens elsewhere; the phone is a thin viewer" model. Both struggle with the gap between phone-friendly tasks and full sessions, which is precisely the constraint SASE should plan for.

Lessons from prior art that should be load-bearing for SASE:

- Pair via QR; never assume LAN-only is sufficient.
- Treat push as hint-only; fetch on open.
- Build the inbox/triage surface first; full-session UX is rarely the right phone target.
- Multi-device read-state sync is a feature, not a polish item.
- A cloud relay (Nabu Casa for HA, tailnet for SASE) is what makes the app actually usable on cellular.

Sources: [Home Assistant Companion architecture](https://companion.home-assistant.io/docs/getting_started/), [Tailscale on mobile](https://tailscale.com/kb/1023/troubleshooting), [GitHub Mobile](https://github.com/mobile).

## Decision Framework

Build or continue the native app if at least three of these are true:

- You want SASE to be usable by people who do not use Telegram.
- Sensitive SASE content should stop flowing through Telegram for normal workflows.
- You need a dashboard/inbox more than a chat notification stream.
- You expect mobile launch/agent management to become a daily workflow, not occasional emergency control.
- You want the host gateway API as a strategic platform for web/editor/desktop clients.
- You will already have Tailscale (or equivalent) installed on your phone, so cellular reach is realistic.
- You want mobile-native affordances (biometric guard, share-sheet launch, widgets) that Telegram cannot provide.
- You are willing to maintain mobile release, auth, connectivity, multi-device sync, and background-delivery code.

Prefer improving Telegram if most of these are true:

- You are the primary user and already live in Telegram.
- The main mobile need is "approve/reject/answer/kill/retry while away."
- You do not need private first-party transport for sensitive content yet.
- You are not ready to own mobile push/release/security maintenance.
- The app would mostly reproduce chat messages with prettier buttons.

Use a Telegram Mini App or lightweight web dashboard if:

- You want to test dashboard UX before committing to native.
- You can accept Telegram as the shell for another quarter.
- You want one UI implementation that can also become a standalone web client later.
- iOS support matters and you are not ready to pay the App Store and APNs cost.

Consider an additional non-Telegram notification transport (ntfy.sh, Gotify, UnifiedPush, or email) if:

- You want privacy-preserving notifications without committing to a full native app yet.
- You need a fallback alert path for "the workstation or tailnet is down" that does not depend on Telegram.
- You want to decouple "where notifications arrive" from "what UI handles them" so the app, TUI, and Telegram can each consume the same gateway state.

## Suggested Path

1. **Keep Telegram as production fallback.** Do not replace it until the app handles the same critical actions reliably.
2. **Finish the gateway as the durable asset.** Pairing, auth, notifications, actions, agents, helpers, attachments, SSE,
   audit, and revocation matter beyond Android.
3. **Build the first Android milestone around foreground value.** Pair with host, show connection state, render a real
   notification inbox, open detail, and complete plan/HITL/question actions.
4. **Add the agent dashboard before push.** Agent list/kill/retry/resume/launch is the clearest "better than Telegram"
   app surface.
5. **Use push hints later.** FCM or UnifiedPush should wake/open the app, not carry SASE content. Treat ntfy.sh as a
   credible alternative if you want to avoid Google Play Services entirely.
6. **Validate cellular reach early.** Test the gateway from cellular over Tailscale Serve before committing to push
   work. If tailnet reach is unreliable in your daily environment, the app's value drops sharply and the project plan
   should react before push effort lands.
7. **Plan multi-device read-state sync from the start.** Even a single user runs the TUI plus Telegram plus the app;
   "handled" must be authoritative on the gateway, not per-client.
8. **Reassess after two weeks of personal use.** If you still approve from Telegram and rarely open the app dashboard,
   the app should pause and the gateway/web/Mini-App path should get priority.

## Bottom Line

The app has meaningful potential, but not because SASE needs another notification channel. Telegram already handles that
well.

The app is valuable if it becomes the mobile SASE console: private, structured, stateful, and comfortable for complex
review/launch/agent-management workflows. The gateway is the strategic investment. The native Android app should be
treated as one client that proves whether that control-plane model is worth deepening.
