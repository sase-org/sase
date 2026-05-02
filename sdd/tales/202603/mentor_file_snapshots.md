---
create_time: 2026-03-22 00:00:00
status: draft
prompt: sdd/prompts/202603/mentor_file_snapshots.md
---

# Plan: Snapshot File Contents at Mentor Save Time for Instant Review

## Problem

Every time the user navigates to a comment in the Mentor Review modal, `_build_code_snippet()` calls
`vcs_provider.file_at_revision()` which spawns a `git show <revision>:<file_path>` subprocess. This means:

1. **Per-comment latency**: Each comment navigation triggers a blocking git subprocess (~10-50ms per call).
2. **Redundant fetches**: If 5 comments reference the same file, that file is fetched 5 separate times.
3. **VCS dependency at review time**: The review modal requires a VCS provider, a resolved revision, and a workspace
   directory — all of which must be set up before the modal opens.
4. **Fragility**: If workspace #1 doesn't have the branch objects (e.g., after a `git gc`), snippets silently fail.

The mentor agent already has the files checked out at the correct revision when it runs. We should capture file contents
at that point and store them alongside the mentor output, so review is purely a disk read with zero git calls.

## Solution: File Snapshots as a Companion File

When a mentor produces comments, snapshot the content of every unique file referenced in those comments. Store the
snapshots in a companion JSON file alongside the existing mentor output file. At review time, load snapshots from disk
and use them directly — falling back to `file_at_revision()` only for old mentor outputs that lack snapshots.

### Why companion files (not inline in mentor output JSON)?

