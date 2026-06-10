---
create_time: 2026-06-10 09:03:55
status: done
prompt: sdd/prompts/202606/single_count_notification_indicator.md
---
# Single-Count Notification Indicator

## Problem

The notification indicator in the `sase ace` TUI top bar currently renders up to **three numbers** at once
(`src/sase/ace/tui/widgets/notification_indicator.py:52-67`):

| State `(priority, rest, muted)` | Today      | Meaning                         |
| ------------------------------- | ---------- | ------------------------------- |
| `(0, 0, 0)`                     | `✉ 0`      | dim — nothing unread            |
| `(0, 3, 0)`                     | `✉ 3`      | gold — 3 normal unread          |
| `(2, 0, 0)`                     | `✉ 2+0`    | orange — 2 priority, 0 normal   |
| `(2, 3, 0)`                     | `✉ 2+3`    | orange — 2 priority, 3 normal   |
| `(0, 0, 4)`                     | `✉ 4`      | dim cyan — muted-only backlog   |
| `(1, 0, 2)`                     | `✉ 1+0 ·2` | orange + dim `·2` muted segment |
| `(0, 2, 1)`                     | `✉ 2 ·1`   | gold + dim `·1` muted segment   |

The `2+3` split and the trailing `·N` segment require the user to memorize a private syntax, and the `+0` case (`✉ 2+0`)
is visual noise. The goal is to show **exactly one count** while keeping every state distinguishable — the user must
still be able to read "is anything urgent?", "how much needs me?", and "is there a snoozed backlog?" from the indicator.

## Design

**One number, one rule: the count is the number of notifications that need your attention (priority + rest). Color
carries urgency. A single dim dot carries "muted backlog exists." Hovering reveals the exact breakdown.**

### Display spec

| State `(priority, rest, muted)` | Proposed | Style                                                  |
| ------------------------------- | -------- | ------------------------------------------------------ |
| `(0, 0, 0)`                     | `✉ 0`    | dim (unchanged)                                        |
| `(0, 3, 0)`                     | `✉ 3`    | gold `#FFD700` (unchanged)                             |
| `(2, 0, 0)`                     | `✉ 2`    | orange `#FF8700` — at least one priority item          |
| `(2, 3, 0)`                     | `✉ 5`    | orange — 5 need attention, ≥1 is priority              |
| `(0, 0, 4)`                     | `✉ 4`    | dim cyan `#5FAFAF` — backlog only (unchanged)          |
| `(1, 0, 2)`                     | `✉ 1 ·`  | orange badge + trailing dim `·` (muted backlog marker) |
| `(0, 2, 1)`                     | `✉ 2 ·`  | gold badge + trailing dim `·` (muted backlog marker)   |

Reading rules (each one already exists in today's color language — nothing new to learn, things to _unlearn_ only):

1. **The number** answers "how many things want me right now?" (`priority + rest`). In the cyan state nothing wants you,
   so the number shows the size of the muted backlog — exactly today's muted-only collapse behavior.
2. **The color** answers "how urgent is the worst of it?" — orange ⇒ at least one priority item, gold ⇒ routine only,
   cyan ⇒ acknowledged backlog only, dim ⇒ inbox zero. Identical palette and precedence to today.
3. **The trailing dim `·`** answers "is there _also_ a muted backlog behind this?" It is today's dim `·N` muted segment
   with the number removed, in the same position and style, so the association carries over.

### No information loss

Two of the three exact figures are no longer on screen at all times (the priority/rest split, the muted count in mixed
states). They stay one gesture away, and the _interpretations_ they served stay at-a-glance:

- **Tooltip (new):** the widget sets `self.tooltip` to the full breakdown on every count change, e.g.
  `"2 priority · 3 other · 1 muted"` (or `"No unread notifications"`). Hovering the badge recovers all three numbers
  exactly. Textual ≥0.45 (pinned: `pyproject.toml:49`) supports `Widget.tooltip` natively.
- **Click to open (new):** the indicator becomes clickable and opens the existing notification modal (the same
  `show_notifications` action bound to `i`), where every notification is listed. Today the widget is display-only, which
  is a small intuitiveness gap regardless of this change.
- The `i` keybinding and modal are untouched and remain the authoritative detail view.

### Alternatives considered (rejected)

- **Grand total (`priority + rest + muted`) as the one number:** simplest rule, but a user with 1 actionable + 10 muted
  items would see `✉ 11` gold — overstating what needs them. The actionable count is the figure people act on; muting
  exists precisely to take items out of it.
- **Severity glyphs instead of color (e.g. `✉! 5`):** redundant with the established color channel; adds noise.
- **Keeping `·N` with the muted count:** that is a second count, which the requirement rules out; the dot keeps the
  signal, the tooltip keeps the figure.

## Implementation

All changes are presentation-only Textual code, so per the Rust core boundary rule everything stays in this repo;
`unread_notification_buckets()`, `is_priority()`/`is_error()`, and the snapshot `counts` API are untouched.

1. **`src/sase/ace/tui/widgets/notification_indicator.py`**
   - Rewrite `_build_content()` per the display spec above (drop the `{priority}+{rest}` split; render `priority + rest`
     as the single badge count; append a bare dim `·` when muted coexists with actionable; keep the dim-zero and cyan
     muted-only collapse branches as-is).
   - Add a `_build_tooltip()` helper and set `self.tooltip` from `__init__` and `set_counts()`.
   - Add a click handler that triggers the app's existing `show_notifications` action.
   - Update the class/method docstrings to describe the new encoding (and fix the stale "top-right" wording).
   - `set_counts(priority, rest, muted)` signature and the legacy `set_count()` wrapper are unchanged, so all call sites
     (`actions/lifecycle.py`, `actions/agents/_notification_polling.py`) need no edits.

2. **`tests/test_notification_indicator.py`**
   - Update the existing nine rendering tests to the new expected strings/styles (notably: priority-only renders `✉ 2`,
     mixed renders the summed count, muted coexistence renders the bare `·` marker with no digits).
   - Add tests for the tooltip text (all-zero, mixed, muted-only) and for the click → `show_notifications` dispatch.

3. **PNG visual snapshots** — the snapshot fixture pins `counts=(priority=1, rest=18, muted=0)`
   (`tests/ace/tui/visual/_ace_png_snapshot_helpers.py:284`), so goldens currently show `✉ 1+18` and will change to
   `✉ 19`. Run `just test-visual`, inspect `.pytest_cache/sase-visual/` diffs to confirm only the indicator region
   changed, and regenerate goldens with `--sase-update-visual-snapshots`.

4. **Docs/help check** — the help modal only documents the `i` binding ("Show notifications"), which is unchanged; the
   footer shows conditional keymaps only, also unaffected. No help/footer edits needed.

5. **Validation** — `just install` (fresh ephemeral workspace), then `just check` before finishing.

## Risks

- **Tooltips need mouse hover**, which some terminal/tmux setups disable. Mitigation: the tooltip is a bonus recovery
  channel, not the only one — color + dot keep the glanceable semantics, and `i`/click open the full modal.
- **Muted-only cyan state reuses the number for a different quantity** (backlog size, not actionable size). This is
  today's exact behavior and the cyan color disambiguates, but the tooltip will spell it out regardless.
