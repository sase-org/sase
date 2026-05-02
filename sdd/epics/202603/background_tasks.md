---
bead_id: sase-3
status: done
prompt: sdd/prompts/202603/background_tasks.md
---

# Plan: Migrate Sync, Mail, and Accept to Background Tasks

## Overview

Migrate `action_sync` (Y), `action_mail` (M), and `action_accept_proposal` (a) from blocking `self.suspend()` calls to
background execution using Textual's `run_worker()` API (Option C from sdd/research/202603/send_cmds_to_axe.md).

## Key Design Decisions

1. **No new UI panel** — use toast notifications for status updates and the existing notification system for errors. A
   dedicated task panel can be added later if needed.
2. **Output capture** — redirect stdout/stderr to `io.StringIO` during background execution. Store captured output for
   optional viewing via notification on failure.
3. **Per-CL deduplication** — prevent concurrent background tasks on the same ChangeSpec.
4. **Workspace lifecycle** — claim workspace before submitting task, release in finally block within the worker thread.
5. **Mail special case** — `prepare_mail()` stays in `self.suspend()` (interactive y/n prompt). Only `execute_mail()` +
   status transition run in background.

## Phase 1: Background Task Infrastructure

**Goal**: Create the task queue system that all three commands will use.

### Files to Create

**`src/sase/ace/tui/task_queue.py`** — Core task state and management:

```python
@dataclass
class TaskInfo:
    task_id: str           # Unique ID (uuid4)
    task_type: str         # "sync", "mail", "accept"
    cl_name: str           # ChangeSpec name
    project_file: str      # Path to project file
    status: str            # "running", "success", "error"
    message: str           # Human-readable status message
    started_at: datetime
    finished_at: datetime | None
    output: str            # Captured stdout/stderr
    error: str | None      # Error message if failed
```

```python
class TaskQueue:
    """Manages background tasks. Thread-safe via a lock."""
    _tasks: dict[str, TaskInfo]
    _lock: threading.Lock

    def submit(task_id, task_type, cl_name, project_file) -> TaskInfo
    def complete(task_id, success, message, output, error=None) -> None
    def get_running_for_cl(cl_name) -> TaskInfo | None  # For dedup
    def get_all() -> list[TaskInfo]
    def remove(task_id) -> None
```

**`src/sase/ace/tui/actions/task_actions.py`** — TUI mixin for submitting/managing tasks:

```python
class TaskActionsMixin:
    """Mixin providing background task submission for the TUI app."""
    _task_queue: TaskQueue  # Initialized in AceApp.__init__ or compose()

    def _submit_background_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        callable: Callable[[], tuple[bool, str]],
        on_success: Callable[[], None] | None = None,
    ) -> bool:
        """Submit a task to run in background via run_worker().

        Returns False if a task is already running for this CL.
        The callable should return (success, message).
        Output capture (stdout/stderr redirect) is handled automatically.
        """

    def _on_task_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion: update TaskQueue, notify, reload."""
```

### Output Capture Helper

Create a context manager in `task_queue.py`:

```python
@contextmanager
def capture_output() -> Generator[io.StringIO, None, None]:
    """Redirect stdout/stderr to a StringIO buffer."""
    buffer = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = buffer
    sys.stderr = buffer
    try:
        yield buffer
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
```

### Integration Points

- Initialize `TaskQueue` in `AceApp.__init__()` (or wherever mixins are composed)
- The mixin's `_submit_background_task` wraps the callable: captures output, runs it, calls `TaskQueue.complete()`, then
  posts a Textual message to trigger `self.notify()` + `_reload_and_reposition()`
- Worker tracking: store `{task_id: Worker}` mapping to enable future cancellation

### Key Details

