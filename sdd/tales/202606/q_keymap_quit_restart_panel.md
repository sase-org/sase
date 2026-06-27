---
create_time: 2026-06-27 13:53:48
status: done
prompt: sdd/prompts/202606/q_keymap_quit_restart_panel.md
---
# `Q` Keymap → Quit / Restart Options Panel

## Summary

Today the `Q` keymap (`stop_axe_and_quit`) immediately stops the axe daemon and quits the TUI. We will change `Q` so
that, instead of acting immediately, it opens a small, single-keypress **options panel** offering three ways to leave
the current TUI session:

1. **Quit & Stop axe** — the current `Q` behavior (robustly stop axe, then quit).
2. **Restart TUI** — close and immediately re-open the TUI, exactly as if the user had quit with `q` and re-run
   `sase ace`. Axe keeps running untouched.
3. **Restart TUI & Restart axe** — close and re-open the TUI exactly as if the user had quit with `q` and re-run
   `sase ace --restart-axe` (the new TUI restarts the axe daemon on startup).

No reliable "restart the TUI" mechanism exists today, so a central part of this work is **designing one** that is
correct and robust with respect to the terminal and the (possibly ephemeral) workspace virtualenv.

## Goals

- Pressing `Q` opens a clean, fast, single-keypress panel; pressing `Esc`/`q` cancels it and returns to the TUI with no
  side effects.
- Each of the three outcomes is faithful to its described semantics.
- The restart mechanism leaves the terminal in a correct state and re-launches the TUI in the **same** environment it
  was started from (same interpreter / workspace venv, same original CLI flags).
- The change is well-tested, including the new restart wiring.

## Non-Goals

- We are **not** renaming the `stop_axe_and_quit` keymap config key. It stays `Q` → `stop_axe_and_quit` so existing user
  keymap overrides keep working; only the action's behavior and human-facing labels change. (See "Design decisions".)
- We are not adding restart entry points other than the `Q` panel.
- We are not changing `q` (plain quit) or the `QuitConfirmModal` tasks-running flow.

## Background — How Things Work Today

- **Binding:** `src/sase/ace/tui/bindings.py` binds `Q` → `stop_axe_and_quit` (label "Stop & Quit"). The same metadata
  is mirrored in `src/sase/ace/tui/keymaps/types.py` (`_BINDING_META` + the `AppKeymaps` dataclass field) and the
  default config `src/sase/default_config.yml` (`stop_axe_and_quit: "Q"`).
- **Action:** `AxeMixin.action_stop_axe_and_quit` (`src/sase/ace/tui/actions/axe.py`) runs an async worker
  `_stop_axe_and_quit` that: stops the stall watchdog → `_kill_all_running_tasks()` → robust
  `stop_axe_daemon_result(timeout=5.0, kill_timeout=2.0)` in a thread → then `_do_quit()` in a `finally` (so quit always
  happens). This is the recently hardened "stop axe robustly before quit" path.
- **Quit teardown:** `LifecycleMixin._do_quit` (`src/sase/ace/tui/actions/lifecycle.py`) runs best-effort cleanup steps
  and always calls `self.exit()` in a `finally`.
- **Launch / exit:** `handle_ace_command` (`src/sase/main/ace_handler.py`) builds `AceApp(...)`, calls `app.run()`
  (blocking), and unconditionally `sys.exit(0)` afterward. There is **no parent launcher** and **no path for the TUI to
  signal "re-open me"**: `AceApp` is an `App[None]` and the handler ignores any return value.
- **`--restart-axe`:** parsed in `src/sase/main/parser_ace.py` (`-R/--restart-axe`), threaded into `AceApp` as
  `_restart_axe`, and applied during startup (`axe_display/_loaders.py`): if axe is running on startup it calls
  `_restart_axe_daemon()`. So "restart axe on startup" is already implemented; option 3 just needs to re-launch with
  that flag present.
- **Existing single-keypress panels** we will mirror for look & feel: `PromptSubmitChoiceModal`
  (`src/sase/ace/tui/modals/prompt_submit_choice_modal.py`) is the cleanest example (a `ModalScreen[Choice | None]` with
  one `Binding` per option calling `dismiss(value)`), styled with the shared `duration-choice-*` classes in
  `src/sase/ace/tui/styles.tcss` (double border, centered title, tone colors, dim footer hint).

## Design

### 1. The Options Panel (presentation)

Add a new modal `QuitOptionsModal(ModalScreen[QuitOption | None])` in `src/sase/ace/tui/modals/quit_options_modal.py`,
modeled directly on `PromptSubmitChoiceModal` and reusing the existing `duration-choice-*` CSS so it matches the rest of
the TUI.

`QuitOption = Literal["quit_stop_axe", "restart_tui", "restart_tui_and_axe"]`

Layout (top to bottom):

- Title: **Quit ACE**
- Three option rows, each `key + bold title` on the first line and a dim one-line consequence beneath it:
  - `1` / `s` — **Quit & Stop axe** — "Stop the axe daemon and exit." (primary tone)
  - `2` / `r` — **Restart TUI** — "Reopen the TUI. Axe keeps running." (primary tone)
  - `3` / `a` — **Restart TUI & axe** — "Reopen the TUI and restart axe." (accent tone)
