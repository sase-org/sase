---
create_time: 2026-06-24 07:49:06
status: done
---
# Plan: Fix linked-repo commits not showing in the Agents-tab COMMITS panel

## Symptom

On the **Agents** tab of `sase ace`, selecting an agent that committed in a **linked repo** (e.g. `sase-core`) does not
show that commit in the metadata-panel **COMMITS** section. Concrete report: the `04y` sase agent made commit
`a943d6f8f3...` in `sase-core`, but the panel shows no `sase-core` group (and the commit is, at best, mis-attributed to
the primary repo).

The COMMITS panel was shipped recently with two sourcing paths: the **primary** repo's commit comes from persisted
metadata, while **linked** repos are **live-fetched off-thread** via a new `git log <base>..HEAD` VCS provider call. The
live-fetch path is the broken part.

## Root-cause diagnosis

There are three distinct problems; together they explain why linked commits never appear.

### Defect A — the live-fetch model is structurally wrong for linked repos

The linked-commit worker (`src/sase/ace/tui/widgets/file_panel/_linked_commits.py`) computes, per linked repo:

```
base = provider.get_default_parent_revision(workspace_dir)   # -> origin/<default-branch>, e.g. origin/master
commits = provider.list_commits(base, "HEAD", workspace_dir)  # git log origin/master..HEAD
```

This cannot work in practice:

1. **Commits are pushed to `origin/<default>`.** When an agent commits in a linked repo whose working branch is the
   default branch, the SASE commit workflow pushes directly to `origin/<branch>`
   (`src/sase/vcs_provider/plugins/_git_commit_dispatch.py` — `create_commit` → `_push_with_retry` → pushes the current
   branch). After the push, `origin/master..HEAD` is **empty**, so the live-fetch returns nothing.
2. **Linked-repo workspaces are shared/reused.** Linked workspaces (e.g. `sase-core_<N>`) are resolved per workspace
   number and reused across agent runs (`resolve_linked_repos_for_project` in `src/sase/linked_repos.py`). By the time
   you select an old agent, the shared workspace's `HEAD`/`origin` reflect whatever the _latest_ run left behind, not
   the selected agent's work. `git log <base>..HEAD` therefore describes the wrong state (or nothing).

So the whole "live-fetch the linked repo's branch range" approach is unsound for this domain. Reviewing finished work is
exactly when the workspace no longer reflects that agent.

### Defect B — `refresh_linked_repos_for_workspace` destroys good metadata on a transient empty re-resolution

`refresh_linked_repos_for_workspace` (`src/sase/axe/run_agent_runner_setup.py:218`) re-resolves linked repos after a
deferred workspace claim and writes them into `agent_meta.json`. On an **empty** re-resolution it unconditionally
deletes the existing metadata:

```python
if resolution.repos:
    agent_meta["linked_repos"] = resolution.to_jsonable()
    agent_meta["sibling_repos"] = resolution.to_jsonable()
else:
    agent_meta.pop("linked_repos", None)     # <-- destructive on a transient empty
    agent_meta.pop("sibling_repos", None)
```

`resolve_linked_repos_for_project` can legitimately return an **empty** resolution transiently — e.g. a linked
checkout's primary path isn't a dir yet, `_resolve_workspace_dir` raises during materialization, or config is briefly
unreadable (`src/sase/linked_repos.py:344-397` skip every entry on such conditions). When that happens, an agent that
_does_ have linked repos loses `linked_repos`/`sibling_repos` from `agent_meta.json`. The TUI then loads
`agent.linked_repos == ()`, so the panel has no linked repos to attribute commits to. This **also** silently breaks
linked **DELTAS** for the same agents (both read `agent.linked_repos`).

### Defect C — the persisted commit is never attributed to the repo it was actually made in

`commit_result.json` (written by `write_result_marker`, `src/sase/workflows/commit/commit_tracking.py:236`) records
`"cwd": os.getcwd()` — the directory where that commit happened. Each `sase commit` invocation **overwrites** this
single marker; an agent that commits in a linked repo (the finalizer instructs `cd <linked path>` then
`/sase_git_commit`, `src/sase/llm_provider/commit_finalizer_prompting.py:75-84`) leaves `commit_result.json` describing
the **linked** commit, with `cwd` pointing at the linked workspace.

But `read_commit_result_metadata` (`src/sase/axe/run_agent_helpers_state.py:28`) **drops `cwd`** and surfaces only
`message`/`result` as `meta_commit_message`/`meta_new_commit`. The render path
(`_agent_commits.py::_primary_commit_infos`) then renders that commit **unconditionally under the primary repo**. So a
linked commit is either mislabeled as primary or (combined with Defects A/B) simply absent from any `sase-core` group.

## Chosen fix (decided with the user)

