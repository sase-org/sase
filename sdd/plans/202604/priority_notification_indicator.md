---
create_time: 2026-04-25 22:56:24
status: done
prompt: sdd/prompts/202604/priority_notification_indicator.md
---
# Priority-Aware Notification Indicator

## Problem

The TUI's `NotificationIndicator` widget treats all unread notifications uniformly:

- A single primary segment renders **gold** (`#FFD700`) when _any_ unread notifications exist.
- A secondary `·N` segment renders the count of muted-but-unread notifications.

This loses important signal. Some notification types — plan approvals, user questions, failed-agent runs, axe error
digests, mentor reviews, and CRS workflow results — are higher-priority and should pop visually relative to background
chatter (sync results, generic workflow completions, HITL prompts, etc.). Today the indicator looks the same whether the
unread queue is "5 sync notices" or "1 plan-approval blocker plus 4 sync notices".

The user also has no visual cue for the "everything is muted" state — when only muted notifications remain, the primary
segment goes dim and the muted secondary segment still renders, but nothing distinguishes "no unread anything" (full
calm) from "no _active_ unread, but muted backlog exists" (acknowledged but pending).

## Goals

1. **Red indicator** when there is at least one unmuted notification of a "priority" type (plan, question, failed agent,
   axe errors, mentor, CRS).
2. **Distinct color** when there are muted unread notifications and zero unmuted unread of any type.
3. **Split the count display**: show the priority count separately from the rest of the unmuted count, mirroring how the
   muted count is already displayed as a separate `·N` segment.

## Non-goals

- No changes to the notification storage model, sender APIs, or modal interaction.
- No changes to per-notification rendering inside the modal (the dim/gold rows added in commit `63679dad` stay as-is).
- No changes to toast routing or severity mapping in `_toasts.py` — those already use their own severity buckets.

## Defining "priority" notifications

The user listed six types. They map cleanly to existing notification fields:

| User term    | Mapping                                                    |
| ------------ | ---------------------------------------------------------- |
| plan         | `action == "PlanApproval"`                                 |
| question     | `action == "UserQuestion"`                                 |
| axe errors   | `sender == "axe"`                                          |
| mentor       | `action == "JumpToMentorReview"`                           |
| crs          | `sender == "crs"`                                          |
| failed agent | `sender == "user-agent"` AND `action == "ViewErrorReport"` |

Since "axe errors" and "failed agent" both use `action="ViewErrorReport"` but originate from different senders, the
classifier needs both `sender` and `action`. We'll centralize this as a single helper:

```python
# sase/notifications/priority.py  (new module)
def is_priority(n: Notification) -> bool:
    if n.action in {"PlanApproval", "UserQuestion", "JumpToMentorReview"}:
        return True
    if n.sender in {"axe", "crs"}:
        return True
    if n.sender == "user-agent" and n.action == "ViewErrorReport":
        return True
    return False
```

Living in `sase/notifications/` (not in the TUI layer) so it's reusable from any future surface (toasts, telegram,
metrics) without dragging in textual.

## Indicator visual design

### Counts

Three integers feed the indicator:

- `priority` — unmuted, unread, priority-type
- `rest` — unmuted, unread, non-priority-type
- `muted` — muted, unread (any type)

### Color states

The **primary segment color** is driven by these counts:

| State                                           | Primary color                            | Reasoning                               |
| ----------------------------------------------- | ---------------------------------------- | --------------------------------------- |
| `priority > 0`                                  | **Red** (`bold #1a1a1a on #FF4444`)      | Action-required; demand attention.      |
| `priority == 0` and `rest > 0`                  | **Gold** (`bold #1a1a1a on #FFD700`)     | Today's behavior; unchanged.            |
| `priority == 0` and `rest == 0` and `muted > 0` | **Dim cyan** (`bold #1a1a1a on #5FAFAF`) | Acknowledged backlog; calm but present. |
| All zero                                        | dim                                      | Today's behavior; unchanged.            |

The dim-cyan choice keeps the badge structurally identical (dark text on a soft background) so the muted-only state is
visibly _different_ from both "nothing" and "active", but reads as quiet rather than alarming. Final hex is open to
taste — happy to swap if you prefer a different color.

### Format

Today: `✉ {unread}` optionally followed by `·{muted} `.

Proposed: keep the envelope and muted secondary, but split the primary count into priority vs. rest:

```
 ✉ {priority}+{rest}   ·{muted}
```

Examples:

