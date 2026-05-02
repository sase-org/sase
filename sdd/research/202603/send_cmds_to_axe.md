# Migrating Long-Running TUI Commands to AXE Background Tasks

## Context

Today, several `sase ace` TUI actions block the UI via `self.suspend()` while running external commands (VCS operations,
workflows, etc.). The user sees command output but cannot interact with the TUI until the operation completes. The `!!`
keymap already demonstrates a working pattern for background execution via the bgcmd slot system (9 slots under
`~/.sase/axe/bgcmd/`).

This document explores what it would take to route long-running TUI commands through the same background execution path.

## Commands to Migrate

### Tier 1: High-impact, long-blocking operations (30-120+ seconds)

These are the strongest candidates - they block the TUI for the longest time and would benefit most from background
execution.

| Action                   | Keymap  | What it does                                            | Why it blocks                        |
| ------------------------ | ------- | ------------------------------------------------------- | ------------------------------------ |
| `action_sync`            | `S`     | Checkout + merge/rebase via VCS + xprompt sync workflow | VCS operations + network I/O         |
| `action_rebase`          | `R`     | Parent selection + VCS rebase                           | VCS operations + conflict resolution |
| `action_run_workflow`    | `W`     | Execute arbitrary xprompt workflow                      | Workflow steps can do anything       |
| `action_accept_proposal` | `a`     | VCS checkout + apply diff + amend                       | VCS operations + diff application    |
| Status -> Reverted       | via `s` | `revert_changespec()`: prune CL, archive diff           | VCS operations                       |
| Status -> Submitted      | via `s` | `submit_changespec()`: push/submit CL                   | VCS + network (push)                 |
| Status -> Archived       | via `s` | `archive_changespec()`: cleanup operations              | VCS operations                       |
| Status -> Restore        | via `s` | `restore_changespec()`: re-apply archived diff          | VCS operations                       |

### Tier 2: Moderate blocking (2-30 seconds)

These are secondary candidates. They block noticeably but not as severely.

| Action             | Keymap   | What it does                 | Why it blocks            |
| ------------------ | -------- | ---------------------------- | ------------------------ |
| `action_rename_cl` | (leader) | Workspace claim + VCS rename | VCS operations           |
| `action_checkout`  | `c`      | VCS checkout to workspace    | VCS operations           |
| `action_open_tmux` | `t`      | VCS checkout + tmux session  | VCS checkout before tmux |
| `action_show_diff` | `d`      | Generate and display diff    | Diff computation         |

### Not candidates (already async or inherently interactive)

| Action                             | Reason                                          |
| ---------------------------------- | ----------------------------------------------- |
| Agent launch (`@`, `/`, `<space>`) | Already spawns in background                    |
| `action_edit_spec`                 | Opens `$EDITOR` - requires interactive terminal |
| `action_reword`                    | Opens `$EDITOR` - requires interactive terminal |
| `action_toggle_axe`                | Already non-blocking (daemon process)           |
| `action_start_bgcmd` (`!!`)        | Already uses bgcmd system                       |
| Navigation/display actions         | Already instant                                 |

## What the Migration Entails

### Option A: Route through existing bgcmd slots

Reuse the `start_background_command()` infrastructure directly.

**How it works today:**

1. User presses `!!` -> modal stack (project, workspace, command)
2. `start_background_command(slot, command, workspace_dir)` spawns `Popen(command, shell=True, ...)`
3. Output captured to `~/.sase/axe/bgcmd/<slot>/output.log`
4. TUI polls slot status on refresh cycle (every 10 seconds)

**What we'd need to change:**

1. **Wrap TUI actions as shell commands.** Each migrated action would need a CLI equivalent that can be invoked as a
   string command. For example, `action_sync` would become something like:

   ```
   sase sync --project foo --cl bar --workspace 101
   ```

   Many of these CLI commands don't exist today.

2. **Slot allocation.** Auto-assign a slot instead of requiring the user to pick one. Add a `find_free_slot()` helper
   that returns the first empty slot (or errors if all 9 are full).

3. **Post-completion hooks.** After a background command finishes, the TUI needs to:
   - Reload the affected ChangeSpec from disk
   - Release any workspace claims
   - Show success/failure notification
   - Update the sidebar status

4. **Error handling.** Capture exit codes and display meaningful error messages, not just raw output.

**Estimated scope:** Medium-large. Requires new CLI subcommands for each operation, modifications to bgcmd state
management, and a callback/notification system for completion.

### Option B: In-process background threads (like home mode workflows)

The TUI already has `_execute_workflow_in_thread()` for home mode workflows, which runs work on a daemon thread.

**How it works today:**

1. Create artifacts directory for state
2. Spawn `threading.Thread(target=workflow_fn, daemon=True)`
3. Thread runs workflow, writes output to artifacts
4. TUI polls artifacts for status/output

**What we'd need to change:**

1. **Adapt the suspend-based actions to run in threads.** Replace `with self.suspend():` blocks with thread spawning.
   The action function body becomes the thread target.

2. **Output capture.** Redirect stdout/stderr from the thread to a log file (similar to bgcmd). This is tricky because
   VCS operations currently print to the real terminal via `suspend()`.

3. **Workspace locking.** Thread-based execution still needs workspace claiming, but now it's concurrent with the main
   TUI thread. Need to ensure the claim/release lifecycle is thread-safe.

4. **State refresh.** After thread completion, signal the main TUI to reload affected data.

**Estimated scope:** Medium. No new CLI commands needed, but threading introduces concurrency concerns with the TUI's
Textual event loop.

### Option C: Hybrid - new `sase ace` internal task queue

