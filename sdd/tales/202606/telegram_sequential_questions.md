---
create_time: 2026-06-26 19:12:41
status: done
prompt: sdd/prompts/202606/telegram_sequential_questions.md
---
# Plan: Sequential, Numbered Multi-Question Delivery over Telegram

## Summary

When a SASE agent asks several questions at once (`sase questions` with a multi-element list), the Telegram integration
today surfaces **only the first question** and, the moment the user taps an answer, writes the final response — silently
leaving questions 2..N unanswered. This plan makes Telegram walk the user through **one question at a time**: answer
question 1, the next question message arrives, and so on, until every question is answered. Each message is clearly
numbered (`Question 2 of 3`) so the user always knows where they are and how many remain. Only after the last question
is answered do we write the single `question_response.json` the agent is waiting on.

This is purely a **Telegram-transport presentation** change. The shared question request/response contract (consumed by
the TUI, mobile, and the agent runner) is unchanged — the final response we write is byte-compatible with what the TUI
writes today. No Rust core or main-`sase` runner changes are required.

## Background: how questions flow today

1. The agent calls `sase questions '<json>'`. The runner (`sase` repo:
   `src/sase/axe/run_agent_helpers_questions.py::handle_questions_flow`) creates a per-session `response_dir` under
   `~/.sase/user_question/<id>/`, writes `question_request.json` (the full `questions` list), emits a `UserQuestion`
   notification, and then **blocks polling for `question_response.json`**.
2. The Telegram **outbound** chop (`sase-telegram` repo: `scripts/sase_tg_outbound.py`) picks up the idle notification
   and calls `formatting.format_notification` → `_format_user_question`, which renders a message with one inline button
   per option **of `questions[0]` only**, plus a `💬 Custom` button. It records a pending action keyed by the 8-char
   notification prefix, storing the sent `message_id`/`chat_id`.
3. The Telegram **inbound** chop (`sase-telegram` repo: `scripts/sase_tg_inbound.py::_handle_callback`) decodes the
   button tap and calls `inbound.process_callback`, which immediately writes `question_response.json` containing a
   **single answer** and a fixed `global_note: "Answered via Telegram"`. The agent's poll loop unblocks and treats the
   session as fully answered.

The defect lives at two points, both in the `sase-telegram` repo:

- `formatting.py::_format_user_question` — only ever reads `questions[0]`.
- `inbound.py::process_callback` / `process_callback_twostep` / `process_text_message` (the `question` branches) — each
  resolves the whole session from one interaction. `_get_question_info` / `_get_question_text` likewise hard-code
  `questions[0]`.

The expected response shape (what the TUI writes and the runner consumes, via `sase` repo
`src/sase/main/qa_markdown.py` + `run_agent_helpers_questions.py::build_qa_round`) is:

```json
{
  "answers": [{ "question": "...", "selected": ["Label"], "custom_feedback": null }],
  "global_note": "..."
}
```

`answers` is index-aligned to `questions`. Our end state must produce one entry per question, in order — which is
exactly what the TUI already produces.

## Goals

- Deliver every question in a multi-question request, **one Telegram message at a time**, advancing only after the
  current question is answered.
- **Number every question clearly** (`Question 2 of 3`) so the count and position are unambiguous.
- Accumulate answers and write **one** final `question_response.json` (full, index-aligned `answers`) only when the last
  question is answered — preserving the agent contract exactly.
- Keep it **intuitive** (single-select still answers in one tap), **reliable** (no lost answers, no answers recorded
  against the wrong question, graceful behaviour when the session is resolved elsewhere), and **beautiful** (answered
  questions visibly collapse to show the chosen answer; a tidy completion summary closes the flow).
- Preserve today's single-question UX exactly (no `1 of 1` noise; one tap writes the response).

## Non-goals

- No change to the question request/response JSON contract, the agent runner, or the TUI modal. (The TUI already handles
  multi-question natively.)
- No new "global note" UI in Telegram — the final `global_note` stays the constant `"Answered via Telegram"` (a
  per-question `💬 Custom` free-text answer covers steering needs).