- When background tasks are running, a single `$warning`-toned line: "N background task(s) will be stopped." (shown for
  all three options, since all three end the current TUI process).
- Footer hint (dim): `1/s quit & stop axe · 2/r restart · 3/a restart + axe · esc cancel`

Key handling (Bindings, all `show=False`, matching the existing modal style): `1`/`s` → quit_stop_axe, `2`/`r` →
restart_tui, `3`/`a` → restart_tui_and_axe, `escape`/`q` → cancel (`dismiss(None)`). Single keypress dismisses with the
chosen value; no Enter required. (Modal bindings are scoped to the modal, so the digit/letter keys cannot leak to the
app underneath.)

Export `QuitOptionsModal` + `QuitOption` from `src/sase/ace/tui/modals/__init__.py`.

### 2. Rewire the `Q` action

In `AxeMixin` (`src/sase/ace/tui/actions/axe.py`), `action_stop_axe_and_quit` becomes a thin launcher that pushes the
panel and routes the choice:

- `quit_stop_axe` → the **existing** `_stop_axe_and_quit()` worker, unchanged.
- `restart_tui` → new `_restart_tui(restart_axe=False)`.
- `restart_tui_and_axe` → new `_restart_tui(restart_axe=True)`.
- cancel (`None`) → no-op.

The panel is passed the running-task count (`_count_running_tasks()`) so it can show the warning line.

`_restart_tui(restart_axe: bool)` mirrors the non-axe parts of `_stop_axe_and_quit`, synchronously (no blocking axe
call, so no worker needed): stop the stall watchdog → `_kill_all_running_tasks()` (guarded) → set the restart directive
on the app → `_do_quit()`. It deliberately does **not** stop axe: for `restart_tui` axe must keep running; for
`restart_tui_and_axe` the freshly launched `sase ace --restart-axe` is what restarts it.

### 3. The restart mechanism (the critical piece)

The reliable way to "restart the TUI" is to let Textual fully tear down first, then re-exec from the handler — **never**
re-exec from inside the running app (that would replace the process while the terminal is still in alt-screen / raw mode
and leave it corrupted). The flow:

1. Define an `AceExitAction` enum (new module `src/sase/ace/tui/exit_action.py`, re-exported from `sase.ace.tui`):
   `QUIT` (default), `RESTART_TUI`, `RESTART_TUI_AND_AXE`.
2. `AceApp` carries a public `exit_action: AceExitAction`, initialized to `QUIT` in `_init_app_state`
   (`src/sase/ace/tui/actions/_state_init.py`, alongside `_restart_axe`). `_restart_tui` sets it to the appropriate
   value before `_do_quit()` → `self.exit()`. (We use a plain attribute rather than Textual's `App.exit(result=...)` so
   the many existing `self.exit()` cleanup call sites stay untouched and the generic `App[None]` type is unchanged.)
3. `handle_ace_command` (`src/sase/main/ace_handler.py`), **after** `app.run()` returns (and after profiler handling),
   inspects `app.exit_action`:
   - `QUIT` → `sys.exit(0)` (unchanged behavior).
   - `RESTART_TUI` → re-exec a fresh `sase ace` with `--restart-axe` stripped.
   - `RESTART_TUI_AND_AXE` → re-exec a fresh `sase ace` with `--restart-axe` ensured present.
4. Re-exec uses `os.execv(sys.executable, [sys.executable, "-m", "sase", *argv])` where `argv` is rebuilt from the live
   `sys.argv[1:]` (which begins with the `ace` subcommand), filtered to drop `-R/--restart-axe` (and defensively
   `-T/--tmux`) and re-add `--restart-axe` for option 3. Re-exec'ing via the current interpreter + `-m sase` preserves
   the exact venv/workspace and is the same convention `ace_tmux.py` already uses. On `OSError`, print an error to
   stderr and `sys.exit(1)`.

Why this is correct and robust:

- **Terminal integrity:** `app.run()` only returns after Textual's driver restores the terminal (leaves alt-screen,
  restores cooked mode, shows cursor), so the re-exec'd process starts from a clean terminal.
- **Faithful re-run:** rebuilding from `sys.argv` preserves every original flag (query, tab, model tier, refresh
  interval, vcs provider, ...) — a true "re-ran `sase ace`". Only the axe-restart flag is normalized per option.
- **Same environment:** `sys.executable -m sase` keeps the ephemeral workspace venv. We intentionally do **not**
  canonicalize to a non-workspace binary (that is correct for the detached axe daemon, but wrong for the interactive
  TUI).
- **tmux:** when launched with `--tmux`, the process that actually runs `app.run()` already had `--tmux` stripped during
  the tmux relaunch, so re-exec stays in the same tmux pane (the desired behavior). Filtering `--tmux` defensively
  guarantees we never recurse into a new tmux window.
- **fd hygiene:** Python opens files close-on-exec by default, so the TUI log file and other fds are released across the
  exec; the fresh process re-opens logging cleanly.

