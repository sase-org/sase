---
bead_id: sase-0xd
---

# Plan: Rewrite `sase axe` with Jack/Chop Architecture

## Context

The current `sase axe` command is a monolithic `AxeScheduler` (in `src/sase/axe/core.py`) that runs 13 periodic jobs in
a single process. This makes it hard to replicate individual checks, debug failures, or reconfigure schedules. The
rewrite decomposes axe into **jacks** (configurable routines with a schedule) and **chops** (individual checks),
enabling:

- Each check to be run independently via `sase axe chop run <name>`
- Jacks to run as isolated subprocesses with independent logs
- Configuration of which chops belong to which jack and at what interval
- Per-jack output viewing in the TUI via `ctrl+n`/`ctrl+p`

---

## Configuration Schema (sase.yml)

```yaml
axe:
  # Global settings shared across all jacks
  max_runners: 5
  zombie_timeout_seconds: 7200
  query: ""
  use_legacy_axe: true # Temporary: TUI !x starts sase ax instead of sase axe

  # Jack definitions
  jacks:
    hooks:
      interval: 1 # seconds
      chops:
        - hook_checks
        - mentor_checks
        - workflow_checks
        - pending_checks_poll
        - comment_zombie_checks
        - suffix_transforms
        - orphan_cleanup

    checks:
      interval: 300 # 5 minutes
      chops:
        - cl_submitted_checks
        - stale_running_cleanup

    comments:
      interval: 60 # 1 minute
      chops:
        - comment_checks

    housekeeping:
      interval: 3600 # 1 hour
      chops:
        - error_digest
```

Chops are registered in Python code via `@register_chop("name")`. Users configure only grouping and schedule in YAML.
Status/metrics writing is built-in jack infrastructure, not a chop.

## Chop Inventory (11 chops)

| Chop Name               | Wraps                                      | Source                |
| ----------------------- | ------------------------------------------ | --------------------- |
| `hook_checks`           | `HookJobRunner.run_hook_checks`            | `axe/hook_jobs.py`    |
| `mentor_checks`         | `HookJobRunner.run_mentor_checks`          | `axe/hook_jobs.py`    |
| `workflow_checks`       | `HookJobRunner.run_workflow_checks`        | `axe/hook_jobs.py`    |
| `pending_checks_poll`   | `HookJobRunner.run_pending_checks_poll`    | `axe/hook_jobs.py`    |
| `comment_zombie_checks` | `HookJobRunner.run_comment_zombie_checks`  | `axe/hook_jobs.py`    |
| `suffix_transforms`     | `HookJobRunner.run_suffix_transforms`      | `axe/hook_jobs.py`    |
| `orphan_cleanup`        | `HookJobRunner.run_orphan_cleanup`         | `axe/hook_jobs.py`    |
| `cl_submitted_checks`   | `CheckCycleRunner.run_full_check_cycle`    | `axe/check_cycles.py` |
| `stale_running_cleanup` | `HookJobRunner.run_stale_running_cleanup`  | `axe/hook_jobs.py`    |
| `comment_checks`        | `CheckCycleRunner.run_comment_check_cycle` | `axe/check_cycles.py` |
| `error_digest`          | `AxeScheduler._run_error_digest`           | `axe/core.py`         |

## State Directory Layout

```
~/.sase/axe/
  orchestrator.pid
  jacks/
    hooks/
      pid
      status.json
      metrics.json
      logs/output.log
    checks/
      ...
    comments/
      ...
    housekeeping/
      ...
  shared/
    runner_count          # File-based atomic counter for cross-process RunnerPool
    recent_errors.json
  bgcmd/                  # Existing bgcmd slots (unchanged)
```

## New Module Structure

```
src/sase/
  ax/                        # LEGACY quarantine (copy of old axe/)
    __init__.py, core.py, process.py, state.py,
    check_cycles.py, hook_jobs.py, runner_pool.py

  axe/                       # NEW architecture
    __init__.py
    config.py                # AxeConfig, JackConfig dataclasses + loader
    chop_registry.py         # @register_chop, ChopContext, get_chop, list_chops
    chops/                   # One module per chop (11 files)
      __init__.py            # Imports all to trigger registration
      hook_checks.py, mentor_checks.py, workflow_checks.py,
      pending_checks_poll.py, comment_zombie_checks.py,
      suffix_transforms.py, orphan_cleanup.py,
      cl_submitted_checks.py, stale_running_cleanup.py,
      comment_checks.py, error_digest.py
    jack.py            # Jack class (single-jack scheduler loop)
    orchestrator.py          # Starts/monitors all jack subprocesses
    process.py               # Start/stop daemon (replaces old process.py)
    state.py                 # Per-jack state management
    runner_pool.py           # SharedRunnerPool (file-based cross-process locking)
    cli.py                   # Handlers for axe jack / axe chop subcommands
```