- No attempt to keep a half-finished Telegram sequence and a separately-opened TUI modal perfectly in sync (last writer
  wins — see Reliability).

## Design overview

Introduce a small amount of **per-session progress state** that lives alongside the request, plus a **single shared
question renderer** used by both the first message (outbound) and every subsequent message (inbound), so the two code
paths can never drift.

The interaction becomes a little state machine driven by Telegram callbacks:

```
            ┌─────────────── tap option (single-select) ───────────────┐
            │                                                           ▼
   render Q_i  ──tap option (multi-select)──►  toggle & re-render Q_i   record answer for Q_i
   (i of N)     ──tap 💬 Custom──► await text ─► record custom for Q_i ─►   │
            ▲                                                           │
            └──────────  more questions? send Q_{i+1}  ◄───────────────┤
                                                                        │
                                         last question?  write final ──►  question_response.json
                                                          + completion summary
```

The agent's blocking poll only ever sees `question_response.json`, which we write exactly once, at the end. The
intermediate progress file is Telegram-private.

### Per-session progress state

New file `question_progress.json` written **inside the existing `response_dir`** (next to `question_request.json`).
Keeping it in `response_dir` means it is session-scoped, naturally isolated across concurrent question sessions,
reachable from any callback (the pending action carries `response_dir`), and invisible to the runner's poll loop (which
only watches `question_response.json`).

Conceptual shape:

```json
{
  "session_id": "...",
  "total": 3,
  "current_index": 1,
  "answers": [{ "question": "...", "selected": ["A"], "custom_feedback": null }],
  "pending_selection": ["B"],
  "active_message_id": 4521,
  "chat_id": "..."
}
```

- `answers` holds the completed answers for questions `0..current_index-1`.
- `pending_selection` is the in-progress multi-select toggle state for the current question (empty for single-select).
- `active_message_id` is the message that currently owns the live keyboard. It is the **stale-tap guard**: a callback
  whose originating message id ≠ `active_message_id` is ignored (answered "already answered"). This closes the race
  where a user taps an older question's buttons after we've moved on, even if the keyboard-removal edit failed.

