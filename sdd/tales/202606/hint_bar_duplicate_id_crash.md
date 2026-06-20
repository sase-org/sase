---
create_time: 2026-06-20 10:28:57
status: done
prompt: sdd/prompts/202606/hint_bar_duplicate_id_crash.md
---
# Plan: Fix `sase ace` crash when re-triggering the view (`v`) hint bar after it loses focus

## Problem

On the **Agents** tab (and any other tab), pressing `v` mounts a `HintInputBar(id="hint-input-bar")` into the detail
container and focuses its `#hint-input` field. Sometimes the bar **silently loses focus**. Once it is no longer focused,
the global `v` binding is live again, so pressing `v` a second time tries to mount a _second_ `HintInputBar` with the
same hard-coded id. Textual then raises:

```
DuplicateIds: Tried to insert a widget with ID 'hint-input-bar', but a widget already exists with that ID
```

The crash backtrace shows the parent `Vertical(id='agent-detail-container')` NodeList already containing one
`HintInputBar(id='hint-input-bar')` when a second is appended.

There are **two independent defects** here, and a robust fix should address both:

1. **The trigger** — why the bar loses focus (root cause of the reported symptom).
2. **The crash** — why a lost-focus bar lets a second mount happen (the unhandled fatal consequence).

## Root cause analysis

### Layer 1 — The focus theft (trigger)

The hint bar focuses `#hint-input` in `HintInputBar.on_mount` (`src/sase/ace/tui/widgets/hint_input_bar.py:161`). Focus
is later stolen by the agents-tab panel refresh machinery, which **unconditionally** re-grabs Textual focus to the
focused `AgentList`:

- `_focus_focused_panel_widget()` — `src/sase/ace/tui/actions/agents/_display_panel_refresh.py:543` (calls
  `widget.focus()` at line 555). It is invoked at the end of:
  - `_refresh_panel_widgets_impl()` (line 223) — full panel rebuild, and
  - `_refresh_affected_panel_widgets()` (line 355) — incremental panel rebuild.
- `_refresh_focused_agent_panel_impl()` — `_display_panel_refresh.py:506-510` focuses the focused-panel widget on a
  panel switch.

None of these check whether a transient input (the hint bar) is currently open. The periodic auto-refresh handler
`_on_auto_refresh` _does_ guard against hint mode (`src/sase/ace/tui/actions/_event_refresh.py:496-501`, returns early
when `_hint_mode_active`), but several panel-rebuild paths fire **outside** that guard and therefore steal focus while
the bar is open:

- An agent load (`_load_agents_async`) started by a prior auto-refresh tick _before_ `v` was pressed completes _after_
  the bar mounts; its display refresh rebuilds panels → focus stolen. (The hint-mode check at `_event_refresh.py:496`
  ran before the load started, so it could not protect a load already in flight.)
- The inotify watcher delta-refresh path and the background live-hint worker (`AgentLiveHintMixin`,
  `src/sase/ace/tui/actions/agents/_loading_live_hints.py`) repaint rows on their own cadence; a membership change falls
  back to a full panel rebuild → `_focus_focused_panel_widget()`.

Because these depend on background timing and incoming agent data, the focus loss is intermittent — matching the user's
"loses focus for some reason."

The correct fix is at the **single choke point**: the focus grab itself must not run while a hint bar is open. Gating
every caller individually is fragile (and contradicts the "treat runtimes/paths uniformly" convention); gating the focus
grab covers all current and future callers.

### Layer 2 — The duplicate mount (crash)

Every hint-bar entry path mounts `HintInputBar(id="hint-input-bar")` with **no check** for an already-mounted bar:

- `src/sase/ace/tui/actions/hints/_files.py:57-58` (`action_view_files`) and `:85-86` (`_view_agent_files`)
- `src/sase/ace/tui/actions/hints/_hooks.py:58-59` (`action_edit_hooks`) and `:107-108` (`action_hooks_from_failed`)
- `src/sase/ace/tui/actions/hints/_mentors.py:57-58` (`action_kill_mentors`)
- `src/sase/ace/tui/actions/hints/_rewind.py:73-76` (`action_start_rewind`)
- `src/sase/ace/tui/actions/hints/_processing.py:215-220` (hook-history modal "edit first" callback)
- `src/sase/ace/tui/actions/proposal_rebase.py:397-400` (`action_accept_proposal`)

Each only checks `detail_container.is_attached`, never whether `#hint-input-bar` already exists. So any state where a
bar is mounted-but-unfocused (Layer 1, or any future focus-loss path) turns the next hint-entry keypress into a fatal
`DuplicateIds`.

Note: simply calling `_remove_hint_input_bar()` then re-mounting in the same synchronous handler does **not** work —
Textual's `Widget.remove()` is deferred (the id stays registered in the parent NodeList until the prune is processed),
so an immediate same-id re-mount would still collide. The guard must therefore _avoid_ mounting a second bar rather than
remove-then-remount.

## Proposed fix

### Fix A — Stop the focus theft (addresses Layer 1, the root cause of the symptom)

Suppress the focused-panel `.focus()` grab whenever a hint bar is active. Add a small predicate on the shared mixin base
and gate the focus calls on it.

