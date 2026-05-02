---
create_time: 2026-04-24 14:37:31
status: done
prompt: sdd/prompts/202604/type_specific_toasts.md
---
# Plan: Type-Specific Toast Notifications in `sase ace` TUI

## Context / Motivation

Today, when one or more unread notifications land while the `sase ace` TUI is open, the auto-refresh loop fires a
generic toast:

> "1 new notification"

The user sees a flash but learns nothing useful — they still have to open the notification modal (`n`) to figure out
what actually happened. Given that every notification already carries structured identity data (`action`, sender,
`action_data`, `notes`), we can do far better: show a short, specific message per notification type (e.g. "Plan ready:
sase_plan_foo.md", "Claude asking a question on @sase-n.4", "Sync failed for feature/bar", "3 axe errors in the last
hour").

This improves three real workflows:

1. **Plan approvals** — user knows immediately that a plan is waiting (and which agent) without opening the modal.
2. **User questions** — user can decide whether to respond now or later without context-switching.
3. **Mixed batches** (e.g. overnight catch-up on auto-refresh) — user gets a concise, structured summary instead of "14
   new notifications".

## Current Implementation (what we have today)

Single point-of-truth for the toast: `src/sase/ace/tui/actions/agents/_notifications.py:34-55`

```python
def _poll_agent_completions(self) -> None:
    notifications = load_notifications()
    unread = [n for n in notifications if not n.read and not n.silent]
    unread_count = len(unread)

    if unread_count > self._last_unread_count:
        self._ring_tmux_bell()
        new_count = unread_count - self._last_unread_count
        self.notify(
            f"{new_count} new notification{'s' if new_count != 1 else ''}",
            severity="information",
            timeout=8,
        )

    self._last_unread_count = unread_count
    ...
```

Key facts:

- Polled every auto-refresh tick via `_on_auto_refresh` → `_poll_agent_completions`.
- "Newness" is detected only by integer count delta — we don't track which specific notifications are new.
- Severity is always `"information"`, even for things that block the user (plan approvals, questions, HITL).
- Silent notifications (`n.silent`) are already filtered out.

### Notification taxonomy (discovered, not built yet)

Defined by the `action` field on `Notification` + the `sender` that created it. See `src/sase/notifications/senders.py`:

| action             | sender     | Meaning                         | Natural severity |
| ------------------ | ---------- | ------------------------------- | ---------------- |
| `PlanApproval`     | `plan`     | Agent plan awaits user approval | warning          |
| `UserQuestion`     | `question` | Claude asking a question        | warning          |
| `HITL`             | `hitl`     | HITL step blocked on user input | warning          |
| `JumpToAgent`      | various    | Agent completed / status change | information      |
| `JumpToChangeSpec` | `sync`     | Sync result for a CL            | information      |
| `ViewErrorReport`  | `axe`      | Axe error digest                | error            |
| `Tmux`             | various    | Tmux-related action             | information      |
| `None`             | any        | Generic / legacy notification   | information      |

Each notification already carries enough structured data to render a specific toast line:

- `notes[0]` is a short human-readable string authored by the sender (e.g. "Plan ready for review: sase_plan_foo.md",
  "Sync success for bar", "3 error(s) in the last hour", "HITL waiting: step 'confirm' in deploy").
- `action_data["agent_name"]` / `action_data["agent_cl_name"]` identify the originating agent, when applicable.

## Design

### Guiding principles

1. **Specific over clever.** Prefer short, literal toast text over cutesy formatting. The toast is a preview, not a
   replacement for the notification modal.
2. **Don't duplicate data.** Reuse `notes[0]` authored by the sender as the base of the toast whenever possible —
   senders already craft these for human consumption. Layer on the agent / CL identity only when helpful.
3. **Severity reflects urgency.** Things blocked on the user (plan, question, HITL) are `warning`. Errors are `error`.
   Everything else is `information`. This is a visible, meaningful change, not decoration.
4. **Respect existing behavior.** Silent notifications stay suppressed. Tmux bell still rings. The unread indicator
   still updates. The `_apply_notification_status_overrides` call still happens.

### Identifying which notifications are new

Count-delta alone isn't enough once we want per-notification text. We need to know _which_ notifications are new, not
just how many.

Replace `self._last_unread_count: int` with `self._last_unread_ids: set[str]` (notification ids). On each poll:

```python
current_ids = {n.id for n in unread}
new_ids = current_ids - self._last_unread_ids
new_notifications = [n for n in unread if n.id in new_ids]
```

- `_initialize_agent_tracking` in `src/sase/ace/tui/actions/lifecycle.py` seeds the set from the initial unread
  notifications.
- `_refresh_notification_count` (used after external dismissals) must also be updated to replace the set rather than
  just the count.
- The `NotificationIndicator.set_count(...)` call continues to use `len(unread)`.

### Toast content

Introduce a small pure helper (new module, `src/sase/ace/tui/actions/agents/_toasts.py`) to keep the mapping centralized
and testable:

```python
def format_notification_toast(n: Notification) -> tuple[str, Severity]:
    """Return (message, severity) for a single new notification."""
```

Per-type formatting rules (all fall back to `notes[0]` when identity fields are missing):

- **PlanApproval**: `"Plan ready for @{agent_name}: {plan_filename}"` severity `warning`. Falls back to `notes[0]` if no
  `agent_name`.
- **UserQuestion**: `"Question from @{agent_name}: {short_note}"` severity `warning`. `short_note` is `notes[0]`
  truncated to ~60 chars.
- **HITL**: `notes[0]` unchanged (already a useful one-liner), severity `warning`.
- **ViewErrorReport**: `"Axe: {notes[0]}"` severity `error`.
- **JumpToChangeSpec** (sync): `notes[0]`, severity `information` (or `error` if the note starts with "Sync fail").
- **JumpToAgent**: `notes[0]`, severity derived from "success"/"fail" keywords in the note if present, else
  `information`.
- **Tmux** / `None` / unknown actions: `notes[0]` if non-empty else the current `"New notification"` placeholder;
  severity `information`.

### Batching behavior

Emitting N independent `self.notify(...)` calls in rapid succession is fine for 1–3 notifications — Textual stacks
toasts and we want to see all of them.

For larger batches we consolidate to avoid spam. Proposed policy:

- **1–3 new:** one toast per notification (using `format_notification_toast`).
- **4+ new:** a single grouped toast per severity level, e.g. `"3 warnings: 2 plans, 1 question"`,
  `"5 new notifications"`. The grouping key is the action category (plan/question/hitl/error/info).

This keeps the common case specific without turning a bulk backfill into a wall of toasts.

### Timeout

Keep the existing `timeout=8`. Blocking notifications (`warning`/`error`) might warrant longer, but we won't adjust that
here — Textual's default notification tray already keeps recent toasts visible on hover, and the unread indicator plus
modal remain the source of truth.

## Scope / Non-goals

In scope:

- New toast formatter helper + tests.
- Track unread notification ids as a set instead of an integer count.
- Wire the formatter into `_poll_agent_completions`.
- Update `_initialize_agent_tracking` and `_refresh_notification_count` to maintain the new set-based tracker.
- Unit tests covering formatter rules, single/multiple toast emission, and set-based new-detection.

Out of scope (intentionally):

- Changing the `Notification` dataclass (no new fields). The existing `notes`/`action`/`action_data` payload is
  sufficient.
- Changing sender functions — they already author useful `notes[0]` strings. Polishing those can happen later,
  per-sender, as needed.
- Reworking the notification modal / indicator widget.
- Rate-limiting or deduplicating toasts across polling cycles beyond the "track seen ids" logic already implied by the
  design.
- Time-window batching (we batch per poll cycle only).

## Files to change

1. `src/sase/ace/tui/actions/agents/_notifications.py` — replace count-based tracker with id-set tracker; call the new
   formatter; apply the batching policy.
2. `src/sase/ace/tui/actions/agents/_toasts.py` — **new file**, pure formatter helper + severity classification.
3. `src/sase/ace/tui/actions/lifecycle.py` — seed `_last_unread_ids` from the initial load.
4. `src/sase/ace/tui/app.py` — update the attribute declaration on the app class (replace `_last_unread_count` with
   `_last_unread_ids`, or keep both if `_last_unread_count` is referenced elsewhere — to be confirmed during
   implementation).
5. `tests/test_notification_toasts.py` — **new file**, unit tests for the formatter and for the polling delta logic
   (with `load_notifications` mocked).

## Risks & mitigations

- **Attribute churn on `AceApp`**: if `_last_unread_count` is read outside the notifications mixin, leave it as a
  derived property (`len(self._last_unread_ids)`) to avoid a wider refactor.
- **Toast text overflow**: Textual truncates, but we'll cap `notes[0]` to a sensible length in the formatter to keep the
  toast legible.
- **Regression on status overrides**: `_apply_notification_status_overrides` operates on the full `unread` list,
  independent of the delta logic, so changing the tracker type doesn't affect it.
- **Missing `action_data` fields**: formatter always falls back to `notes[0]`, so a sender that omits optional identity
  keys still produces a reasonable toast.

## Test plan

- `format_notification_toast` covers each action type, including missing `action_data`, empty `notes`, and unknown
  action strings.
- Polling helper, with `load_notifications` patched:
  - No new ids → no `notify` call, no bell.
  - One new PlanApproval → one `warning` toast, bell rings.
  - Two new mixed → two toasts.
  - Five new mixed → one grouped toast (1 per severity bucket).
  - Silent notifications never produce toasts regardless of count.
- `_refresh_notification_count` correctly rebuilds the id set after an external dismissal.

## Open questions (flag, don't block)

- Do we want the **grouped** toast line (>=4 notifications) to break down by **sender** (e.g. "2 plan, 1 sync, 1 axe")
  or by **severity bucket** (as proposed)? Severity is simpler and matches the styling, so we'll start there and iterate
  if the user wants finer grain.
- Should blocking notifications (plan/question) bypass the batching policy even in large batches, so the user always
  sees them individually? Tentatively: **yes** — ship the simpler policy first, revisit if overnight batches actually
  drown them out.