- **Q1 — Persisted attribution.** Stop live-fetching. Surface `cwd` from `commit_result.json` and attribute the
  already-persisted commit to its real repo (primary vs a specific linked repo). Reliable, zero live-git, works even for
  `--code` agents with null `linked_repos`. Shows the finalizer commit per repo (the single persisted marker), not every
  branch commit. The live-fetch infra becomes redundant and is removed.
- **Q2 — Stop the destructive pop.** Only overwrite `linked_repos`/`sibling_repos` when the re-resolution is non-empty;
  never delete good metadata on a transient empty. This also repairs linked-DELTAS for the affected agents.

### Accepted limitation (documented)

`commit_result.json` is a **single** marker, overwritten by each `sase commit`. Persisted attribution therefore surfaces
the **one** most-recently-persisted commit, correctly attributed to its repo — not every commit across every repo. An
agent that committed in both primary and a linked repo shows only the last finalizer commit (correctly placed). This is
strictly more correct than today (which mislabels it) and matches the chosen Q1 option; full per-repo coverage
(persisting one marker per repo at commit time) is an explicit non-goal here.

## Design

### A. Persist the commit `cwd` (one-line finalize change, rides existing plumbing)

Extend `read_commit_result_metadata` (`src/sase/axe/run_agent_helpers_state.py`) to also surface `commit_result.json`'s
`cwd` as a new step-output field — `meta_commit_cwd`. Because this function already feeds
`extract_step_output_and_diff_path`, which merges commit metadata into `step_output` at finalize, the `cwd` is baked
into the `done.json` marker for **new** agents and flows through _every_ existing load path (legacy filesystem loader
and the snapshot/wire loader) with **no new disk reads and no Rust/wire change** — `done.step_output` already carries
the commit message today, so `cwd` simply travels alongside it.

### B. Attribute the persisted commit at render time (zero-I/O)

Rewrite `append_agent_commits_section` (`src/sase/ace/tui/widgets/prompt_panel/_agent_commits.py`) to route the single
persisted commit (`meta_commit_message` + `meta_new_commit`) into the correct repo group using `meta_commit_cwd`,
matched against in-memory agent state only:

1. Normalize `meta_commit_cwd`.
2. If it equals / is contained in `agent.workspace_dir` → **primary** group (name from `meta_project` / project-file
   stem, as today).
3. Else if it equals / is contained in some `agent.linked_repos[*].workspace_dir` → that **linked** group, rendered with
   the shared `WORKSPACE_GLYPH` / accent styling (unchanged visual language).
4. Else if `cwd` is present but unmatched (e.g. metadata still missing) → derive a repo name from the `cwd` basename,
   stripping a trailing `_<workspace_num>` suffix (defense-in-depth for popped/`--code` cases).
5. If `cwd` is absent (a pre-existing marker not covered by the backfill in C) → fall back to the **primary** group,
   i.e. today's behavior, so nothing regresses.

This is pure in-memory work (reads `step_output` + `agent.workspace_dir`/`agent.linked_repos`), satisfying the TUI-perf
rule that the render/event-loop path does no disk or subprocess I/O. COMMITS continues to render on both the cheap (j/k)
and full header paths.

### C. Backfill `cwd` for already-finalized agents (off the event loop)

The reported `04y` agent already finished, so its `done.json` `step_output` predates change A and lacks
`meta_commit_cwd`. Add a small enrichment that, **when an agent has a persisted commit but no `meta_commit_cwd`**, reads
the agent's `commit_result.json` from its artifacts dir once to recover `cwd` and injects it into `step_output`. This
runs in the off-event-loop agent loaders (the loader thread pool), called from both done-load paths
(`_load_done_agent_for_dir` and `_build_done_agent_from_record` in `src/sase/ace/tui/models/_loaders/_done_loaders.py`,
both of which already have the artifacts dir). It is gated to fire only for committed agents missing the field, so once
agents are finalized under change A it is a no-op, and it self-heals existing agents like `04y` without a re-run.

### D. Stop the destructive linked-repo metadata pop (Defect B)

In `refresh_linked_repos_for_workspace` (`src/sase/axe/run_agent_runner_setup.py`), only assign
`linked_repos`/`sibling_repos` when `resolution.repos` is non-empty; on an empty resolution, **leave existing values
untouched** (no `pop`). Keep always refreshing `workspace_dir` and applying env. This prevents transient empties from
erasing good metadata and benefits linked-DELTAS too.

### E. Remove the redundant live-fetch infrastructure

With attribution sourced from the persisted marker, the git-log machinery is dead and structurally wrong; remove it:

- Delete `src/sase/ace/tui/widgets/file_panel/_linked_commits.py` (worker, caches, eligibility, `CommitInfo`,
  `LinkedCommitGroup`). Move the tiny `CommitInfo` display type into `_agent_commits.py` (the only remaining consumer).
