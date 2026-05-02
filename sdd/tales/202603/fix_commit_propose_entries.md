---
create_time: 2026-03-26 11:31:10
status: done
prompt: sdd/prompts/202603/fix_commit_propose_entries.md
---

# Plan: Fix #commit/#propose ChangeSpec COMMITS entry creation and meta ID outputs

## Root Cause Analysis

After analyzing the logpack at `~/tmp/260326_103816/` and tracing the code, I identified **two bugs** preventing
ChangeSpec updates and correct meta field output.

### Bug 1: `post_commit.py:90` — Too-strict `result` check blocks ALL commits and likely proposals too

In `append_post_commit_entry()` at `src/sase/workflows/commit_utils/post_commit.py:90`:

```python
if not isinstance(commit_result, dict) or not commit_result.get("result"):
    return PostCommitResult(success=False)
```

- For `create_commit` (Mercurial amend), `vcs_create_commit()` returns `(True, None)`, so `commit_result.json` has
  `"result": null`. The check `not commit_result.get("result")` evaluates to `not None` → `True`, causing an early
  return. **This blocks ALL commit entry creation.**
- For `create_proposal`, `result` is non-null (CL URL), so it passes this check. But...

### Bug 2: `entries.py:321` — Silent exception swallowing in `add_proposed_commit_entry`

The logpack shows that for the proposal run, `_append_entry` completes with `entry_id=""`, meaning
`add_proposed_commit_entry` returned `(False, None)`. The function has:

```python
try:
    with changespec_lock(project_file):
        ...
        return True, entry_id
except Exception:
    return False, None  # <-- silently swallows ALL errors
```

Whatever exception is occurring (file locking on Google's distributed filesystem, ChangeSpec not found, I/O error) is
completely hidden. We need to surface these errors to make diagnosis possible.

### Consequences

1. Neither `#commit` nor `#propose` workflows update the ChangeSpec with COMMITS entries
2. `#commit` has no `meta_commit_id` output at all (only `meta_new_commit` which is empty for Mercurial)
3. `#propose`'s `_emit_proposal_id` falls back to the CL URL (`http://cl/...`) instead of entry ID (`0a`)

### Evidence from logpack

- **Commit run** (`20260326103138`): `commit_result.json` has `"result": null` → `_append_entry` output is `{}` (no
  output captured, function called but result ignored)
- **Proposal run** (`20260326103154`): `commit_result.json` has `"result": "http://cl/889536953"` → `_append_entry`
  output is `{"entry_id": ""}` → `_emit_proposal_id` falls back to CL URL

## Implementation Steps

### Step 1: Fix the `result` null check in `post_commit.py`

**File:** `src/sase/workflows/commit_utils/post_commit.py:90`

The mere existence of a valid `commit_result.json` dict means the commit succeeded (it's only written after
`CommitWorkflow.run()` returns `True`). Remove the `result` truthiness check:

```python
# Before:
if not isinstance(commit_result, dict) or not commit_result.get("result"):
    return PostCommitResult(success=False)

# After:
if not isinstance(commit_result, dict):
    return PostCommitResult(success=False)
```

### Step 2: Add error logging to `add_proposed_commit_entry` and `add_commit_entry`

**File:** `src/sase/workflows/commit_utils/entries.py`

The bare `except Exception: return False, None` at line 321 (and the equivalent at line 438) silently swallows errors.
Add stderr logging so exceptions surface in workflow output:

```python
except Exception as exc:
    import sys
    print(f"[sase] add_proposed_commit_entry failed: {exc}", file=sys.stderr)
    return False, None
```

Same for `add_commit_entry`.

### Step 3: Add `_emit_commit_id` step to `commit.yml`

**File:** `src/sase/xprompts/commit.yml`

The commit workflow currently has no equivalent of propose's `_emit_proposal_id`. Add:

1. Capture `entry_id` from `_append_entry` (currently it calls the function but ignores the result)
2. Add an `_emit_commit_id` step that emits `meta_commit_id` from the entry_id

```yaml
- name: _append_entry
  hidden: true
  if: "{{ create.success }}"
  python: |
    from sase.workflows.commit_utils.post_commit import append_post_commit_entry
    r = append_post_commit_entry(mode="commit")
    print(f"entry_id={r.entry_id or ''}")
  output:
    entry_id: word

- name: _emit_commit_id
  hidden: true
  if: "{{ create.success }}"
  python: |
    entry_id = {{ _append_entry.entry_id | default("") | tojson }}
    if entry_id:
        print(f"meta_commit_id={entry_id}")
  output:
    meta_commit_id: word
```

### Step 4: Verify and test

1. `just install && just check` — ensure lint/type/test pass
2. Verify the fix works with the existing tests for `entries.py` and `post_commit.py`
3. Add a test case for `append_post_commit_entry` with `result: null` in commit_result.json (the commit case)

## Files Modified

1. `src/sase/workflows/commit_utils/post_commit.py` — remove `result` truthiness check (Step 1)
2. `src/sase/workflows/commit_utils/entries.py` — add error logging to exception handlers (Step 2)
3. `src/sase/xprompts/commit.yml` — capture entry_id and emit `meta_commit_id` (Step 3)

## Risks and Mitigations

- **Risk:** Removing the `result` check could allow entry creation from incomplete/failed commits.
  - **Mitigation:** `commit_result.json` is only written after `CommitWorkflow.run()` returns `True`, so its existence
    already implies success. The dict-type check is sufficient.
- **Risk:** The proposal `_append_entry` failure may have a deeper root cause (e.g., filesystem locking on Google
  infra).
  - **Mitigation:** Step 2 surfaces the actual exception. Once we can see the error, we can fix the root cause in a
    follow-up if needed. The `_emit_proposal_id` fallback to CL URL is already in place as a safety net.

## Success Criteria

- `#commit` workflow creates a `(N)` COMMITS entry and emits `meta_commit_id=N`
- `#propose` workflow creates a `(Na)` COMMITS entry and emits `meta_proposal_id=Na`
- Agents panel shows `Commit Id: N` / `Proposal Id: Na` instead of CL URLs
- Errors in entry creation are logged to stderr (visible in workflow logs)
