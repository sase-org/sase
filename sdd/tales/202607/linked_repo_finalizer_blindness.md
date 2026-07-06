---
create_time: 2026-07-06 17:29:17
status: done
prompt: sdd/prompts/202607/linked_repo_finalizer_blindness.md
---
# Fix Linked-Repo Commit Finalizer Blindness + Recover q/p's Stashed sase-telegram Work

## Problem

The sase agents `q` and `p` (both `#coder` runs, plans `~/.sase/plans/202607/telegram_stale_launch_feedback.md` and
`~/.sase/plans/202607/telegram_project_display_names.md`) implemented and fully verified changes in linked
`sase-telegram` workspaces, then ended their runs without committing. The commit finalizer **did** run for both
(contrary to first impressions), but reported `status: clean, reason: no_changes` and never committed anything.

### Root cause chain (verified)

1. The finalizer's `collect_dirty_state()` (`src/sase/llm_provider/commit_finalizer_state.py`) only treats a linked repo
   as a blocking dirty repo when the run's artifacts dir contains an `opened_linked_workspaces.json` marker recording
   that the agent opened it.
2. That marker is written by `sase workspace open` (`handle_open_clean` in `src/sase/main/workspace_handler_list.py`),
   but only when `ctx.is_sibling` is true. `is_sibling` is derived solely from the opened project's ProjectSpec having
   `PROJECT_STATE: sibling`.
3. The linked-repo ProjectSpecs on this machine (e.g. `~/.sase/projects/sase-telegram/sase-telegram.sase`,
   `~/.sase/projects/sase-core/sase-core.sase`) have **no `PROJECT_STATE:` line** — they parse as implicit `active`, so
   `is_sibling` is false and the marker is never recorded. (These specs were pre-created with `WORKSPACE_DIR`, so the
   `_materialize_sibling_project_context` path that would have stamped `sibling` never ran.)
4. Net effect: **no artifacts dir on this machine has ever contained the opened-linked marker** — linked-repo
   finalization has never fired. The finalizer only checked the primary workspace, found it clean, and reported
   `no_changes`, even though `SASE_LINKED_REPOS_JSON` in the agent env pointed at the exact dirty linked workspace.
5. The uncommitted work was then swept into stash backups by later workspace prep/open calls (`prepare_workspace`
   stashes dirt before resetting to origin/master):
   - Agent `q`'s diff (195 insertions: `src/sase_telegram/scripts/sase_tg_inbound.py`, `tests/test_inbound.py`) →
     `stash@{0}` ("gh_sase-org__sase-linked-sase-telegram") in
     `/home/bryan/.local/state/sase/workspaces/sase-org/sase-telegram/sase-telegram_13`.
   - Agent `p`'s diff (444 insertions: `src/sase_telegram/formatting.py`,
     `src/sase_telegram/scripts/sase_tg_inbound.py`, `tests/test_formatting.py`, `tests/test_inbound.py`) → `stash@{0}`
     ("sase-telegram-workspace-12-workspace-open") in
     `/home/bryan/.local/state/sase/workspaces/sase-org/sase-telegram/sase-telegram_12`.

Both diffs were verified by their authors (`just check` green in the plugin repo) before being orphaned; nothing was
lost.

## Fix

All changes are Python-side orchestration in the sase repo; no Rust core (`sase-core`) API changes are needed (the
lifecycle facade already exposes read/apply).

### 1. Make opened-linked-repo recording independent of ProjectSpec lifecycle state

In `handle_open_clean` (`src/sase/main/workspace_handler_list.py`), record the opened linked repo when `ctx.is_sibling`
**or** the opened project is one of the current run's configured linked repos. Detection: the opened `ctx.project_name`
appears in `linked_repo_metadata_from_env(os.environ)` (canonical `SASE_LINKED_REPOS_JSON`, with the deprecated sibling
alias already handled by that helper). This is exactly the population for which recording matters —
`record_opened_linked_repo` is already a no-op outside agent runs (no `SASE_ARTIFACTS_DIR`).

