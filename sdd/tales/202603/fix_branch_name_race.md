---
create_time: 2026-03-29 19:02:41
status: done
---

# Fix: Branch name race condition in concurrent PR agents

## Problem

When multiple agents run concurrently with the same `pr(name=X)` workflow, `compute_suffixed_cl_name` reads the project
file under a lock to find the next `_<N>` suffix, but **releases the lock before the VCS operation creates and pushes
the branch**. Two agents calling it concurrently both see the same set of existing names, compute the same suffix, and
race to push the same branch to origin. The loser's push fails, so that agent never creates a PR.

**Concrete trace (from the snapshots):**

Both @p.1 (workspace #103, Codex) and @n.1 (workspace #102, Claude opus) ran with `pr(name=timestamps)`. Both computed
the same suffixed branch name (e.g. `timestamps_14`). One agent pushed first; the other's push failed with a remote ref
conflict, causing `vcs_create_pull_request` to return `(False, err)` and no PR was created for that agent.

The root cause is a classic TOCTOU (time-of-check-time-of-use) gap: the suffix is **checked** under a lock, but the name
is only **used** (branch pushed) after the lock is released.

## Fix: Reservation entry in the project file

Make `compute_suffixed_cl_name` **write a minimal reservation entry** to the project file within the same lock
acquisition that computes the suffix. This way, the next agent to compute a suffix sees the reserved name and picks the
next number.

### Phase 1: `compute_suffixed_cl_name` writes a reservation

**File:** `src/sase/workflows/commit/changespec_operations.py`

Change `compute_suffixed_cl_name` so that after computing the suffix, it appends a minimal ChangeSpec block to the
project file **within the lock**:

```
NAME: timestamps_14
STATUS: Reserved
```

This guarantees atomicity — the next agent that acquires the lock will see `timestamps_14` in the existing names and
skip to `timestamps_15`.

Return a `(suffixed_name, reserved)` tuple (or keep the `str | None` return and track reservation state via a new `bool`
parameter/flag).

### Phase 2: `add_changespec_to_project_file` replaces reservations

**File:** `src/sase/workflows/commit/changespec_operations.py`

When `add_changespec_to_project_file` runs (after the VCS push succeeds), it should detect if a `Reserved` entry with
the target base name already exists. If so, **replace the reservation in-place** with the full ChangeSpec block (keeping
the same suffixed name) instead of computing a new suffix.

The caller (`_create_changespec` in `workflow.py`) already passes the base name. Add a new `reserved_name` parameter so
it can also pass the pre-computed suffixed name. When `reserved_name` is provided:

1. Look for `NAME: <reserved_name>` with `STATUS: Reserved` in the file.
2. Replace that block with the full ChangeSpec.
3. Skip the suffix recomputation.

### Phase 3: Cleanup on VCS failure

**File:** `src/sase/workflows/commit/workflow.py`

If `vcs_create_pull_request` fails (line 146: `if not ok`), call a new `remove_reservation` helper to delete the
reservation entry from the project file. This prevents stale reservations from accumulating.

Add a `remove_reservation(project_file, reserved_name)` function to `changespec_operations.py` that acquires the lock,
finds the `NAME: <reserved_name> / STATUS: Reserved` block, removes it, and writes atomically.

### Phase 4: Pass reservation through the workflow

**File:** `src/sase/workflows/commit/workflow.py`

- Store the suffixed name returned by `compute_suffixed_cl_name` on `self._reserved_name`.
- On VCS failure, call `remove_reservation(project_file, self._reserved_name)`.
- On VCS success, pass `reserved_name=self._reserved_name` to `_create_changespec` → `create_changespec_for_workflow` →
  `add_changespec_to_project_file`.
