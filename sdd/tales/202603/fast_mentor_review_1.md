---
create_time: 2026-03-22 21:17:22
status: done
prompt: sdd/prompts/202603/fast_mentor_review_1.md
---

# Plan: Fast Mentor Review Panel (VCS-agnostic, No Workspace Checkout)

## Problem

When pressing `,m` to open the Mentor Review panel, the TUI blocks while it:

1. Claims an available axe workspace (100-199)
2. Gets the workspace directory
3. Claims it in the RUNNING field
4. Runs `git fetch origin +branch:branch` (network I/O — **slowest**)
5. Runs `git checkout branch` in the workspace (**second slowest**)

All of this exists for **one reason**: `_build_code_snippet()` needs to `open()` and read files at the branch's revision
to show syntax-highlighted code alongside mentor comments.

## Solution: Add `file_at_revision()` to the VCS Provider Interface

Add a new VCS provider method that reads a single file at a specific revision directly from the VCS object store. For
git: `git show <rev>:<path>`. Each VCS plugin implements it with its own backend command.

This eliminates the need to claim a workspace, fetch a branch, or check out anything. The method runs against the
primary workspace repo (workspace #1), which already has the branch objects because the mentor ran on them.

## Changes

### Phase 1: Add `file_at_revision()` to VCS Provider Layer

Four files in `src/sase/vcs_provider/`:

**`_base.py`** — Add optional method to `VCSProvider` ABC (alongside `show_revision`, `committed_diff`, etc.):

```python
def file_at_revision(
    self, revision: str, file_path: str, cwd: str
) -> tuple[bool, str | None]:
    """Read a single file's contents at a specific revision.

    Returns ``(True, file_content)`` on success, ``(False, error)`` on failure.
    The *file_path* should be relative to the repository root.
    """
    raise NotImplementedError(
        "file_at_revision is not supported by this VCS provider"
    )
```

**`_hookspec.py`** — Add hook spec to `VCSHookSpec` (in the optional core operations section):

```python
@hookspec(firstresult=True)
def vcs_file_at_revision(
    self, revision: str, file_path: str, cwd: str
) -> tuple[bool, str | None]: ...
```

**`_plugin_manager.py`** — Add delegation to `VCSPluginManager`:

```python
def file_at_revision(
    self, revision: str, file_path: str, cwd: str
) -> tuple[bool, str | None]:
    return self._call_or_raise(
        "vcs_file_at_revision", revision=revision, file_path=file_path, cwd=cwd
    )
```

**`plugins/_git_common.py`** — Add implementation to `GitCommon`:

```python
@hookimpl
def vcs_file_at_revision(
    self, revision: str, file_path: str, cwd: str
) -> tuple[bool, str | None]:
    out = self._run(["git", "show", f"{revision}:{file_path}"], cwd)
    if not out.success:
        return (False, f"git show failed: {out.stderr.strip()}")
    return (True, out.stdout)
```

`git show <rev>:<path>` reads from the object store directly — no checkout needed, works from any clone that has the
objects.

### Phase 2: Update Mentor Review Modal to Use VCS Provider

**`src/sase/ace/tui/modals/mentor_review_modal.py`**:

1. Replace `workspace_dir` in `_MentorReviewData` with VCS provider fields:

   ```python
   # Remove: workspace_dir: str = ""
   # Add:
   vcs_provider: VCSProvider | None = None
   revision: str = ""
   vcs_cwd: str = ""
   ```

   Note: `VCSProvider` import is under `TYPE_CHECKING` to avoid circular imports.

2. Remove `_resolve_file_path()` method entirely.

3. Update `_build_code_snippet()` to use `file_at_revision()` instead of `open()`:

   ```python
   def _build_code_snippet(self, file_path, line_number, header_lines):
       if not self._data.vcs_provider or not self._data.revision:
           return None
       try:
           ok, content = self._data.vcs_provider.file_at_revision(
               self._data.revision, file_path, self._data.vcs_cwd
           )
           if not ok or not content or not content.strip():
               return None
       except (NotImplementedError, Exception):
           return None
       # ... rest of snippet rendering unchanged ...
   ```

4. Update `build_mentor_review_data()` signature: replace `workspace_dir` param with `vcs_provider`, `revision`, and
   `vcs_cwd`. Pass them through to `_MentorReviewData`.

### Phase 3: Update Mentor Review Mixin (Eliminate Workspace Claiming)

**`src/sase/ace/tui/actions/agent_workflow/_mentor_review.py`**:

1. Replace the workspace claiming flow in `_open_mentor_review()`:

   ```python
   # Get VCS provider from the primary workspace (read-only, no claim needed)
   from sase.running_field import get_workspace_directory_for_num
   from sase.vcs_provider import get_vcs_provider

   ws_dir, _ = get_workspace_directory_for_num(1, project_basename)
   provider = get_vcs_provider(ws_dir)
   revision = provider.resolve_revision(changespec_name, project_basename, ws_dir)

   data = build_mentor_review_data(
       latest_entry, changespec.name,
       vcs_provider=provider, revision=revision, vcs_cwd=ws_dir,
   )
   ```

2. Delete `_claim_mentor_review_workspace()` method entirely.

3. Delete `_release_mentor_review_workspace()` method entirely.

4. Simplify the dismiss callback — remove workspace release logic:
   ```python
   def on_mentor_review_dismiss(result):
       if result is None:
           return
       if isinstance(result, MentorKillResult):
           self._kill_mentor_from_review(result, project_file)
           return
       self._launch_mentor_apply_agent(result.accepted_comments, result.cl_name, project_file)
   ```

### Phase 4: Plugin Repos

**`../retired Mercurial plugin/`** — Needs a `vcs_file_at_revision` hookimpl using the appropriate backend command (e.g.
`hg cat -r <rev> <path>` or equivalent).

**`../sase-github/`** — Inherits from `GitCommon`, gets the git implementation for free. No changes needed.

## Edge Cases

- **Branch not fetched locally**: If somehow the branch objects aren't in the repo, `file_at_revision()` returns
  `(False, ...)` and the snippet area shows empty. This is the same graceful degradation as when `workspace_dir` was
  empty before. In practice, the mentor ran on this branch so objects exist.
- **File path format**: Mentor comments use paths relative to repo root, which is exactly what `git show <rev>:<path>`
  expects. If a comment has an absolute path, we'd need to strip the repo root prefix — but this should be validated.

## Performance Improvement

| Step                     | Before            | After            |
| ------------------------ | ----------------- | ---------------- |
| Find available workspace | ~10ms             | eliminated       |
| Claim workspace          | ~50ms             | eliminated       |
| git fetch + checkout     | **2-10+ seconds** | eliminated       |
| Read file for snippet    | ~1ms (open)       | ~10ms (git show) |
| Release workspace        | ~50ms             | eliminated       |
| **Total**                | **2-10+ seconds** | **~50ms**        |
