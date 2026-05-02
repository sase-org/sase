# Plan: Add `--restart-axe` option to `sase ace`

## Goal

Add a `--restart-axe` CLI flag to `sase ace` that stops and restarts the axe daemon on startup. If axe is not running,
the flag is a no-op. The stop/start cycle runs in a background task so it doesn't block TUI startup.

## Design

The flag integrates into the existing auto-start-axe flow in `on_mount()`. When `--restart-axe` is set:

1. After loading axe status, if axe is running, stop it (via `stop_axe_daemon()`), then start it (via
   `start_axe_daemon()`), all in a single background worker.
2. If axe is not running, do nothing (the normal `_auto_start_axe` logic may still apply).

The restart takes priority over `_auto_start_axe` — if restart is requested and axe is already running, we restart it
regardless. The existing auto-start path already handles the "not running" case.

Interaction with `--no-axe`: If both `--no-axe` and `--restart-axe` are passed, `--restart-axe` takes priority (it
explicitly asks to restart). But since `--no-axe` disables auto-start and `--restart-axe` only acts when axe is already
running, they're compatible: restart stops+starts the running daemon, while no-axe prevents auto-start of a stopped one.

## Changes

### 1. `src/sase/main/parser_ace.py` — Add CLI argument

Add `--restart-axe` (`-R`) flag between `-r` and `-a` (alphabetical order):

```python
ace_parser.add_argument(
    "-R",
    "--restart-axe",
    action="store_true",
    help="Restart the axe daemon on startup (no-op if axe is not running)",
)
```

### 2. `src/sase/main/ace_handler.py` — Pass flag to AceApp

Pass the new `restart_axe` arg to `AceApp`:

```python
app = AceApp(
    ...
    restart_axe=getattr(args, "restart_axe", False),
)
```

### 3. `src/sase/ace/tui/app.py` — Accept and store the flag

- Add `restart_axe: bool = False` parameter to `__init__`.
- Store as `self._restart_axe`.
- In `on_mount()`, after `_load_axe_status()`, add restart logic:
  - If `self._restart_axe and self.axe_running`: call `self._restart_axe_daemon()` (new method).
  - The existing `_auto_start_axe` block should be skipped if a restart was triggered (to avoid double-starting).

### 4. `src/sase/ace/tui/actions/axe.py` — Add `_restart_axe_daemon()` method

Add a new method to `AxeMixin` that runs stop + start in a single background worker:

```python
def _restart_axe_daemon(self) -> None:
    """Restart axe daemon: stop then start in a background worker."""
    if self._axe_worker is not None:
        return
    self._set_axe_stopping(True)

    def _do_restart() -> tuple[bool, str]:
        proc = get_axe_process_module()
        stopped = proc.stop_axe_daemon()
        if not stopped:
            return (False, "Axe was not running")
        pid = proc.start_axe_daemon()
        if pid is not None:
            return (True, f"Axe restarted (pid {pid})")
        return (False, "Failed to restart axe")

    self._axe_worker = self.run_worker(_do_restart, thread=True)
```

This reuses the existing `_on_axe_worker_done` handler (already wired via worker state changes) for completion.

## Files Modified

1. `src/sase/main/parser_ace.py` — new `--restart-axe` argument
2. `src/sase/main/ace_handler.py` — pass `restart_axe` to `AceApp`
3. `src/sase/ace/tui/app.py` — new `__init__` param, `on_mount` restart logic
4. `src/sase/ace/tui/actions/axe.py` — new `_restart_axe_daemon()` method