### 2. Defense in depth: finalizer treats dirty suffix-strategy linked workspaces as blocking even without the marker

In `collect_dirty_state()` (`src/sase/llm_provider/commit_finalizer_state.py`), also check the configured
suffix-strategy sibling targets (already resolved from env/config into `sibling_targets`) for dirt, and include dirty
ones as blocking `DirtyRepo`s even when no opened marker exists. Rationale: since launch prep now cleans suffix-strategy
linked workspaces at agent launch (`prepare_linked_repo_workspaces_if_needed`), any end-of-run dirt in them was produced
by this run and must be committed. Strategy-`none` repos keep their current advisory-only handling (they point at real
user checkouts where pre-existing dirt is expected). Preserve existing name/path dedup so a repo found via both marker
and config is reported once.

This change alone would have saved q's and p's work even with the marker bug present.

### 3. Data heal: stamp `PROJECT_STATE: sibling` on existing linked-repo ProjectSpecs

Add the missing `PROJECT_STATE: sibling` line (via the existing lifecycle facade, `apply_project_lifecycle_update`) to
the linked-repo ProjectSpecs that exist with `WORKSPACE_DIR` but no explicit state — currently `sase-telegram` and
`sase-core` — so `is_sibling` is truthful for every current and future consumer. This matches what
`_materialize_sibling_project_context` would have written had it created these specs.

### Tests

- `tests/main/test_workspace_handler_list_path.py`: opening a project that is a configured linked repo per env records
  the marker even when its ProjectSpec lacks `PROJECT_STATE: sibling`; non-linked, non-sibling projects still do not
  record.
- `tests/llm_provider/test_commit_finalizer_siblings.py` (+ `tests/llm_provider/_commit_finalizer_sibling_helpers.py` as
  needed): a dirty suffix-strategy configured target with **no** opened marker is blocking; strategy-`none` stays
  advisory; dedup when both marker and config name the same repo.
- Keep `tests/test_linked_repos.py` / `tests/llm_provider/test_commit_finalizer_linked_repos_compat.py` green.

### Verification

`just install` then `just check`. Known environment caveats: the full test phase can be SIGTERM-killed in the sandbox
(exit 144 — not a real failure; fall back to ruff/mypy plus targeted pytest of the touched test modules), and there are
8 pre-existing `llm_provider` `invoke_agent` failures caused by the dev env's `default_effort: xhigh`.

## Recovery of q's and p's work

1. Export each stash to a patch file with `git stash show -p --include-untracked stash@{0}` from the two workspaces
   listed above (read-only; the stashes stay in place as backup), save the patches to the current run's artifacts dir,
   and register them with the `/sase_artifact` skill.
2. Launch two new agents via the `/sase_run` skill (per the user's instruction), one per orphaned diff. Each prompt will
   instruct the agent to:
   - Open its own linked `sase-telegram` workspace with
     `sase workspace open -p sase-telegram -r "<reason>" <its own workspace num>`.
   - Apply its patch (`git apply --3way`), using the referenced plan file (`telegram_stale_launch_feedback.md` for q's
     diff, `telegram_project_display_names.md` for p's) to resolve any drift.
   - Re-verify in the plugin repo (`just install`, targeted pytest, `just check`), including the known gotcha that the
     plugin venv resolves a stale published `sase==0.1.0` and needs the current linked `sase` repo installed editable
     first.
   - Commit the sase-telegram changes (explicitly authorized in the prompt, via the standard sase commit flow).
3. Serialize the two launches (second agent uses `%wait:` on the first) because both diffs touch
   `src/sase_telegram/scripts/sase_tg_inbound.py` and `tests/test_inbound.py`; the second agent rebases/3-way-applies
   onto the first's commit and resolves any conflicts guided by its plan file.

## Out of scope

- Migrating/healing linked-repo ProjectSpecs on other machines (the env-based detection in Fix 1 makes the system
  self-sufficient without the heal).
- Changing how strategy-`none` (shared-checkout) linked repos are finalized.
- Rust core changes.
