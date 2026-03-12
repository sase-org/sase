# Plan: Centralize All Project Spec Writes into a Single `spec_writer` Chop

## Context

Currently ~38 call sites across ~13 modules write to `.gp` project spec files, each independently acquiring an fcntl
file lock via `changespec_lock()` and writing via `write_changespec_atomic()`. This leads to lock contention between
concurrent writers (axe chops, TUI, CLI commands), race conditions requiring defensive re-reads under lock (e.g.,
`merge_hook_updates`), and self-healing deduplication for corruption that has occurred in production.

The goal is to funnel ALL writes through a single `spec_writer` lumberjack chop that:

1. Handles common spec updates directly (knows the write patterns)
2. Accepts write requests from external processes via a filesystem queue API
3. Notifies callers when writes complete

## Architecture

### Communication: Filesystem Queue

Requests and responses are JSON files in `~/.sase/spec_writer/`:

```
~/.sase/spec_writer/
  requests/          # Callers write request JSON files here
    <uuid>.json
  responses/         # Chop writes response JSON files here
    <uuid>.json
```

This fits the existing chop model (run-to-completion each tick, file-based state) and survives process restarts (pending
requests persist on disk).

### Data Models

New package: `src/sase/spec_writer/`

```python
# models.py
class OperationType(StrEnum):
    # Category 1: Simple field updates
    SET_STATUS = "set_status"
    SET_CL = "set_cl"
    SET_PARENT = "set_parent"
    SET_DESCRIPTION = "set_description"
    SET_NAME = "set_name"
    UPDATE_PARENT_REFERENCES = "update_parent_references"
    # Category 2: Hook operations
    SET_HOOKS = "set_hooks"
    MERGE_HOOKS = "merge_hooks"
    ADD_HOOK = "add_hook"
    SET_HOOK_SUFFIX = "set_hook_suffix"
    CLEAR_HOOK_SUFFIX = "clear_hook_suffix"
    UPDATE_HOOK_SUFFIX_TYPE = "update_hook_suffix_type"
    RERUN_DELETE_HOOKS = "rerun_delete_hooks"
    TRY_CLAIM_HOOK_FOR_FIX = "try_claim_hook_for_fix"
    # Category 3: Commit operations
    ADD_COMMIT_ENTRY = "add_commit_entry"
    # ... (more)
    # Category 4: Comments
    # Category 5: Mentors
    # Category 6: RUNNING field
    CLAIM_WORKSPACE = "claim_workspace"
    RELEASE_WORKSPACE = "release_workspace"
    # Category 7: File-level
    ADD_CHANGESPEC = "add_changespec"
    TRANSITION_STATUS = "transition_status"  # composite
    RAW_WRITE = "raw_write"  # escape hatch

@dataclass
class SpecWriteRequest:
    request_id: str           # UUID
    timestamp: float          # time.time()
    project_file: str         # absolute path to .gp file
    operation: OperationType
    params: dict[str, Any]    # operation-specific
    caller_pid: int = 0       # for debugging

@dataclass
class SpecWriteResponse:
    request_id: str
    success: bool
    error: str | None = None
    result: dict[str, Any] | None = None  # return values (e.g., entry_id, summary)
```

### Client API

```python
# client.py
def submit_spec_write(request: SpecWriteRequest) -> str:
    """Fire-and-forget: write request JSON, return request_id."""

def submit_spec_write_and_wait(
    request: SpecWriteRequest, timeout: float = 10.0
) -> SpecWriteResponse:
    """Submit and poll for response with exponential backoff (10ms -> 100ms)."""
```

### Chop Processing Loop

Each tick, the `spec_writer` chop:

1. Scans `~/.sase/spec_writer/requests/` for pending `.json` files
2. Groups requests by `project_file`
3. For each project file: acquires lock once, sorts by timestamp, applies sequentially
4. Writes response files for each processed request
5. Removes processed request files
6. Reaps stale requests (>60s old) with error responses

