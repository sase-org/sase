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

## Decision Framework

Build or continue the native app if at least three of these are true:

- You want SASE to be usable by people who do not use Telegram.
- Sensitive SASE content should stop flowing through Telegram for normal workflows.
- You need a dashboard/inbox more than a chat notification stream.
- You expect mobile launch/agent management to become a daily workflow, not occasional emergency control.
- You want the host gateway API as a strategic platform for web/editor/desktop clients.
- You are willing to maintain mobile release, auth, connectivity, and background-delivery code.

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

## Suggested Path

1. **Keep Telegram as production fallback.** Do not replace it until the app handles the same critical actions reliably.
2. **Finish the gateway as the durable asset.** Pairing, auth, notifications, actions, agents, helpers, attachments, SSE,
   audit, and revocation matter beyond Android.
3. **Build the first Android milestone around foreground value.** Pair with host, show connection state, render a real
   notification inbox, open detail, and complete plan/HITL/question actions.
4. **Add the agent dashboard before push.** Agent list/kill/retry/resume/launch is the clearest "better than Telegram"
   app surface.
5. **Use push hints later.** FCM or UnifiedPush should wake/open the app, not carry SASE content.
6. **Reassess after two weeks of personal use.** If you still approve from Telegram and rarely open the app dashboard,
   the app should pause and the gateway/web/Mini-App path should get priority.

## Bottom Line

The app has meaningful potential, but not because SASE needs another notification channel. Telegram already handles that
well.

The app is valuable if it becomes the mobile SASE console: private, structured, stateful, and comfortable for complex
review/launch/agent-management workflows. The gateway is the strategic investment. The native Android app should be
treated as one client that proves whether that control-plane model is worth deepening.