### Behavior matrix

| Option               | Stall watchdog | Running TUI tasks | Axe daemon                         | Process                          |
| -------------------- | -------------- | ----------------- | ---------------------------------- | -------------------------------- |
| 1. Quit & Stop axe   | stopped        | killed            | robustly stopped                   | exits (`sys.exit(0)`)            |
| 2. Restart TUI       | stopped        | killed            | left running                       | re-exec `sase ace`               |
| 3. Restart TUI & axe | stopped        | killed            | left running; restarted by new TUI | re-exec `sase ace --restart-axe` |

## Design Decisions (calling these out for review)

- **Keep the config key `stop_axe_and_quit`.** The key now does more than its name implies, but renaming it would break
  existing user keymap overrides and require config migration. We keep the key and the `action_stop_axe_and_quit` method
  name; we update only the human-facing labels ("Stop & Quit" → e.g. "Quit / Restart") in `bindings.py`,
  `keymaps/types.py`, and the help modal (`modals/help_modal/axe_bindings.py`, description e.g. "Quit / restart menu").
- **The panel is the single confirmation.** Selecting an option proceeds directly; we do not also chain the `q`-style
  `QuitConfirmModal`. All three options end the current TUI process, so all three kill running background TUI tasks
  (consistent with today's `Q`, which already kills them unconditionally). To keep this honest, the panel surfaces the
  running-task count. Note these background tasks are TUI-side operations (commits, PR ops); the user's actual agents
  run under the axe daemon and, for option 2, are completely untouched.
- **Restart signaled via an app attribute, not Textual's return value.** Lower blast radius (no change to `App[None]`,
  no need to pass a value through every `self.exit()` cleanup call site) and trivially testable.
- **Re-exec in the handler, not in the app.** Required for terminal correctness.

## Files Touched

New:

- `src/sase/ace/tui/modals/quit_options_modal.py` — the panel + `QuitOption`.
- `src/sase/ace/tui/exit_action.py` — `AceExitAction` enum.
- Tests (see below).

Modified:

- `src/sase/ace/tui/actions/axe.py` — rewrite `action_stop_axe_and_quit` to push the panel and route; add
  `_restart_tui`.
- `src/sase/ace/tui/actions/_state_init.py` — init `exit_action = QUIT`.
- `src/sase/ace/tui/__init__.py` — re-export `AceExitAction`.
- `src/sase/ace/tui/modals/__init__.py` — export the new modal + `QuitOption`.
- `src/sase/main/ace_handler.py` — read `exit_action` after `app.run()`; add the re-exec helper.
- `src/sase/ace/tui/bindings.py`, `src/sase/ace/tui/keymaps/types.py`,
  `src/sase/ace/tui/modals/help_modal/axe_bindings.py` — relabel `Q` and update help text (per the "update help when
  changing an option" rule in `src/sase/ace/AGENTS.md`).
- `src/sase/ace/tui/styles.tcss` — only if a dedicated container width/ID is needed beyond the reused
  `duration-choice-*` classes.

## Testing

- **Action routing** (rework `tests/ace/tui/actions/test_axe_stop_quit.py` and/or a new sibling):
  `action_stop_axe_and_quit` now pushes `QuitOptionsModal`; simulate each dismissed choice and assert it routes to the
  right path (`quit_stop_axe` → `_stop_axe_and_quit` worker; restart options → `_restart_tui` with correct
  `restart_axe`). Preserve coverage of the existing `_stop_axe_and_quit` worker (watchdog → kill-tasks → stop → quit;
  still quits when stop/kill raises) by testing that worker directly.
- **`_restart_tui`:** sets `exit_action` to the correct value, stops the watchdog, kills tasks (guarded), calls
  `_do_quit`, and does **not** stop axe.
- **Re-exec helper (handler):** unit-test the argv builder with `os.execv` monkeypatched — assert `RESTART_TUI` strips
  `-R/--restart-axe`, `RESTART_TUI_AND_AXE` ensures exactly one `--restart-axe`, `--tmux`/`-T` are dropped, the `ace`
  subcommand is preserved, and `QUIT` does not exec.
- **Modal:** a Textual `Pilot` test that pressing each key dismisses with the expected `QuitOption` and `esc`/`q`
  dismisses `None`.
- **Optional (nice-to-have):** a PNG visual snapshot of the panel (`tests/ace/tui/visual/`) to lock in the "beautiful"
  appearance, since the repo already maintains an ACE visual snapshot suite.
- Run `just check` before finishing (note: `just install` first, per the ephemeral-workspace rule).

## Risks & Mitigations

- **Broken terminal after restart** — mitigated by re-exec'ing only in the handler after `app.run()` returns; covered
  conceptually by the design and verifiable manually with `/verify` (press `Q`, choose Restart, confirm the TUI cleanly
  reappears and the terminal is normal afterward).
- **Wrong venv on restart** — mitigated by `sys.executable -m sase`.
- **Lost original flags on restart** — mitigated by rebuilding from `sys.argv`.
- **Orphaned background subprocesses** — mitigated by killing running tasks before teardown (same as today's `Q`).

```

```
