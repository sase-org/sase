# Add Beads Epic Support to `sase axe`

## Context

Currently, beads epic orchestration is fully manual: a user creates an epic with `/bd:new_epic`, then manually runs
`/bd:next` in separate claude sessions to work each child bead, and finally runs `/bd:land_epic` to close the epic. This
plan automates that loop: `sase axe` will periodically discover projects with beads, find ready child beads, and
automatically dispatch agents to work them. When all children complete, it dispatches a landing agent to verify and
close the epic.

Additionally, the bd slash commands currently live in the global chezmoi repo but are sase-project-specific (they
reference `tools/sase_bd`). They should be migrated to the sase project repo.

---

## Phase 1: Migrate `/bd:*` Slash Commands + Update AGENT.md

### Goal

Move bd slash commands from chezmoi to the sase project repo and add AGENT.md instructions for multi-phase plans.

### Files to Create

- `.claude/commands/bd/new_epic.md` - copied from chezmoi, keep `tools/sase_bd` references (these are sase-project-level
  commands)
- `.claude/commands/bd/land_epic.md` - same
- `.claude/commands/bd/next.md` - same

### Files to Modify

- `AGENT.md` - add new section about multi-phase plans and epics:
  - When writing plans, if the plan seems large enough to benefit from multiple phases (each implemented by a distinct
    claude instance) **and you are not already working a child bead** (i.e., the current task is not associated with an
    epic's child bead), break the plan into numbered phases
  - When asked to implement a plan with multiple distinct phases, use `/bd:new_epic <plan_file>` to create an epic bead,
    child beads for each phase, and set up the bead dependencies correctly. **Then terminate the session WITHOUT
    implementing any of the work.** The `sase axe` scheduler will automatically pick up the child beads and dispatch
    agents to work them.

### Chezmoi Cleanup

- Delete `~/.local/share/chezmoi/home/dot_claude/commands/bd/new_epic.md`
- Delete `~/.local/share/chezmoi/home/dot_claude/commands/bd/land_epic.md`
- Delete `~/.local/share/chezmoi/home/dot_claude/commands/bd/next.md`
- Commit changes in chezmoi repo using `/commit` skill (NOT `git commit`)
- Run `chezmoi apply` to remove the deployed global copies

### Notes

- `/bd:new_epic` is already invokable by both users (via `/bd:new_epic <file>`) and Claude (via the Skill tool) since
  Claude Code discovers commands from both global and project-level `.claude/commands/` directories
- No additional skill creation needed

### Verification

- Verify `.claude/commands/bd/` contains all 3 files
- Verify AGENT.md has the new section
- Run `just lint`

---

## Phase 2: Create `work_epics` Core Module

### Goal

Create the core logic for discovering projects with beads, parsing `bd ready` output, and identifying what work needs to
be dispatched.

### Files to Create

#### `src/sase/axe/work_epics.py`

Data structures:

```python
@dataclass
class BeadProject:
    project_name: str
    project_file: str      # ~/.sase/projects/<name>/<name>.gp
    workspace_dir: str     # primary workspace directory (from WORKSPACE_DIR)

@dataclass
class ReadyChildBead:
    bead_id: str
    title: str
    parent_id: str         # epic bead ID (bead_id without .<N> suffix)
    project: BeadProject

@dataclass
class LandableEpic:
    bead_id: str
    title: str
    project: BeadProject

@dataclass
class WorkEpicsResult:
    ready_children: list[ReadyChildBead]
    landable_epics: list[LandableEpic]
    errors: list[str]
```

Key functions:

- `discover_bead_projects() -> list[BeadProject]` - Scan `~/.sase/projects/*/` for git projects with `.beads/`
  directories. Reuse `parse_workspace_dir()` from `src/sase/gh_workspace.py`. Skip projects without WORKSPACE_DIR,
  without `.git/`, or without `.beads/`.
- `is_child_bead(bead_id: str) -> bool` - Check for `.<N>` suffix pattern (e.g., `sase-abc.1`)
- `extract_parent_id(child_bead_id: str) -> str` - Strip `.<N>` suffix (e.g., `sase-abc.1` -> `sase-abc`)
- `_run_bd_command(args, workspace_dir) -> list[dict]` - Run `bd <args> --json` in workspace_dir via subprocess. Always
  run in the PRIMARY workspace dir (where `.beads/` exists).
- `scan_project_for_work(project, log) -> tuple[list[ReadyChildBead], list[LandableEpic], list[str]]` - Core logic:
  1. Run `bd ready --json` in project's primary workspace dir
  2. Separate into child beads (ID matches `.<N>` pattern) and non-child beads
  3. For child beads: create `ReadyChildBead` entries
  4. For non-child beads that appear to be epics (type == "epic"): check
     `bd list --json --status=in_progress --filter-parent <id>` for in-progress children. If none in-progress, add to
     `landable_epics`.
- `scan_all_projects(log) -> WorkEpicsResult` - Aggregate results across all projects

### Key Design Decisions

- Run `bd` directly (not `tools/sase_bd`) since the scanner always runs in the primary workspace dir where `.beads/`
  exists
- Use `--json` flag on all bd commands for reliable parsing
- Handle subprocess errors gracefully (log + continue, don't crash the scheduler)
- An epic in `bd ready` with no visible children means all children are either done or in-progress; we must check
  `bd list --status=in_progress --filter-parent` to distinguish

#### `tests/test_work_epics.py`

- Test `is_child_bead()` with `"sase-abc.1"` (True), `"sase-abc"` (False), `"sase-abc.12"` (True), `"sase-a.b.1"` (True)
- Test `extract_parent_id()`: `"sase-abc.1"` -> `"sase-abc"`, `"sase-abc.12"` -> `"sase-abc"`
- Test `discover_bead_projects()` with mocked filesystem
- Test `scan_project_for_work()` with mocked bd output

### Verification

- `just check` (fmt-check + lint + test)

---

## Phase 3: Create Epic Agent Runner + Launching Infrastructure

### Goal

Create the subprocess runner for bead agents and the workspace claiming / launching logic.

### Files to Create

#### `src/sase/axe_bead_runner.py`

Subprocess script launched by axe for each bead task. Simplified version of `axe_run_agent_runner.py` (follow its
patterns).

Arguments: `bead_id`, `project_dir` (primary workspace), `workspace_dir` (clone), `output_path`, `workspace_num`,
`project_file`, `action` (`work_child` or `land_epic`), `timestamp`

Flow:

1. `install_sigterm_handler("bead")`
2. Read bead details via `bd show <bead_id> --json` (run in `project_dir`, the primary workspace)
3. `os.chdir(workspace_dir)` (the clone workspace, for code work)
4. Build prompt based on action:
   - `work_child`: "Run `bd show <bead_id>` to see details. Complete the work described. When done, close with
     `bd close <bead_id>`. Do NOT close the parent epic bead." Include note that bd commands should be run from
     `<project_dir>` (the primary workspace) or using `tools/sase_bd` if it exists.
   - `land_epic`: Content from `land_epic.md` slash command, adapted to reference the specific bead_id and primary
     workspace dir.
5. `create_anonymous_workflow(prompt)` + `execute_workflow()` (same pattern as `axe_run_agent_runner.py`)
6. Write `done.json` marker to artifacts dir
7. In `finally`: `release_workspace()`, send notification

#### `src/sase/axe/bead_launcher.py`

Handles workspace claiming and subprocess launching for bead agents.

```python
# In-memory tracking of active bead agents (bead_id -> pid)
_active_beads: dict[str, int] = {}

def is_bead_active(bead_id: str) -> bool
    """Check if bead has a running agent (validate PID is alive)."""

def launch_child_bead_agent(bead: ReadyChildBead, log) -> bool
    """Mark bead in-progress, claim workspace, launch agent subprocess."""

def launch_land_epic_agent(epic: LandableEpic, log) -> bool
    """Mark epic in-progress, claim workspace, launch landing agent."""

def cleanup_dead_bead_entries(log) -> int
    """Remove entries for dead processes from _active_beads."""
```

Launch flow (follows `_start_crs_workflow` pattern in `src/sase/ace/scheduler/workflows_runner/starter.py`):

1. Run `bd update <bead_id> --status in_progress` in primary workspace dir
2. Call `get_first_available_axe_workspace(project_file)` for workspace number
3. Call `ensure_git_clone(primary_workspace_dir, workspace_num)` for clone dir
4. Write prompt to temp file
5. Open output file,
   `subprocess.Popen([sys.executable, axe_bead_runner.py, ...], cwd=workspace_dir, start_new_session=True)`
6. `claim_workspace(project_file, workspace_num, workflow_name, pid, ...)`
7. If claim fails, terminate subprocess and revert bead status
8. Record in `_active_beads[bead_id] = pid`

### Key Files to Reuse

- `src/sase/running_field.py`: `claim_workspace()`, `release_workspace()`, `get_first_available_axe_workspace()`
- `src/sase/gh_workspace.py`: `ensure_git_clone()`, `parse_workspace_dir()`
- `src/sase/axe_runner_utils.py`: `install_sigterm_handler()`, `was_killed()`
- `src/sase/shared_utils.py`: `create_artifacts_directory()`, `convert_timestamp_to_artifacts_format()`

### Workspace and bd Access for Agents

The `sase_bd` wrapper (`tools/sase_bd`) resolves clone workspace dirs (e.g., `sase__100/`) back to the primary
workspace. Since `ensure_git_clone()` creates full git clones, clone workspaces contain `tools/sase_bd`. The agent
prompt should instruct the agent to use `tools/sase_bd` if present, or to run `bd` commands from the primary workspace
directory (passed as context).

#### `tests/test_bead_launcher.py`

- Test `is_bead_active()` with alive/dead PIDs
- Test launch flow with mocked subprocess and workspace management
- Test double-dispatch prevention
- Test cleanup of dead entries

### Verification

- `just check`

---

## Phase 4: Create `#work_epics` Workflow + Integrate into Axe Scheduler

### Goal

Create the `#work_epics` xprompt workflow and wire it into the axe scheduler's periodic job system.

### Files to Create

#### `xprompts/work_epics.yml`

An xprompt workflow invokable as `#work_epics:<project_dir>`. Accepts a `path` type input and delegates to the Python
modules from Phases 2-3.

```yaml
input:
  - name: project_dir
    type: path

steps:
  - name: orchestrate
    python: |
      from sase.axe.work_epics import run_work_epics
      project_dir = {{ project_dir | tojson }}
      result = run_work_epics(project_dir)
      print(f"children_launched={result.children_launched}")
      print(f"epics_launched={result.epics_launched}")
    output: { children_launched: int, epics_launched: int }
```

The `run_work_epics(project_dir)` function (in `src/sase/axe/work_epics.py`, added in this phase) is the main entry
point. It:

1. Resolves the `BeadProject` from `project_dir`
2. Calls `scan_project_for_work()` from Phase 2
3. Calls `launch_child_bead_agent()` / `launch_land_epic_agent()` from Phase 3
4. Returns a result dataclass with counts

This allows both manual invocation (`#work_epics:/path/to/project`) and programmatic invocation from the axe scheduler.

#### `src/sase/axe/bead_jobs.py`

The bead equivalent of `hook_jobs.py`. Ties together scanning (Phase 2) and launching (Phase 3) with the runner pool.

```python
class BeadJobRunner:
    def __init__(self, runner_pool, metrics, log_callback): ...

    def run_bead_checks(self) -> None:
        """Called every 60 seconds by the scheduler.

        1. cleanup_dead_bead_entries()
        2. scan_all_projects() to find ready children + landable epics
        3. For each ready child: check runner_pool, check is_bead_active, reserve_slot, launch
        4. For each landable epic: same checks, launch land_epic agent
        """
```

### Files to Modify

#### `src/sase/axe/core.py`

- Import `BeadJobRunner` from `bead_jobs`
- In `__init__`: create `self._bead_runner = BeadJobRunner(self.runner_pool, self._metrics, self._log)`
- In `_setup_jobs()`: add new job at 60-second interval:
  ```python
  self.scheduler.every(60).seconds.do(
      self._safe_run_job, self._run_bead_epic_checks, "bead_epics"
  ).tag("bead_epics")
  ```
- Add `_run_bead_epic_checks()` method that calls `self._bead_runner.run_bead_checks()`

Note: The axe scheduler calls `run_work_epics()` (the same function the `#work_epics` xprompt workflow calls) directly
from Python, bypassing the workflow executor overhead. The xprompt YAML file exists for manual invocation via
`#work_epics:<dir>`; the axe calls the underlying function directly for efficiency.

#### `src/sase/axe/work_epics.py` (additions to Phase 2 module)

Add `run_work_epics(project_dir, runner_pool=None, log=None)` entry point function:

- Resolves `BeadProject` from `project_dir` (find matching project in `discover_bead_projects()`)
- Calls `scan_project_for_work()`
- Calls `launch_child_bead_agent()` / `launch_land_epic_agent()` for each result
- When `runner_pool` is provided (axe context): respects slot limits
- When `runner_pool` is None (manual `#work_epics` invocation): launches all available agents
- Returns `WorkEpicsRunResult(children_launched, epics_launched)`

#### `src/sase/axe/state.py`

- Add to `AxeMetrics`: `bead_agents_launched: int = 0`

### Edge Cases

- **Runner pool limits**: Bead agents share the global runner pool with hooks/CRS/mentors. `reserve_slot()` before each
  launch ensures limits are respected.
- **Double-dispatch prevention**: Two layers - (1) `bd update --status in_progress` removes bead from `bd ready` output
  on next scan, (2) `_active_beads` dict catches same-cycle duplicates.
- **Failed agents**: Workspace released in `finally` block. Bead stays in_progress. Manual intervention needed
  (`bd update <id> --status open`).
- **Dead processes**: `cleanup_dead_bead_entries()` runs at start of every bead check cycle, validates PIDs.
- **Projects without beads**: `discover_bead_projects()` skips them (no `.beads/` dir).
- **Non-git projects**: Skipped by `discover_bead_projects()` (no `.git/` dir).

#### `tests/test_bead_jobs.py`

- Test `BeadJobRunner.run_bead_checks()` with mocked scanner and launcher
- Test runner pool integration (slots checked, reserved, limits respected)
- Test active beads are skipped
- Test scan errors are logged but don't crash

### Verification

- `just check`
- Verify `xprompts/work_epics.yml` is valid and discovered by the workflow loader
- Start `sase axe` and verify bead check logs appear every 60 seconds
- Create a test epic with child beads, verify agents are dispatched
- Verify runner pool limits are respected when other runners are active
