# Telegram Integration Improvements for SASE (Research)

Date: 2026-03-18

## Scope

This note covers:

1. Improvements to the `sase-telegram` integration itself.
2. Telegram power-user workflow improvements that make SASE faster/easier to run day-to-day.

## Current State Snapshot (from local code)

The plugin in `../sase-telegram` is already strong:

- Two-way flow is implemented (`sase_tg_outbound`, `sase_tg_inbound`).
- Rich notification handling exists (plan/HITL/question/workflow/error digest).
- Inline keyboard callbacks are wired with pending-action persistence.
- Basic flood handling exists (local sliding-window limiter + retry on `RetryAfter`).
- Agent operations from Telegram already exist (`.list`, `.listx`, `.kill`, text-to-launch).

Observed gaps/opportunities in current code:

- Inbound polling currently calls `get_updates(..., timeout=0)` (short polling).
- `allowed_updates` is not configured.
- Single-chat assumptions are strong (`SASE_TELEGRAM_BOT_CHAT_ID`).
- Dot commands are powerful but not discoverable in Telegram UI.
- MarkdownV2 complexity creates ongoing parse/escaping risk.

## High-Impact Integration Improvements

### 1) Move inbound to long polling + `allowed_updates`

Why:

- Bot API docs recommend long polling over short polling for production behavior.
- `allowed_updates` cuts noise and parsing overhead.

What to change:

- Use `timeout` > 0 (e.g. 20-50s) in inbound `getUpdates`.
- Set `allowed_updates=["message", "callback_query"]` (and optionally others when needed).

Expected result:

- Fewer API calls and less churn.
- Lower chance of race behavior around frequent poll cycles.

### 2) Add command/menu discoverability via Bot API metadata

Why:

- You already have hidden “power” commands (`.list`, `.kill`, etc.).
- Telegram has built-in command and menu surfaces.

What to change:

- Register bot commands with `setMyCommands`.
- Configure menu with `setChatMenuButton` (`MenuButtonCommands` or `MenuButtonWebApp`).
- Set profile descriptions using `setMyDescription` and `setMyShortDescription`.

Expected result:

- Better UX for infrequent users.
- Less memorization of syntax.

### 3) Add structured response buttons for common actions

Why:

- Inline keyboard can now include copy-focused and inline-query flows.
- For approval or command snippets, one-tap “copy” beats retyping.

What to change:

- Use `InlineKeyboardButton.copy_text` for common command snippets.
- Consider `switch_inline_query_current_chat` for workflows where users pick from prefilled bot actions.

Expected result:

- Faster operator response loops, fewer typo-driven failures.

### 4) Improve outbound experience for long-running work

Why:

- Bot API now supports `sendMessageDraft` (stream partial output).
- `sendChatAction` gives immediate “working...” feedback.

What to change:

- For expensive operations (PDF conversion, large attachments, agent launch), send `sendChatAction` first.
- Experiment with `sendMessageDraft` for progressive updates while agents run.

Expected result:

- Better perceived responsiveness.
- Reduced “did it hang?” operator uncertainty.

### 5) Add topic-based organization for busy users

Why:

- New Bot API support includes private-chat topics (`message_thread_id`, `createForumTopic` updates in 2025/2026).
- Busy SASE users need separation by project/agent/class of notification.

What to change:

- Optional routing rules: plan reviews in one topic, HITL in another, errors in another.
- Store thread/topic mapping in config.

Expected result:

- Cleaner chat history and better triage.

### 6) Tighten delivery semantics

Why:

- Current inbound flow saves update offset before processing; this avoids duplicates but can drop updates on crash
  between save and handle.

What to change:

- Option A: keep current at-most-once behavior but document clearly.
- Option B: move to effectively-once behavior with idempotency keys per update and commit offset after durable handling.

Expected result:

- Clearer reliability model and fewer edge-case surprises.

### 7) Revisit rate limiting model

Why:

- Official limits are per-chat/group/global; current limiter is local sliding-window only.

What to change:

- Track per-chat + global budget separately.
- Keep honoring `RetryAfter` with backoff.
- Optionally move to PTB `BaseRateLimiter`/`AIORateLimiter` if shifting to a single async runtime.

Expected result:

- More predictable behavior under bursty notification load.

## Telegram Power-User Workflow Improvements

### 1) “SASE Ops” chat folder + folder tags

Workflow:

- Create a dedicated folder for SASE bot chat + related team chats.
- Use tags/colors to separate projects/contexts.

Why it helps:

- Faster context-switching with less chat-list noise.

### 2) Use Saved Messages as personal SASE command/runbook hub

Workflow:

- Store reusable prompts, incident templates, and one-liners in Saved Messages.
- Use reaction tags for searchable categories (`#incident`, `#release`, `#triage` equivalents via tag reactions).

Why it helps:

- Faster prompt reuse and less cognitive load.

### 3) Business quick replies for recurring approvals/feedback

Workflow:

- If using Telegram Premium/Business, define quick replies for common responses:
  - “Approve with note ...”
  - “Reject and request simplification ...”
  - “Run follow-up checks ...”

Why it helps:

- Cuts response latency for repetitive human-in-the-loop steps.

### 4) Business chat deep links for one-tap launch presets

Workflow:

- Generate deep links that prefill common SASE prompts.
- Pin these links in your team docs/wiki.

Why it helps:

- Consistent, low-friction launch entry points.

### 5) Topic hygiene for high-volume operators

Workflow:

- Pin one topic per major workflow: `Plan Reviews`, `HITL`, `Run Results`, `Incidents`.

Why it helps:

- Better scrollback and triage under load.

## Prioritized Implementation Plan

1. `P0`: inbound long polling + `allowed_updates` + command metadata (`setMyCommands`, descriptions).
2. `P1`: button UX upgrades (`copy_text`, optional inline query flows) + `sendChatAction`.
3. `P2`: topic routing + reliability model hardening + richer rate-limit strategy.
4. `P3`: optional experiments with `sendMessageDraft` streaming and Business deep-link workflows.

## Risks / Tradeoffs

- Topic- and business-oriented features can add subscription/platform complexity.
- Streaming and richer UX increases state management complexity.
- Changing delivery semantics (offset commit timing) can affect duplicate-vs-loss behavior; requires explicit decision.

## Sources

- Telegram Bot API (current docs/changelog, includes Bot API 9.5 on 2026-03-01):
  - https://core.telegram.org/bots/api
  - https://core.telegram.org/bots/api-changelog
- Telegram Bots FAQ (limits, polling/webhook behavior):
  - https://core.telegram.org/bots/faq
- Telegram API docs for power-user features:
  - Folders: https://core.telegram.org/api/folders
  - Saved Messages: https://core.telegram.org/api/saved-messages
  - Business features: https://core.telegram.org/api/business
- python-telegram-bot docs:
  - ApplicationBuilder: https://docs.python-telegram-bot.org/en/latest/telegram.ext.applicationbuilder.html
  - AIORateLimiter: https://docs.python-telegram-bot.org/en/latest/telegram.ext.aioratelimiter.html

## Notes on Source Interpretation

- Recommendations tied to `sase-telegram` internals are based on local code inspection of `../sase-telegram`.
- Feature recommendations (topics, draft streaming, command/menu UX, folder/saved/business workflows) are inferred from
  Telegram docs as of 2026-03-18.
