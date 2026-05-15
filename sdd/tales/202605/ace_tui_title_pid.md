---
create_time: 2026-05-15 13:50:31
status: done
prompt: sdd/prompts/202605/ace_tui_title_pid.md
---
# Plan: Append `(PID: <sase_ace_pid>)` to the `sase ace` TUI title

## Goal

The TUI launched by `sase ace` currently displays the title `sase ace` in its Textual `Header` widget. We want that
title to become:

```
sase ace (PID: <sase_ace_pid>)
```

where `<sase_ace_pid>` is the PID of the running `sase ace` process (i.e. the Python process hosting the Textual
`AceApp`). This makes it trivial to identify a particular TUI instance — e.g. when multiple `sase ace` windows are open,
or when correlating a TUI with `ps`, log lines, or attach/kill commands.

## Background / Where the title comes from

- `src/sase/ace/tui/app.py:114` declares `TITLE = "sase ace"` on the `AceApp` Textual `App` subclass. Textual reads
  `App.TITLE` (class var) at startup to seed the reactive `app.title` attribute, and the `Header()` widget (rendered by
  `AceApp.compose`, `src/sase/ace/tui/app.py:246`) displays `app.title` on its top row.
- No other production code references the string `"sase ace"` as a title — only docs under `sdd/`.
- The entry point is `handle_ace_command` in `src/sase/main/ace_handler.py`, which constructs `AceApp(...)` and calls
  `app.run()`. The TUI runs in-process, so `os.getpid()` from inside `AceApp` is exactly the "`sase ace` PID" the user
  means.
- No test currently asserts the literal title string, so no test needs to change for the existing assertion to keep
  passing. (We will add a small targeted test — see below.)

## Design considerations

A few choices to make explicit before implementing:

1. **Title vs. sub-title.** Textual's `Header` can show both `app.title` and `app.sub_title`. The user explicitly asked
   us to "append … to that title", so the PID should be part of `app.title`, not a sub_title. This also keeps the value
   visible regardless of any future Header styling tweaks.

2. **Class constant vs. runtime assignment.** `App.TITLE` is a class-level constant evaluated at class-definition time,
   so we cannot easily interpolate a PID there without doing it at import time (which would bake in the importing
   process's PID rather than the actual TUI process's PID — usually the same, but conceptually wrong, and outright wrong
   if `AceApp` is ever imported in a parent and then `run` is called in a forked child). We will instead:
   - Keep `TITLE = "sase ace"` as a sensible default (it is what shows in error/help output and during very early init).
   - Set `self.title = f"sase ace (PID: {os.getpid()})"` once, from inside the app, after `super().__init__()`. This
     produces the correct PID for the actual running process and is what `Header` will display.

3. **Where to set `self.title`.** Two reasonable options:
   - In `AceApp.__init__`, immediately after `super().__init__()` (the existing `__init__` already has access to
     `os.getpid()` via the module-level `import os`).
   - In an `on_mount` hook.

   `__init__` is simpler and runs unconditionally; `on_mount` only runs once the app is mounted (which is also fine
   here, but adds an extra method). **Recommendation:** set it in `__init__`. Single line, easy to find, behaves
   identically whether or not the app gets mounted (e.g. in tests that instantiate `AceApp` without running it).

4. **Format.** The user's spec is exact: ` (PID: <sase_ace_pid>)` with a leading space, capital "PID", colon-space,
   integer, closing paren. We will match that verbatim. The integer is rendered with `str(os.getpid())` — no padding.

5. **Window/terminal title.** Textual additionally sets the terminal window title from `app.title`. Updating
   `self.title` therefore also updates the terminal tab/ window title, which is a free win (you can pick a `sase ace`
   window by PID from your window list).

6. **Scope of "title".** We are only changing the in-TUI `Header` title (and, as a side effect, the terminal window
   title that Textual sets from it). We are **not** changing:
   - Tmux pane titles (handled separately by `src/sase/ace/tui/graphics/_viewer_launch.py`).
   - Logging or trace context.
   - The `sase ace` argparse `description` / `--help` output.

## Implementation steps

1. **Edit `src/sase/ace/tui/app.py`:**
   - Leave `TITLE = "sase ace"` (line 114) in place as the default class-level value.
   - In `AceApp.__init__` (around `src/sase/ace/tui/app.py:204`), immediately after `super().__init__()`, add:
     ```python
     self.title = f"sase ace (PID: {os.getpid()})"
     ```
   - `os` is already imported at the top of the file (line 4), so no new imports.

2. **Add a focused unit test.** Create or extend a small test (e.g. a new file `tests/ace/tui/test_app_title.py`, or
   append to an existing TUI-app-level test if one already targets `AceApp` construction):
   - Instantiate `AceApp(query="!!!", auto_start_axe=False)` — `auto_start_axe=False` keeps the test from touching the
     axe daemon.
   - Assert `app.title == f"sase ace (PID: {os.getpid()})"`.
   - Assert the title starts with `"sase ace "` and ends with `")"` so the format is anchored.

3. **Sanity-check downstream string consumers.** Quick grep for `"sase ace"` already confirmed no production code
   matches against the title string literally; the only hits outside `app.py` are `sdd/` design docs, which can keep
   referring to the short form.

4. **Run `just check`** before declaring done (per repo convention in `memory/short/build_and_run.md`).

## Out of scope / explicit non-goals

- No changes to the CLI's `--help` output.
- No new option to toggle PID display on/off (the user did not ask for it; adding a toggle would be speculative).
- No changes to how PIDs are surfaced elsewhere (logs, `sase ace` discovery, etc.).
- No changes to tmux pane titles or terminal multiplexer integration.

## Risks / things to watch

- **Test snapshots / screenshots:** PNG visual snapshots for the TUI live in `tests/ace/tui/visual/snapshots/png/`. If
  any of them include the `Header` row, the rendered title will change and the snapshot may need to be regenerated with
  `--sase-update-visual-snapshots`. We will run `just test-visual` and address any failures by accepting the new
  goldens, since this is an intentional visual change.
- **PID variability across runs:** Snapshots that include the title would no longer be byte-stable (PID differs each
  run). If any visual snapshot captures the title, we have two options: (a) update those snapshots to use a
  deterministic title for testing (e.g. monkeypatch `os.getpid` in the visual fixture), or (b) crop the title out of the
  snapshot. We will pick the smaller change once we see which (if any) snapshots are affected — most likely (a),
  patching `os.getpid` in the visual conftest, since the fixture already pins fonts and colors for determinism.
