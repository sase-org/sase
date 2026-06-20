---
create_time: 2026-06-20 14:07:18
status: done
prompt: sdd/prompts/202606/finalizer_opened_sibling_authoritative_path.md
---
# Plan: Make the commit finalizer use the recorded opened-sibling workspace path

## Summary

After a GitHub org rename (`bbugyi200` → `bobs-org`) for the `bob-cli` repo and its `bob-plugins` sibling, the commit
finalizer silently stopped committing changes the agent made in the `bob-plugins` sibling repo. The `029` agent
(`029--code`, run `20260620133122`) edited `plugins/task-status-cycler/main.js` in `bob-plugins`, but the finalizer
reported `status: clean / reason: no_changes` and left the change uncommitted. That change is still sitting uncommitted
in `…/workspaces/bobs-org/bob-plugins/bob-plugins_11` today.

Root cause (proven by reproduction below): the finalizer decides **which** sibling repos to commit and **where they
live** by _re-resolving_ `bob-cli`'s `sibling_repos` config at finalize time (`resolve_sibling_repos_for_project`), then
gates that set by the _names_ of siblings the agent opened. The agent, however, opened the sibling through a
**different** resolution path (`sase workspace open` → the `bob-plugins` **project spec**), which already recorded the
real workspace directory in `opened_siblings.json`. The org rename made these two resolution sources diverge
transiently, so the finalizer's config-derived target set dropped `bob-plugins` entirely (only an internally-discarded
warning), and the agent's work was silently abandoned. The finalizer **already captures the correct path** in
`opened_siblings.json` but ignores it.

The fix: make the recorded opened-sibling `workspace_dir` authoritative for committable sibling repos, instead of
recomputing the path from drift-prone config. This uses data we already capture, is robust to org renames / repo moves /
mid-session config edits, and completes the design direction started by commit `db79196c8` ("gate finalizer sibling
checks by opened workspaces").

## Background: how sibling commit finalization works today

- When an agent runs `sase workspace open -p <sibling> <N>`, `handle_open_clean`
  (`src/sase/main/workspace_handler_list.py:194-197`) calls `record_opened_sibling(ctx.project_name, path)`. `path` is
  the **actual** checkout dir the agent will work in, resolved through the sibling's **project spec** (`<sibling>.sase`
  `WORKSPACE_DIR`) and the managed workspace root (derived from the git remote URL). This writes `opened_siblings.json`
  under `SASE_ARTIFACTS_DIR`, recording `{name, workspace_dir}` per opened sibling.

- At finalize time, `collect_dirty_state` (`src/sase/llm_provider/commit_finalizer_state.py`):
  1. Builds `sibling_targets` by **re-resolving** config/env (`_configured_sibling_targets` →
     `_sibling_targets_from_env` when `SASE_SIBLING_REPOS_JSON` is set, else `_sibling_targets_from_config` →
     `resolve_sibling_repos_for_project`). This reads `bob-cli`'s `sase.yml` `sibling_repos[].path` and recomputes each
     sibling's numbered workspace dir.
  2. Reads `opened_sibling_names(artifact_root)` → just the **set of names**.
  3. In `_dirty_configured_sibling_repos_for_strategy`, iterates the **config/env** targets, skips any whose name is not
     in `opened_names`, and calls `git_changed_files(target.workspace_dir)` using the **config-resolved** path.

The recorded `workspace_dir` in `opened_siblings.json` is therefore captured but **never used** for resolution — only
the names are consumed (for gating). `resolve_sibling_repos_for_project` silently skips any sibling whose configured
primary path `is_dir()` check fails (it appends a warning to `SiblingRepoResolution.warnings`, which the finalizer
discards).

## Evidence / reproduction (already verified in this investigation)

Subject: agent `029--code`, project `bob-cli`, workspace `bob-cli_11`, run
`~/.sase/projects/bob-cli/artifacts/ace-run/202606/20/20260620133122`.

1. **Live finalizer result** (`commit_finalizer_result.json`):
   `{"status":"clean","reason":"no_changes","changed_files":[],"passes":0}`.

2. **The work was real and is still uncommitted**: `git -C …/workspaces/bobs-org/bob-plugins/bob-plugins_11 status`
   shows `M plugins/task-status-cycler/main.js`. The agent's own narration confirms it ran `sase workspace open` for
   `bob-plugins`, was assigned `bob-plugins_11`, and edited `main.js`.

3. **`opened_siblings.json` recorded the correct path**:
   `bob-plugins → …/workspaces/bobs-org/bob-plugins/bob-plugins_11`, and `git_changed_files()` on that recorded path
   returns `['plugins/task-status-cycler/main.js']`.

4. **Reproduced the failure**: feeding `collect_dirty_state` a `SASE_SIBLING_REPOS_JSON` that omits `bob-plugins` (the
   transient org-rename state where config re-resolution dropped it) yields `is_clean: True` with zero committable repos
   — exactly matching the live `clean / no_changes`. With the _current_ (post-rename, repaired) config it resolves
   correctly, confirming the failure was a transient divergence that the finalizer should have been robust to. No
   `sase-core` (Rust) counterpart exists for this logic; it is Python-only.

5. **Why the agent still opened the sibling fine while the finalizer missed it**: the timeline shows `bob-cli`'s
   `sase.yml` and git remote were switched to `bobs-org` (commit `291bf31`, 12:55) before the agent launched (13:31).
   `sase workspace open` resolves through the `bob-plugins` **project spec** (already `bobs-org`); the finalizer
   re-resolves through `bob-cli`'s **`sibling_repos` config path** and the managed-root recomputation — a separate path
   that diverged during the rename. The two must be reconciled.