Progress is initialized lazily by inbound on the first callback (defaults: `current_index=0`, `answers=[]`,
`total=len(questions)`, `active_message_id=` the tapped message's id), so **outbound needs no knowledge of the progress
file** — its only change is rendering.

### Single shared renderer (the no-drift guarantee)

Add a canonical renderer in `sase-telegram` `formatting.py`:

- `render_question_message(question, *, index, total, selected, prefix) -> (text, InlineKeyboardMarkup)` — builds the
  numbered message + buttons for one question. Used by `_format_user_question` (for the first question, index 0) **and**
  by the inbound advance path (questions 1..N-1). One renderer, one look.
- `format_answered_question(question, *, index, total, selected, custom_feedback) -> text` — the collapsed "answered"
  text we edit the message into.
- `format_questions_complete(answers) -> text` — the final confirmation summary.

Numbering rule: when `total == 1`, omit the `N of N` prefix (exactly today's look). When `total > 1`, prefix with
`Question {index+1} of {total}`.

### Pure decision logic

Add `sase-telegram` `question_flow.py` — **pure**, no Telegram API calls (mirrors how `inbound.py` keeps decode/state
logic free of I/O). It owns the progress dataclass + load/save/clear helpers and two decision functions:

- `apply_question_choice(request, progress, choice)` — given a decoded button choice (an option index, `custom`, or
  `submit`), returns one of:
  - **Toggle** (multi-select option flipped → new `pending_selection`, re-render current question),
  - **AwaitCustom** (user chose `💬 Custom` → start the two-step text flow for the current question),
  - **Advance** (current question answered → recorded answer + the next index to render),
  - **Complete** (last question answered → the full final `response_data`).
- `apply_question_custom_text(request, progress, text)` — completes a `💬 Custom` free-text answer for the current
  question, returning **Advance** or **Complete** just like a button answer.

These return _data_; the inbound script performs all Telegram side effects (send/edit/answer) and file writes. This
keeps the logic exhaustively unit testable without a bot.

### Inbound orchestration

In `scripts/sase_tg_inbound.py`:

- `_handle_callback`: after the existing kill/retry/bead and already-resolved guards, route `action_type == "question"`
  callbacks to a new `_handle_question_callback`, which:
  1. Loads `question_request.json` + progress (initializing progress if absent).
  2. Applies the stale-tap guard (`active_message_id`) and the already-resolved guard (if `question_response.json`
     already exists, dismiss the keyboard and stop).
  3. Calls `question_flow.apply_question_choice` and acts on the result:
     - **Toggle**: `edit_message_reply_markup` (or re-render) to reflect the new checkbox state; persist
       `pending_selection`.
     - **AwaitCustom**: save awaiting-feedback keyed by `active_message_id` (reusing the existing two-step machinery),
       prompt "Send your answer as a text message", chop the keyboard.
     - **Advance**: edit the current message into its `format_answered_question` form (keyboard removed), `send_message`
       the next question via the shared renderer, then update progress (`current_index += 1`, append answer, new
       `active_message_id`, reset `pending_selection`) **and** update the pending action's stored `message_id` to the
       new message.
     - **Complete**: edit the final question into its answered form, write `question_response.json`, send the
       `format_questions_complete` summary, remove the pending action, and clear progress.
- `_handle_text_message`: the `question`-type two-step completion must route through `apply_question_custom_text`
  (record custom answer for the current question, then Advance or Complete) instead of the current path that writes the
  final response immediately.

`inbound.py` changes: generalize `_get_question_info`/`_get_question_text` to the current question index (or fold them
into `question_flow`), and remove the "resolve everything in one shot" behaviour from the `question` branches of
`process_callback` / `process_callback_twostep` / `process_text_message` in favor of the progress-aware path. The
non-question branches (plan, hitl) are untouched.

### Outbound

`scripts/sase_tg_outbound.py` is essentially unchanged: it keeps sending the first `UserQuestion` message and recording
the pending action. The only behavioural change rides in `_format_user_question`, which now renders the first question
(index 0) through the shared renderer rather than dumping the multi-question summary. Outbound stays idle-gated as today
(Telegram is the away-channel; if the user is active the TUI owns the flow).

### One small client addition

`telegram_client.py` exposes `send_message`, `answer_callback_query`, `edit_message_reply_markup`, but not text editing.
Add a thin `edit_message_text` wrapper (Bot API `editMessageText`, same retry/escape conventions as the existing
wrappers) so answered questions can visibly collapse to show the chosen answer. If we decide editing text is
undesirable, the fallback is to only chop the keyboard — but the in-place collapse is what makes the transcript clean
and is the recommended path.

## Visual / UX design

**Live question (multi-select example), `Question 2 of 3`:**

```
❓ Question 2 of 3

Which databases should we support?

[ ☑️ PostgreSQL ]
[ ⬜ SQLite ]
[ ⬜ MySQL ]
[ ✅ Submit ]   [ 💬 Custom ]
```

Single-select questions render the same header but each option is a one-tap answer (no Submit row) — preserving today's
instant-answer feel.

**After answering (message collapses in place, keyboard removed):**

```
✅ Question 2 of 3 · PostgreSQL, MySQL

Which databases should we support?
```

**Completion summary after the last answer:**

```
✅ All 3 questions answered
1. PostgreSQL, MySQL
2. Yes
3. “use the new migration tool” (custom)
```

The numbering, the in-place collapse, and the closing summary together make the flow feel guided and finished rather
than a one-shot button press.

## Files to change

`sase-telegram` repo (primary):

- `src/sase_telegram/question_flow.py` — **new**: progress dataclass + load/save/clear, `apply_question_choice`,
  `apply_question_custom_text`.
- `src/sase_telegram/formatting.py` — add `render_question_message`, `format_answered_question`,
  `format_questions_complete`; refactor `_format_user_question` to render question 0 via the shared renderer with
  numbering.
- `src/sase_telegram/inbound.py` — generalize question helpers to the current index; retire the single-shot `question`
  resolution paths in favor of the progress-aware flow; add a `submit` choice for multi-select.
- `src/sase_telegram/callback_data.py` — accommodate the `submit` choice (no format change; the existing 3-field
  encoding already fits).
- `src/sase_telegram/scripts/sase_tg_inbound.py` — `_handle_question_callback` dispatch in `_handle_callback`; route
  question two-step text completion in `_handle_text_message`; update pending `message_id` on advance.
- `src/sase_telegram/telegram_client.py` — add `edit_message_text`.
- `tests/` — `test_question_flow.py` (new, exhaustive state-machine coverage), plus extensions to `test_inbound.py` and
  `test_formatting.py`.

`sase` repo: none expected. (If we want richer first-message context we _could_ adjust the `q_summary`/notes built in
`run_agent_helpers_questions.py`, but it is not required — the renderer reads the request file directly.)

## Edge cases & reliability

- **Single question (N=1):** Advance == Complete on the first answer; render without numbering. Byte-identical outcome
  to today.
- **Stale taps:** Guarded by `active_message_id` (ignore + "already answered"). Keyboards are also chopped on advance,
  so stale buttons normally vanish.
- **Resolved elsewhere (TUI/CLI/mobile/auto-approve):** Before sending the next question, check for an existing
  `question_response.json` (and reuse the existing shared-store `already_handled`/`stale` guards). If resolved, dismiss
  the keyboard and stop. The existing `find_externally_handled` cleanup chops the _current_ active message because we
  keep the pending `message_id` current.
- **Free-text mid-sequence:** `💬 Custom` records `custom_feedback` for the current question and advances; only the last
  question's custom text completes the session.
- **No-options question:** Renders with just `💬 Custom` (free-text only) — works through the same two-step path.
- **Multi-surface race (half-finished Telegram sequence + freshly opened TUI modal):** The TUI shows all N questions
  and, on submit, writes a full response; Telegram's partial progress is discarded (last writer wins). Documented as an
  accepted limitation; the agent never double-resolves because its poll returns on the first `question_response.json`
  and the runner unlinks its pending marker.
- **Concurrent question sessions:** Isolated by `response_dir` (progress file) and notification prefix (pending action).
  No shared mutable state.
- **Crash/restart between questions:** Progress is on disk; the next inbound tick resumes from `current_index`. Stale
  sessions age out via the existing 24-hour pending-action cleanup and `response_dir` lifecycle.

## Testing

- **`question_flow` unit tests (new):** the full state machine — single vs multi-select; toggle on/off; submit; custom
  button → await → text; advance vs complete; index alignment of the final `answers`; N=1 parity; stale-tap and
  already-resolved guards; resume-from-disk.
- **`formatting` tests:** numbering (`2 of 3`, omitted at `1 of 1`); multi-select checkbox rendering and Submit row
  presence; answered-collapse text; completion summary; MarkdownV2 escaping of question/option text.
- **`inbound`/script tests:** extend existing `test_inbound.py` question cases — a multi-question session walks Q1→Q2→Q3
  producing one final response with three aligned answers; `message_id` is updated on advance; keyboard chop on
  advance/complete; existing single-question tests updated to the new path with unchanged outcomes.
- Run the `sase-telegram` repo's own `just`/pytest suite for the changed package.

## Rollout / scope

- **Phase 1 — sequential core:** progress state, shared renderer + numbering, inbound advance/complete,
  `_format_user_question` refactor, completion summary, `edit_message_text`. This alone fully satisfies the request for
  single-select and free-text questions.
- **Phase 2 — multi-select correctness:** toggle + Submit handling (fixes the pre-existing gap where a multi-select
  question could only capture one selection). Builds directly on Phase 1's progress + renderer plumbing; can ship in the
  same change or as an immediate fast-follow.

Both phases are confined to the `sase-telegram` plugin; no contract, runner, or core changes.