Create a lightweight task queue within the TUI process itself, separate from bgcmd.

**How it would work:**

1. Actions submit tasks to an internal queue (not shell commands, but Python callables)
2. A worker thread (or small thread pool) executes tasks
3. Output is captured to a buffer and displayed in a new "Tasks" panel
4. Completion triggers a Textual message/event for the main thread to handle

**What we'd need:**

1. **Task abstraction.** A `BackgroundTask` dataclass with: callable, args, workspace_num, changespec_name, status,
   output buffer, started_at, finished_at.

2. **Task panel in TUI.** A new sidebar section or tab showing running/completed tasks with their output (similar to
   bgcmd display but integrated into the main TUI).

3. **Textual-native async.** Use Textual's `work` decorator or `run_worker()` for proper integration with the event
   loop. This avoids raw threading issues.

4. **Workspace management.** Tasks claim workspaces on start and release on completion/error, with proper cleanup on
   task cancellation.

**Estimated scope:** Medium-large initially, but the cleanest long-term architecture.

## Recommendation

**Option C (hybrid internal task queue)** is the best path forward because:

- It avoids the "shell command serialization" problem of Option A (no need to create CLI commands for every operation).
- It integrates properly with Textual's event loop (unlike raw threading in Option B).
- It keeps the bgcmd system for its intended purpose (user-initiated arbitrary shell commands) while giving structured
  TUI operations their own execution path.
- Textual's `run_worker()` already handles thread-to-main-thread communication cleanly.

## Downsides and Mitigations

### 1. Loss of real-time output visibility

**Problem:** Today, `self.suspend()` gives the user a full terminal showing command output as it happens. Background
execution means output is captured to a buffer and displayed after-the-fact (or polled periodically).

**Mitigation:** Use a streaming output panel that updates on a short interval (1-2 seconds instead of the current
10-second bgcmd refresh). Textual's reactive system can trigger re-renders when the output buffer changes. For critical
operations (merge conflicts), surface a notification immediately.

### 2. Conflict resolution becomes harder

**Problem:** Sync and rebase operations can hit merge conflicts that require interactive resolution. When suspended, the
user can resolve these in-terminal. In the background, there's no interactive terminal.

**Mitigation:**

- Detect conflict state in the background task and pause it (set status to "needs attention").
- Surface a notification in the TUI: "Sync for CL X hit a merge conflict in workspace 101."
- Provide a "resume in terminal" action that suspends the TUI and drops the user into the workspace to resolve the
  conflict, then resumes the background task.
- For VCS providers that support it, auto-resolve trivial conflicts and only pause on real ones.

### 3. Concurrent workspace access

**Problem:** Multiple background tasks could try to use the same workspace simultaneously, corrupting VCS state.

**Mitigation:** The workspace claiming system (100-199 range) already handles this. Ensure background tasks claim
workspaces before starting and release them on completion/error/cancellation. Add a per-workspace mutex in the task
queue to prevent double-booking.

### 4. Error handling is less visible

**Problem:** When a command fails in `suspend()` mode, the user sees the error output immediately and knows something
went wrong. In the background, failures can go unnoticed.

**Mitigation:**

- Surface failed tasks prominently: change the task's sidebar entry color to red, show a notification, optionally
  flash/bell.
- Capture exit codes and classify errors (conflict vs. network vs. programming bug).
- Auto-open the task's output panel when it fails.

### 5. ChangeSpec state can become stale

**Problem:** If a background task modifies a ChangeSpec while the user is viewing it in the TUI, the displayed data
becomes stale.

**Mitigation:** After task completion, trigger a targeted reload of the affected ChangeSpec (not a full query reload).
Use Textual messages to signal the main thread: "ChangeSpec X was modified, please refresh." The TUI already has
`_load_changespecs()` and per-spec reload logic.

### 6. Task ordering and dependencies

**Problem:** A user might start a sync, then immediately try to rebase the same CL. The rebase should wait for sync to
finish.

**Mitigation:** Implement per-ChangeSpec task serialization. If a task is already running for a given CL, new tasks for
that CL queue behind it (or the TUI warns the user). This is similar to how workspace claiming already prevents
concurrent access, but at a higher level.

### 7. Nine-slot limit (Option A only)

**Problem:** The bgcmd system has a hard limit of 9 slots. If TUI commands share these slots with user-initiated `!!`
commands, they could fill up quickly.

**Mitigation:** This is why Option C is preferred - internal tasks have their own queue with no artificial slot limit.
If using Option A, increase MAX_SLOTS or partition slots (e.g., 1-5 for user commands, 6-15 for TUI operations).

### 8. Process cleanup on TUI exit

**Problem:** If the user quits the TUI while background tasks are running, orphaned processes could leave workspaces in
a dirty state.

**Mitigation:**

- On TUI exit, show a warning if tasks are running: "N tasks still running. Quit anyway?"
- If the user quits, send SIGTERM to all running task processes.
- On next TUI startup, detect orphaned task state and offer cleanup.
- For Option A/bgcmd: tasks survive TUI exit (by design). Document that workspace state may need manual cleanup.

## Migration Order

If we proceed, migrate commands in this order based on impact and complexity:

1. **`action_sync`** - Most frequently blocked operation, well-understood VCS workflow
2. **`action_accept_proposal`** - High frequency in review workflows, straightforward
3. **Status transitions** (submit, revert, archive, restore) - Moderate frequency, similar pattern
4. **`action_rebase`** - Complex due to conflict resolution, but high value
5. **`action_run_workflow`** - Most complex (arbitrary workflows), save for last
6. **Tier 2 operations** (rename, checkout, tmux, diff) - Lower priority, shorter blocking time
