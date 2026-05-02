---
create_time: 2026-04-27 22:43:00
status: ready
prompt: sdd/prompts/202604/live_diff_cache_invalidation.md
---

# Plan: Fix Live-Diff Regression in `sase ace` Agents-Tab File Panel

## Problem

The user reports that the **live diff** in the `sase ace` TUI's "Agents" tab file panel is broken: the diff for an
actively-running agent stops updating as the agent edits files. The user attributes this to a recent performance
optimization, and cited the agent named `sase-10.4` as an example where they expected to see a diff but did not.

## Root Cause

Commit `a4f97a7f feat(ace/tui/perf): artifact + render caching (sase-w.6)` added a module-level `_diff_cache` in
`src/sase/ace/tui/widgets/file_panel/_diff.py` to short-circuit redundant `diff_with_untracked` calls.

The cache key, built by `compute_diff_cache_key()` and inlined in `get_agent_diff()`, derives a "worktree fingerprint"
from `.git/index` (mtime_ns, size). A 2-second TTL bucket is used as a fallback **only** when `_git_index_signature`
returns `None` (i.e. when there is no `.git/index` at all):

```python
fingerprint = _git_index_signature(workspace_dir)
ttl_bucket = (
    int(time.time() // DIFF_CACHE_TTL_SECONDS) if fingerprint is None else None
)
```

The bug: `.git/index` only mutates on git plumbing operations (`git add`, `git commit`, occasional stat-cache refresh).
**It does not change when the working tree is edited.** Meanwhile the cached value comes from
`vcs_diff_with_untracked()` (`src/sase/vcs_provider/plugins/_git_query_ops.py:156-181`), which runs `git diff HEAD` plus
an `ls-files --others` walk — both of which reflect the **working tree**, not the index.

I verified this locally:

```
$ stat -c '%Y %s' .git/index
1777343854 137
$ echo b >> f.txt        # edit a tracked file, no `git add`
$ stat -c '%Y %s' .git/index
1777343854 137           # unchanged
$ git diff HEAD          # but the diff sees the change
diff --git a/f.txt b/f.txt
…
```

So while a running agent edits files in its workspace, the cache becomes "permanently warm" and `get_agent_diff()` keeps
returning the original first-fetch result — typically the empty/`None` value captured before the agent had written
anything. The TTL fallback never activates because `.git/index` exists in every normal git workspace.

### Why "sase-10.4" specifically renders nothing

`sase-10.4` is a multi-prompt epic-phase agent (artifact dir `~/.sase/projects/sase/artifacts/ace-run/20260427213715/`,
`agent_meta.name = "sase-10.4"`, `stopped_at = 2026-04-28T02:30:05`). It is currently DONE.

For DONE agents, `get_agent_diff()` returns `None` if `agent.diff_path` is missing — the early-return added by
`351af00a` in March to prevent showing unrelated workspace diffs. No diff file exists in `~/.sase/diffs/` for any
`sase-10.x` agent, so `diff_path` is empty.

