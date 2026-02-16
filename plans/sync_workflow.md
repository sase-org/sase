---
bead_id: sase-5rn
---

# Merge Conflict Resolution via XPrompt Workflow

## Context

When running `sync_workspace()` (git: `git fetch + git rebase origin/<default>`, hg: `sase_hg_sync`), merge conflicts
can occur. Currently, the TUI sync action (`src/sase/ace/tui/actions/sync.py`) calls `provider.sync_workspace()` and
reports failure with no conflict resolution. This plan adds automated AI-powered merge conflict detection and resolution
as an xprompt workflow.

**Core idea**: A `sync.yml` workflow that attempts sync, detects conflicts, and enters a `repeat` loop where a Claude
agent reads conflicted files, resolves them, stages resolutions, and continues the rebase/sync — looping until all
commits are cleanly applied.

---

## Phase 1: VCS Provider Conflict Detection & Resolution API

**Goal**: Add methods to the VCS provider abstraction for detecting, inspecting, and managing merge conflict state.

### Files to modify

- `src/sase/vcs_provider/_base.py` — Add default methods (raise `NotImplementedError`)
- `src/sase/vcs_provider/_git.py` — Git implementations
- `src/sase/vcs_provider/_hg.py` — Hg implementations
- `tests/test_vcs_provider_git_core.py` — Unit tests for new git methods

### New methods on `VCSProvider`

```python
def is_sync_in_progress(self, cwd: str) -> bool:
    """Check if an interrupted sync/rebase is in progress (conflicts pending)."""

def get_conflicted_files(self, cwd: str) -> list[str]:
    """Return list of file paths with unresolved merge conflicts."""

def continue_sync(self, cwd: str) -> tuple[bool, str | None]:
    """Continue an interrupted sync after conflicts are resolved.
    Caller must stage resolved files first (git add / hg resolve --mark)."""

def abort_sync(self, cwd: str) -> tuple[bool, str | None]:
    """Abort an interrupted sync/rebase, restoring pre-sync state."""
```

### Git implementations (`_GitProvider`)

| Method                 | Implementation                                                                                                                                       |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `is_sync_in_progress`  | Check for `.git/rebase-merge/` or `.git/rebase-apply/` directory via `os.path.isdir()` (need to find `.git` dir first via `git rev-parse --git-dir`) |
| `get_conflicted_files` | `git diff --name-only --diff-filter=U` — returns files with unmerged entries                                                                         |
| `continue_sync`        | `git rebase --continue` (timeout=600). Note: caller stages files before calling this. May itself return conflicts from next commit.                  |
| `abort_sync`           | `git rebase --abort`                                                                                                                                 |

### Hg implementations (`_HgProvider`)

| Method                 | Implementation                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------- |
| `is_sync_in_progress`  | `hg resolve --list` — returns True if any lines start with `U ` (unresolved)                      |
| `get_conflicted_files` | Parse `hg resolve --list` output, return file paths from lines starting with `U `                 |
| `continue_sync`        | `hg resolve --mark --all` then continue rebase (may need `sase_hg_sync --continue` or equivalent) |
| `abort_sync`           | `hg update --clean .` or `hg rebase --abort` depending on sync mechanism                          |

### Tests

Add tests in `tests/test_vcs_provider_git_core.py` for the git implementations using a temp git repo:

- Test `is_sync_in_progress` returns False on a clean repo
- Test `get_conflicted_files` returns empty list on a clean repo
- Test conflict scenario: create two branches that modify the same line, attempt rebase, verify `is_sync_in_progress()`
  returns True and `get_conflicted_files()` returns the file
- Test `abort_sync` cleans up the conflict state
- Test `continue_sync` after manually resolving conflicts

---

## Phase 2: `sync.yml` XPrompt Workflow

**Goal**: Create the merge-conflict-resolving sync workflow.

### Files to create/modify

