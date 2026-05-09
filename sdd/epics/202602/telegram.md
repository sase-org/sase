---
bead_id: sase-70gx
status: done
---

# Telegram Integration Plan

## Context

Sase agents run autonomously in background workflows, producing notifications (plan approvals, HITL requests, user
questions, error digests, workflow completions) that currently require the user to be watching the `sase ace` TUI. When
the user steps away, these notifications go unnoticed until they return. This integration sends those notifications to
Telegram when the user is inactive, with inline keyboard buttons for actionable items (approve/reject plans, accept HITL
requests, answer questions), enabling remote interaction without returning to the TUI.

## Architecture Overview

Two new chop scripts run in the existing `heartbeats` lumberjack (60s interval):

- **`sase_chop_tg_outbound`** -- Checks if user is inactive (no TUI interaction for N seconds), loads unread
  notifications newer than the last sent, formats them as Telegram messages with inline keyboards, and sends them.
- **`sase_chop_tg_inbound`** -- Polls Telegram for inline keyboard callbacks and text messages, decodes the callback
  data, and writes the appropriate response files (`plan_response.json`, `hitl_response.json`, `question_response.json`)
  so the polling handlers in sase core pick them up seamlessly.

Core sase changes are minimal: activity timestamp tracking in the TUI + a public API for chops to read it.

---

## Phase 1: Activity Tracking in sase Core

**Repo**: `sase` (sase core)

### 1.1 New module: `src/sase/ace/tui_activity.py`

Public API for reading/writing user activity timestamps:

```python
ACTIVITY_FILE = "~/.sase/tui_last_activity"

def write_activity_timestamp(epoch: float) -> None:
    """Atomic write of Unix epoch to activity file."""

def get_tui_last_activity() -> float | None:
    """Read last activity timestamp, or None if missing."""

def get_tui_inactive_seconds() -> float | None:
    """Seconds since last TUI interaction, or None if unknown."""
```

Uses atomic write (write to `.tmp`, then `os.replace`) for crash safety.

### 1.2 Track activity in TUI

**File**: `src/sase/ace/tui/actions/event_handlers.py`

- In `on_key()`, at the very top (before any mode checks): `self._last_activity_time = time.monotonic()` -- zero-cost
  in-memory update, no disk I/O.
- In `_on_countdown_tick()` (runs every 1s): flush to disk if 10+ seconds since last flush:
  ```python
  now_mono = time.monotonic()
  if now_mono - getattr(self, '_last_activity_flush', 0) >= 10:
      if hasattr(self, '_last_activity_time'):
          write_activity_timestamp(time.time())
          self._last_activity_flush = now_mono
  ```

**File**: `src/sase/ace/tui/app.py`

- In `on_mount()`: initialize `_last_activity_time`, `_last_activity_flush`, write initial timestamp.

### 1.3 `I` keybinding: mark inactive

**File**: `src/sase/ace/tui/app.py`

- Add binding: `Binding("I", "mark_inactive", "Mark Inactive", show=False)`
- `action_mark_inactive()`: writes `write_activity_timestamp(0)` (epoch 0 = maximally inactive), shows toast "Marked as
  inactive". The next heartbeat cycle (up to 60s) picks this up and sends pending notifications.

### 1.4 Public API registration

**File**: legacy public API whitelist -- add `get_tui_last_activity` and `get_tui_inactive_seconds`.

### 1.5 Tests

**File**: `tests/test_tui_activity.py` -- unit tests for `write_activity_timestamp`, `get_tui_last_activity`,
`get_tui_inactive_seconds` with tmp dirs.

### Verification

- `just check` passes
- `sase ace --agent --keys I` shows the toast and writes `~/.sase/tui_last_activity` with value `0.0`
- Normal TUI usage updates the activity file every ~10 seconds

---

## Phase 2: sase-telegram Repo Scaffold

**Repo**: New repo at `~/projects/github/bbugyi200/sase-telegram/`

### 2.1 Repository structure

