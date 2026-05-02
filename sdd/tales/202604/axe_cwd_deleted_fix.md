---
create_time: 2026-04-23 17:45:58
status: done
prompt: sdd/prompts/202604/axe_cwd_deleted_fix.md
---
# Plan: Fix `sase axe` chop failures caused by a deleted CWD

## Problem

The error digest `.sase/home/.sase/axe/error_digests/digest_20260423_174048.txt` records 8 errors across three
`sase axe` lumberjack cycles. Five of them are the same crash:

```
FileNotFoundError: [Errno 2] No such file or directory
  File ".../pathlib/__init__.py", line 927, in cwd
    cwd = os.getcwd()
  File ".../sase/config/core.py", line 138, in _get_local_config_path
    local_path = Path.cwd() / "sase.yml"
  File ".../sase/core/time.py", line 19, in get_timezone
    config = load_merged_config()
```

The failing callers are the chop entry points `sase_chop_suffix_transforms` and `sase_chop_comment_checks`. Each one
calls `datetime.now(get_timezone())` on its first real line of work; `get_timezone()` loads the merged config, which
calls `Path.cwd()`, which raises because the process's current-working-directory inode no longer exists.

The other three errors in the digest are `pending_checks_poll timed out after 90s`. That timeout almost certainly shares
the same root cause — when the chop subprocess inherits a dead CWD, it produces no output and the parent lumberjack
kills it once the chop-level timeout elapses (90 s is the configured timeout for that chop). It is _not_ worth modelling
this as a separate bug; once the CWD fix lands, the timeout should stop reproducing. The plan will include a short
verification step to confirm that.

## Why the CWD is dead

The chops are launched from `src/sase/axe/chop_script_runner.py:75` via `subprocess.run([script, ...])` with **no `cwd=`
argument**, so the child inherits the parent `sase axe` daemon's CWD. The daemon itself never calls `os.chdir`, so the
CWD is simply wherever the user started `sase axe`. Given the tracebacks reference `sase_101/` (a `sase_<N>` ephemeral
workspace), the daemon was almost certainly launched inside that workspace, and a later workspace wipe/recreate cycle
replaced the directory inode. The daemon's kernel-level CWD pointer now references a deleted inode, and every subsequent
`os.getcwd()` — in the daemon itself and in every chop subprocess it spawns — fails.

This is a well-known Unix footgun: removing the directory a long-lived process is `chdir`'d into leaves the process with
a dangling CWD that cannot be recovered without an explicit `os.chdir` to a surviving directory.

## Design principles

Two independent layers of protection are warranted because each one defends against a different failure mode:

1. **Don't let `get_timezone()` / `load_merged_config()` crash on a missing CWD.** The merged config loader only uses
   the CWD to look for a repo-local `sase.yml` override. If the CWD is gone, there cannot be a local override, so
   returning `None` is semantically correct. Today this code path is a tripwire for every caller of `get_timezone()`,
   and `get_timezone()` is called from dozens of places (logging, timestamps, chop drivers). One defensive `try/except`
   removes the tripwire for all of them.

2. **Don't let chop subprocesses inherit a dangling CWD in the first place.** Even with the config loader hardened,
   other user code inside chops will hit the same problem (anything that calls `Path.cwd()`, `os.listdir('.')`, relative
   paths, etc.). Passing an explicit, guaranteed-to-exist `cwd=` to `subprocess.run` in the chop runner isolates chops
   from whatever state the daemon is in.

3. **Stabilize the daemon's own CWD at startup.** Even with the two fixes above, logging and other code in the axe
   daemon will still occasionally touch the CWD and could misbehave if the daemon was started in a doomed directory. A
   one-liner `os.chdir(os.path.expanduser("~"))` at the top of `Lumberjack.run()` turns this into a non-issue for all
   future axe invocations.

We want all three. Layer 1 is the smallest/most-targeted fix and unblocks the user immediately; Layers 2 and 3 harden
the system against related failures without changing observable behavior for healthy runs.