- Add a helper (e.g. `_hint_input_bar_active()`) returning
  `self._hint_mode_active or self._accept_mode_active or self._rewind_mode_active`. These flags cover all six bar modes
  (view/hooks/failed_hooks/mentors set `_hint_mode_active`; accept sets `_accept_mode_active`; rewind sets
  `_rewind_mode_active`).
- In `_focus_focused_panel_widget()` (`_display_panel_refresh.py:543`) and the focus block in
  `_refresh_focused_agent_panel_impl()` (lines 506-510), early-return / skip the `.focus()` call when
  `_hint_input_bar_active()` is `True`.

**Why the flags, not a widget query:** the flags are set _before_ the bar mounts and cleared by
`_remove_hint_input_bar()` _before_ the bar is removed (`_processing.py:44-51`). Using the flags (rather than
`query("#hint-input-bar")`) avoids the deferred-removal window — the moment we begin tearing the bar down, the gate
opens again so focus is restored normally after close. (Verify, as part of implementation, that `action_accept_proposal`
and `action_start_rewind` set their respective flags _before_ mounting; if not, move the assignment up so the gate is
effective for those modes too.)

### Fix B — Make hint-bar entry idempotent (addresses Layer 2, crash-proofing / defense in depth)

Guarantee at most one `#hint-input-bar` ever exists. At the very top of each hint-entry action — before any state
mutation — if a bar is already mounted, re-focus its input and return instead of mounting a duplicate. Centralize this
in one helper to keep all entry points uniform:

- Add a helper (e.g. `_refocus_existing_hint_bar()` on the shared hint base) that finds a mounted `#hint-input-bar`,
  focuses its `#hint-input`, and reports whether one was present.
- At the start of `action_view_files`, `_view_agent_files`, `action_edit_hooks`, `action_hooks_from_failed`,
  `action_kill_mentors`, `action_start_rewind`, `action_accept_proposal`, and the modal "edit first" callback, call the
  helper and `return` early when a bar already exists.

This uses widget existence (not the flags) deliberately: the check must run before the action sets its own mode flag,
and a stuck bar reliably has the widget present. Result: even if some unknown future path drops focus, pressing `v` (or
any hint key) re-focuses the open bar rather than crashing.

### Fix C — Confirm close still restores focus (regression guard for Fix A)

Because Fix A suppresses the panel focus grab while a bar is open, confirm that closing the bar
(`_remove_hint_input_bar`, `_processing.py:41`) still returns focus to the focused `AgentList`. The flags are cleared
before removal, so the gate is open by the time any post-close refresh runs, and Textual auto-moves focus when the
focused Input is removed. If manual verification shows focus is _not_ reliably restored on close, add an explicit
focused-panel refocus at the end of `_remove_hint_input_bar` for the agents tab. Treat this as a verify-then-harden
step, not a speculative change.

## Files to change

- `src/sase/ace/tui/actions/agents/_display_panel_refresh.py` — gate the two focus grabs (Fix A).
- `src/sase/ace/tui/actions/hints/_types.py` (or the appropriate shared hint mixin base) — add the
  `_hint_input_bar_active()` and `_refocus_existing_hint_bar()` helpers.
- `src/sase/ace/tui/actions/hints/_files.py`, `_hooks.py`, `_mentors.py`, `_rewind.py`, `_processing.py`, and
  `src/sase/ace/tui/actions/proposal_rebase.py` — add the duplicate-mount guard at each entry point (Fix B).
- `src/sase/ace/tui/actions/hints/_processing.py` — only if Fix C verification shows a focus-restore gap.

This is presentation/Textual-glue behavior (focus management, widget mounting), so it stays in this repo — it does not
cross the Rust core boundary.

## Testing

- **Regression test for the crash (Fix B):** drive the TUI on the agents tab, mount the hint bar, move focus away from
  it (simulate the lost-focus state), then trigger the view action again; assert no `DuplicateIds` is raised and exactly
  one `#hint-input-bar` exists. Model harness usage on the existing agents-tab tests (e.g.
  `tests/ace/tui/test_agents_live_hint_refresh.py`, `tests/ace/tui/test_agent_panel_first_selection.py`).
- **Focus-theft test (Fix A):** with a hint bar open and `_hint_mode_active` set, invoke a panel rebuild
  (`_refresh_affected_panel_widgets` / `_refresh_panel_widgets` / `_refresh_focused_agent_panel`) and assert focus stays
  on `#hint-input` (i.e. `_focus_focused_panel_widget` does not steal it).
- **Close-focus test (Fix C):** open then cancel/submit the bar and assert focus returns to the focused `AgentList` and
  `v`/`j`/`k` work again.
- Run `just check` (after `just install`, per the ephemeral-workspace note) before completion.

## Risks & edge cases

- **Modes other than view:** the same guard/flag set covers hooks, failed_hooks, mentors, accept, and rewind, so all
  hint entry points are protected uniformly.
- **Stuck-bar mode mismatch:** if a `view` bar is somehow stuck and the user presses a different hint key, Fix B
  re-focuses the existing (view) bar rather than switching modes. This is an acceptable, non-fatal outcome (user can
  press Esc and retry); Fix A should prevent the stuck state from arising in the first place.
- **Deferred removal:** the plan deliberately avoids remove-then-remount of the same id within one handler, since
  Textual's deferred removal would still collide.
- **No new keybindings/config:** no footer, help-modal, or `default_config.yml` updates are required — this is a pure
  bug fix with no user-facing surface changes.