### Latency

The hooks lumberjack runs every 1s. Average write latency is ~500ms. This is acceptable for background operations (axe
chops) and tolerable for interactive operations (TUI/CLI) which already have VCS latency.

## Critical Files

| File                                                | Role                                                                        |
| --------------------------------------------------- | --------------------------------------------------------------------------- |
| `src/sase/ace/changespec/locking.py`                | Current write infrastructure (`changespec_lock`, `write_changespec_atomic`) |
| `src/sase/ace/hooks/persistence.py`                 | Hook write ops with merge/dedup logic                                       |
| `src/sase/ace/hooks/mutations.py`                   | 6 hook mutation operations                                                  |
| `src/sase/status_state_machine/field_updates.py`    | Simple field update ops (status, CL, parent, description)                   |
| `src/sase/status_state_machine/transitions.py`      | Composite status transition with cascading side effects                     |
| `src/sase/running_field.py`                         | RUNNING field operations (claim/release workspace)                          |
| `src/sase/commit_workflow/changespec_operations.py` | ChangeSpec creation                                                         |
| `src/sase/commit_utils/entries.py`                  | Commit entry additions                                                      |
| `src/sase/commit_utils/modifiers.py`                | Proposal rejection                                                          |
| `src/sase/ace/comments/operations.py`               | Comment field updates                                                       |
| `src/sase/ace/mentors.py`                           | Mentor field updates                                                        |
| `src/sase/ace/revert.py`                            | ChangeSpec name rename                                                      |
| `src/sase/axe/chop_script_context.py`               | ChopScriptContext pattern to follow                                         |
| `src/sase/default_config.yml`                       | Lumberjack/chop registration                                                |

## Phases

### Phase 1: Foundation - Request/Response Framework and Chop Skeleton

Build the queue, client library, chop skeleton, and the first category of handlers (simple field updates) end-to-end.
All existing write paths remain untouched -- the new code is purely additive.

**New files:**

- `src/sase/spec_writer/__init__.py` - Package init, re-exports
- `src/sase/spec_writer/models.py` - `SpecWriteRequest`, `SpecWriteResponse`, `OperationType` enum
- `src/sase/spec_writer/queue.py` - `enqueue_request()`, `dequeue_pending()`, `write_response()`, `read_response()`,
  `cleanup_stale()`
- `src/sase/spec_writer/client.py` - `submit_spec_write()`, `submit_spec_write_and_wait()`
- `src/sase/spec_writer/handlers/__init__.py`
- `src/sase/spec_writer/handlers/fields.py` - Handlers for: set_status, set_cl, set_parent, set_description, set_name,
  update_parent_references
- `src/sase/scripts/sase_chop_spec_writer.py` - Chop script: read context, drain queue, dispatch, write responses
- `tests/spec_writer/` - Unit tests for queue, client, field handlers

**Modified files:**

- `pyproject.toml` - Add `sase_chop_spec_writer` entry point
- `src/sase/scripts/__init__.py` - Add chop entry
- `src/sase/default_config.yml` - Add `spec_writer` chop to hooks lumberjack

Reuses existing pure-transform functions from `field_updates.py` (`apply_status_update`, `_apply_cl_update`,
`_apply_parent_update`, `_apply_description_update`).

---

### Phase 2: Hook and Commit Write Handlers + First Caller Migration

Implement all HOOKS and COMMITS field handlers. Migrate the axe chop callers (hook_checks, suffix_transforms,
workflow_checks) to use the client API as a proof-of-concept migration.

**New files:**

- `src/sase/spec_writer/handlers/hooks.py` - All hook handlers (set_hooks, merge_hooks, add_hook, set/clear_hook_suffix,
  update_hook_suffix_type, rerun_delete_hooks, try_claim_hook_for_fix)
- `src/sase/spec_writer/handlers/commits.py` - Commit entry handlers (add_commit_entry, add_proposed_commit_entry,
  reject_proposals_and_set_status, reject_all_new_proposals)