- **Backward compatibility**: Existing mentor output files remain valid without schema migration.
- **Separation of concerns**: Mentor output JSON stores the mentor's review; file snapshots are auxiliary data.
- **Independent lifecycle**: Snapshots can be cleaned up independently (they're large — full file contents).
- **Loading flexibility**: The review modal can load snapshots lazily or skip them if not needed.

### Why not an in-memory cache?

An in-memory LRU cache on `file_at_revision()` would help with redundant fetches within a single review session, but it
wouldn't help with the fundamental problem: every modal open still requires VCS setup and at least one git call per
unique file. Snapshotting at save time eliminates all git calls at review time.

## Storage Format

### File naming

```
~/.sase/mentors/<cl>-<profile>-<mentor>-<timestamp>-files.json
```

Mirrors the existing mentor output naming with a `-files` suffix. Example:

```
~/.sase/mentors/my_feature-code-quality-260322_120000.json        # existing mentor output
~/.sase/mentors/my_feature-code-quality-260322_120000-files.json  # NEW: file snapshots
```

### File contents

```json
{
  "revision": "abc123def",
  "files": {
    "src/sase/ace/tui/app.py": "import os\nimport sys\n...",
    "src/sase/workflows/mentor.py": "\"\"\"Workflow for...\"\"\"\n..."
  }
}
```

- `revision`: The VCS revision the files were captured at (for diagnostics/cache invalidation).
- `files`: Map of `file_path → full_file_content` for every unique file referenced in comments.

### Size considerations

Typical mentor output has 3-10 comments referencing 2-5 unique files. Average Python file is ~5-20KB. So a typical
snapshot file is ~10-100KB — comparable to the mentor output JSON itself. Acceptable.

## Changes

### Phase 1: Capture and Save File Snapshots (Save Time)

**`src/sase/ace/mentor_output.py`** — Add save/load functions for file snapshots:

```python
def save_file_snapshots(
    cl_name: str,
    profile_name: str,
    mentor_name: str,
    timestamp: str,
    revision: str,
    files: dict[str, str],
) -> Path:
    """Save file content snapshots alongside mentor output.

    File is written to ``~/.sase/mentors/<cl>-<profile>-<mentor>-<ts>-files.json``.
    """
    SASE_MENTORS_DIR.mkdir(parents=True, exist_ok=True)
    safe_cl = cl_name.replace("/", "_")
    filename = f"{safe_cl}-{profile_name}-{mentor_name}-{timestamp}-files.json"
    path = SASE_MENTORS_DIR / filename
    data = {"revision": revision, "files": files}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def load_file_snapshots(
    cl_name: str,
    profile_name: str,
    mentor_name: str,
    timestamp: str,
) -> dict[str, str]:
    """Load file snapshots for a mentor output.

    Returns an empty dict if the file doesn't exist or is malformed.
    """
    safe_cl = cl_name.replace("/", "_")
    filename = f"{safe_cl}-{profile_name}-{mentor_name}-{timestamp}-files.json"
    path = SASE_MENTORS_DIR / filename
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("files", {})
    except (json.JSONDecodeError, TypeError, AttributeError):
        log.warning("Malformed file snapshots: %s", path)
        return {}
```

Note: No indentation in `json.dumps` — these files can be large and we don't need human readability. This saves ~30%
disk space compared to indented output.

**`src/sase/workflows/mentor.py`** — Capture file contents after parsing mentor output:

After `_parse_mentor_json()` succeeds and before/alongside `save_mentor_output()`, read the referenced files:

```python
# After line ~368 (after save_mentor_output call)
if mentor_output is not None and mentor_output.comments:
    # Snapshot files referenced by comments for fast review
    unique_paths = {c.file_path for c in mentor_output.comments}
    file_contents: dict[str, str] = {}
    for fp in unique_paths:
        try:
            full_path = os.path.join(os.getcwd(), fp)
            with open(full_path, encoding="utf-8", errors="replace") as f:
                file_contents[fp] = f.read()
        except OSError:
            log.debug("Could not snapshot %s for mentor review", fp)
    if file_contents:
        from sase.ace.mentor_output import save_file_snapshots
        save_file_snapshots(
            resolved_cl_name,
            self.profile_name,
            self.mentor_name,
            self._timestamp,
            revision,  # needs to be captured earlier in the workflow
            file_contents,
        )
```

**Revision capture**: The mentor workflow resolves the CL name to a branch, checks it out, and runs. We need to capture
the current revision (e.g., `git rev-parse HEAD`) at the point the mentor runs. Look at how `MentorWorkflow.run()` sets
up the workspace — the revision is available from `vcs_provider.resolve_revision()` or can be captured with a simple
`git rev-parse HEAD` after checkout. Need to trace this through the workflow to find the exact variable. The `revision`
variable should be stored as an instance attribute on `MentorWorkflow` during the workspace setup phase, then referenced
when saving snapshots.

### Phase 2: Load File Snapshots at Review Time

**`src/sase/ace/tui/modals/mentor_review_modal.py`**:

1. Add `file_snapshots` field to `_MentorReviewData`:

   ```python
   @dataclass
   class _MentorReviewData:
       mentors: list[MentorInfo]
       acceptance: MentorAcceptanceState
       cl_name: str
       entry_id: str
       vcs_provider: VCSProvider | None = None
       revision: str = ""
       vcs_cwd: str = ""
       file_snapshots: dict[str, str] = field(default_factory=dict)  # NEW
       total_comments: int = field(init=False, default=0)
   ```

2. Update `build_mentor_review_data()` to load and merge file snapshots from all mentor outputs:

   ```python
   # After building the mentors list and ts_output_map, load file snapshots
   from sase.ace.mentor_output import load_file_snapshots

   all_snapshots: dict[str, str] = {}
   for sl in mentor_entry.status_lines or []:
       snapshots = load_file_snapshots(cl_name, sl.profile_name, sl.mentor_name, sl.timestamp)
       all_snapshots.update(snapshots)  # later mentors overwrite — same revision, same content

   # Pass to _MentorReviewData
   return _MentorReviewData(
       ...,
       file_snapshots=all_snapshots,
   )
   ```

3. Update `_build_code_snippet()` to check snapshots first:

   ```python
   def _build_code_snippet(self, file_path, line_number, header_lines):
       # Try file snapshots first (instant, no subprocess)
       content = self._data.file_snapshots.get(file_path)

       # Fall back to VCS provider for old mentor outputs without snapshots
       if content is None and self._data.vcs_provider and self._data.revision:
           try:
               ok, vcs_content = self._data.vcs_provider.file_at_revision(
                   self._data.revision, file_path, self._data.vcs_cwd
               )
               if ok and vcs_content and vcs_content.strip():
                   content = vcs_content
           except (NotImplementedError, Exception):
               pass

       if content is None:
           return None

       # ... rest of snippet rendering unchanged (line count, lexer, Syntax object) ...
   ```

### Phase 3: Simplify the Review Modal Opening (Optional Optimization)

With file snapshots, the VCS provider + revision resolution in `_open_mentor_review()` becomes a **fallback** path
rather than the primary path. If all mentor outputs have snapshots, we don't need VCS at all.

**`src/sase/ace/tui/actions/agent_workflow/_mentor_review.py`**:

Could defer VCS setup to only happen if `build_mentor_review_data()` detects missing snapshots. But for simplicity and
backward compatibility, keep the current VCS setup as-is — it's lightweight (~10ms for `resolve_revision()` against
local objects) and provides the fallback.