| priority | rest | muted | Renders    | Primary color   |
| -------- | ---- | ----- | ---------- | --------------- |
| 0        | 0    | 0     | `✉ 0`      | dim             |
| 0        | 3    | 0     | `✉ 0+3`    | gold            |
| 2        | 3    | 0     | `✉ 2+3`    | red             |
| 2        | 0    | 1     | `✉ 2+0 ·1` | red             |
| 0        | 0    | 4     | `✉ 0+0 ·4` | dim cyan        |
| 0        | 0    | 0     | `✉ 0`      | dim (collapsed) |

Suppression rules to keep the bar tidy:

- When _all_ of priority/rest/muted are zero, render the legacy `✉ 0` (no `+`, no `·`) — visually identical to today's
  empty state.
- When `priority + rest == 0` but `muted > 0`, still render `0+0` so the two-part format stays consistent across all
  non-empty states. (The muted-only color cue plus the `·N` segment carry the meaning.)
- The `·{muted} ` secondary segment continues to be suppressed when `muted == 0`, exactly as today.

Open question: do we want a different separator than `+` (e.g. `·`, `/`, `|`) to reduce visual collision with the
existing `·` muted separator? My default is `+` because it suggests "and these other ones too", but I'm flexible.

## Implementation plan

### Files to change

1. **`src/sase/notifications/__init__.py`** — re-export the new `is_priority` helper alongside `Notification`,
   `load_notifications`, etc.

2. **`src/sase/notifications/priority.py`** _(new)_ — define `is_priority(notification)` per the mapping above.

3. **`src/sase/ace/tui/widgets/notification_indicator.py`** — replace `set_counts(unread, muted)` with
   `set_counts(priority, rest, muted)`; rewrite `_build_content` to implement the color states and split format.
   `set_count` (legacy single-int wrapper) stays, calling `set_counts(0, count, 0)` for source compat.

4. **`src/sase/ace/tui/actions/agents/_notifications.py`** — split `unread_active` into `unread_priority` and
   `unread_rest` via `is_priority()` and pass three counts to `indicator.set_counts(...)`. Three call sites:
   `_poll_agent_completions`, `_refresh_notification_count`, `_refresh_notification_count_async`. The toast/bell logic
   that triggers on newly arrived unmuted notifications is unaffected (still keyed off `unread_priority + unread_rest`).

### Files NOT to change

- `src/sase/notifications/store.py`, `models.py`, `senders.py` — no schema changes needed.
- `src/sase/ace/tui/modals/notification_modal.py` — modal rendering is separate and unaffected.
- `src/sase/ace/tui/actions/agents/_toasts.py` — severity mapping is independent of the indicator color.

### Tests

Update `tests/test_notification_indicator.py`:

- Replace existing `_build_content(unread, muted)` cases with `_build_content(priority, rest, muted)` cases covering:
  - all-zero → `✉ 0` and dim style
  - rest-only → `✉ 0+3` and gold background
  - priority-only → `✉ 2+0` and red background
  - both unmuted → `✉ 2+3` and red background (priority dominates)
  - muted-only → `✉ 0+0 ·4` and dim-cyan background
  - priority + muted → `✉ 1+0 ·2` (red primary, dim secondary)
  - rest + muted → `✉ 0+2 ·1` (gold primary, dim secondary)

Add a small unit test for `is_priority`:

- new `tests/test_notification_priority.py` covering the six mapping rules plus a few negative cases (sync, hitl,
  user-agent + JumpToAgent which is _not_ priority since the agent succeeded).

No new tests needed in `_notifications.py` — the existing flow is still exercised via the modal/store tests.

## Risks & considerations

- **"Failed agent" scope**: my mapping treats only `sender="user-agent" + action="ViewErrorReport"` as a failed agent.
  Workflow runners (`user-workflow`), `fix-hook`, and `summarize-hook` also emit `ViewErrorReport` notifications on
  failure. If you want those to count as priority too, we can broaden to "any `ViewErrorReport`" — that subsumes axe
  too, and simplifies `is_priority`. Worth a quick decision before I code it.
- **`set_count` legacy wrapper**: only used by old call sites if any remain; can probably delete it once confirmed
  unused. I'll grep before removing.
- **Color accessibility**: `#FF4444` and `#FFD700` are both bright; users on high-contrast or colorblind themes may not
  distinguish them strongly. If this matters, we can supplement with a leading sigil (e.g., `! ✉` for priority vs `✉`
  alone for normal). I'd hold off unless you ask.
- **Footer/help docs**: the `?` help modal currently doesn't document the indicator semantics. I'll add a one-line
  description to keep the help-popup convention.
