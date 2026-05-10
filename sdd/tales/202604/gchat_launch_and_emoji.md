---
name: gchat_launch_and_emoji
description: Add agent-launch Google Chat notifications and prefix every outbound
  gchat message with a sase identifier emoji
type: plan
create_time: 2026-04-25 10:23:02
status: wip
prompt: sdd/prompts/202604/gchat_launch_and_emoji.md
---

# Google Chat: Launch Notifications + Sase Identifier Emoji

## Problem

Two related gaps in the Google Chat integration:

1. **No agent-launch notification.** When the user (or anything else) launches a new agent — via the TUI `@`-key,
   `sase run -d`, an inbound gchat dot-command, repeat fan-out, alt-split, multi-prompt, retry-spawn, etc. — there is no
   Chat message announcing it. The user sees the agent on the Agents tab and eventually receives a `✅ Complete` message
   when it finishes, but the launch event itself is silent. Existing notification types (`plan_approval`,
   `hitl_request`, `user_question`, `workflow_complete`, `sync_result`, `axe_error_digest`, `image`) cover everything
   _except_ launches.

2. **Sase-sent messages are visually indistinguishable from the user's own messages.** The Google Chat space is a
   personal DM-style space where every message — both sase-generated and user-typed — appears under the user's own
   account, so on a phone the only signal that something came from sase is the contextual emoji each formatter happens
   to start with (`📋`, `❓`, `🔧`, `✅`, etc.). Inbound confirmation replies (`✅ Approved`, `❌ Rejected`) and
   dot-command results (`.list`, `.kill`, …) do not always have a leading emoji and are easy to mistake for the user's
   own previous reply. The user wants a single, consistent "this came from sase" prefix on **every** outbound message.

## Goals

- Every successful agent launch produces a Google Chat notification that names the agent, shows a truncated prompt, and
  (when relevant) flags retry-spawned launches and the model used.
- Every outbound Google Chat message — notifications, inbound confirmations, edited messages (strike-throughs),
  dot-command output — starts with a single sase-identifier emoji so the user can scan the thread and instantly tell
  sase-sent messages from their own.
- Emoji prefixing is centralised at one chokepoint so future message sites get it for free.

## Non-goals

- Changing what each existing notification type _says_ (only prefixing).
- Adding launch notifications for non-agent activity (chops, lumberjack jobs, etc.).
- Restructuring the notification storage / dispatch pipeline.

## Architecture summary (current state)

Outbound flow:

```
sase_101: notify_*()  →  ~/.sase/notifications/notifications.jsonl
                                     ↓
retired chat plugin outbound chop polls store  →  format_notification()  →  gchat_client.send_message()
                                                                                ↓
                                                                      gchat CLI → Google Chat
```

- Single notification creation chokepoint: `sase/notifications/senders.py` (sase_101).
- Single send chokepoint for outbound: `retired_chat_plugin/gchat_client.py::send_message()` (retired chat plugin).
- Single formatting dispatcher: `retired_chat_plugin/formatting.py::format_notification()` (retired chat plugin).
- Inbound replies and dot-command output bypass `format_notification` and go straight to `send_message()`.

These three chokepoints are exactly the leverage points we need.

## Design

### Part A — Agent-launch notifications (sase_101)

**New sender:** `notify_agent_launched()` in `src/sase/notifications/senders.py`. Mirrors the shape of
`notify_workflow_complete` but with `sender="agent-launch"` and `action=None` (informational, no reply buttons).
Captures: `agent_name` (the `@-name` users see), `cl_name`, `prompt`, `workflow_name`, `project_name`, `workspace_num`,
`pid`, optional `llm_provider`, `model`, and a `retry_attempt` int when this launch is a retry-spawned child.

**Trigger point:** call it from `spawn_agent_subprocess()` in `src/sase/agent/launcher.py`, immediately after the
workspace is successfully claimed and just before returning `AgentLaunchResult`. This is the single chokepoint that
_all_ launch paths funnel through:

- TUI `@`-key launches (`ace/tui/actions/agent_workflow/_agent_launch.py`)
- `sase run -d` and `launch_agent_from_cwd`
- Multi-prompt (`agent/multi_prompt_launcher.py`)
- Repeat fan-out (`agent/repeat_launcher.py`)
- Alt-split
- Retry spawn (`axe/run_agent_retry_spawn.py`, via `retry_transfer_from_pid`)
- Inbound gchat agent launches (`retired chat plugin/.../sase_gc_inbound.py`)

Putting the call here means we get one notification per _spawned subprocess_, which is the right granularity (a
multi-prompt with 3 segments produces 3 launch notifications, matching what shows up on the Agents tab).

**Retry handling.** When `retry_transfer_from_pid is not None`, populate `retry_attempt`/`retry_of_timestamp` on the
notification so the formatter can render `🔁 Retry #N` instead of a plain launch banner. We do NOT suppress the
notification — visibility into retry chains is valuable.

**Silencing escape hatch.** Add an optional `silent` parameter (default `False`). The agent-launch notification is on by
default for all launches. If a future caller (e.g. background mentor jobs) needs to suppress, it can pass `silent=True`,
which the existing outbound filter already honours (`retired chat plugin/outbound.py:43`). No config flag is needed for the
initial cut.

**Tests:** unit-test the new sender (notification is appended with the right shape), and add an integration test that
asserts `spawn_agent_subprocess()` writes exactly one launch notification per call (and zero on workspace-claim failure,
since we only notify after success).

### Part B — Launch formatter (retired chat plugin)

Add `_format_agent_launch(n)` in `retired_chat_plugin/formatting.py` and route to it from `format_notification()` when
`notification.sender == "agent-launch"`.