- `run_worker(fn, thread=True)` runs `fn` on a daemon thread and posts `Worker.StateChanged` when done
- The callable must be fully self-contained (no references to Textual widgets — those aren't thread-safe)
- Use `self.call_from_thread(self.notify, msg)` or `self.app.post_message()` for thread→main communication
- Rich Console objects used inside the callable should write to the StringIO buffer, not the real terminal

### Tests

- `tests/ace/tui/test_task_queue.py` — unit tests for `TaskQueue` (submit, complete, dedup, thread safety)
- Output capture context manager tests

---

## Phase 2: Migrate `action_sync` (Y keymap)

**Goal**: Sync runs in background. User sees "Sync started for CL X" toast, continues using TUI, and gets notified on
completion.

### Changes to `src/sase/ace/tui/actions/sync.py`

1. **Extract `_sync_task()`** — a standalone function (not a method) that takes all needed args and returns
   `tuple[bool, str]`. This is the callable submitted to the task queue. It contains the body of the current
   `run_handler()`:
   - Claim workspace
   - Clean workspace
   - Checkout CL
   - Execute sync workflow
   - Parse result
   - Release workspace (in finally)
   - Return (success, message)

2. **Refactor `action_sync()`** — instead of `with self.suspend(): run_handler()`:
   - Validate status (unchanged)
   - Check dedup: `if self._task_queue.get_running_for_cl(changespec.name): notify("already running"); return`
   - Build the callable (closure capturing changespec data, workspace info, etc.)
   - Call `self._submit_background_task("sync", cl_name, project_file, callable, on_success=on_sync_success)`
   - `on_success` callback: `reset_dollar_hooks()` + `_reload_and_reposition()`

3. **Notification flow**:
   - Immediately: `self.notify(f"Sync started for {cl_name}")`
   - On success: `self.notify(f"Synced {cl_name}: {message}")`
   - On failure: `self.notify(f"Sync failed for {cl_name}: {error}", severity="error")`
   - On failure with sync notification: still call `notify_sync_result()` for the notification system

### Key Details

- The `execute_workflow("sync", ...)` call sets `SASE_SYNC_CWD` env var. Since this runs in a thread, use thread-local
  or pass it directly. Safest: set/restore env var inside the task callable with a lock, or pass workspace_dir through
  the workflow API if possible.
- `_abort_if_needed()` must still be called in error paths within the task callable.
- The `_reload_and_reposition()` call must happen on the main thread via `call_from_thread()`.

### Tests

- Verify sync task callable returns correct (bool, str) for success/failure cases
- Verify dedup prevents concurrent syncs on same CL
- Verify workspace is always released (even on error)

---

## Phase 3: Migrate `action_mail` (M keymap) — Post-Confirmation Only

**Goal**: The interactive confirmation (y/n prompt) stays in `self.suspend()`. After the user confirms, `execute_mail()`
and the status transition run in background.

### Changes to `src/sase/ace/mail_ops.py`

No changes needed — `prepare_mail()` and `execute_mail()` are already separate functions.

### Changes to `src/sase/ace/handlers/mail.py`

Refactor `handle_mail()` to separate the interactive and non-interactive parts:

```python
def handle_mail_prepare(
    self: WorkflowContext,
    changespec: ChangeSpec,
    workspace_num: int,
    workspace_dir: str,
) -> MailPrepResult | None:
    """Interactive part: checkout + prepare_mail (y/n prompt). Runs in suspend()."""

def handle_mail_execute(
    changespec: ChangeSpec,
    workspace_dir: str,
    workspace_num: int,
) -> tuple[bool, str]:
    """Non-interactive part: execute_mail + status transition. Runs in background task.
    Releases workspace in finally block.
    Returns (success, message)."""
```

### Changes to `src/sase/ace/tui/actions/base.py`

Refactor `action_mail()`:

1. Validate status is Ready (unchanged)
2. Claim workspace (before suspend, since we need it for both phases)
3. `with self.suspend():` — run `handle_mail_prepare()` (interactive y/n)
4. If user declined (`should_mail=False`): release workspace, return
5. If user confirmed: submit `handle_mail_execute()` as background task
   - The background task owns the workspace from this point and releases it in its finally block
6. Notify: "Mailing {cl_name}..."
7. On success: notify + reload
8. On failure: notify error + reload

### Key Details

- Workspace lifecycle spans two phases: claimed before suspend, transferred to background task, released by task. The
  task callable must release the workspace in its finally block.
- The `Console` object used by `execute_mail()` in background must write to the captured StringIO, not the terminal.
  Pass a `Console(file=buffer)` constructed inside the capture context.
- The `update_changespec_cl_atomic()` call (for newly created PRs) happens inside `execute_mail()` — this is thread-safe
  since it writes to a file atomically.

### Tests

- Verify prepare phase returns correct MailPrepResult
- Verify execute phase runs independently and releases workspace
- Verify CL URL update works from background thread

---

## Phase 4: Migrate `action_accept_proposal` (a keymap)

**Goal**: After the user selects proposal IDs via `HintInputBar`, the `AcceptWorkflow.run()` executes in background.

### Changes to `src/sase/ace/tui/actions/proposal_rebase.py`

Refactor `_run_accept_workflow()`:

1. **Extract `_accept_task()`** — standalone callable:

   ```python
   def _accept_task(
       proposals: list[tuple[str, str | None]],
       cl_name: str,
       project_file: str,
       mark_ready_to_mail: bool,
       skip_amend: bool,
   ) -> tuple[bool, str]:
       """Run AcceptWorkflow in background. Returns (success, message)."""
       workflow = AcceptWorkflow(...)
       success = workflow.run()
       if not success:
           conflict_result = workflow.conflict_result
           if conflict_result and not conflict_result.success:
               return (False, format_conflict_message(conflict_result))
           return (False, "Accept workflow failed")
       return (True, f"Accepted proposals for {cl_name}")
   ```

2. **Refactor `_run_accept_workflow()`** — instead of `with self.suspend(): run_handler()`:
   - Build the callable with all necessary args
   - Submit via `self._submit_background_task("accept", cl_name, project_file, callable)`
   - Notify: "Accepting proposals for {cl_name}..."
   - On success: notify + reload
   - On failure: notify with conflict message if applicable

### Key Details

- `AcceptWorkflow` handles its own workspace management internally — verify this is thread-safe.
- The `self.notify(msg)` calls currently inside `run_handler()` (showing "Accepting proposal X...") should move to
  before the task submission, since they need to run on the main thread.
- `HintInputBar` interaction (Phase 1 of accept flow) is already non-blocking — no changes needed there.

### Tests

- Verify accept task callable returns correct results for success/conflict/failure
- Verify conflict messages are properly formatted and surfaced

---

## Implementation Notes

### Thread Safety Checklist

- [ ] `TaskQueue._tasks` access is protected by `_lock`
- [ ] No Textual widget access from worker threads (use `call_from_thread()`)
- [ ] Workspace claim/release uses existing atomic file operations
- [ ] `SASE_SYNC_CWD` env var is set/restored within the task (consider using a lock or thread-local)
- [ ] Rich Console objects in background tasks write to StringIO, not terminal

### Notification Strategy

| Event                              | Method                                                | Severity |
| ---------------------------------- | ----------------------------------------------------- | -------- |
| Task started                       | `self.notify()` toast                                 | info     |
| Task succeeded                     | `self.notify()` toast + `_reload_and_reposition()`    | info     |
| Task failed                        | `self.notify()` toast                                 | error    |
| Sync resolved (with notifications) | `notify_sync_result()` (existing notification system) | —        |

### Deduplication Rules

- One background task per CL at a time
- If user tries to start a second task for the same CL: show warning toast, do not submit
- Different CLs can have concurrent tasks

### Migration Backward Compatibility

- No keybinding changes — Y, M, a keymaps stay the same
- User experience change: instead of seeing command output in terminal, they see toast notifications
- If background task fails, the error message should be at least as informative as the current terminal output
