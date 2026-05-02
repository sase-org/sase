---
create_time: 2026-03-29 17:30:03
status: done
prompt: sdd/prompts/202603/fix_refresh_docs_999.md
---

# Fix: refresh_docs workflow showing 999 for commit count

## Problem

The `sase/refresh_docs` workflow's `count_commits` step displays `"count": 999` instead of the real commit count. This
is a sentinel value the code uses when it can't determine the actual count, but it's confusing to the user.

## Root Cause

The `count_commits` step in `xprompts/refresh_docs.yml` uses a globally shared marker file
(`~/.sase/projects/sase/refresh_docs_marker`) that stores a commit SHA. The workflow runs across different ephemeral
workspace clones (`sase_<N>` directories).

The failure scenario:

1. A previous run in workspace A completes and writes the marker with SHA `2be3e593` (a recent commit).
2. A new run starts in workspace B, whose git clone is stale -- it hasn't fetched commits up to `2be3e593`.
3. `git cat-file -t 2be3e593` fails in workspace B because that commit object doesn't exist locally.
4. The code falls back to `count = 999`.

Evidence from this specific case:

- The marker contains `2be3e593` (commit from the main repo's history).
- The workflow ran with HEAD at `a1891503`, which is 22 commits **behind** the marker SHA.
- `a1891503` is an ancestor of `2be3e593` -- the workspace was simply stale.

## Fix

Store both the SHA **and** the commit's author timestamp in the marker file. When the SHA isn't found in the current
workspace (cross-clone scenario), fall back to timestamp-based counting which works universally across any clone.

### Changes to `xprompts/refresh_docs.yml`

**`count_commits` step** -- change the fallback logic:

- Parse marker as `<sha> <unix_timestamp>` (with backward compat for old `<sha>`-only format)
- When SHA exists: precise `git rev-list --count <sha>..HEAD`
- When SHA missing but timestamp available: approximate `git rev-list --count --after=<ts> HEAD`
- When neither works (first run or old-format marker): keep 999 sentinel (transient, resolves after first successful
  run)

**`update_marker` step** -- write SHA + timestamp:

- Get HEAD sha and its commit timestamp via `git log -1 --format=%ct HEAD`
- Write `<sha> <timestamp>` to marker

### Why timestamp-based fallback works

- Commit timestamps are properties of the commit object, not of any specific clone. `git rev-list --after=<unix_ts>`
  works regardless of which SHAs are locally available.
- The count is approximate (e.g., merged branches with older author dates may be missed), but it's close enough for the
  threshold comparison and gives a meaningful number to display.
- The 999 sentinel is preserved only for true first-run (no marker) or old-format markers with no timestamp -- both are
  transient states that resolve after the first successful run.
