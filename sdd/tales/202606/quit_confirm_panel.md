---
create_time: 2026-06-23 06:54:26
status: done
prompt: sdd/prompts/202606/quit_confirm_panel.md
---
# Plan: Beautiful Quit Confirmation Panel with Background-Task Details

## Product context

When a user presses `q` to quit the `sase ace` TUI while background tasks are still running, the app currently pushes a
bare, generic yes/no dialog (`ConfirmActionModal`) that reads:

> `N background task(s) still running. Quit and kill them?`

This is functional but ugly and uninformative — the user is asked to kill an unknown set of tasks with no idea what they
are, how long they've been running, or what they're doing. We want to replace it with a **dedicated, beautiful
quit-confirmation panel** that:

1. Clearly signals the destructive, "are you sure?" nature of the choice.
2. Lists **every running background task** that will be killed, with rich per-task detail.
3. Offers a clean, keyboard-first y/n decision with a safe default.

This is a **presentation-only** change in the Textual TUI layer (new modal widget, layout, CSS, and the one call site
that opens it). It does **not** cross the Rust core backend boundary: the background-task registry it reads
(`TaskQueue`) is already a TUI-local Python construct for sync/mail/accept worker jobs, not shared domain logic. No
`sase-core` changes are required.

## What counts as a "background task" here

The quit check today only consults `TaskQueue.running_count` (TUI worker jobs: sync, mail, accept, and agent-launch
cleanup tasks). Those are exactly the tasks that get killed on quit. This plan **keeps that scope**: the panel details
precisely the set of tasks that the confirm action will kill — no more, no less. (Separate concepts like live agents
from `list_running_agents()` and AXE background-command slots are tracked by other systems, are _not_ killed by the quit
path today, and are intentionally out of scope. Pulling them in would be a behavioral change, not a visual one.)

## Current behavior (for reference)

- `src/sase/ace/tui/actions/lifecycle.py`
  - `action_quit()` — counts running tasks via `_count_running_tasks()`; if `> 0`, pushes
    `ConfirmActionModal(title="Quit", message=...)` with an `_on_confirm` callback that calls
    `_kill_all_running_tasks()` then `_do_quit()`.
  - `_count_running_tasks()` / `_kill_all_running_tasks()` — helpers over `self._task_queue`.
- `src/sase/ace/tui/modals/confirm_action_modal.py` — the generic shared yes/no modal. It is reused by many other call
  sites (e.g. `task_queue_modal.action_kill_task`), so it **must not** be specialized for quit.
- `src/sase/ace/tui/task_queue.py` — `TaskInfo` dataclass with the data we can surface: `task_type`
  ("sync"/"mail"/"accept"/…), `cl_name`, `status`, `message`, `started_at`, `display_name`, and the `label` property
  (`display_name` or `"{task_type} {cl_name}"`).

## Design

### New dedicated modal: `QuitConfirmModal`

Create `src/sase/ace/tui/modals/quit_confirm_modal.py` with `class QuitConfirmModal(ModalScreen[bool])`, modeled on the
rich-content confirm pattern already used by `AgentCleanupModal` / `ConfirmRevertAgentModal` (summary cards + styled
rows) and the status glyph/relative-time vocabulary from `TaskQueueModal`.

Constructor takes a snapshot list of the running tasks: `QuitConfirmModal(tasks: list[TaskInfo])`. The call site builds
this snapshot, so the modal stays decoupled and trivially testable. The dialog is a momentary decision, so a snapshot at
open time is correct and avoids flicker — no live polling in v1 (noted as a deferred enhancement below).

**Bindings** (keyboard-first, same vocabulary as existing confirm modals):

- `y` / `Y` → confirm (quit & kill)
- `n` / `escape` / `q` → cancel (keep running)
- `j` / `k` / `up` / `down` → scroll the task list when it overflows

Returns `True` on confirm, `False`/`None` on cancel — drop-in compatible with the existing
`_on_confirm(confirmed: bool | None)` callback.

### Visual layout

```
┌─ Quit SASE? ──────────────────────────────────────────────┐
│                                                            │
│  ⚠  3 background tasks are still running.                  │
│     Quitting now will kill them before they finish.        │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ ●  sync my-feature-cl          SYNC      12s        │   │
│  │    Syncing my-feature-cl…                           │   │
│  │                                                      │   │
│  │ ●  mail bugfix-cl              MAIL       4s         │   │
│  │    Mailing bugfix-cl…                                │   │
│  │                                                      │   │
│  │ ●  accept proposal-xyz        ACCEPT     1m         │   │
│  │    Accepting proposal-xyz…                           │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│        [ Quit & kill all (y) ]   [ Keep running (n) ]      │
│                                                            │
│   y quit & kill all · n/esc keep running · j/k scroll      │
└────────────────────────────────────────────────────────────┘
```

**Structure** (`compose`):

- Outer `Container#quit-confirm-container` — `border: thick $primary`, `background: $surface`, `padding: 1 2`, fixed
  width (~64) with `max-width`/`max-height` caps, centered (`align: center middle`).
- Title `Label#quit-confirm-title` — bold, e.g. `Quit SASE?`.
- Warning summary `Static#quit-confirm-summary` — a `⚠` glyph in `$warning` plus pluralized text ("1 background task is"
  / "N background tasks are still running…"). Two lines, the second muted.