## Goal

The commit finalizer must commit uncommitted changes in any sibling repo the agent actually opened during the run, using
the **recorded** workspace directory as the source of truth — even when config-based re-resolution of that sibling has
drifted (org rename, repo move, path edit, or removal). It must never again silently report `clean / no_changes` while
leaving an opened sibling's changes behind.

## Design

### 1. Expose the recorded opened-sibling workspace dirs (`src/sase/sibling_repos.py`)

Add a public accessor that returns the full opened-sibling records, not just names:

- `opened_sibling_workspace_dirs(artifact_root: Path | None) -> dict[str, str]` (name → recorded `workspace_dir`), built
  from the existing `_opened_sibling_records` helper. Keep `opened_sibling_names` for any callers that only need names.

### 2. Drive committable siblings from the opened record (`commit_finalizer_state.py`)

Rework `_dirty_configured_sibling_repos` (the **suffix / committable** path only) so it iterates the **opened-sibling
records** and uses each record's recorded `workspace_dir` to detect changes, rather than iterating config/env targets
and recomputing the path:

- For each opened sibling `(name, recorded_workspace_dir)`:
  - Classify its strategy from the config/env `sibling_targets` when present (`name → workspace_strategy`). If the
    sibling is classified `none` (static, e.g. `chezmoi`), leave it to the advisory path (unchanged). If it is `suffix`
    **or absent from config** (config drifted / dropped it), treat it as committable.
  - Resolve the path to check as: the **recorded** `workspace_dir` first; fall back to the config/env target's
    `workspace_dir` only when no record path is available.
  - `git_changed_files(path)`; if non-empty, emit a `DirtyRepo(kind="sibling")`.
- Dedupe so a sibling is listed once (key on normalized path / name).

Keep the **advisory** path (`_dirty_configured_advisory_sibling_repos`, `workspace_strategy: none`) exactly as it is
today — config/env-driven, not gated by opened siblings. This preserves the static-sibling advisory behavior (chezmoi,
etc.).

Net effect: an opened sibling whose config resolution drifted (or vanished) is still committed from its real, recorded
workspace path. A configured-but-not-opened sibling remains ignored (unchanged from `db79196c8`). A static `none`
sibling remains advisory (unchanged).

### 3. Defense-in-depth: never silently drop an opened sibling with changes

Belt-and-suspenders so this class of bug cannot silently recur: if an opened sibling's recorded `workspace_dir` exists
and has uncommitted changes but could not be classified/committed for any reason, surface it (route it into the
dirty/advisory details rather than dropping it). With the design above this should be unreachable for normal cases, but
it guarantees the finalizer's `clean / no_changes` can never coexist with an opened sibling that has pending changes.

## Files to change

- `src/sase/sibling_repos.py` — add `opened_sibling_workspace_dirs` accessor.
- `src/sase/llm_provider/commit_finalizer_state.py` — make committable-sibling detection opened-record-authoritative
  (the core fix); advisory path unchanged.
- (Only if needed for threading) `src/sase/llm_provider/commit_finalizer.py` re-exports — the module already re-exports
  `_dirty_configured_sibling_repos` et al.; keep the public surface stable.

## Tests

- `tests/test_sibling_repos.py`: add coverage for `opened_sibling_workspace_dirs` (name→workspace_dir mapping,
  missing/malformed file handling, no-artifacts no-op), mirroring the existing `opened_sibling_names` tests.
- `tests/llm_provider/test_commit_finalizer_siblings.py`: add the **regression test** for this bug — an opened sibling
  recorded at path `P` with uncommitted changes, while config/env resolution does **not** include the sibling (or
  resolves it to a different/nonexistent path): assert the finalizer detects `P` as a committable dirty sibling (not
  `clean`). Verify the existing guards still hold:
  - `test_dirty_configured_sibling_without_open_marker_is_ignored` (unopened siblings ignored),
  - `test_dirty_primary_sibling_checkout_is_ignored_when_workspace_is_configured` (commit the numbered workspace, not
    the primary checkout — naturally satisfied since the recorded path _is_ the numbered workspace),
  - the `none`-strategy advisory tests (advisory path unchanged).
- Run `just check` (lint + mypy + tests) before completing, per repo policy. Install first (`just install`) because of
  the ephemeral workspace.

## Out of scope / follow-ups

- **Recovering the `029` agent's lost change**: the edit to `plugins/task-status-cycler/main.js` is still present and
  uncommitted in `bob-plugins_11`; it can be committed manually (or by re-running the finalizer once this fix ships).
  Not a code change.
- **The discarded `resolve_sibling_repos_for_project` warnings**: these warnings (e.g. "primary path does not exist")
  are silently dropped by the finalizer. A broader improvement would log them, but it is not required once committable
  detection no longer depends on that resolution.
- **`github_orgs` config staleness**: the global `~/.config/sase/sase.yml` `github_orgs` list still contains `bbugyi200`
  and lacks `bobs-org`. This did not cause the bug (project keys are derived from the git remote URL, not
  `github_orgs`), so it is noted but not addressed here.

## Risk / compatibility

- Behavior change is confined to the **committable suffix-sibling** path; advisory and main-repo logic are untouched.
- The change only _broadens_ what gets committed in the drift case (opened + dirty siblings that were previously
  dropped). Non-drift runs resolve identically, since the recorded path equals the config-resolved path. No new external
  calls or services; commits remain gated by "the agent opened this sibling", so we never commit siblings the run did
  not touch.