---

## Phases

### Phase 1: Quarantine Legacy Code → `sase ax` (PARALLEL)

**Goal**: Move current axe code to `sase ax` so `sase axe` is free for the new implementation.

**Tasks**:

1. Create `src/sase/ax/` by copying files from `src/sase/axe/` (core.py, process.py, state.py, check_cycles.py,
   hook_jobs.py, runner_pool.py, `__init__.py`)
2. Update all internal imports in `src/sase/ax/` from `sase.axe.*` → `sase.ax.*`
3. Add `ax` subcommand to `src/sase/main/parser.py` (same args as current `axe`)
4. Add `ax` handler to `src/sase/main/entry.py` importing from `sase.ax`
5. Add `use_legacy_axe: true` to chezmoi `sase.yml` under `axe:`
6. Update `src/sase/axe_config.py` to parse `use_legacy_axe` field
7. Update TUI `src/sase/ace/tui/actions/axe.py`: when `use_legacy_axe` is true, `_start_axe()` calls `sase ax` instead
   of `sase axe`
8. Update `src/sase/axe/process.py` `start_axe_daemon()` to check `use_legacy_axe` and run `sase ax` if true

**Files created**: `src/sase/ax/` (7 files) **Files modified**: `parser.py`, `entry.py`, `axe_config.py`, `axe.py` (TUI
mixin), `process.py`, chezmoi `sase.yml` **Verify**: `just check` passes. `sase ax --help` works. TUI `!x` starts/stops
`sase ax`.

---

### Phase 2: Chop Registry + Implementations (PARALLEL)

**Goal**: Create the chop abstraction and implement all 11 chops as thin wrappers around existing logic.

**Tasks**:

1. Create `src/sase/axe/chop_registry.py`:
   - `ChopContext` dataclass (log callback, runner_pool, metrics, parsed_query, max_runners, zombie_timeout,
     changespecs, jack_name, state_dir)
   - `@register_chop("name")` decorator
   - `get_chop(name)`, `list_chops()`, `get_all_chops()` functions
2. Create `src/sase/axe/chops/__init__.py` that imports all chop modules
3. Create 11 chop modules in `src/sase/axe/chops/`, each wrapping existing code:
   - Each chop is a function decorated with `@register_chop("name")` that takes `ChopContext`
   - Delegates to existing `CheckCycleRunner` / `HookJobRunner` methods
   - Minimal new logic - thin wrapper only
4. Write tests for chop registry (registration, lookup, listing)

**Files created**: `chop_registry.py`, `chops/__init__.py`, 11 chop modules, test file **Files modified**: None
**Verify**: `just check` passes. `from sase.axe.chop_registry import list_chops; list_chops()` returns 11 names.

---

### Phase 3: Config + State + SharedRunnerPool (PARALLEL)

**Goal**: New config loading for jack YAML schema, per-jack state management, cross-process runner pool.

**Tasks**:

1. Create `src/sase/axe/config.py`:
   - `JackConfig` dataclass (name, interval, chops list)
   - `AxeConfig` dataclass (max_runners, zombie_timeout, query, use_legacy_axe, jacks dict)
   - `load_axe_config()` that parses new schema with backward compat (if no `jacks:` key, generate defaults from old
     flat config)
2. Create `src/sase/axe/state.py`:
   - Per-jack directory creation (`~/.sase/axe/jacks/{name}/`)
   - PID file read/write per jack
   - `JackStatus` / `JackMetrics` dataclasses
   - Status/metrics/log writing per jack
   - Output log tail reading per jack (for TUI)
3. Create `src/sase/axe/runner_pool.py`:
   - `SharedRunnerPool` using `fcntl.flock` on `~/.sase/axe/shared/runner_count`
   - `reserve_slot()`, `release_slot()`, `get_current_runners()`, `is_at_limit()`
   - Wraps existing `count_all_runners_global()` for backward compat
4. Write tests for config loading, state management, shared runner pool

**Files created**: `config.py`, `state.py`, `runner_pool.py`, test files **Files modified**: May update
`src/sase/axe_config.py` (or replace it) **Verify**: `just check` passes. Config loads from both old and new YAML
formats. State dirs created correctly.

---

### Phase 4: Jack + Orchestrator + CLI (depends on Phases 1, 2, 3)

**Goal**: Implement the Jack class, orchestrator, CLI subcommands, and wire everything together.

**Tasks**:

1. Create `src/sase/axe/jack.py`:
   - `Jack` class with `run()` main loop using `schedule` library
   - On each tick: refresh changespecs once, build `ChopContext`, iterate chops
   - PID file, SIGTERM handler, status/metrics writing (built-in infrastructure)
   - Output logging to `~/.sase/axe/jacks/{name}/logs/output.log`
