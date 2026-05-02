---
create_time: 2026-04-25 22:44:56
status: done
prompt: sdd/prompts/202604/notification_mute_1.md
---
# Plan: Mute / Unmute Notifications in the Notification Panel

## Problem

The notification indicator (gold pill in the TUI header) draws attention to _every_ unread notification, even ones the
user already knows about and doesn't care to act on. Today the user has only two coarse choices: dismiss it (loses the
entry entirely) or mark it read (visually identical to ones they read intentionally). They want a third option — keep it
visible in the panel for reference, but stop it from contributing to the urgent unread count that drives the indicator.

We also want the indicator to be _honest_: if the user has muted three notifications, the indicator should still tell
them that, just in a quieter way. Otherwise muting feels like the notification "disappeared" and the user loses trust in
the indicator as their source of truth.

## Goals

1. **Visible-but-quiet:** Muted notifications still appear in the notification panel, exactly where they were.
2. **Indicator is honest:** The gold pill only lights up for non-muted unread, _and_ shows a dim secondary count of
   muted unread alongside it so muted items aren't invisible.
3. **One key to flip it.** Toggling mute is a single keystroke in the notification modal — same ergonomic class as `x`
   (dismiss) and `R` (read all).
4. **Visually obvious, not noisy.** A muted row is recognizable at a glance without making the panel look busy.
5. **Reliable across restarts.** Muted state lives in the existing JSONL store and survives reloads, just like `read` /
   `dismissed` / `silent`.

## Non-Goals (v1)

- **Bulk "mute all unread"** — defer until users actually ask for it. Easy to add later (mirrors `R` / `mark_all_read`).
- **Per-sender or pattern-based mute rules** — auto-muting future notifications matching a sender/regex is a separate
  feature with its own design surface (config, precedence, undo). Per-notification mute does not block it.
- **CLI entry point** (`sase notification mute <id>`) — the TUI is the only surface for v1.
- **Toast/bell suppression changes** — mute applies to a notification that has _already arrived_; the toast already
  fired. (`silent=True` continues to handle the "don't toast in the first place" case.)
- **A muted-only filter view** in the panel. Muted rows live alongside unread ones.

## Design

### Mental model

There are now four orthogonal per-notification flags, and the design keeps them orthogonal:

| Flag        | Meaning                                                  | In panel? | In unread count? | Toast on arrival? |
| ----------- | -------------------------------------------------------- | --------- | ---------------- | ----------------- |
| `read`      | User has seen it                                         | hidden¹   | excludes         | n/a (post hoc)    |
| `dismissed` | User threw it away                                       | hidden    | excludes         | n/a (post hoc)    |
| `silent`    | Sender requested no toast/bell on arrival                | hidden    | excludes         | suppresses        |
| **`muted`** | User downgraded it — stays visible, doesn't ping anymore | **shown** | **excludes**     | n/a (post hoc)    |

¹ The notification panel today filters with `not n.read and not n.silent`, so read notifications don't appear. Mute is
orthogonal — a muted-then-read notification is read-first (filtered out).

The new flag is the user-driven analogue of `silent` (which is sender-driven). Both keep the notification visible-ish
but quiet the indicator. `read` and `muted` are intentionally orthogonal — unmuting a notification puts it back into the
unread pool if the user never actually looked at it.

### Indicator design (the headline change vs. v1)

Today's indicator is a single gold pill: `✉ {n}` — bold black-on-gold when `n > 0`, dim when `n == 0`.

New rendering shows two counts side by side, but only when there's something to show:

```
unread=0, muted=0    →    ✉ 0                   (existing dim style)
unread=5, muted=0    →    ✉ 5                   (existing bold gold style)
unread=0, muted=2    →    ✉ 0   ·2              (dim ✉ 0 + dim secondary)
unread=5, muted=2    →    ✉ 5   ·2              (bold gold ✉ 5 + dim secondary)
```

Concretely, the widget builds a single `rich.Text` with two appended segments:

- **Primary segment** — `✉ {unread}` with the existing styling rules (bold black-on-gold when `unread > 0`, dim when
  `0`).