```
sase-telegram/
  CLAUDE.md                        # Points to @AGENTS.md
  AGENTS.md                        # Repo-specific agent instructions
  Justfile                         # install, lint, fmt, test, check, clean, build
  pyproject.toml                   # hatchling, ruff, mypy, pytest
  src/sase_telegram/
    __init__.py
    credentials.py                 # get_bot_token(), get_chat_id(), get_bot_username()
    telegram_client.py             # TelegramClient wrapper around python-telegram-bot
    callback_data.py               # encode/decode callback_data strings
    pending_actions.py             # Track pending inline keyboard actions
    rate_limit.py                  # Sliding window rate limiter
    scripts/
      __init__.py                  # Entry point wrappers
      sase_chop_tg_outbound.py     # Outbound chop script
      sase_chop_tg_inbound.py      # Inbound chop script
  tests/
    __init__.py
```

### 2.2 pyproject.toml

Following `sase-github/pyproject.toml` pattern exactly:

- Build: hatchling
- Dependencies: `sase>=0.1.0`, `python-telegram-bot>=21.0`
- Entry points under `[project.scripts]`:
  - `sase_chop_tg_outbound = "sase_telegram.scripts:sase_chop_tg_outbound"`
  - `sase_chop_tg_inbound = "sase_telegram.scripts:sase_chop_tg_inbound"`
- Tool config: ruff (same rules), mypy (same strictness), pytest (same options)
- `[tool.hatch.build.targets.wheel]` packages = `["src/sase_telegram"]`

### 2.3 Justfile

Identical to `sase-github/Justfile`.

### 2.4 credentials.py

- `get_bot_token()` -- runs `pass show telegram_sase_bot_token` via subprocess, caches result for session
- `get_chat_id()` -- reads `SASE_TELEGRAM_BOT_CHAT_ID` env var
- `get_bot_username()` -- reads `SASE_TELEGRAM_BOT_USERNAME` env var

### 2.5 telegram_client.py

Thin synchronous wrapper around `python-telegram-bot` (which is async internally). Methods:

- `send_message(chat_id, text, parse_mode, reply_markup)` -> message_id
- `send_document(chat_id, file_path, caption)` -> message_id
- `get_updates(offset, timeout)` -> list of Update objects
- `answer_callback_query(callback_query_id, text)` -- acknowledge button press
- `edit_message_reply_markup(chat_id, message_id, reply_markup)` -- remove buttons after action

Uses `asyncio.run()` to bridge sync chop scripts to async python-telegram-bot.

### 2.6 callback_data.py

Telegram inline keyboard buttons carry up to 64 bytes of `callback_data`. Encoding:

```
{action_type}:{notification_id_prefix}:{choice}
```

Examples:

- `plan:a1b2c3d4:approve` (plan approval)
- `plan:a1b2c3d4:reject` (plan rejection)
- `hitl:e5f6g7h8:accept` (HITL accept)
- `hitl:e5f6g7h8:reject` (HITL reject)
- `hitl:e5f6g7h8:feedback` (HITL reject with feedback -- triggers text prompt)
- `q:i9j0k1l2:0` (user question -- select option index 0)
- `q:i9j0k1l2:1` (user question -- select option index 1)
- `q:i9j0k1l2:other` (user question -- custom answer via text)

The notification ID prefix is the first 8 chars of the UUID (sufficient for practical uniqueness).

### 2.7 pending_actions.py

Persists `~/.sase/telegram/pending_actions.json` -- maps `notification_id_prefix` to the full notification data
(action_data dict, files, question data) needed to write response files on callback.

- `save_pending_action(notification: Notification, extra_data: dict | None)` -- store for later callback
- `load_pending_actions() -> dict[str, dict]` -- load all pending
- `remove_pending_action(prefix: str)` -- remove after handling
- `cleanup_stale(max_age_hours: int = 24)` -- remove expired entries (called at start of both chops)

### 2.8 rate_limit.py

Sliding window rate limiter using `~/.sase/telegram/rate_limit.json`:

- `check_rate_limit(window_seconds=10, max_messages=None) -> bool` -- True if sending allowed
- `record_send()` -- record a sent message timestamp
- Max messages default: 5 per 10-second window (configurable via `SASE_TELEGRAM_RATE_LIMIT` env var)
- Auto-prunes timestamps older than 10 minutes

### Verification

- `just check` passes in the new repo
- `just install` makes `sase_chop_tg_outbound` and `sase_chop_tg_inbound` available on PATH
- `python -c "from sase_telegram.credentials import get_bot_token; print(get_bot_token())"` succeeds