- Remove the worker wiring in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_async.py`
  (`start_agent_linked_commit_refresh`, `_apply_agent_linked_commit_worker_result`,
  `_start_agent_linked_commit_refresh_from_context`, request/worker attrs, SUCCESS dispatch) and its trigger in
  `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py:38`.
- Remove the `LinkedCommitGroup` re-export from `src/sase/ace/tui/widgets/file_panel/__init__.py`.
- Remove the `list_commits` VCS provider method end-to-end (it has no other caller): `vcs_list_commits` hookspec
  (`src/sase/vcs_provider/_hookspec.py`), base wrapper (`_base.py`), plugin-manager dispatch (`_plugin_manager.py`), and
  git implementation (`plugins/_git_query_ops.py`).
- Re-privatize the eligibility helpers in `src/sase/ace/tui/widgets/file_panel/_linked_deltas.py`
  (`existing_workspace_dir`, `suffix_workspace_linked_repos`) that were made public only for `_linked_commits.py`, since
  the cross-module consumer is gone (linked-DELTAS keeps using them internally).

## What explicitly does NOT change

- Primary-repo commit sourcing stays persisted (`meta_commit_message`/`meta_new_commit`); the COMMITS section UI/styling
  (header, `▣ <repo>` subheaders, `<sha> <subject>` rows, omitted-when-empty) is unchanged.
- `extract_meta_fields` keeps excluding the commit keys from WORKFLOW VARIABLES; `meta_commit_cwd` is added to that
  exclusion set so it never renders as a workflow variable.
- No new keybinding/mode/config value; no CLI subcommand/option.
- No `sase-core`/Rust change and no `sase-github` change (the removed `list_commits` was inherited via shared mixins;
  the GitHub plugin simply loses an unused method).
- DELTAS/ARTIFACTS sections, the file panel, and the linked-deltas caches are otherwise untouched (Defect B fix only
  _helps_ deltas).

## Verification

1. **Unit — attribution render** (`tests/ace/tui/widgets/test_agent_display_step_metadata.py`, rewritten off the deleted
   cache): primary `cwd` → primary group; linked `cwd` matching `agent.linked_repos` → that linked group with glyph
   styling; unmatched `cwd` → basename-derived group; missing `cwd` → primary fallback; section omitted when no commit.
2. **Unit — finalize/backfill**: `read_commit_result_metadata` surfaces `meta_commit_cwd`; the loader backfill injects
   `meta_commit_cwd` from `commit_result.json` when absent and is a no-op when present.
3. **Unit — Defect B**: `refresh_linked_repos_for_workspace` preserves existing `linked_repos`/`sibling_repos` on an
   empty resolution and still overwrites on a non-empty one.
4. **Removal hygiene**: delete the now-obsolete tests (`tests/ace/tui/widgets/test_linked_commits.py`, the
   `list_commits` cases in `tests/test_vcs_provider_git_query.py`, `tests/test_vcs_provider_plugin_manager.py`,
   `tests/test_vcs_provider_contract.py`); update the visual test
   (`tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py`) to seed the linked commit via `step_output` +
   `agent.linked_repos` instead of the removed cache, and regenerate the affected PNG golden.
5. **Gate**: `just install` then `just check` (lint + mypy + tests incl. the visual suite).
6. **Manual end-to-end**: select the `04y` agent (or any agent that committed in a linked repo); confirm the `sase-core`
   commit now appears under a `sase-core` group; confirm a primary-only agent still shows its primary commit; confirm an
   agent whose linked metadata was transiently popped now retains it after a fresh run (and its linked deltas reappear).

## Files to change (sase repo only)

- `src/sase/axe/run_agent_helpers_state.py` — surface `cwd` as `meta_commit_cwd` in `read_commit_result_metadata`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_commits.py` — cwd-based attribution; host `CommitInfo`.
- `src/sase/ace/tui/widgets/prompt_panel/_helpers.py` — add `meta_commit_cwd` to `COMMIT_META_KEYS`.
- `src/sase/ace/tui/models/_loaders/_done_loaders.py` (+ a small shared enrichment helper) — off-loop `cwd` backfill for
  pre-existing committed agents.
- `src/sase/axe/run_agent_runner_setup.py` — non-destructive `refresh_linked_repos_for_workspace` (Defect B).
- Remove live-fetch: `src/sase/ace/tui/widgets/file_panel/_linked_commits.py` (delete),
  `.../prompt_panel/_agent_display_async.py`, `.../prompt_panel/_agent_display.py`, `.../file_panel/__init__.py`,
  `.../file_panel/_linked_deltas.py` (re-privatize shared helpers), `src/sase/vcs_provider/_hookspec.py`, `_base.py`,
  `_plugin_manager.py`, `plugins/_git_query_ops.py`.
- Tests + visual golden as in Verification.

## Out of scope

- Persisting one commit marker per repo at commit time (full multi-repo coverage) — the not-chosen Q1 follow-up.
- Switching the primary repo to live-fetch.
- Refining the commit `base` revision (merge-base / ChangeSpec parent).
- Any commit _action_ (reword/amend/revert) — this is view-only.
- The workflow-detail snapshot display (`aggregate_meta_fields`).
