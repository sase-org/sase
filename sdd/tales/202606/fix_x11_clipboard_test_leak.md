---
create_time: 2026-06-15 19:04:59
status: done
prompt: sdd/prompts/202606/fix_x11_clipboard_test_leak.md
---
# Fix X11 authentication errors triggered by the test suite

## Problem

When running the test suite inside a tmux session over an SSH-forwarded X11 display, an "X11 authentication" error
message intermittently pops up in the terminal while tests run. The message text varies with the state of the X
authority cookie, e.g.:

- `Authorization required, but no authorization protocol specified` (Xlib), or
- `X11 connection rejected because of wrong authentication.` (sshd)

These appear when the SSH X11 forwarding cookie for the forwarded display is stale or missing. The user wants the root
cause diagnosed and fixed so the test suite stops emitting this noise.

## Root cause (diagnosed and verified)

The test suite spawns the **real `xclip` binary** against the SSH-forwarded X display, and that X11 connection attempt
is what produces the authentication noise.

Chain of facts established during investigation:

1. `src/sase/core/clipboard.py` implements `copy_to_system_clipboard()`. On Linux, when `DISPLAY` is set (true under SSH
   X11 forwarding — here `DISPLAY=localhost:10.0`), it shells out to `xclip -selection clipboard` (then `xsel` as a
   fallback). `xclip` is installed at `/usr/bin/xclip`, so the command actually runs and opens an X11 connection to the
   forwarded display.

2. `copy_to_system_clipboard()` redirects the subprocess's own `stderr` to `DEVNULL`, but that does **not** suppress the
   auth message: when the cookie is stale, the message is emitted by sshd / the ssh client onto the session terminal as
   part of the forwarded-X11 channel handshake, independent of the child process's stderr. So the existing `DEVNULL`
   redirect cannot prevent the popup — the only real fix is to not open the X11 connection at all during tests.

3. There is an autouse guard fixture intended to stop this — `_mock_system_clipboard` in `tests/conftest.py` — but it
   only patches a **single** import site: `sase.ace.tui.widgets._vim_normal_ops.copy_to_system_clipboard`. Every other
   module that does `from ... import copy_to_system_clipboard` is left bound to the real function:
   - `src/sase/ace/tui/widgets/_vim_visual.py`
   - `src/sase/ace/tui/actions/clipboard/_helpers.py`
   - `src/sase/main/ace_handler.py`
   - `src/sase/memory/review_tui/app.py`
   - `src/sase/prompt/cli_copy.py`
   - `src/sase/core/__init__.py`

4. **Reproduction / proof.** I shimmed `xclip`/`xsel`/`wl-copy` with logging wrappers on `PATH` and ran the full fast
   suite (`tools/run_pytest fast`). The shim recorded **6 real `xclip -selection clipboard` invocations**, all from vim
   **visual-mode** yank/case/paste tests in `tests/test_prompt_visual_mode.py`:
   - `test_visual_uppercase_selection`
   - `test_visual_lowercase_selection`
   - `test_visual_toggle_case_updates_selection_and_register`
   - `test_visual_p_replaces_selection_and_stores_replaced_text`
   - `test_linewise_visual_toggle_case_preserves_line_boundaries`
   - `test_linewise_visual_p_preserves_following_line`

   These exercise `src/sase/ace/tui/widgets/_vim_visual.py:280` (`_store_visual_register` →
   `copy_to_system_clipboard(text)`), whose binding the autouse fixture does **not** patch. The visual-mode test file
   does not patch the clipboard itself, so the real `xclip` runs.

**Summary:** the autouse clipboard guard is incomplete. It patches one of several import sites, so visual-mode clipboard
operations (and any future un-patched call site) reach the real `xclip`, opening X11 connections that surface
authentication errors in tmux.

## Fix design

Patch the clipboard at the **single internal chokepoint** that every public entry point funnels through, instead of
trying to enumerate every `from ... import` site (fragile and already proven to drift).

Both `copy_to_system_clipboard()` and `clipboard_available()` call the module-private `_clipboard_commands()` via a
module-global lookup at call time. Patching `sase.core.clipboard._clipboard_commands` to return `[]` makes:

