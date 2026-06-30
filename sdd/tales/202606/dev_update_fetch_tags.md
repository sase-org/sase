---
create_time: 2026-06-30 05:22:49
status: done
---
# Plan: Sync git tags during dev/editable updates so version numbers are correct

## Problem

On the **Updates** tab of the SASE Admin Center, pressing `u` to update dev/editable installs does fast-forward the
checkouts to their upstream, but the version numbers it reports are stale. For example, `sase-github` showed
`v0.1.2+6.g6bdb1da00` after an update when it should have shown `v0.1.4`.

That `vX.Y.Z+<distance>.g<sha>` string is a `git describe`-style version: it means "the nearest tag is `v0.1.2`, and
HEAD is 6 commits past it." The presence of a `+distance` suffix on a checkout that is supposedly current is the tell:
the new release tag (`v0.1.4`) was never pulled down, so `git describe` is anchored to an old tag.

## Root cause

The dev-update fetch helper builds a `git fetch` command with an **explicit refspec** but **no `--tags`**:

- `fetch_git_upstream()` in `src/sase/version/_git.py` (~lines 170-181) builds:
  - `git fetch --quiet <remote> <branch>` when a remote and tracking branch are known (the normal case), or
  - `git fetch --quiet <remote>` when only a remote is known.

Git only auto-follows tags when fetching **without** an explicit command-line refspec. Once you pass `<remote> <branch>`
on the command line, tag auto-following is disabled, so new remote tags are never downloaded. The fast-forward merge
advances HEAD onto the upstream commit, but the local tag database is stale, so `git describe --tags` resolves to the
old tag plus a distance — exactly the `v0.1.2+6.g6bdb1da00` symptom.

This single helper feeds **both** version-relevant paths, so the one bug shows up twice:

1. **Preview / "latest available"** — `detect_dev_latest()` in `src/sase/dev_update/detect.py` calls
   `fetch_git_upstream(status)` and then probes the upstream ref to compute the "latest" version shown before you press
   `u`.
2. **Actual update** — `execute_dev_update()` in `src/sase/dev_update/execute.py` fetches via
   `_fetch_actionable_roots()` → `fetch_git_upstream(...)`, then fast-forward merges. After the merge, the displayed
   "installed" version is probed from HEAD via `probe_git_metadata_at_ref()` (`git describe --tags ...`), which sees
   only the stale local tags.

Confirming evidence: the version probe (`probe_git_metadata_at_ref` in `src/sase/version/_git.py`) is purely a local
`git describe --tags` / `git rev-list --count` read — it never refreshes tags itself, so it is entirely dependent on the
fetch step pulling tags. And the Rust core's own release CI already fetches with `git fetch --force --tags origin`,
which is the correct, robust pattern this plan adopts.

## Fix

Add tag fetching to the shared `fetch_git_upstream()` helper so every dev-update fetch synchronizes tags. Because both
the preview and execute paths route through this one helper, a single change corrects both the "latest available"
preview and the post-update "installed" version.

### Core change

In `src/sase/version/_git.py`, `fetch_git_upstream()`:

- Include `--tags` in the fetch arguments for both branches (remote + branch, and remote-only). Resulting commands:
  - `git fetch --quiet --tags <remote> <branch>`
  - `git fetch --quiet --tags <remote>`

**Recommendation — also pass `--force` with `--tags`** (i.e. `git fetch --quiet --tags --force <remote> <branch>`):

- Release automation (release-please / release-plz) can recreate or move tags. Plain `--tags` refuses to overwrite a
  local tag that has diverged from the remote, which would silently re-introduce a stale-version symptom.
- `--force` makes the local tag set converge to the remote's, which is what we want for these read-only mirror
  checkouts.
- This matches the pattern already used by the Rust core's release CI (`git fetch --force --tags origin`).

This is the recommended approach. If we prefer the most minimal change, `--tags` alone fixes the reported case; the
trade-off is the moved-tag edge case above.

### Rust core boundary note

Per the repo's Rust-core boundary rule, shared backend/domain behavior belongs in the sibling `sase-core` crate.
Investigation confirmed there is **no** Rust-side runtime equivalent of this fetch/version-probe logic today — it lives
entirely in Python (`src/sase/version/_git.py` and `src/sase/dev_update/`). This change is a correction to an existing
Python git invocation, not new domain logic, so the fix belongs in place in Python. A broader migration of
version/dev-update logic into the Rust core is a separate, out-of-scope effort and is called out here only for
awareness.

## Tests

- **Update the pinning test**: `tests/dev_update/test_git_helpers.py`,
  `test_fetch_and_merge_git_ops_use_resolved_upstream` asserts the fetch args are exactly
  `("fetch", "--quiet", "origin", "main")`. Update it to expect the new tag flags (e.g.
  `("fetch", "--quiet", "--tags", "--force", "origin", "main")`, matching whichever flag set is chosen).
- **Add a regression test** that asserts tags are fetched in both code paths:
  - remote + tracking branch → args include `--tags` (and `--force` if adopted), and
  - remote-only (no `remote_branch`) → args include `--tags`.
- **Confirm intent at a higher level**: verify the dev-update detect/execute layers (`tests/dev_update/`) still exercise
  `fetch_git_upstream` so the tag-fetch flows through both the preview and execute paths. Add or extend a test there if
  the helper-level test does not already give confidence that both callers benefit.

## Out of scope (noted, not changed here)

- `src/sase/vcs_provider/plugins/_git_query_ops.py` issues `git fetch origin` (no explicit refspec) for PR/branch
  checkout workflows. That is a separate subsystem from the Updates tab version display, and because it omits an
  explicit refspec git already auto-follows tags there, so it is unlikely to exhibit this bug. Leave it unchanged in
  this fix; flag as a possible separate follow-up if tag staleness is ever observed in PR workflows.

## Verification

1. `just install` (required first in an ephemeral workspace), then `just check` (lint + mypy + targeted tests +
   `sase validate`).
   - Known-noise caveats unrelated to this change: pre-existing `llm_provider` `default_effort` failures and the
     full-suite SIGTERM in the sandbox. Prefer running the targeted `tests/dev_update/` and `tests/version/` subsets to
     confirm this fix.
2. Manual smoke test: in an editable checkout that is behind a freshly-published remote tag, run the Updates-tab `u`
   flow (or the underlying dev-update entry point) and confirm the displayed version resolves to the real tag (e.g.
   `v0.1.4`) with no spurious `+distance` suffix, and that `git tag --list` in the checkout now contains the new tag.

## Files touched (expected)

- `src/sase/version/_git.py` — add `--tags` (recommended: `--tags --force`) to `fetch_git_upstream()`.
- `tests/dev_update/test_git_helpers.py` — update the fetch-args assertion; add tag-fetch regression coverage for both
  branches.
- Possibly `tests/dev_update/` (detect/execute) — extend coverage if needed to confirm both callers fetch tags.