- **Secondary segment** — `·{muted}` appended only when `muted > 0`, always rendered dim. The `·` (middle dot) is a
  deliberately quiet glyph: it doesn't compete with the envelope, doesn't read as urgent, and is ASCII-adjacent enough
  to render reliably. (Plain emoji 🔕 was considered but width-and-rendering across terminals is unreliable; the dot is
  a safer choice.)

Why two segments rather than a combined number like `✉ 5 (2 muted)`:

- The user said it themselves — _alongside_, not _added to_. Combining them re-introduces the dishonesty mute is meant
  to fix.
- Bold-on-dim is a stronger visual hierarchy than parentheses. The eye lands on the gold count first, then the dim count
  second.
- The secondary segment is suppressed entirely when `muted == 0`, so non-mute users never see new chrome.

The widget gains a new method `set_counts(unread: int, muted: int)`. The existing `set_count(unread)` is kept as a
one-line wrapper that calls `set_counts(unread, 0)`, so any caller we miss continues to work and tests remain
backward-compatible.

### Visual treatment in the panel

The row currently uses a bold gold `* ` prefix to scream _unread_. Muted should read as the _opposite_: still there, but
hushed. Treatment:

|                   | Prefix      | Row style |
| ----------------- | ----------- | --------- |
| Unread, not muted | `* ` (gold) | normal    |
| Unread, muted     | `~ ` (dim)  | dim       |
| Read, not muted   | `  ` (none) | normal    |
| Read, muted       | `~ ` (dim)  | dim       |

Why a tilde, not an emoji or a `[muted]` suffix:

- It pairs visually with the existing `*` (asterisk = "look at me", tilde = "wave / quiet"), so the two states feel like
  siblings instead of competing styles.
- ASCII-only matches the tone of the rest of the panel — no glyph churn between systems / fonts.
- It survives both unread _and_ read states without making the row look like an error or a strikethrough.

The dim row style does the heavy lifting; the tilde is a small marker that makes mute legible even when the user is
scanning quickly. No suffix tag, no extra color — every additional bit of chrome is one more thing for the eye to parse,
and the goal is _quiet_.

### Keybinding

Add `m` → toggle mute on the highlighted notification. Single key for both directions because:

- It's symmetric with how `x` / `R` work (one key, one effect).
- Separate `m` / `M` for mute / unmute would force the user to track _current_ state before pressing — exactly the
  cognitive load mute is supposed to remove.
- `m` is unused by current modal bindings (`x`, `y`, `n`, `e`, `R`, `ctrl+n/p/d/u`).

The action method:

1. Reads the highlighted notification's current `muted`.
2. Calls the store with the toggled value.
3. Rebuilds the list so the new prefix / dim style is reflected immediately.
4. Keeps highlight on the same row (don't jump the user — they're often muting a streak).
5. Fires a small `self.notify("Muted")` / `"Unmuted"` toast for confirmation.

The modal's inline hints `Label` (`#notification-hints`, line 99 of `notification_modal.py`) gains `m: mute`.

### Counting

Two derived counts replace the single existing `unread_count`:

```python
unread_active = [n for n in notifications if not n.read and not n.silent and not n.muted]
unread_muted  = [n for n in notifications if not n.read and not n.silent and     n.muted]
indicator.set_counts(len(unread_active), len(unread_muted))
```

Apply this everywhere a count is computed today:

- `_poll_agent_completions` (`src/sase/ace/tui/actions/agents/_notifications.py:34`)
- `_refresh_notification_count` (same file, ~line 223)
- `_refresh_notification_count_async` (same file, ~line 244)
- The unread-id seed set in `src/sase/ace/tui/actions/lifecycle.py:40`

The toast-and-bell trigger continues to fire for **newly arrived** notifications. Specifically: `new_notifications` is
computed against the active-unread set (not the muted-unread set), so a notification that somehow arrives muted from day
one wouldn't toast — and equally, muting an existing notification doesn't retroactively un-toast it.

## Reliability

- **Persistence:** muted state goes through the same fcntl-locked JSONL writer as `read` / `dismissed`. No new storage
  surface, no new failure modes.
- **Default:** `muted=False` for new notifications. Old JSONL entries without the field load as `muted=False` via
  `data.get("muted", False)` in `_notification_from_dict` (no migration needed).