- `tests/spec_writer/test_hooks_handler.py`
- `tests/spec_writer/test_commits_handler.py`

**Modified files:**

- `src/sase/spec_writer/models.py` - Extend OperationType enum with Category 2 & 3 ops
- `src/sase/scripts/sase_chop_spec_writer.py` - Add dispatch for new handlers
- `src/sase/ace/hooks/persistence.py` - Migrate `update_changespec_hooks_field`, `merge_hook_updates`,
  `update_hook_status_line_suffix_type` to use client API
- `src/sase/ace/hooks/mutations.py` - Migrate `set_hook_suffix`, `add_hook_to_changespec`, `clear_hook_suffix`,
  `try_claim_hook_for_fix`, `rerun_delete_hooks_by_command` to use client API

Reuses existing pure-transform functions (`_apply_hook_suffix_update`, `_apply_clear_hook_suffix`, `apply_hooks_update`,
`format_hooks_field`).

During this phase, both old and new write paths coexist. The fcntl lock ensures mutual exclusion.

---

### Phase 3: Remaining Handlers (Comments, Mentors, RUNNING, File-Level, Composite)

Complete all remaining write handlers and migrate their callers.

**New files:**

- `src/sase/spec_writer/handlers/comments.py`
- `src/sase/spec_writer/handlers/mentors.py`
- `src/sase/spec_writer/handlers/running.py`
- `src/sase/spec_writer/handlers/file_ops.py` - add_changespec, create_project_file, raw_write, set_workspace_dir
- `src/sase/spec_writer/handlers/transitions.py` - Composite `transition_status` handler (performs all sub-writes:
  status change, suffix strip/append, parent reference updates, running field updates, mentor flags, sibling reverts
  within single lock acquisition)
- `src/sase/spec_writer/handlers/renumber.py`

**Modified files (caller migration):**

- `src/sase/ace/comments/operations.py` - Use client API
- `src/sase/ace/mentors.py` - Use client API
- `src/sase/running_field.py` - Use client API
- `src/sase/status_state_machine/transitions.py` - Use client API
- `src/sase/commit_workflow/changespec_operations.py` - Use client API
- `src/sase/commit_utils/modifiers.py` - Use client API
- `src/sase/ace/revert.py` - Use client API
- `src/sase/workspace_utils.py` - Use client API
- `src/sase/workspace_provider/plugins/bare_git_ref.py` - Use client API
- `src/sase/accept_workflow/renumber.py` - Use client API
- `src/sase/rewind_workflow/renumber.py` - Use client API

---

### Phase 4: Cleanup and Hardening

Remove legacy direct-write paths. The spec_writer chop is now the single writer.

**Tasks:**

- Audit all remaining imports of `changespec_lock` / `write_changespec_atomic` -- confirm they all route through the
  spec_writer client
- Make `write_changespec_atomic` package-private (rename to `_write_changespec_atomic`) or add deprecation warning for
  external callers
- Remove now-unused public wrappers from caller modules (the `_atomic` suffix functions in field_updates.py that were
  thin wrappers around lock+write)
- Update `src/sase/ace/changespec/__init__.py` exports
- Clean up old retry/dedup logic that was compensating for multi-writer races (e.g., `merge_hook_updates` dedup,
  `claim_workspace` retry loop) since the single-writer model eliminates those races
- Add integration test: submit multiple concurrent write requests for the same project file and verify they're applied
  correctly and in order
- Run `just check` (fmt-check + lint + test)
- Verify `sase ace --agent` end-to-end tests pass

## Verification

After each phase:

1. `just install && just check` passes
2. `sase ace --agent` produces expected output
3. Manual smoke test: `sase axe` runs and chops execute without errors
4. After Phase 4: verify no direct `changespec_lock`/`write_changespec_atomic` calls remain outside `spec_writer/`