No changes needed here unless we want to make it lazy.

## Testing

### Unit tests for save/load (`tests/test_mentor_output.py` or similar):

- `test_save_file_snapshots_creates_file`: Verify file is created at expected path with correct JSON structure.
- `test_load_file_snapshots_returns_contents`: Verify round-trip save → load.
- `test_load_file_snapshots_missing_file`: Returns empty dict.
- `test_load_file_snapshots_malformed_json`: Returns empty dict with warning.

### Unit tests for review modal (`tests/test_mentor_review_modal.py`):

- `test_build_code_snippet_uses_snapshots`: When `file_snapshots` has the file, VCS provider is never called.
- `test_build_code_snippet_falls_back_to_vcs`: When `file_snapshots` is empty, VCS provider is used.
- `test_build_mentor_review_data_loads_snapshots`: Verify snapshots are loaded and merged into `_MentorReviewData`.

### Integration / E2E:

- Run a mentor workflow against a test CL, verify `-files.json` companion file is created.
- Open mentor review modal, verify code snippets render without VCS calls.

## Migration / Backward Compatibility

- **Old mentor outputs** (no companion `-files.json`): `load_file_snapshots()` returns `{}`, and the modal falls back to
  `file_at_revision()`. Zero behavior change for existing data.
- **New mentor outputs**: Companion file is always created if the mentor produced comments. Review uses snapshots.
- **No schema changes** to existing files. No migration needed.

## Performance Impact

| Operation                 | Before                         | After                                   |
| ------------------------- | ------------------------------ | --------------------------------------- |
| Mentor save time          | ~0ms extra                     | ~5-20ms (read 2-5 files from disk)      |
| Review modal open         | ~50ms (VCS setup)              | ~50ms (unchanged, VCS kept as fallback) |
| Per-comment navigation    | ~10-50ms (git show subprocess) | **~0ms** (dict lookup)                  |
| 10-comment review session | ~100-500ms total git calls     | **~0ms** total git calls                |

The save-time cost is negligible (mentor workflows take minutes; adding 5-20ms of file reads is invisible). The review
time improvement is the main win — navigating between comments becomes instant.

## File Summary

| File                                             | Change                                                  |
| ------------------------------------------------ | ------------------------------------------------------- |
| `src/sase/ace/mentor_output.py`                  | Add `save_file_snapshots()` and `load_file_snapshots()` |
| `src/sase/workflows/mentor.py`                   | Capture file contents after mentor output parsing       |
| `src/sase/ace/tui/modals/mentor_review_modal.py` | Add `file_snapshots` to data, check before VCS fallback |

Three files changed. No deletions. No schema migrations. Full backward compatibility.