---

## Phase 3: Outbound Telegram Messages

**Repo**: `sase-telegram`

### 3.1 outbound.py -- Core logic

```python
LAST_SENT_FILE = "~/.sase/telegram/last_sent_ts"
INACTIVE_THRESHOLD_VAR = "SASE_TELEGRAM_INACTIVE_SECONDS"  # default 600

def should_send() -> bool:
    """True if user inactive >= threshold."""

def get_unsent_notifications() -> list[Notification]:
    """Notifications that are unread AND newer than last_sent_ts."""

def mark_sent(notifications: list[Notification]) -> None:
    """Update high-water mark to latest notification timestamp."""
```

**High-water mark**: `~/.sase/telegram/last_sent_ts` stores the ISO-8601 timestamp of the most recently sent
notification. On each tick, the outbound chop loads all notifications from the JSONL store, filters to those that are:

1. Not read (`read=False`)
2. Not dismissed (`dismissed=False`)
3. Have a timestamp newer than the stored high-water mark

If no file exists (first run), nothing is sent (avoids dumping backlog).

### 3.2 formatting.py -- Message formatting

Each notification type gets a distinct, beautiful Telegram message:

**PlanApproval** (`action="PlanApproval"`):

```
--- Message ---
📋 *Plan Ready for Review*
_Agent: {agent_cl_name}_

{plan_name}

{first 2000 chars of plan content in code block, or summary if too long}

--- Keyboard ---
[✅ Approve]  [❌ Reject]

--- Attachments ---
Plan file (if > 2000 chars, send full file as document)
```

**HITL** (`action="HITL"`):

```
--- Message ---
🔄 *Human\-in\-the\-Loop Request*
_Workflow: {workflow_name}_
_Step: {step_name} \({step_type}\)_

Output preview (from hitl_request.json, truncated)

--- Keyboard ---
[✅ Accept]  [❌ Reject]  [💬 Feedback]
```

**UserQuestion** (`action="UserQuestion"`):

```
--- Message ---
❓ *Agent Question*
_Agent: {agent_cl_name}_

{question text}

--- Keyboard ---
[Option A]  [Option B]  [Option C]  [✏️ Custom]

(one button per option from questions[0].options, plus "Custom" for free-text)
```

**Workflow Complete** (informational):

```
--- Message ---
✅ *Workflow Complete*
_Sender: {sender}_

{notes joined with newlines}

--- Attachments ---
Any files from notification.files
```

**Error Digest** (`sender="axe"`):

```
--- Message ---
⚠️ *Error Digest*

{notes text}

--- Attachments ---
Error digest file
```

**Generic** (sync result, etc.):

```
--- Message ---
📢 *{sender}*

{notes joined with newlines}
```

All text is escaped for Telegram MarkdownV2. The `formatting.py` module includes a `escape_markdown_v2(text)` helper.

### 3.3 sase_chop_tg_outbound.py -- Entry point

```python
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()
    read_chop_context(args.context)

    cleanup_stale()  # Clean old pending actions

    if not should_send():
        return

    unsent = get_unsent_notifications()
    if not unsent:
        return

    token = get_bot_token()
    chat_id = get_chat_id()
    client = TelegramClient(token)

    sent = []
    for notification in unsent:
        if not check_rate_limit():
            break  # Stop sending, will resume next tick

        text, keyboard, files = format_notification(notification)
        msg_id = client.send_message(chat_id, text, reply_markup=keyboard)
        record_send()

        for file_path in files:
            if not check_rate_limit():
                break
            client.send_document(chat_id, file_path)
            record_send()

        # Track actionable notifications for inbound callback handling
        if notification.action in ("PlanApproval", "HITL", "UserQuestion"):
            save_pending_action(notification, extra_data={"message_id": msg_id})

        sent.append(notification)

    if sent:
        mark_sent(sent)
```

For **UserQuestion**, the outbound chop also reads the `question_request.json` file (from `response_dir`) to get the
full question data (options, etc.) and stores it in the pending action so the inbound chop can construct the response.

### 3.4 Tests

- `test_formatting.py` -- unit tests for each notification type's formatting output
- `test_outbound.py` -- mock `load_notifications`, `get_tui_inactive_seconds`, verify send logic

### Verification

