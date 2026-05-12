---
create_time: 2026-05-11 18:46:32
bead_id: sase-2x
tier: epic
status: done
prompt: sdd/prompts/202605/manual_chop_runs_live_output.md
---

# Manual Chop Runs and Live Chop Output Plan

## Goal

Add an AXE TUI workflow that lets the user run the currently selected chop manually, and make every running chop's
captured command output update live in the AXE tab.

This work should preserve the current AXE-tab performance model: navigation and ordinary repaint paths render from
in-memory caches populated by async/background collectors, not from synchronous disk reads in `j`/`k`, `ctrl+n`,
`ctrl+p`, or row rendering.

## Current System Shape

The relevant implementation is already concentrated in a few modules:

- `src/sase/axe/lumberjack.py` owns scheduled chop execution. Script chops currently use
  `subprocess.run(..., capture_output=True)`, so output is available only after the subprocess exits. Agent chops record
  a completed `agent_launched` history entry after launch.
- `src/sase/axe/chop_script_runner.py` owns script discovery and the existing foreground `run_chop_script` helper.
- `src/sase/axe/cli.py` and `src/sase/main/parser_ace.py` expose `sase axe chop run <name>`, but the current command is
  foreground-only, identifies chops only by chop name, and does not write the same per-lumberjack run history used by
  the AXE TUI.
- `src/sase/axe/state.py` owns `ChopRunEntry`, per-chop run logs, the run index, bounded tail readers, lumberjack logs,
  and AXE state directories. `ChopRunStatus` currently has only terminal states: `success`, `failure`, `timeout`,
  `missing_script`, and `agent_launched`.
- `src/sase/ace/tui/actions/axe_display/_data.py` collects configured lumberjacks, chop snapshots, run metadata, and
  output tails off the UI thread.
- `src/sase/ace/tui/actions/axe_display/_loaders.py` applies collector data, derives selected chop identity, maintains
  per-chop run offsets, and implements targeted refresh for `y`.
- `src/sase/ace/tui/actions/axe_display/_render.py`, `src/sase/ace/tui/widgets/bgcmd_list.py`, and
  `src/sase/ace/tui/widgets/axe_dashboard.py` render sidebar rows and chop detail panels from cached snapshots.
- `src/sase/ace/tui/actions/base.py` dispatches `r` on the AXE tab today only for done background-command reruns.
- `src/sase/ace/tui/widgets/_keybinding_bindings.py` computes AXE footer affordances. It already shows `r re-run` for
  completed bgcmds and `ctrl+n` / `ctrl+p` for chop run history.

Existing tests that should guide the implementation:

- `tests/ace/tui/test_axe_navigation.py`: AXE navigation must not read from disk.
- `tests/ace/tui/test_axe_collector.py`: collector payloads must contain the cache data the render path needs.
- `tests/ace/tui/test_axe_force_refresh.py`: targeted refresh should be narrow and non-blocking.
- `tests/ace/tui/test_axe_chop_selection.py` and `tests/ace/tui/test_axe_chop_run_nav.py`: selected chop identity and
  run-history navigation semantics.
- `tests/test_axe_lumberjack_state.py`, `tests/test_axe_lumberjack.py`, `tests/test_axe_lumberjack_agent_chops.py`, and
  `tests/test_axe_chop_script_runner.py`: backend state and chop execution contracts.

## Product Design

Use the existing AXE `r` action for manual chop runs:

- On a selected `ChopItem`, `r` runs that exact `(lumberjack_name, chop_name)` manually.
- On a selected done `BgCmdItem`, `r` keeps the current background-command re-run behavior.
- On lumberjack rows and running bgcmd rows, `r` remains unavailable/no-op.

Manual chop runs should be operationally visible:

- A manual run creates a normal chop run-history entry for the selected lumberjack/chop, so it appears as the newest run
  and participates in the existing `ctrl+n` / `ctrl+p` history.
- Scheduled and manual runs use the same output streaming and metadata format. Any difference should be represented as
  explicit metadata, not as a separate storage system.
- A manual run bypasses `run_every` cadence, because the user explicitly requested it.
- A manual run should use the selected chop's configured environment, timeout, agent prompt, and parent lumberjack's
  default `chop_timeout`.
- If the selected chop already has a live script run, the conservative first behavior should be to notify and skip the
  launch rather than start an overlapping duplicate. Agent chops should keep the existing live-agent dedupe semantics.

Live output behavior:

- Script chop run logs must be appended while the subprocess is running, not written only at process exit.
- A running script chop should have a run-history metadata entry immediately, with a `running` status, `started_at`,
  optional `pid`, no `finished_at` yet, and the log filename.
- As output arrives, the per-run log file grows. The collector tails the newest runs and the dashboard displays the
  current tail. If the user is looking at the newest run of a running chop, the detail panel should update on normal AXE
  refresh ticks and targeted refreshes without the user leaving the row.
- When the process exits, the same run entry is finalized with terminal status, exit code, duration, error/traceback
  when applicable, and final output byte count.

## Data Contract

Extend the existing per-chop run-history model rather than introducing a second manual-run registry:

```text
~/.sase/axe/lumberjacks/<lumberjack>/
  chops/
    <chop>/
      runs/
        <run-id>.json
        <run-id>.log
      index.json
```

Recommended `ChopRunEntry` additions:

- `status`: add `running` to the existing terminal status set.
- `finished_at`: change to nullable for active runs.
- `duration_ms`: allow `0` or computed elapsed duration for active runs; the TUI can format elapsed runtime from
  `started_at` while status is `running`.
- `pid`: script chop subprocess PID. Keep `agent_pid` for agent chops unless a broader cleanup is worthwhile.
- `source`: `scheduled`, `manual`, or `oneshot` so UX and debugging can distinguish why a run started.
- `started_by`: optional short identifier reserved for future use; for now the TUI can set `ace`.

State helper expectations:

- `start_chop_run(...)` writes the initial metadata and index entry before command execution starts.
- `append_chop_run_output(...)` or a file-handle-oriented helper appends command output to the run log as chunks arrive.
- `finish_chop_run(...)` atomically updates metadata with terminal status and prunes history to the newest 10 once the
  run is finished. Running entries must remain visible and must not be pruned out from under an active process.
- `read_chop_run_index(...)`, `read_chop_run(...)`, and `read_chop_run_log_tail(...)` remain bounded and tolerant of
  missing/corrupt files.

## Phase 1: Streaming Run State for Script Chops

Owner: backend/state and runner agent.

Scope:

- Extend `ChopRunStatus` / `ChopRunEntry` in `src/sase/axe/state.py` to represent active runs.
- Add state helpers for starting, appending output to, and finishing a run.
- Refactor script execution in `src/sase/axe/chop_script_runner.py` to support a streaming mode based on `Popen`, with
  stdout and stderr combined in output order when feasible. Keep the existing `run_chop_script` API compatible for
  current foreground callers/tests, or introduce a second streaming helper and migrate scheduled execution to it.
- Update `Lumberjack._run_single_chop` so scheduled script chops create a run entry before the subprocess starts, append
  output live, and finalize the same entry on success, failure, timeout, missing script, and Python exceptions.
- Preserve the aggregate lumberjack log behavior, but do not rely on it for per-chop command output.
- Include subprocess PID in active script run metadata and clean it up/finalize correctly on timeout.

Tests:

- Add/extend `tests/test_axe_lumberjack_state.py` for active run creation, nullable `finished_at`, finalization, pruning
  with active runs present, and bounded tail reads during an active run.
- Add/extend `tests/test_axe_chop_script_runner.py` for streaming stdout/stderr chunks, cwd/env propagation, timeout,
  and return status.
- Add lumberjack tests proving a long-running script writes output before it exits and finalizes the same run id.

Acceptance:

- A script chop that prints, sleeps, then prints again has readable first output in its per-run log before process exit.
- Terminal metadata updates the same run entry rather than creating a second entry.
- Existing scheduled chop behavior and tests still pass.

## Phase 2: Reusable Manual Chop Runner and CLI Contract

Owner: backend/manual-run agent.

Scope:

- Extract a reusable `run_configured_chop_once(...)` service, likely in a new `src/sase/axe/chop_runner.py` or adjacent
  module, that can run one configured chop by `(lumberjack_name, chop_name)` using the same context-building,
  environment, timeout, state, and streaming run-history contract as the scheduled path.
- Make the service support `source="manual"` and `source="scheduled"` without duplicating execution logic between the
  scheduler, CLI, and TUI.
- Add config lookup by exact lumberjack and chop. Preserve existing `sase axe chop run <name>` behavior for backwards
  compatibility, but add an explicit lumberjack selector for duplicate chop names, such as
  `sase axe chop run <name> --lumberjack <lumberjack>`.
- For script chops, run in the foreground for CLI callers while still writing the live run-history log. For TUI callers,
  expose a non-blocking launch helper that starts a detached one-shot process or submits safe worker-thread work without
  freezing the UI. Prefer a real subprocess if feasible so a manual run is not killed just because the TUI exits.
- For agent chops, route through `launch_agent_from_cwd` with the same chop metadata env already used by scheduled agent
  chops, and record the run under the selected lumberjack rather than `_oneshot`.
- Implement live-run detection for `(lumberjack_name, chop_name)`. If a script chop is already running, return a typed
  "already running" result so the TUI can notify without racing another copy.

Tests:

- Add CLI tests in `tests/test_axe_cli.py` for `--lumberjack`, duplicate-name disambiguation, missing lumberjack/chop,
  script env/timeout inheritance, and run-history recording.
- Add backend tests for manual source metadata and live-run dedupe.
- Add agent-chop tests that manual launches keep chop env metadata and registry recording consistent.

Acceptance:

- `sase axe chop run hook_checks --lumberjack hooks` writes a run entry under `hooks/chops/hook_checks`.
- A duplicate chop name requires or honors explicit lumberjack selection.
- Manual runs bypass `run_every` but respect timeout and configured env.

## Phase 3: TUI Manual Run Action and Footer Affordance

Owner: TUI action/keybinding agent.

Scope:

- Extend `BaseActionsMixin.action_run_workflow` on the AXE tab:
  - selected done `BgCmdItem` continues to re-run bgcmds;
  - selected `ChopItem` dispatches to a new `_run_selected_chop(...)` path;
  - other AXE rows remain no-op.
- Add an AXE mixin helper that resolves the selected `ChopItem`, invokes the manual-run backend without blocking the UI,
  handles "already running" and launch errors, refreshes AXE cache after launch, and keeps selection on the same chop.
- Add a pending/launching indicator if the backend launch has a delay before the run entry appears. Keep this in TUI
  state, not in the durable run history unless a subprocess was actually started.
- Update `KeybindingFooter._compute_axe_bindings` so selected chops show `r run chop`. If the selected chop has a
  running newest run, the footer can show `r running` or hide the binding depending on the final backend behavior.
- Update default keymap docs/tests only if new key names are introduced. Prefer reusing existing `run_workflow` (`r`) so
  `src/sase/default_config.yml` does not need a new key.

Tests:

- Add tests beside `tests/ace/tui/test_axe_rerun_bgcmd.py` proving `r` dispatches to manual chop run for `ChopItem`
  while bgcmd behavior is unchanged.
- Add footer binding tests for selected chop, selected done bgcmd, and lumberjack row.
- Add tests for launch failure/already-running notifications and selection preservation.

Acceptance:

- Pressing `r` on a chop row starts exactly that selected chop.
- Existing bgcmd re-run behavior is unchanged.
- The TUI does not block while a manual script or agent chop starts.

## Phase 4: Live Collector and Dashboard Updates

Owner: TUI data/rendering agent.

Scope:

- Extend `ChopRunSnapshot` and dashboard rendering to handle `running` entries:
  - status label and color for running;
  - elapsed runtime display when `finished_at` is null;
  - optional script PID;
  - source marker for manual vs scheduled when compactly useful.
- Make `collect_chop_snapshot(...)` include active runs and their latest log tails. It already reads from bounded
  per-run metadata/logs, so the main change should be metadata interpretation and status display.
- Ensure auto-refresh updates selected running chop output. If the global refresh interval is too slow for "live"
  output, add a focused lightweight timer while the AXE tab is visible that targeted-refreshes:
  - the selected running chop;
  - any visible running chop row metadata needed for sidebar status markers.
- Avoid disk reads in `BgCmdList.update_list` and render/navigation paths. Live data should still arrive through
  collector or targeted async refresh.
- Keep run-history offset semantics intuitive: when a selected chop is pinned to the newest run (`offset == 0`), new
  output for that running run updates in place; when the user has moved to an older run (`offset > 0`), do not yank them
  back to newest unless the selected run disappears.

Tests:

- Extend `tests/ace/tui/test_axe_collector.py` for running run snapshots and output-tail changes.
- Extend `tests/ace/tui/widgets/test_axe_dashboard_chop_detail.py` for running status, elapsed display, PID/source
  metadata, and empty/still-growing output.
- Extend navigation disk-free tests to cover live-running chop rows.
- Add a focused async/TUI test that simulates a running run log changing and verifies targeted refresh updates the
  dashboard from cache.

Acceptance:

- While a selected script chop is running and appending output, the AXE detail panel shows new output without waiting
  for process exit.
- Sidebar chop status can indicate running state without synchronous row-level disk reads.
- `ctrl+n` / `ctrl+p` and `j` / `k` remain cache-only.

## Phase 5: Integration, Documentation, and Visual Verification

Owner: final integration agent.

Scope:

- Update `docs/axe.md` to document manual TUI chop runs, `sase axe chop run --lumberjack`, live output behavior, and
  duplicate chop-name rules.
- Update any help modal or command palette metadata if the AXE `r` binding is documented there.
- Add or update visual snapshot coverage for the AXE chop detail view when a run is `running`, if the existing PNG
  snapshot fixtures can do that deterministically.
- Run focused tests from all prior phases, then `just install` and `just check`.
- Do a manual smoke test with a temporary script chop that emits multiple lines over time:
  - start AXE/ACE or use the TUI launch path;
  - select the chop;
  - press `r`;
  - confirm the first line appears before the command exits;
  - confirm final status transitions to success/failure.

Acceptance:

- Documentation matches the shipped CLI/TUI behavior.
- Focused tests and `just check` pass.
- There is at least one test or smoke artifact proving output is visible before process completion.

## Risks and Decisions

- The core risk is trying to solve live output only in the TUI. That cannot satisfy the requirement because current
  scheduled script execution buffers output until the subprocess exits. The backend runner must stream output to the
  durable per-run log first.
- A real subprocess for TUI manual runs is more durable than a TUI worker thread. If implementation complexity is high,
  a worker thread is acceptable for a first pass only if the behavior is documented and tests prove the TUI stays
  responsive.
- The first implementation should not allow overlapping script runs for the same `(lumberjack, chop)`. That keeps state,
  logs, and shared resources predictable. A later feature can add an explicit "run another copy anyway" confirmation if
  there is demand.
- Agent chops do not have direct command stdout in the chop run log. Their run entry should stay as `agent_launched` and
  point users toward the agent's own logs/artifacts.