- **Idempotency:** the store API takes the desired end state (`mark_muted(id, muted=True/False)`), so toggling is a
  single read-decide-write performed by the modal. Calling `mark_muted` with the value already on disk is a no-op write
  that's still safe under the lock.
- **Concurrency:** if a background process appends a new notification mid-mute, the exclusive lock around the load /
  mutate / rewrite cycle prevents loss — same guarantee `mark_dismissed` provides today.
- **Orthogonality:** because `muted` doesn't touch `read` or `dismissed`, there's no state-machine to keep consistent. A
  muted-then-dismissed notification is just dismissed (filtered out at load); a muted-then-read notification is just
  read-and-muted.

## Edge cases

- **Read-all (`R`)**: marks every visible notification read. After `R`, both the unread count and the muted-unread count
  drop to zero, and the indicator collapses to the dim `✉ 0` form. No special handling needed.
- **Dismiss (`x`)**: independent of mute. Dismissing a muted notification removes it from disk like any other.
- **Plan/Question notifications**: mutable. Muting one doesn't bypass the y/n confirm flow on dismiss, and doesn't
  affect the agent status override scan in `_apply_notification_status_overrides`. That scan iterates over `unread`
  today; we'll change it to iterate over the union (active + muted) so PLANNING / QUESTION status overrides keep firing
  regardless of mute. (Muting should quiet the indicator, not break the agent's lifecycle.)
- **External response auto-dismiss** (Telegram-approved plans): unaffected — auto-dismiss runs over all unread,
  independent of mute.

## Files Changed

| File                                                     | Change                                                                                                                                         |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/notifications/models.py`                       | Add `muted: bool = False` to `Notification`.                                                                                                   |
| `src/sase/notifications/store.py`                        | Read `muted` in `_notification_from_dict`; add `mark_muted(id, muted: bool = True) -> bool`.                                                   |
| `src/sase/notifications/__init__.py`                     | Export `mark_muted`.                                                                                                                           |
| `src/sase/ace/tui/widgets/notification_indicator.py`     | New `set_counts(unread, muted)`; render two-segment Text; keep `set_count` as wrapper.                                                         |
| `src/sase/ace/tui/actions/agents/_notifications.py`      | Compute active-unread and muted-unread; pass both to indicator; toast/bell only on active-unread arrivals; pass union to status-override scan. |
| `src/sase/ace/tui/actions/lifecycle.py`                  | Update unread-id seed set to exclude muted.                                                                                                    |
| `src/sase/ace/tui/modals/notification_modal.py`          | `m` keybinding + `action_toggle_mute`; `~ ` / dim styling in `_create_styled_label`; updated inline hints label.                               |
| `tests/test_notification_models.py`                      | Default-value snapshot includes `muted=False`.                                                                                                 |
| `tests/test_notification_store.py`                       | `mark_muted(id, True/False)` round-trip; missing-id returns `False`; backward-compat (loading record without `muted` field).                   |
| `tests/test_notification_modal.py`                       | Pressing `m` toggles mute, persists, rebuilds row with `~ ` / dim.                                                                             |
| `tests/test_notification_indicator.py` _(extend or new)_ | `set_counts(0,0)` / `(5,0)` / `(0,2)` / `(5,2)` render the right segments and styles.                                                          |

No CSS changes — styling is inline Rich markup, matching the existing approach for the gold unread bullet.

## Acceptance

- Pressing `m` on a notification toggles its mute state; the row's prefix and color update without reordering the list.
- The header indicator's primary count drops by 1 when an unread notification is muted, and rises by 1 when it's
  unmuted; the dim secondary count moves the opposite direction.
- The secondary muted-count segment only renders when `muted > 0`, and is always dim.
- Closing and reopening the TUI preserves muted state.
- All four flag combinations (`muted` × `read`) render with the documented prefix/style.
- `just check` passes.

## Out of scope (future work)

- Mute-by-sender rules ("always mute fix-hook notifications").
- A separate filter to hide muted rows in the panel (`M`-toggle to show/hide muted).
- Persisted "snooze until" muting that auto-unmutes after a duration.
- Bulk mute / unmute action.
