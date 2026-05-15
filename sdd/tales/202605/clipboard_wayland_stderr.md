---
create_time: 2026-05-15 10:54:16
status: done
prompt: sdd/prompts/202605/clipboard_wayland_stderr.md
---
# Fix Noisy wl-copy stderr in Copy-Mode Keymaps

## Problem

When the user invokes any `sase ace` copy-mode keymap (the second key after `%`), the message

```
Please check whether /run/user/1000/wayland-0 socket exists and is accessible.
```

is printed into the user's terminal, visually corrupting the TUI. The copy itself succeeds — but the noise is disruptive
and looks like a real error.

## Root Cause

`src/sase/core/clipboard.py`:

```python
def _clipboard_commands() -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pbcopy"]]
    if sys.platform.startswith("linux"):
        return [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    return []


def copy_to_system_clipboard(content: str) -> bool:
    for clipboard_cmd in _clipboard_commands():
        try:
            subprocess.run(clipboard_cmd, input=content, text=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return False
```

Two compounding issues:

1. **wl-copy is always tried first on Linux**, even when there is no Wayland session. The user is on an X11/TTY session
   (`XDG_SESSION_TYPE=tty`, `DISPLAY=localhost:10.0`, `WAYLAND_DISPLAY` unset, no `/run/user/1000/wayland-0`) but
   `wl-copy` is installed at `/usr/bin/wl-copy`, so the binary executes and exits non-zero.
2. **`subprocess.run` does not redirect stderr**, so `wl-copy`'s "please check whether ... socket exists" message is
   written straight to the TUI's stderr (= the user's terminal). The fallback chain then catches the
   `CalledProcessError` and falls through to `xclip`, which works — but the noise has already been emitted.

Net effect: copy works, but every copy-mode keymap leaves a wayland error rendered over the TUI.

## Proposed Fix

Make the candidate list environment-aware so we don't invoke commands that we already know can't work, and as a
belt-and-suspenders measure suppress subprocess stderr/stdout for the fallback probes.

Both changes live in `src/sase/core/clipboard.py`.

### 1. Environment-gated candidate list

On Linux, gate each command on its required display server env var:

- Include `wl-copy` only if `WAYLAND_DISPLAY` is set.
- Include `xclip` and `xsel` only if `DISPLAY` is set.
- If neither is set, fall back to the full union (preserves current behavior for headless edge cases where one of the
  tools may still happen to work).

When both are set (a Wayland session with XWayland), keep Wayland-first ordering to match today's behavior.

### 2. Suppress subprocess output

Pass `stdout=subprocess.DEVNULL` and `stderr=subprocess.DEVNULL` on every `subprocess.run` attempt. The function only
cares about the exit code; stderr from any candidate (wl-copy in a tty, a misbehaving xclip, etc.) must not bleed into
the TUI.

## Files To Change

- **`src/sase/core/clipboard.py`** — env-aware `_clipboard_commands()` and stderr/stdout suppression in
  `copy_to_system_clipboard()`.
- **`tests/test_clipboard_utils.py`** — update the existing Linux-fallback test to assert `stderr=subprocess.DEVNULL` /
  `stdout=subprocess.DEVNULL` in the call kwargs, and add new tests covering the env-gated ordering:
  - Wayland only (`WAYLAND_DISPLAY` set, `DISPLAY` unset) → only `wl-copy`.
  - X11 only (`DISPLAY` set, `WAYLAND_DISPLAY` unset) → only `xclip`, then `xsel`.
  - Both set → `wl-copy`, then `xclip`, then `xsel` (mirrors the existing assertion).
  - Neither set → all three (headless fallback).

No other call sites need changes. `src/sase/ace/tui/actions/clipboard/_helpers.py` re-imports `copy_to_system_clipboard`
unchanged, and every caller (modals, vim normal ops, ace_handler, etc.) treats the function as a boolean black box.

## Verification

- `just check` (lint + tests).
- Manual: in the current X11 session, invoke a copy-mode keymap (for example `% y` on the agents tab) and confirm:
  - No wayland error appears in the terminal.
  - The copied content lands in the clipboard, observable via `xclip -o -selection clipboard`.

## Out of Scope

- The darwin `pbcopy` path — unchanged.
- A user-facing config knob to pin a specific clipboard tool — not needed for this fix; revisit only if env-based
  detection picks the wrong tool in a real session.
- Caching the chosen command across calls — premature; copy is infrequent and the probe is cheap.