## Plan

### 1. Harden `_get_local_config_path`

File: `src/sase/config/core.py`

Wrap the `Path.cwd()` call so that a missing CWD degrades gracefully to "no local override". `FileNotFoundError` is the
only new exception to catch; everything else (permission errors, etc.) should continue to propagate. Add a short comment
explaining _why_ — "the axe daemon can outlive its CWD if a workspace it was launched from is wiped" — so a future
reader doesn't delete the guard thinking it's paranoia.

### 2. Pass an explicit `cwd=` when launching chop scripts

Files: `src/sase/axe/chop_script_runner.py`, `src/sase/axe/lumberjack.py`

Add a `cwd: str | None = None` parameter to `run_chop_script()` and forward it to `subprocess.run(..., cwd=cwd)`.
Default `None` preserves the current call-site semantics for anyone else invoking the helper (the change is
back-compatible).

In `Lumberjack._run_single_chop` (the only in-tree caller for non-agent chops), pass a stable directory. The
lumberjack's own `self._state_dir` is a natural choice: it is created on startup, never wiped during the daemon's
lifetime, and semantically tied to the daemon.

Also update the related mocked test in `tests/test_axe_chop_script_runner.py` to cover the new `cwd=` argument and
confirm it is forwarded to the subprocess call.

### 3. Stabilize the daemon CWD at startup

File: `src/sase/axe/lumberjack.py`

Early in `Lumberjack.run()` (before the first `_log` that stamps a timestamp), call `os.chdir(os.path.expanduser("~"))`.
The home directory is guaranteed to exist on any Unix system, is stable across workspace wipes, and is unrelated to any
workspace directory the daemon might have been launched from.

This is a single line, but it eliminates an entire class of problems where the daemon process itself (not its chop
subprocesses) touches the CWD.

### 4. Verify the `pending_checks_poll` timeout is a secondary symptom

After implementing #1–#3, reproduce the failure mode locally (manual:
`mkdir /tmp/doomed && cd /tmp/doomed && python -c "import os; os.rmdir('/tmp/doomed'); ..."` style) or — if that is not
feasible — trigger a workspace wipe in a scratch axe run and confirm that:

- The `FileNotFoundError` traces stop appearing in the error digest.
- The `pending_checks_poll timed out after 90s` entries also stop appearing in subsequent cycles.

If the timeout still reproduces after the CWD fix lands, it is a genuinely independent bug and we should open a separate
investigation rather than couple it to this change.

## Out of scope

- **Root-cause fix for why anything deletes the directory the daemon is sitting in.** That is a workspace-lifecycle
  concern (`allow_retry` wipe paths, manual `rm -rf`, etc.). The three layers above make the daemon robust to the
  deletion happening at all, which is a better posture than playing whack-a-mole with individual deletion paths.
- **Switching chop-script discovery or execution strategy** (e.g., keeping chops in-process). Much bigger change,
  unrelated to this bug.
- **Restructuring `get_timezone()` to not hit the config loader at all.** Tempting, but changes far-reaching semantics
  (config-driven timezone) and is not necessary to fix the reported crash.

## Files touched

- `src/sase/config/core.py` — defensive `try/except` in `_get_local_config_path`.
- `src/sase/axe/chop_script_runner.py` — add `cwd=` parameter to `run_chop_script`.
- `src/sase/axe/lumberjack.py` — pass `self._state_dir` as chop cwd; `os.chdir(~)` at daemon startup.
- `tests/test_axe_chop_script_runner.py` — cover the new `cwd=` argument.

## Verification

- `just check` passes (lint + mypy + tests).
- New/updated unit test confirms `run_chop_script` forwards `cwd=` to `subprocess.run`.
- New unit test confirms `_get_local_config_path` returns `None` (instead of raising) when `Path.cwd()` raises
  `FileNotFoundError`.
- Manual check: after restarting `sase axe`, the error digest stops accruing `FileNotFoundError` entries across a
  workspace-wipe cycle.