- Install package, add `tg_outbound` chop to heartbeats lumberjack in `sase_athena.yml`
- Create a test notification: `echo '{"action":"HITL"}' | .venv/bin/sase notify --sender test`
- Mark inactive: press `I` in sase ace
- Wait for heartbeat cycle -- verify Telegram message received with inline keyboard buttons

---

## Phase 4: Inbound Telegram Message Handling

**Repo**: `sase-telegram`

### 4.1 inbound.py -- Core logic

```python
OFFSET_FILE = "~/.sase/telegram/update_offset.txt"
AWAITING_FEEDBACK_FILE = "~/.sase/telegram/awaiting_feedback.json"

def get_last_offset() -> int
def save_offset(offset: int) -> None

def process_callback(query: CallbackQuery, pending: dict) -> bool:
    """Decode callback_data, look up pending action, write response file."""

def process_text_message(text: str) -> bool:
    """Check if we're awaiting feedback; if so, use text as feedback content."""
```

### 4.2 Response file formats (matching existing TUI handlers exactly)

**Plan approval** -- writes to `{response_dir}/plan_response.json`:

- Approve: `{"action": "approve"}`
- Reject: `{"action": "reject"}` (note: no feedback field means simple rejection)
- Reject with feedback: `{"action": "reject", "feedback": "user's text"}`

Matches `handle_plan_approval()` in `src/sase/ace/tui/actions/agents/_notification_actions.py:446-479`.

**HITL** -- writes to `{artifacts_dir}/hitl_response.json`:

- Accept: `{"action": "accept", "approved": true}`
- Reject: `{"action": "reject", "approved": false}`
- Feedback: `{"action": "feedback", "approved": false, "feedback": "user's text"}`

Matches `handle_hitl()` in `_notification_actions.py:284-298`.

**UserQuestion** -- writes to `{response_dir}/question_response.json`:

- Option selected:
  `{"answers": [{"question": "...", "selected": ["Option Label"], "custom_feedback": ""}], "global_note": "Answered via Telegram"}`
- Custom text:
  `{"answers": [{"question": "...", "selected": [], "custom_feedback": "user's text"}], "global_note": "Answered via Telegram"}`

Matches `handle_user_question()` in `_notification_actions.py:348-366`.

### 4.3 Feedback flow (two-step interaction)

When user taps "Feedback" on HITL or "Reject" on a plan (which could support feedback via a follow-up):

1. Outbound sends "Feedback" callback
2. Inbound receives callback, stores `{notif_prefix: action_info}` in `awaiting_feedback.json`, answers callback with
   "Send your feedback as a text message"
3. On next tick, if a text message arrived and `awaiting_feedback.json` has entries, the text is used as the feedback
   content and the response file is written

For plan rejection: "Reject" button does a simple rejection (matching TUI behavior where reject without feedback kills
the agent). If we want reject-with-feedback, we can add a separate "Reject + Feedback" button.

### 4.4 Post-action cleanup

After successfully handling a callback:

1. `answer_callback_query(callback_query_id, "Done!")` -- removes loading spinner in Telegram
2. `edit_message_reply_markup(chat_id, message_id, None)` -- removes inline keyboard buttons (prevents double-tap)
3. `remove_pending_action(prefix)` -- clean up pending state

### 4.5 sase_chop_tg_inbound.py -- Entry point

```python
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()
    read_chop_context(args.context)

    cleanup_stale()  # Clean old pending actions

    token = get_bot_token()
    client = TelegramClient(token)

    offset = get_last_offset()
    updates = client.get_updates(offset=offset, timeout=0)  # non-blocking poll

    if not updates:
        return

    pending = load_all_pending_actions()

    for update in updates:
        if update.callback_query:
            success = process_callback(update.callback_query, pending, client)
            if success:
                # Remove keyboard buttons from the message
                client.edit_message_reply_markup(
                    chat_id, update.callback_query.message.message_id, None
                )
        elif update.message and update.message.text:
            process_text_message(update.message.text)

    # Advance offset past all processed updates
    save_offset(updates[-1].update_id + 1)
```

### 4.6 Edge cases

- **Request file gone** (notification dismissed in TUI before Telegram response): Check if request file exists before
  writing response. If missing, answer callback with "This request has expired" and remove pending action.
