---
create_time: 2026-05-15 13:01:52
status: done
prompt: sdd/prompts/202605/bead_work_gitignored_db.md
---
# Fix `sase bead work` failing because `git add` warns on the gitignored `beads.db`

## Problem

`sase bead work` calls `commit_bead_work_launch` (`src/sase/bead/sync.py:38`) which runs:

```
git add -- sdd/beads ":(exclude)sdd/beads/beads.db*"
```

When `sdd/beads/beads.db` exists on disk (the common case — it's the SQLite store that backs the JSONL log), git emits:

```
The following paths are ignored by one of your .gitignore files:
sdd/beads/beads.db
hint: Use -f if you really want to add them.
```

and exits with code **1**, even though the include pathspec `sdd/beads` plus the `:(exclude)…/beads.db*` exclusion _do_
still stage the non-ignored files (`issues.jsonl`, `events/streams/*.jsonl`). `_run_git_or_raise` interprets the
non-zero exit as failure and raises `BeadWorkLaunchCommitError`, which surfaces as
`Error: agents launched for epic <id>, but committing bead state failed: …` and exits with code 1 — even though the
agents _were_ launched and the bead state _was_ in fact partially staged.

The same broken pattern is used by `git_sync` (line 30–35) and `bead_state_is_clean` (line 96–106).
`bead_state_is_clean` happens to not break because `git status --porcelain` does not emit the ignored-files warning, but
its pathspec construction is the same shape, so it warrants the same fix for consistency.

## Root cause

`:(exclude)` pathspecs filter _which files get staged_, but they do not suppress git's "you tried to add a path that's
gitignored" diagnostic. That diagnostic is driven by what the include pathspec (`sdd/beads`) walks, not by what survives
the exclude filter. Manual reproduction in `/tmp/gitbead-test2` confirms: exit 1, ignored-files warning, and the
non-ignored files staged anyway.

`--ignore-errors` does **not** help (still exits 1). Setting `advice.addIgnoredFile=false` silences the hint text but
**not** the exit code.

## Solution

Stop relying on git to walk the `sdd/beads` directory. Instead, enumerate the files we want to stage with
`git ls-files`, which natively respects `.gitignore` and so will never return `beads.db`. Then pass the resulting
explicit file list to `git add --`.

The canonical enumeration command:

```
git ls-files --modified --others --deleted --exclude-standard -z -- <rel_beads>/
```

- `--modified` — tracked files whose worktree differs from the index
- `--others` — untracked files
- `--deleted` — tracked files removed from the worktree (so `git add` records the deletion)
- `--exclude-standard` — apply `.gitignore`/`.git/info/exclude`/global ignores
- `-z` — NUL-terminate output for robust parsing

Manual reproduction in `/tmp/gitbead-test3` confirms this approach correctly handles a mix of new, modified, deleted,
and ignored files: exit 0, only non-ignored files staged, deletions recorded.

## Implementation

All changes live in `src/sase/bead/sync.py` and `tests/test_bead/test_sync.py`.

### 1. New helper: enumerate bead-state files to stage

Replace `_bead_state_pathspecs` with a helper that returns the **list of specific files** to stage. Keep a separate
small helper for the relative bead path used in commit messages / error strings.

```python
def _list_bead_state_changes(beads_dir: Path, repo_root: Path) -> list[str]:
    """Return the set of bead-state files (relative to repo_root) that have
    uncommitted changes — modified, untracked, or deleted — excluding any
    files matched by .gitignore (so `beads.db` and its SQLite sidecars are
    never returned)."""
    rel_beads = _relative_pathspec(beads_dir, repo_root)
    result = subprocess.run(
        ["git", "ls-files",
         "--modified", "--others", "--deleted",
         "--exclude-standard", "-z",
         "--", f"{rel_beads}/"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise BeadWorkLaunchCommitError(
            _format_git_failure(f"enumerate bead-state changes under {rel_beads}",
                                _to_text_result(result))
        )
    # Split on NUL, drop trailing empty, dedupe while preserving order
    raw = result.stdout.split(b"\x00")
    seen: dict[str, None] = {}
    for entry in raw:
        if entry:
            seen.setdefault(entry.decode(), None)
    return list(seen)
```

Note: `ls-files` can list the same path twice (e.g. `--modified` + `--deleted` for a path that's been removed after
modification), so we dedupe.

Add a tiny `_to_text_result` adapter (or just decode stderr inline) so `_format_git_failure` keeps working with the
byte-mode subprocess result.

### 2. Refactor `git_sync` (sync.py:23)

```python
def git_sync(beads_dir: Path) -> None:
    if not beads_dir.exists():
        return
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return
    files = _list_bead_state_changes(beads_dir, repo_root)
    if not files:
        return
    subprocess.run(
        ["git", "add", "--", *files],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
```

`git_sync` currently swallows errors (it's a best-effort stage). Preserve that: if `_list_bead_state_changes` raises,
let it propagate only from `commit_bead_work_launch` paths — `git_sync` is allowed to silently no-op. Decision: wrap the
call in a try/except for `git_sync` to keep its fire-and-forget semantics, or hoist the listing into an inner helper
that returns `[]` on subprocess failure for `git_sync`. **Recommendation:** the latter — make `_list_bead_state_changes`
raise (so the commit path can fail loudly) and add a thin `_list_bead_state_changes_silent` that swallows for
`git_sync`. This keeps the existing "git_sync is best-effort" contract.

### 3. Refactor `commit_bead_work_launch` (sync.py:38)

```python
def commit_bead_work_launch(beads_dir, bead_id, title, *, kind) -> bool:
    del title
    if not beads_dir.exists():
        return False
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return False

    files = _list_bead_state_changes(beads_dir, repo_root)
    if not files:
        return False

    _run_git_or_raise(
        ["git", "add", "--", *files],
        cwd=repo_root,
        action=f"stage {_relative_pathspec(beads_dir, repo_root)}",
    )

    # Confirm the add actually produced staged changes vs the index. With the
    # new enumeration this should always be true when files != [], but keep
    # the guard so we don't create empty commits if a race wiped the changes.
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *files],
        cwd=repo_root,
        capture_output=True, text=True, check=False,
    )
    if diff_result.returncode == 0:
        return False
    if diff_result.returncode != 1:
        raise BeadWorkLaunchCommitError(
            _format_git_failure("inspect staged changes", diff_result)
        )

    subject_kind = "legend" if kind == "legend" else "bead"
    message = f"chore: mark {subject_kind} work launched for {bead_id}"
    _run_git_or_raise(
        ["git", "commit", "-m", message, "--", *files],
        cwd=repo_root,
        action=f"commit {_relative_pathspec(beads_dir, repo_root)}",
    )
    return True
```

Key change in the `git diff --cached` check on line 66 of current code: the pathspec list changes from
`[<dir>, :(exclude)beads.db*]` to the explicit file list. That's strictly more correct — we're asking "did these
_specific_ files end up staged?", which is exactly the question we want answered.

Likewise the `git commit -- …` pathspec at line 82 becomes the explicit list, so we don't accidentally include unrelated
staged files in the commit. (This preserves the property tested by
`test_commit_bead_work_launch_leaves_unrelated_staged_files_staged`.)

### 4. Refactor `bead_state_is_clean` (sync.py:89)

Current behavior is fine in practice (status doesn't warn-and-fail like add does), but for consistency, route it through
the same helper:

```python
def bead_state_is_clean(beads_dir) -> bool:
    if not beads_dir.exists():
        return True
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return True
    try:
        files = _list_bead_state_changes(beads_dir, repo_root)
    except BeadWorkLaunchCommitError:
        return True  # preserve current "swallow errors" behavior
    return not files
```

This eliminates a parallel `git status --porcelain` invocation and unifies the "what counts as a bead-state change?"
logic into one helper. (Optional — if this feels like scope creep, leave `bead_state_is_clean` alone and just fix the
two write paths.)

### 5. Delete `_bead_state_pathspecs`

Once no callers remain.

## Tests

Add to `tests/test_bead/test_sync.py`:

### Regression test — the actual bug

```python
def test_git_sync_succeeds_when_gitignored_beads_db_present(tmp_path):
    _init_git_repo(tmp_path)
    # Mirror the production gitignore line so beads.db is ignored.
    (tmp_path / ".gitignore").write_text("sdd/beads/beads.db*\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "gi"], cwd=tmp_path, check=True)

    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')
    (beads_dir / "beads.db").write_bytes(b"\x53\x51\x4c\x69\x74\x65")  # "SQLite"
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')

    git_sync(beads_dir)  # must not raise, must not leave beads.db staged

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert "sdd/beads/issues.jsonl" in staged
    assert "sdd/beads/events/streams/sase-1.jsonl" in staged
    assert "sdd/beads/beads.db" not in staged
```

And the same shape for `commit_bead_work_launch`:

```python
def test_commit_bead_work_launch_succeeds_when_gitignored_beads_db_present(tmp_path):
    # same setup …
    assert commit_bead_work_launch(beads_dir, "sase-1", "Test", kind="epic") is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert "sdd/beads/beads.db" not in files
    assert "sdd/beads/issues.jsonl" in files
    assert "sdd/beads/events/streams/sase-1.jsonl" in files
```

### Edge-case tests

- **Deletion handling**: setup with a committed event-stream file, delete it, call `commit_bead_work_launch`. Assert the
  commit records the deletion (so bead state stays in sync when an event stream is reaped).
- **All-ignored / nothing-to-stage**: setup where only `beads.db` is new on disk, with nothing else changed. Assert
  `commit_bead_work_launch` returns `False` and no commit is created. (Today this case raises because of the exit-code-1
  bug; after the fix it should be a clean no-op.)
- **Subdirectory untracked files**: confirm new files under newly created subdirectories (e.g.
  `sdd/beads/events/streams/<new-bead-id>.jsonl` where `events/streams/` itself is also new) get picked up. `--others`
  does this.

Verify existing tests still pass — particularly `test_commit_bead_work_launch_leaves_unrelated_staged_files_staged`,
since that's the property guaranteeing the commit doesn't sweep in unrelated work.

## Edge cases and open questions

- **The `git_sync` silent-failure contract.** Today `git_sync` swallows any subprocess error (it uses `check=False` and
  never inspects the result). The plan preserves that. Worth deciding: should the new ls-files invocation in `git_sync`
  actually report problems? Recommendation: no — `git_sync` is called from `BeadProject.sync()` which has no
  error-handling story for it; changing that is out of scope.
- **Performance.** We now run one extra `git` subprocess per `git_sync` / `commit_bead_work_launch` call (the `ls-files`
  enumeration). Both code paths already shell out to git multiple times, so the marginal cost is negligible. The
  `tests/test_bead/test_cli_work_*` suite mostly mocks `commit_bead_work_launch`, so test runtime shouldn't shift.
- **Pathspec for `git diff --cached --quiet` after the add.** With an explicit file list this is a strictly tighter
  check than the old `[<dir>, :(exclude)…]`. No behavior loss.
- **Mocking surface.** `tests/test_bead/test_cli_work_epic_lifecycle.py`, `test_cli_work_legend.py`,
  `test_cli_work_epic_launch.py` mock `commit_bead_work_launch` itself — they don't care about its internals, so no
  changes needed there.
- **`_bead_state_pathspecs` is module-private and only referenced inside `sync.py`** — safe to remove.
- **Race condition: bead state changes between enumerate and add.** If a concurrent process modifies a bead-state file
  after our `ls-files` call but before our `git add`, the added file reflects the _new_ contents. This is also how the
  old code behaved (git's directory walk had the same race), so no regression. Not worth guarding against.
- **`beads.db-shm`/`beads.db-wal` sidecars.** SQLite WAL/SHM files match `beads.db*` in the gitignore.
  `ls-files --exclude-standard` will drop them automatically — no special-case needed.

## Verification

1. `just lint`
2. `just test tests/test_bead/test_sync.py` — new + existing tests pass
3. `just test tests/test_bead/` — full bead suite passes (mocked-commit tests should be unaffected)
4. `just check` — full project gate
5. Manual smoke: in this repo, run `sase bead work <some-epic-id>` and confirm the post-launch commit succeeds even
   though `sdd/beads/beads.db` is on disk.