- Task list `VerticalScroll#quit-confirm-tasks` (bordered `solid $secondary`, `max-height` capped so a large set scrolls
  instead of overflowing the screen). One `Static.quit-confirm-task-card` per task, each rendering a Rich `Text` with:
  - **Line 1:** status glyph `●` (bold, `$warning`/yellow for running) · **bold label** (`task.label`) · a colored
    **type chip** (e.g. `SYNC` rendered as inverse/`black on <color>`, color mapped per type: sync→blue, mail→magenta,
    accept→green, default→cyan) · right-aligned **elapsed time** (compact `12s` / `3m` / `1h 4m`, dim).
  - **Line 2:** the task's `message` (live status line), dim, truncated to width.
- Button row `Horizontal#quit-confirm-buttons` (centered):
  `Button("Quit & kill all (y)", id="confirm-btn", variant="error")` and
  `Button("Keep running (n)", id="cancel-btn", variant="primary")`.
- Hints `Static#quit-confirm-hints` — dim, centered: `y quit & kill all · n/esc keep running · j/k scroll`.

**Safety:** focus defaults to the **cancel** ("Keep running") button on mount, so a reflexive `Enter` does _not_ destroy
work; `y` still confirms explicitly. This matches the destructive intent.

**Helpers:**

- A module-level `_format_elapsed(started_at: datetime) -> str` returning compact elapsed time (`"12s"`, `"3m"`,
  `"1h 4m"`). Module-level so the visual test can monkeypatch it for deterministic snapshots (same approach
  `test_ace_png_snapshots_prompt_stash.py` uses for `format_relative_time`).
- A `_TYPE_CHIP_STYLES` dict mapping task types → chip colors, with a default fallback so unknown task types still
  render cleanly.
- Correct singular/plural in the summary line.

### CSS

Add a `QuitConfirmModal` section to `src/sase/ace/tui/styles.tcss` following existing conventions (`AgentCleanupModal`
is the closest template): `align: center middle` on the modal; container with `border: thick $primary` /
`background: $surface` / `padding: 1 2`; bold title with `margin-bottom`; bordered scrollable task list with
`max-height`; per-card spacing; centered button row with `margin: 0 1` button spacing; muted centered hints. Use only
existing theme tokens (`$primary`, `$surface`, `$secondary`, `$warning`, `$error`, `$text-muted`).

### Wiring

- `src/sase/ace/tui/modals/__init__.py` — export `QuitConfirmModal`.
- `src/sase/ace/tui/actions/lifecycle.py` — in `action_quit()`, build the running-task snapshot
  (`running = [t for t in self._task_queue.get_all() if t.status == "running"]`) and push `QuitConfirmModal(running)`
  instead of `ConfirmActionModal`. The existing `_on_confirm` callback (kill all → quit) and the `count == 0` fast path
  are unchanged. `_count_running_tasks()` / `_kill_all_running_tasks()` stay as-is.

`ConfirmActionModal` is left untouched and continues serving all its other callers.

## Testing

1. **Behavioral unit test** (under `tests/ace/tui/actions/` or `tests/ace/tui/modals/`):
   - With ≥1 running task, `action_quit()` pushes a `QuitConfirmModal` (not `ConfirmActionModal`) and does not quit
     immediately.
   - Confirm path → `_kill_all_running_tasks()` runs and the app quits.
   - Cancel path → nothing is killed and the app stays open.
   - With zero running tasks, quit proceeds with no modal (regression guard).
   - The modal builds one card per task and renders each task's label/type/message.

2. **Visual PNG snapshot test** — add `tests/ace/tui/visual/test_ace_png_snapshots_quit_confirm.py` following the
   `test_ace_png_snapshots_prompt_stash.py` pattern: monkeypatch `_format_elapsed` for deterministic durations, push
   `QuitConfirmModal` with a fixed set of `TaskInfo` fixtures that exercise every row state (different task types/chips,
   a long label/message that truncates, singular-vs-plural summary), `await page.expect_modal("QuitConfirmModal")`, then
   `assert_page_png(...)`. Generate the golden with `--sase-update-visual-snapshots` and commit it under
   `tests/ace/tui/visual/snapshots/png/`.

3. **Checks:** run `just install` first (ephemeral workspace), then `just check`, and `just test-visual` for the new
   snapshot.

## Docs / conventions to verify

- The `q` quit keymap itself is unchanged, so no footer/keybinding-config updates are needed. Confirm the `?` help modal
  doesn't describe the old quit-confirmation wording; update it only if it does.
- No new CLI options/subcommands, so no CLI-rules or generated-skills work.

## Out of scope (possible follow-ups)

- Live refresh of the panel (ticking durations, auto-dropping tasks that finish while open). Snapshot semantics are
  intentionally chosen for v1 simplicity and determinism.
- Surfacing running agents / AXE background-command slots in the quit flow — those are tracked by separate systems and
  are not killed by the quit path today; including them would be a behavioral change, not a visual one.

## Files touched

- `src/sase/ace/tui/modals/quit_confirm_modal.py` (new)
- `src/sase/ace/tui/modals/__init__.py` (export)
- `src/sase/ace/tui/actions/lifecycle.py` (call site in `action_quit`)
- `src/sase/ace/tui/styles.tcss` (new `QuitConfirmModal` styles)
- `tests/ace/tui/actions/` or `tests/ace/tui/modals/` (behavioral test, new)
- `tests/ace/tui/visual/test_ace_png_snapshots_quit_confirm.py` (+ committed golden PNG, new)
