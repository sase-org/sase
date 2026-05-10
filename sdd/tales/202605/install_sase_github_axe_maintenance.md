---
create_time: 2026-05-01 01:54:59
status: done
prompt: sdd/prompts/202605/install_sase_github_axe_maintenance.md
---
# Plan: Make `install_sase_github` Safe While Axe Is Running

## Problem

Running `install_sase_github` can temporarily break the global uv-tool `sase` environment while the axe daemon is still
running. The observed axe digest from `2026-05-01T01:32` shows `waits` and `telegram` chops failing with:

```text
ModuleNotFoundError: No module named 'sase_core_rs.sase_core_rs'
ImportError: sase_core_rs is not importable in this environment
```

The uv-tool environment is healthy after the installer finishes, so this is not a permanent package-resolution failure.
It is a live-update race:

1. `install_sase_github` runs `uv tool install --force --editable ...`.
2. It then runs `just -f "$SASE_DIR/Justfile" rust-install-uv-tool`.
3. `rust-install-uv-tool` delegates to `rust-install`, which currently purges native `sase_core_rs` extension artifacts
   before `maturin develop --release` rebuilds them.
4. During that purge/build window, fast axe chops continue to run:
   - `waits.wait_checks` every 2 seconds
   - `telegram.tg_outbound` every 5 seconds
   - other periodic chops depending on timing
5. Those subprocesses import the package from the same uv-tool venv and fail because `sase_core_rs/__init__.py` exists
   but the native extension does not.
6. The `housekeeping.error_digest` chop later emits `ViewErrorReport` notifications for the expected transient failures.

The current installer already includes the previous local `sase-core-rs` resolver fix, so the remaining issue is update
atomicity while background automation is active.

## Goals

- Running `install_sase_github` should not produce axe error digests from expected install/rebuild windows.
- The uv-tool `sase` environment should never be observed by scheduled chops in a known broken intermediate state.
- The fix should work for sibling installer scripts with the same shape, especially `install_retired_mercurial_plugin`.
- Existing axe jobs should resume automatically after a successful install.
- If installation fails, the user should get a clear install failure and axe should not silently keep running against a
  broken environment.

## Non-Goals

- Do not suppress all axe errors globally.
- Do not make notification delivery ignore real failures.
- Do not remove the Rust backend hard dependency from production code.
- Do not depend on the user manually stopping `sase ace` or axe before installs.

## Recommended Design

Use a two-layer fix: a robust installer wrapper immediately prevents the current failure, and a small axe maintenance
mode makes future tool/environment updates explicit and reusable.

### Phase 1: Installer-Level Axe Quiescing

Update the chezmoi-managed installer scripts:

- `~/.local/share/chezmoi/home/bin/executable_install_sase_github`
- `~/.local/share/chezmoi/home/bin/executable_install_retired_mercurial_plugin`

Before modifying the uv-tool venv:

1. Detect whether axe is running.
2. If running, stop it with `sase axe stop`.
3. Run the git sync, optional `uv tool install --force --editable ...`, and `rust-install-uv-tool`.
4. Run a post-install health probe:
   - `$(uv tool dir)/sase/bin/python -c "import sase_core_rs; ..."`
   - `sase core health --json`
5. Restart axe only after the health probe succeeds, and only if it was running before the install.

Add `trap` handling so failures are explicit:

- If the install fails before health is restored, do not blindly restart axe.
- Print a targeted message that axe was left stopped because the uv-tool env may be incomplete.
- If the install succeeds but axe restart fails, return a non-zero exit with a clear restart message.

This phase directly prevents scheduled chops from running against a partially rebuilt venv.

### Phase 2: Axe Maintenance Sentinel

Add an axe maintenance marker in core, for example:

```text
~/.sase/axe/maintenance.json
```

with fields such as:

```json
{
  "reason": "install_sase_github",
  "pid": 12345,
  "started_at": "2026-05-01T..."
}
```

Add small helpers under `src/sase/axe/state.py` or a focused `maintenance.py` module:

- `enter_maintenance(reason: str) -> context manager`
- `read_maintenance() -> dict | None`
- `clear_stale_maintenance(max_age_seconds=...)`

Teach `Lumberjack._run_tick()` or the top of each chop loop to skip all chops while maintenance is active. The skip
should be logged as an informational line and should not increment the error counter. This gives the installer a stable
coordination primitive even if a future install path chooses not to stop axe completely.

Expose this in CLI form if useful:

```bash
sase axe maintenance enter --reason install_sase_github
sase axe maintenance exit
sase axe maintenance status
```

The installer can then create the marker before stopping/restarting, so already-running or recently-restarted
lumberjacks have a shared signal to stay quiet.

### Phase 3: Reduce the Broken Native-Extension Window

Review the `rust-install` implementation:

```just
{{ VENV }}/bin/python tools/purge_sase_core_rs_extensions
cd {{ sase_core_dir }}/crates/sase_core_py && \
    VIRTUAL_ENV={{ VENV }} \
    PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
    {{ VENV }}/bin/maturin develop --release
```

The purge step is the point where the environment becomes unimportable. Prefer one of these safer approaches:

1. Build a wheel outside the target venv, then install it into the venv in a single package-manager operation.
2. If purge remains necessary, restrict purge to stale duplicate artifacts and avoid deleting the only importable native
   extension before the replacement has been built.
3. Add a dedicated `rust-install-uv-tool-safe` target used by installer scripts, with a post-build import probe and no
   long unimportable window.

This is a hardening phase; Phase 1 is still needed because `uv tool install --force` can also replace scripts while
background chops are active.

### Phase 4: Error Digest Hygiene

Do not filter away the `sase_core_rs` ImportError as a general rule. Once maintenance exists, expected install windows
should not create errors at all.

After the scheduler skips maintenance windows, add a narrow guard so `error_digest` does not notify for maintenance
metadata itself. It should continue to report any real chop failure that occurs outside maintenance.

## Validation Plan

### Chezmoi

Run:

```bash
cd ~/.local/share/chezmoi
just check
```

After changes are committed/applied:

```bash
chezmoi apply --force
```

### Core SASE

If Phase 2 or Phase 3 touches core:

```bash
cd /home/bryan/projects/github/sase-org/sase_101
just install
just check
```

Add focused tests for:

- maintenance marker read/write and stale cleanup
- lumberjack tick skips chops without recording errors while maintenance is active
- maintenance skip does not suppress normal errors after the marker is cleared
- installer health-probe helper behavior, if factored into a testable shell/Python helper

### Manual End-To-End

With axe running:

```bash
sase axe lumberjack status
install_sase_github -i
"$(uv tool dir)/sase/bin/python" -c "import sase_core_rs; print('ok')"
sase core health --json
sase axe lumberjack status
```

Then confirm:

- no new `ModuleNotFoundError: sase_core_rs.sase_core_rs` entries appear in `~/.sase/axe/recent_errors.json`
- no new axe error digest notification is appended for the install window
- telegram outbound still works after restart

## Files Expected To Change

Immediate fix:

- `~/.local/share/chezmoi/home/bin/executable_install_sase_github`
- `~/.local/share/chezmoi/home/bin/executable_install_retired_mercurial_plugin`

Core hardening:

- `src/sase/axe/state.py` or new `src/sase/axe/maintenance.py`
- `src/sase/axe/lumberjack.py`
- `src/sase/main/parser_ace.py`
- `src/sase/main/axe_handler.py`
- `Justfile`
- focused tests under `tests/`

## Rollout Order

1. Implement Phase 1 in chezmoi first because it eliminates the user-visible failure quickly.
2. Apply chezmoi and run `install_sase_github -i` with axe running to verify no digest spam.
3. Implement Phase 2 in core if we want a durable primitive for any future environment update.
4. Evaluate Phase 3 after Phase 1 is stable; it is valuable, but not required to stop the current notifications.