- `xprompts/sync.yml` — **New**: The main sync workflow
- `xprompts/resolve_conflicts.md` — **New** (optional): Helper xprompt with detailed conflict resolution instructions
- `src/sase/scripts/sync_setup.py` — **New**: Extracted setup step logic
- `src/sase/scripts/sync_attempt.py` — **New**: Extracted sync attempt step logic
- `src/sase/scripts/sync_report.py` — **New**: Extracted report step logic

### Workflow design: `xprompts/sync.yml`

```yaml
input:
  - name: branch_name
    type: word
    default: ""

steps:
  - name: setup
    python: |
      from sase.scripts.sync_setup import main
      main()
    output: { vcs_type: word, branch_name: word, cwd: path }

  - name: sync_attempt
    python: |
      from sase.scripts.sync_attempt import main
      main(cwd={{ setup.cwd | tojson }})
    output: { success: bool, has_conflicts: bool, error: text, conflicted_files: text }

  - name: resolve
    # AI agent resolves conflicts in a loop
    if: "{{ sync_attempt.has_conflicts }}"
    repeat:
      until: "{{ resolve.all_resolved }}"
      max_iterations: 20
    prompt: |
      A {{ setup.vcs_type }} sync/rebase operation has resulted in merge conflicts
      that need to be resolved.

      Working directory: {{ setup.cwd }}
      Branch: {{ setup.branch_name }}
      VCS: {{ setup.vcs_type }}

      {% if setup.vcs_type == "git" %}
      ## Git Conflict Resolution Steps

      1. **Find conflicted files**: Run `git diff --name-only --diff-filter=U`
      2. **Read each file**: Look for conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`)
         - Content between `<<<<<<< HEAD` and `=======` is YOUR version (current branch)
         - Content between `=======` and `>>>>>>> <commit>` is the INCOMING version (from rebase)
      3. **Resolve each file**: Edit to keep the correct code and remove ALL conflict markers
      4. **Stage resolved files**: Run `git add <file>` for EACH resolved file
      5. **Continue rebase**: Run `git -c core.editor=true rebase --continue`
         - If this produces MORE conflicts, set `all_resolved=false`
         - If this succeeds (exit code 0), set `all_resolved=true`
      6. **Verify**: Run `git diff --name-only --diff-filter=U` to check for remaining conflicts
      {% else %}
      ## Mercurial Conflict Resolution Steps

      1. **Find conflicted files**: Run `hg resolve --list` (lines starting with `U` are unresolved)
      2. **Read each file**: Look for conflict markers
      3. **Resolve each file**: Edit to keep the correct code and remove ALL conflict markers
      4. **Mark resolved**: Run `hg resolve --mark <file>` for EACH resolved file
      5. **Check**: Run `hg resolve --list` again - if all show `R` (resolved), set `all_resolved=true`
      {% endif %}

      ## Resolution Guidelines
      - When in doubt, prefer the INCOMING version (it's more recent)
      - For import statements: keep both if they import different things
      - For function changes: understand the intent of both sides before merging
      - NEVER leave conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in any file
      - If a file has conflicts you can't resolve (e.g., binary files), report it

      ## Required Output
      Report your results as:
      - `all_resolved`: true if rebase/sync completed successfully with no remaining conflicts
      - `files_resolved`: number of files you resolved in this round
    output: { all_resolved: bool, files_resolved: int }

  - name: report
    hidden: true
    python: |
      from sase.scripts.sync_report import main
      main(
          success={{ sync_attempt.success }},
          has_conflicts={{ sync_attempt.has_conflicts }},
          all_resolved={{ resolve.all_resolved | default(false) }},
      )
    output: { status: word, message: text }
```

### Key design decisions

1. **`repeat` loop with `until`**: The AI agent is invoked fresh each iteration. After resolving conflicts and running
   `git rebase --continue`, the agent reports whether more conflicts exist. The loop continues until `all_resolved=true`
   or max iterations (20) is hit.

2. **`git -c core.editor=true rebase --continue`**: The `-c core.editor=true` prevents git from opening an editor for
   the commit message during rebase continue.

3. **AI agent has full tool access**: The prompt step invokes a Claude agent via `invoke_agent()` that can read/edit
   files and run bash commands — everything needed to resolve conflicts.

4. **VCS-polymorphic prompt**: Uses Jinja2 conditionals to give VCS-specific instructions.

---

## Phase 3: TUI Integration & Abort Safety

**Goal**: Wire the sync workflow into the TUI sync action and ensure abort safety.

### Files to modify

- `src/sase/ace/tui/actions/sync.py` — Update to use workflow, add abort safety

### Changes to `sync.py`

The current `action_sync` method directly calls `provider.sync_workspace()`. Update it to:

1. **Attempt sync** via the workflow (invoke `sync.yml`):

   ```python
   from sase.xprompt import execute_workflow
   result = execute_workflow("sync", [], {"branch_name": changespec.name}, ...)
   ```

2. **Abort safety**: If the workflow fails and a rebase is still in progress, abort it:

   ```python
   if not result.success:
       provider = get_vcs_provider(workspace_dir)
       if provider.is_sync_in_progress(workspace_dir):
           provider.abort_sync(workspace_dir)
   ```

3. **Suspend TUI**: The workflow runs in the `self.suspend()` context (same as current), since the AI agent needs
   terminal access for tool use.

### Key changes in `run_handler()`

```python
def run_handler() -> tuple[bool, str]:
    # ... existing workspace claim logic ...

    try:
        # Use sync workflow instead of direct VCS calls
        from sase.xprompt import execute_workflow

        result = execute_workflow(
            "sync",
            positional_args=[],
            named_args={"branch_name": changespec.name},
            artifacts_dir=artifacts_dir,
        )

        if result and "resolved" in (result.output or ""):
            return (True, f"Synced {changespec.name} (conflicts resolved)")
        elif result:
            return (True, f"Synced {changespec.name}")
        else:
            return (False, "Sync workflow failed")
    except Exception as e:
        # Abort safety: clean up any in-progress rebase
        try:
            provider = get_vcs_provider(workspace_dir)
            if provider.is_sync_in_progress(workspace_dir):
                provider.abort_sync(workspace_dir)
        except Exception:
            pass
        return (False, f"sync failed: {e}")
    finally:
        # ... existing workspace release ...
```

### Testing

- Manual test: Create a git repo with a branch that conflicts with main, run sync from TUI, verify AI resolves conflicts
- Unit test: Mock VCS provider methods, verify workflow invocation and abort safety
- Edge cases to verify:
  - Binary file conflicts (should be reported, not resolved)
  - Delete/modify conflicts
  - Multiple commits with conflicts (the repeat loop)
  - Sync with no conflicts (fast path, no AI invocation)

---

## Verification Plan

1. **Unit tests** (Phase 1): Run `just test` to verify new VCS provider methods
2. **Workflow test** (Phase 2): Invoke `#sync` from the CLI to test the workflow YAML parsing and execution
3. **Integration test** (Phase 3):
   - Create a test git repo with conflicting changes
   - Run the TUI sync action
   - Verify conflicts are detected, AI resolves them, rebase completes
4. **Lint**: Run `just lint` after each phase

## Critical files reference

| File                                                 | Role                                     |
| ---------------------------------------------------- | ---------------------------------------- |
| `src/sase/vcs_provider/_base.py`                     | Abstract VCS interface                   |
| `src/sase/vcs_provider/_git.py`                      | Git provider (sync = fetch+rebase)       |
| `src/sase/vcs_provider/_hg.py`                       | Hg provider (sync = sase_hg_sync)        |
| `src/sase/ace/tui/actions/sync.py`                   | TUI sync action                          |
| `xprompts/sync.yml`                                  | New sync workflow                        |
| `xprompts/git.yml`                                   | Reference: existing git workflow pattern |
| `src/sase/xprompt/workflow_executor.py`              | Workflow execution engine                |
| `src/sase/xprompt/workflow_executor_loops.py`        | Repeat/while loop handling               |
| `src/sase/xprompt/workflow_executor_steps_prompt.py` | Prompt step → `invoke_agent()`           |
| `src/sase/vcs_provider/_registry.py`                 | `detect_vcs()`, `get_vcs_provider()`     |