- **Double-tap**: Removing the inline keyboard after first action prevents this. If somehow a duplicate arrives, the
  pending action is already removed, so it returns False.
- **Stale pending actions**: `cleanup_stale()` runs at start of both chops, removes entries older than 24 hours.

### 4.7 Tests

- `test_inbound.py` -- mock Telegram updates, verify correct response files are written
- `test_callback_data.py` -- encode/decode roundtrip tests

### Verification

- Send a plan approval notification to Telegram (via outbound chop)
- Tap "Approve" button in Telegram app
- Verify `plan_response.json` appears at the expected path with `{"action": "approve"}`
- Verify the plan_approve_handler picks it up and the agent continues

---

## Phase 5: Lumberjack Config + Integration + Polish

**Repos**: The chezmoi repo and `sase-telegram`

### 5.1 Lumberjack configuration

**File**: `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`

Add to the existing `heartbeats` lumberjack:

```yaml
heartbeats:
  interval: 60
  chops:
    - name: pylimit_split
      description: "Run the pylimit_split xprompt workflow"
      agent: "#gh:sase #pylimit_split %approve"
      run_every: 60
    - name: tg_outbound
      description: "Send unread notifications to Telegram when user is inactive"
    - name: tg_inbound
      description: "Process Telegram inline keyboard responses and text messages"
```

### 5.2 MarkdownV2 escaping

Telegram MarkdownV2 requires escaping: `_ * [ ] ( ) ~ ` > # + - = | { } . !`

The `formatting.py` module must include a robust `escape_markdown_v2()` function and use it on all user-generated
content (notification notes, plan file content, question text).

### 5.3 Large content handling

- Plan files > 4096 chars (Telegram message limit): Send first ~3000 chars as a message, attach full file as document
- Error digest files: Always attach as document, send summary in message text
- HITL output: Truncate in message, mention "see TUI for full output"

### 5.4 Integration testing

- Full outbound flow: create notification -> mark inactive -> heartbeat fires -> Telegram message received
- Full inbound flow: tap button in Telegram -> heartbeat fires -> response file written -> handler picks it up
- Rate limiting: send many notifications rapidly, verify rate limiter kicks in
- Edge case: dismiss notification in TUI, then tap button in Telegram -> "expired" response

### 5.5 CLAUDE.md for new repo

Create `CLAUDE.md` and `AGENTS.md` for the `sase-telegram` repo following the sase-github pattern.

### Verification

- `just check` passes in both repos
- End-to-end: run sase ace, trigger a plan notification, press `I`, wait for heartbeat, receive Telegram message, tap
  Approve, verify plan is approved and agent continues

---

## Key Files Reference

### sase core (to modify)

- `src/sase/ace/tui_activity.py` -- NEW: activity tracking module
- `src/sase/ace/tui/app.py` -- add `I` binding, init activity tracking
- `src/sase/ace/tui/actions/event_handlers.py` -- track keypress times, flush to disk
- Legacy public API whitelist -- register new public API methods

### sase core (reference only, do not modify)

- `src/sase/notifications/models.py` -- Notification dataclass
- `src/sase/notifications/store.py` -- JSONL storage with file locking
- `src/sase/notifications/senders.py` -- notification creation functions
- `src/sase/ace/tui/actions/agents/_notification_actions.py` -- response file format reference
- `src/sase/main/plan_approve_handler.py` -- plan response format reference
- `src/sase/main/user_question_handler.py` -- question response format reference
- `src/sase/axe/chop_script_context.py` -- chop context serialization

### sase-telegram (all new)

- `src/sase_telegram/credentials.py`
- `src/sase_telegram/telegram_client.py`
- `src/sase_telegram/callback_data.py`
- `src/sase_telegram/pending_actions.py`
- `src/sase_telegram/rate_limit.py`
- `src/sase_telegram/outbound.py`
- `src/sase_telegram/inbound.py`
- `src/sase_telegram/formatting.py`
- `src/sase_telegram/scripts/sase_chop_tg_outbound.py`
- `src/sase_telegram/scripts/sase_chop_tg_inbound.py`

### Config (to modify)

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` -- add chops to heartbeats lumberjack

### Template repos (reference for scaffolding)

- `sase-github/pyproject.toml`
- `sase-github/Justfile`