Rendered text (illustrative):

```
🚀 *Claude Sonnet 4.6 Agent Launched*  _@plan-review-fix_

📝 *Prompt:*
fix the gchat launch notifications and add a sase emoji prefix…

🧵 workspace sase_5 · pid 18342
```

For retries, swap the heading to `🔁 *Agent Retry #2 Launched*` and append `↪️ retry of @parent-name` on the following
line. Reuse `format_provider_model_label()` from `sase.llm_provider.registry` for the model label, matching
`_format_workflow_complete`.

No `Option`s, no attachments. Truncate prompt at the existing `PROMPT_DISPLAY_MAX = 1000`.

### Part C — Universal sase identifier emoji (retired chat plugin)

**Choice of emoji.** Use `🤖` (robot face). Rationale: universally read as "automated / AI", visually distinct from
every emoji currently used by formatters (📋 ❓ 🔧 ✅ ✏️ 📚 🚀 ⚠️ 🖼️ 🔔 🔁), renders cleanly on phones, and is short
enough not to crowd the line.

**Where to apply it.** Centralise in `retired_chat_plugin/gchat_client.py`:

- `send_message(space, text, …)` prepends `🤖 ` to `text` before invoking the CLI.
- `edit_message(space, message_id, text)` does the same — necessary because the strike-through flow in
  `sase_gc_inbound.py::_strike_message` rebuilds an edited message body and we want the prefix preserved on the edited
  result.

Use a small idempotent helper:

```python
SASE_PREFIX = "🤖 "

def _ensure_sase_prefix(text: str) -> str:
    return text if text.startswith(SASE_PREFIX) else SASE_PREFIX + text
```

Idempotency matters because:

- `pending_actions` stores the original `formatted.text` as `rendered_text`. If a future code path ever pre-prefixes
  before calling `send_message`, the helper protects against double-prefixing.
- `edit_message` is called with text derived from `rendered_text`; whether `rendered_text` was stored with or without
  the prefix, the edited message ends up with exactly one prefix.

**Why centralise at the client and not at the formatter.** Inbound confirmations (`_post_confirmation`, `✅ Approved` /
`❌ Rejected`) and dot-command results (`.list`, `.kill`) call `send_message` _directly_, bypassing
`format_notification`. Putting the prefix in the formatter would miss them. Putting it in the client guarantees every
outbound message — current and future — gets the prefix.

**`upload_file` is unaffected** (no text body).

**Strike-through interaction.** `_strike_options_block` produces `~Options consumed~` appended to the original body.
After `edit_message` re-prefixes, the struck message still starts with `🤖 `. Verified by inspection of
`sase_gc_inbound.py:141-155`.

### Part D — Update existing formatter constants for consistency

The contextual emojis in formatters (📋, ❓, 🔧, …) stay where they are — they convey meaning ("this is a plan", "this
is a question") that the universal `🤖 ` prefix doesn't replace. The two work together:

```
🤖 📋 *Plan Review*  _@foo_
🤖 ❓ *Question*
🤖 ✅ *Complete*  _@foo_
🤖 🚀 *Agent Launched*  _@foo_
🤖 ✅ Approved
```

No edits to the existing formatter functions are required for the prefix; it lands purely at the client layer.

## Files affected

**sase_101:**

- `src/sase/notifications/senders.py` — add `notify_agent_launched`.
- `src/sase/notifications/__init__.py` — export it.
- `src/sase/agent/launcher.py` — call `notify_agent_launched` after successful claim in `spawn_agent_subprocess`.
- `tests/notifications/test_senders.py` (or equivalent) — unit test.
- `tests/agent/test_launcher.py` (or equivalent) — integration test.
- `src/sase/telemetry/metrics.py` — add `agent_launch` label to `NOTIFICATIONS_SENT` if labels are restricted.

**retired chat plugin:**

- `src/retired_chat_plugin/formatting.py` — add `_format_agent_launch`, route from `format_notification`.
- `src/retired_chat_plugin/gchat_client.py` — add `SASE_PREFIX`, `_ensure_sase_prefix`, apply in `send_message` and
  `edit_message`.
- `tests/test_formatting.py` — test the new formatter.
- `tests/test_gchat_client.py` — test prefix idempotency on send and edit, and that `upload_file` is untouched.

## Rollout / risk

- **Notification noise.** A user with a busy day spinning up many agents will see one Chat message per launch.
  Acceptable: this is the explicit ask, and the `silent=True` escape hatch is wired in. If it becomes too noisy in
  practice, a follow-up could batch consecutive launches inside a short window — out of scope here.
- **Backwards compatibility.** Inbound parsing in `sase_gc_inbound.py` matches against `*Reply with a number...*` text —
  the `🤖 ` prefix doesn't affect that regex. Pending-action storage keys on `notif_id_prefix`, not on message text.
  Strike-through regex matches by content suffix, not the start of the message. No risk to existing flows.
- **Other plugins.** `sase-telegram` is a separate plugin with its own formatting layer; this plan does not touch it. If
  we want a uniform "sase prefix" experience there too, that's a follow-up.

## Verification

1. `just check` in sase_101 (lint + tests).
2. `just check` in retired chat plugin.
3. Manual smoke test:
   - Launch an agent from the TUI; confirm `🤖 🚀 *Agent Launched*` lands in Chat.
   - Trigger a plan approval; confirm `🤖 📋 *Plan Review*`.
   - Reply `1` to approve; confirm `🤖 ✅ Approved` and the original message struck through with prefix preserved.
   - Send `.list` from Chat; confirm response begins with `🤖 `.
   - Force a retry-spawn (or stub one); confirm the retry-launch heading.