- `copy_to_system_clipboard()` iterate over nothing → return `False`, spawning **no** subprocess, and
- `clipboard_available()` → return `False`,

regardless of how any caller imported the public functions. This neutralizes all six import sites at once and is
future-proof against new call sites.

This is behavior-safe for the affected tests: the return value of `copy_to_system_clipboard` is not consumed at either
widget call site (`_vim_visual.py` and `_vim_normal_ops.py` call it fire-and-forget), and the visual-mode tests assert
only on register/selection/mode state, never on a clipboard-success notification. Tests that patch
`copy_to_system_clipboard` at their own import site (e.g. `test_copy_agent_name.py`, `test_ace_handler.py`,
`test_notification_modal_action_bindings.py`, the mentor-review and agent-artifacts copy tests) are unaffected — their
local patch shadows the source and never reaches `_clipboard_commands`.

### Changes

1. **`tests/conftest.py` — strengthen the autouse guard.** Replace the narrow `_vim_normal_ops`-only patch in
   `_mock_system_clipboard` with a patch of `sase.core.clipboard._clipboard_commands` returning `[]`. Make the fixture
   honor an opt-out marker so the dedicated clipboard unit tests can still exercise the real logic:

   ```python
   @pytest.fixture(autouse=True)
   def _mock_system_clipboard(request):
       """Prevent tests from touching the real system clipboard / X11 display."""
       if request.node.get_closest_marker("real_clipboard"):
           yield
           return
       with patch("sase.core.clipboard._clipboard_commands", return_value=[]):
           yield
   ```

2. **`pyproject.toml` — register the marker.** `--strict-markers` is enabled, so add `real_clipboard` to
   `[tool.pytest.ini_options] markers`, e.g.
   `"real_clipboard: test exercises the real clipboard command resolution (opts out of the clipboard guard)"`.

3. **`tests/test_clipboard_utils.py` — opt out.** These five tests call the real `_clipboard_commands()` /
   `copy_to_system_clipboard()` with their own controlled `subprocess`/`env`/`platform` patches and must bypass the
   guard. Add a module-level `pytestmark = pytest.mark.real_clipboard`.

### Alternatives considered (and rejected)

- **Extend the fixture to also patch `_vim_visual` (and the other four sites).** This is the minimal "add the missing
  one" fix, but it is exactly the fragile per-import-site approach that already drifted once; it would need updating for
  every new call site. Rejected in favor of the single chokepoint.
- **Unset `DISPLAY`/`WAYLAND_DISPLAY` in tests.** Insufficient: `_clipboard_commands()` returns all of
  `wl-copy`/`xclip`/`xsel` when neither variable is set, so `xclip` would still be spawned (it would just fail to
  connect instead of hitting the forwarded display).
- **Patch `sase.core.clipboard.subprocess.run`.** `sase.core.clipboard.subprocess` is the global `subprocess` module, so
  this would patch `subprocess.run` process-wide and break unrelated subprocess usage. Too broad.

## Scope / non-goals

- **In scope:** stop the test suite from opening real X11 clipboard connections.
- **Out of scope:** the interactive `sase ace` experience over SSH (a real copy in the TUI will still talk to `xclip`);
  changing production clipboard behavior; the `_clipboard_commands()` "try everything when neither DISPLAY nor WAYLAND
  is set" design. These can be follow-ups if desired but are not part of this fix.
- **Note (unrelated):** `tests/test_core_agent_scan_records.py::test_repeat_stopped_record_carries_repeat_stop_fields`
  fails in this workspace independent of the clipboard change (it failed both before and after, and is unrelated to
  X11/clipboard). Not addressed here.

## Verification

1. Re-run the full fast suite under the `xclip`/`xsel`/`wl-copy` logging shim and confirm **0** real clipboard
   invocations (was 6).
2. `just check` (lint + mypy + tests) passes, with no new failures attributable to this change. Confirm
   `tests/test_clipboard_utils.py` still passes via its `real_clipboard` opt-out, and that the previously-leaking
   `tests/test_prompt_visual_mode.py` tests still pass.