2. Create `src/sase/axe/orchestrator.py`:
   - `Orchestrator` class that spawns each jack as `sase axe jack run <name>`
   - Monitor child processes, handle SIGTERM by forwarding to children
   - Write orchestrator PID file, aggregate status
3. Create `src/sase/axe/process.py` (new):
   - `start_axe_daemon()` - starts orchestrator as daemon
   - `stop_axe_daemon()` - SIGTERM to orchestrator
   - `is_axe_running()` - checks orchestrator PID
   - `get_axe_status()` - reads orchestrator + per-jack status
   - `get_jack_names()` - returns active jack names
4. Create `src/sase/axe/cli.py`:
   - `sase axe chop list` - print all registered chops
   - `sase axe chop run <name>` - run single chop once, exit
   - `sase axe jack list` - print configured jacks from sase.yml
   - `sase axe jack run <name>` - run single jack in foreground
   - `sase axe jack status` - show status of all jacks
5. Update `src/sase/main/parser.py`:
   - Replace flat `axe` parser with nested subparsers: `axe jack {list,run,status}`, `axe chop {list,run}`
   - `sase axe` with no subcommand → orchestrator mode
6. Update `src/sase/main/entry.py`:
   - Route `axe` subcommands to `cli.py` handlers
   - Route bare `sase axe` to orchestrator
7. Update `src/sase/axe/__init__.py` with new public API
8. Write tests

**Files created**: `jack.py`, `orchestrator.py`, `process.py` (new), `cli.py`, test files **Files modified**:
`parser.py`, `entry.py`, `__init__.py` **Verify**: `just check` passes. `sase axe chop list` prints 11 chops.
`sase axe jack list` prints 4 jacks. `sase axe jack run hooks` runs in foreground. `sase axe` starts orchestrator
spawning 4 jack processes.

---

### Phase 5: TUI Integration (depends on Phase 4)

**Goal**: Update AXE tab to show per-jack outputs with `ctrl+n`/`ctrl+p` cycling.

**Tasks**:

1. Update `src/sase/ace/tui/actions/axe.py`:
   - Add `_axe_jack_names: list[str]` and `_axe_jack_idx: int` state
   - When on AXE tab with axe view selected, `ctrl+n`/`ctrl+p` cycle through jack outputs
   - `_refresh_axe_display()` reads from current jack's `output.log`
   - `_load_axe_status()` reads per-jack status and builds name list
   - Import new `process.py` functions (`get_jack_names`)
   - When `use_legacy_axe` is true, maintain old single-output behavior
2. Update `src/sase/ace/tui/widgets/axe_dashboard.py`:
   - Add jack name label at top of output section (e.g., `[hooks] (1/4)`)
   - `update_display()` accepts jack name + index + total
3. Update `src/sase/ace/tui/app.py`:
   - Bind `ctrl+n`/`ctrl+p` on AXE tab to jack cycling actions
   - Update footer to show navigation hint when on axe view
4. Update help modal for new AXE tab keybindings

**Files modified**: `actions/axe.py`, `widgets/axe_dashboard.py`, `app.py`, help modal **Verify**: `just check` passes.
TUI AXE tab shows jack name. `ctrl+n`/`ctrl+p` cycles through outputs.

---

### Phase 6: Cleanup (depends on Phase 5)

**Goal**: Remove legacy `sase ax`, `use_legacy_axe`, and all compatibility shims.

**Tasks**:

1. Delete `src/sase/ax/` directory entirely
2. Remove `ax` subcommand from `parser.py` and `entry.py`
3. Remove `use_legacy_axe` from config dataclass and all code that checks it
4. Remove `use_legacy_axe: true` from chezmoi `sase.yml`
5. Remove backward-compat config parsing (old flat `axe:` format without `jacks:`)
6. Delete any `tests/test_ax_*.py`
7. Remove old `src/sase/axe_config.py` if fully replaced by `src/sase/axe/config.py`

**Files deleted**: `src/sase/ax/` (entire dir), old test files, possibly `axe_config.py` **Files modified**:
`parser.py`, `entry.py`, config files, TUI `axe.py` **Verify**: `just check` passes. `sase ax` no longer exists. No
references to `sase.ax` or `use_legacy_axe` in codebase.

---

## Phase Dependencies

```
Phase 1 (Quarantine) ──────┐
Phase 2 (Chop Registry) ───┼──→ Phase 4 (Jack+Orchestrator+CLI)
Phase 3 (Config+State) ────┘              │
                                          ▼
                                    Phase 5 (TUI)
                                          │
                                          ▼
                                    Phase 6 (Cleanup)
```

Phases 1, 2, 3 run in parallel (3 agents). Phases 4-6 are sequential.