This is a **separate, pre-existing** issue (named multi-prompt epic-phase agents don't get a saved `diff_path`) and is
out of scope here. It explains why the user's specific cited example shows nothing even after we fix the cache.

The "live diff is broken" framing, however, almost certainly refers to the cache-staleness regression for the
still-RUNNING siblings (`sase-10.5`, `sase-10.6`, `sase-10.land`). Those are the agents the user is actually watching
for diff updates.

## Goal

Make the `_diff_cache` invalidate on a signal that actually correlates with "the working tree may have changed", while
preserving the j/k-burst dedupe benefit the cache was added for.

## Relevant Code

- `src/sase/ace/tui/widgets/file_panel/_diff.py:29` — `DIFF_CACHE_TTL_SECONDS = 2.0`.
- `src/sase/ace/tui/widgets/file_panel/_diff.py:63-83` — `compute_diff_cache_key()` (used by `_start_background_fetch`
  for in-flight worker dedupe).
- `src/sase/ace/tui/widgets/file_panel/_diff.py:116-152` — the inlined cache-key block in `get_agent_diff()`.
- `src/sase/vcs_provider/plugins/_git_query_ops.py:156-181` — `vcs_diff_with_untracked()`, the underlying call we are
  caching.
- `tests/ace/tui/widgets/file_panel/test_diff_cache.py` — existing cache tests.

## Approach

**Make the TTL bucket the primary invalidation signal.** Always include it in the cache key, regardless of whether the
`.git/index` signature is available. Keep the index signature as a secondary discriminator (so a stage/commit during a
TTL window still invalidates immediately).

Concrete changes in `_diff.py`:

1. Drop the `if fingerprint is None` gate around `ttl_bucket`. Compute `ttl_bucket` unconditionally in both
   `compute_diff_cache_key()` and the inline block in `get_agent_diff()`.
2. Update the module docstring and the docstring on `compute_diff_cache_key()` / the comment on `DIFF_CACHE_TTL_SECONDS`
   to explain that the TTL is the primary invalidation signal because `git diff HEAD` reflects the working tree, which
   `.git/index` does not track.
3. Tighten `DIFF_CACHE_TTL_SECONDS` from `2.0` to `1.0`. The 2 s value was chosen as a fallback ceiling; now that it is
   the live-diff staleness bound the user actually feels, ~1 s feels right — fast enough that fresh edits show up within
   a heartbeat, slow enough to absorb j/k navigation bursts (typical j-mash is sub-second).

The DiffCacheKey type alias should also reflect the change: `int | None` becomes `int` for the bucket field.

## Phases

### Phase 1 — Make TTL the primary invalidation signal

Files:

- `src/sase/ace/tui/widgets/file_panel/_diff.py`
- `tests/ace/tui/widgets/file_panel/test_diff_cache.py`

Changes:

- Remove the `if fingerprint is None` conditional on `ttl_bucket` in both call sites.
- Lower `DIFF_CACHE_TTL_SECONDS` to `1.0`.
- Update module/function docstrings to explain why TTL must always run.
- Update `DiffCacheKey` type alias: bucket field becomes `int` (no longer `int | None`).

Test updates required by the type/key shape change:

- `test_compute_diff_cache_key_includes_provider_name` — replace `assert key[4] is None` with
  `assert isinstance(key[4], int)`.
- `test_compute_diff_cache_key_uses_ttl_bucket_when_no_git_index` — still valid in spirit; the assertions on
  `key[3] is None` (no fingerprint) and `isinstance(key[4], int)` continue to hold. May want to rename to clarify the
  TTL bucket is always present, not just on the no-`.git/index` path.
- `test_get_agent_diff_caches_on_unchanged_worktree` — freeze `time.time` (e.g.
  `patch.object(diff_mod.time, "time", return_value=...)`) so the test exercises "two calls within one TTL bucket"
  deterministically rather than relying on real-time being fast.
- `test_get_agent_diff_invalidates_when_index_changes` — still valid; the index-sig component still discriminates.

### Phase 2 — Add a regression test for working-tree edits

File: `tests/ace/tui/widgets/file_panel/test_diff_cache.py`

Add a test that pins the regression we're fixing:

- Set up a workspace with `.git/index` (so the previous code path took the index-sig branch).
- First call: capture diff `A` from a fake provider; `.git/index` is unchanged.
- Advance the frozen clock past `DIFF_CACHE_TTL_SECONDS`.
- Have the fake provider now return diff `B` (simulating a working-tree edit the agent just made).
- Second call: assert the result is `B` and the provider was called twice.

This test fails on master (cache hit returns `A`) and passes after Phase 1.

### Phase 3 (out of scope, follow-up bead)

Note for the user — do not implement here:

- Named multi-prompt epic-phase agents (e.g. `sase-10.x`) don't get a saved `diff_path`, so DONE agents in this family
  render "No changes detected" once stopped. This is a separate, pre-existing gap (predates the perf changes), and the
  fix likely lives in the run/diff-snapshot pipeline rather than the file panel. Worth tracking as its own bead.

## Out of Scope

- Reworking the `file_cache` layer in `_messages.py` (10-second staleness check on `update_display`). It's correct on
  its own and isn't the source of the regression.
- Removing `_diff_cache` entirely in favor of relying solely on `_inflight_diff_tasks`. The cache still pays for itself
  during j/k bursts within a single TTL window; we just need it to invalidate properly.
- Switching to a working-tree fingerprint based on file mtimes (e.g. walking the tree). Too expensive for the hot path,
  and the TTL-only approach is sufficient.
- Fixing `diff_path` for named multi-prompt epic-phase agents (Phase 3 above).

## Risks / Trade-offs

- **Slightly more `git diff HEAD` calls.** With a 1 s TTL, rapid arrow-key navigation across many distinct agents will
  re-fetch the diff for each. But the cache continues to dedupe re-selects of the _same_ agent within a 1 s window, and
  `_inflight_diff_tasks` continues to coalesce concurrent re-selects. Acceptable.
- **Test determinism.** Freezing `time.time` is straightforward but adds boilerplate. Worth it to keep the tests fast
  and non-flaky.
