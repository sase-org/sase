---
create_time: 2026-06-23 17:23:26
status: done
prompt: sdd/prompts/202606/agent_commit_messages_panel.md
---
# Plan: Show all of an agent's commit messages (primary + linked repos) in the Agents-tab metadata panel

## Product context

On the **Agents** tab of `sase ace`, selecting an agent shows a metadata panel (the prompt-panel header built by
`build_header_text` in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`). Today that panel surfaces the
agent's **primary-repo** commit message as a generic "Commit Message" / "New Commit" line inside the **WORKFLOW
VARIABLES** section — sourced from the persisted `meta_commit_message` / `meta_new_commit` fields (`commit_result.json`,
read by `read_commit_result_metadata`).

Two gaps:

1. **Linked-repo commits are invisible.** We recently shipped linked-repo _deltas_ (changed-file lists per linked repo
   under "DELTAS:") and linked-repo _diff pages_ in the file panel. But the commit messages an agent makes in a linked
   repo (e.g. `sase-core`, `sase-github`) are never shown anywhere.
2. **The primary commit is buried** among arbitrary workflow variables and labeled generically.

**This feature:** introduce one purpose-built **COMMITS** section in the metadata panel that lists _every_ commit
message the agent produced, grouped per repository — the primary repo first, then each linked repo — using the same
glyph/accent styling already used for linked repos in the DELTAS section. The primary commit message moves out of
WORKFLOW VARIABLES into this section.

This was scoped with the user via three decisions:

- **Sourcing (Q1):** linked-repo commits are **live-fetched off-thread**, mirroring the just-shipped linked-deltas
  pattern (no backend/runner changes; works retroactively while workspaces exist; degrades gracefully).
- **Presentation (Q2):** one **unified COMMITS section** grouping all repos; the primary message moves here and the
  generic "Commit Message" line is dropped from WORKFLOW VARIABLES.
- **Scope (Q3):** show **all commits on the agent's branch** (`git log <base>..HEAD`) per repo, not just HEAD.

### Design goals (intuitive, reliable, beautiful)

- **Intuitive:** all of an agent's commit messages live in exactly one place, grouped by repo, primary first. Same
  per-repo `▣ <repo>` visual language the user already learned from DELTAS, so linked repos read as "more of the same."
- **Reliable:** the primary group keeps its **persisted** source (works for completed/recycled/merged agents — the most
  important case for reviewing finished work). Linked groups live-fetch with the same in-memory, zero-I/O-on-render
  caching the linked-deltas feature uses; nothing blocks the Textual event loop; the section disappears cleanly when an
  agent has no commits.
- **Beautiful:** a compact `<short-sha> <subject>` row per commit, repo subheaders with the shared workspace glyph and
  accent colors, omitted entirely when empty — matching the existing DELTAS aesthetic.

## Key design decision: asymmetric sourcing, unified presentation

The primary repo and linked repos are sourced differently but rendered identically. This is deliberate:

- **Primary repo → persisted source (unchanged).** `meta_commit_message` / `meta_new_commit` already capture the agent's
  own SASE commits and survive workspace recycling and branch merges. Switching the primary to live
  `git log origin/main..HEAD` would _regress_ completed agents (once a branch merges, `base..HEAD` is empty) and is less
  precise in stacked-ChangeSpec workflows (it would surface ancestor commits). So the primary group reuses the existing
  persisted data; we only **relocate** where it renders.
- **Linked repos → live-fetch (new).** Linked repos have no persisted commit record today (the SASE commit workflow is
  not linked-repo aware), so the only option without backend changes is to live-fetch `git log <base>..HEAD` off-thread.
  This is exactly the linked-deltas pattern.

The user sees one coherent COMMITS section; the sourcing split is invisible.

### Background: how the relevant pieces work today (anchors, no behavior changes unless stated)

1. **Metadata panel assembly.** `build_header_text(agent, *, cheap, hint_state, summary)`
   (`prompt_panel/_agent_display_parts.py`) appends sections in order. Relevant tail: `OUTPUT VARIABLES` (line ~548,
   rendered on **both** the cheap j/k fast-path and the full path) → a `not cheap and summary is not None` block
   (`DELTAS`, `ARTIFACTS`) → `WORKFLOW VARIABLES` (lines ~566-576, rendered on **both** paths from
   `meta_fields = extract_meta_fields(step_output)`).

2. **Commit message source today.** `extract_meta_fields(step_output)` (`prompt_panel/_helpers.py`) returns every
   `meta_*` field (minus `SPECIAL_META_KEYS`) as `(display_name, value)`; `format_meta_key("meta_commit_message")` →
   `"Commit Message"`. The values originate from `read_commit_result_metadata`
   (`src/sase/axe/run_agent_helpers_state.py`) reading `commit_result.json` (`message` → `meta_commit_message`, `result`
   → `meta_new_commit`). A separate consumer, `_workflow_data.py::load_workflow_detail_snapshot` (line ~48), uses
   `aggregate_meta_fields(steps)` for the **workflow detail** display (a different widget) — **out of scope** here.

3. **Linked-deltas live-fetch pattern (the template).** `file_panel/_linked_deltas.py`:
   - `_eligible_linked_repos(agent)` — dedup + `workspace_strategy == "suffix"` + non-empty `workspace_dir` + status
     gate (`status not in {Done, Failed}`).
   - module-level caches under one `Lock`: a per-repo keyed cache, a public `agent.identity → tuple[group]` cache, and a
     monotonic-time map; 1-second TTL bucket keeps the cache from going permanently warm while an agent edits.
   - `compute_linked_delta_groups(agent)` runs **off-thread** (may shell out via the VCS provider); writes the public
     cache. `get_cached_linked_delta_groups(agent)` is a **zero-I/O** lock-guarded read safe on the event loop.
     `should_refresh_linked_delta_groups(agent)` is an in-memory TTL check.
   - The worker is launched from `prompt_panel/_agent_display_async.py` (`start_agent_linked_delta_refresh` →
     `run_worker(thread=True)`), with staleness checks, and `_apply_agent_linked_delta_worker_result` re-renders the
     header on success via `_update_display_impl(agent)`.

4. **VCS provider.** `resolve_vcs_provider_for_live_diff(workspace_dir)` (`file_panel/_diff.py`) returns a cached
   provider. The provider already exposes `get_default_parent_revision(cwd)` (→ `origin/<default-branch>`),
   `get_description`, `diff_with_untracked`, `has_local_changes` — all wired hookspec → `_base.py` →
   `_plugin_manager.py` → git plugin `_git_query_ops.py` (subprocess via `self._run([...])`). There is **no** method
   that lists commits between two revisions. VCS logic is pure Python (no `sase_core_rs` usage in
   `src/sase/vcs_provider/`); the git plugin mixins are shared with the `sase-github` plugin via `GitCommon`.

5. **Boundary check** (`memory/rust_core_backend_boundary.md`): the VCS provider _is_ the shared Python backend adapter
   for VCS behavior; commit-log retrieval belongs there (a web/CLI frontend would call the same provider), exactly where
   `get_description`/`diff_with_untracked` live. No `sase-core` / Rust change — consistent with the linked-deltas/diff
   work.

## Design

### A. New VCS provider method: list commits on a branch

Add a `list_commits(base_ref, head_ref, cwd)` operation following the existing `get_description` wiring end-to-end:

- **Hookspec** `vcs_list_commits` in `src/sase/vcs_provider/_hookspec.py` (`firstresult=True`,
  `-> tuple[bool, str | None]`).
- **Base wrapper** `list_commits(...)` in `src/sase/vcs_provider/_base.py` raising `NotImplementedError` (default).
- **Plugin-manager dispatch** in `src/sase/vcs_provider/_plugin_manager.py` via
  `_call_or_raise("vcs_list_commits", ...)`.
- **Git implementation** in `src/sase/vcs_provider/plugins/_git_query_ops.py` (`GitQueryOpsMixin`):
  `git log --format=%h%x1f%s <base>..<head>` via `self._run([...])`. Return `(True, stdout or None)`; `(False, err)` on
  failure. `%x1f` (unit separator) safely separates short-sha from subject; `%s` is single-line so output splits on `\n`
  cleanly. Subject-only keeps it compact and avoids multiline-body parsing.
- **`sase-github` parity:** the GitHub plugin inherits `GitQueryOpsMixin` through `GitCommon`, so it gets this method
  for free — **no change needed in the linked repo**, consistent with "uniform agent runtimes / providers."

Returning raw text (not parsed structs) matches the existing provider contract; parsing into `CommitInfo` happens in the
TUI layer (B), exactly as the diff is parsed by `parse_unified_diff_deltas`.

### B. Live-fetch linked-repo commits off-thread (mirror linked-deltas)

New module `src/sase/ace/tui/widgets/file_panel/_linked_commits.py`, co-located with `_linked_deltas.py` to reuse its
low-level helpers (`_existing_workspace_dir`, the VCS-provider resolver, the git-index signature):

- **Data types** (frozen dataclasses):
  - `CommitInfo(short_sha: str, subject: str)`
  - `LinkedCommitGroup(repo_name: str, workspace_dir: str, commits: tuple[CommitInfo, ...], fetched_at: datetime | None = None)`
- **Eligibility — status-agnostic (deliberate divergence from linked-deltas).** Eligible iff
  `workspace_strategy == "suffix"` and `workspace_dir` is non-empty and exists on disk — **regardless of agent status**.
  Rationale: committed work is precisely what you review _after_ an agent finishes, whereas uncommitted deltas are not;
  a Done-but-unmerged agent should still show its linked commits. (Recycled/merged cases degrade to "no group" — the
  accepted Q1 caveat.) To keep this DRY, factor the dedup+suffix+workspace filtering shared with
  `_linked_deltas._eligible_linked_repos` into a small status-agnostic helper, and have the deltas path layer its status
  gate on top.
- **Caching:** mirror linked-deltas exactly — a per-repo keyed cache
  (`(identity, repo, workspace, provider, git-index signature, 1s TTL bucket)`), a public
  `agent.identity → tuple[LinkedCommitGroup, ...]` cache, a monotonic map, one `Lock`. Reuse the existing git-index
  signature for the key; the 1s TTL bucket is the real staleness bound, so new commits surface within ≤1s.
- **Computation** `_compute_repo_commit_group(agent, repo_name, workspace_dir)`: resolve provider,
  `base = provider.get_default_parent_revision(workspace_dir)`, `provider.list_commits(base, "HEAD", workspace_dir)`,
  parse into `CommitInfo` tuple; return a group only when commits are non-empty (negative-cache the empty case).
  `compute_linked_commit_groups(agent)` (off-thread) iterates eligible repos and writes the public cache.
- **Public API:** `get_cached_linked_commit_groups(agent) -> tuple[LinkedCommitGroup, ...]` (zero-I/O, event-loop safe)
  and `should_refresh_linked_commit_groups(agent)` (in-memory TTL check).

> Known limitation (documented, accepted): `<base>..HEAD` with `base = origin/<default>` lists every commit on the
> branch not yet in mainline; in a stacked-branch linked repo this could include ancestor commits. This matches the
> `base..HEAD` scope the user chose (Q3) and the linked-deltas precedent; refining `base` to a merge-base/ChangeSpec
> parent is out of scope.

### C. Worker wiring (prompt panel)

In `prompt_panel/_agent_display_async.py`, add a sibling worker to the linked-delta one:
`start_agent_linked_commit_refresh(...)` → `run_worker(compute_linked_commit_groups(agent), thread=True)` with the same
de-dup/staleness machinery; `_apply_agent_linked_commit_worker_result` re-renders the header on SUCCESS via
`_update_display_impl(request.agent)` (which repaints the COMMITS section straight from the now-warm zero-I/O cache).
Trigger it from the same context entry-point that starts the delta refresh, gated by
`should_refresh_linked_commit_groups(agent)`.

No new cross-widget message is needed: unlike linked deltas (which must notify the file panel), commits live only in the
header, so the existing `_update_display_impl` re-render suffices.

### D. Render the unified COMMITS section

Add `append_agent_commits_section(text, agent)` (new builder, e.g. `prompt_panel/_agent_commits.py`, parallel to
`_agent_deltas.py`) and call it from `build_header_text` **immediately before the DELTAS block** so committed work sits
directly above uncommitted changes. Crucially, render it on **both** the cheap and full paths (so the primary commit
never flickers on j/k): the primary source is `step_output` (no I/O) and the linked source is
`get_cached_linked_commit_groups(agent)` (zero-I/O) — both cheap-safe, unlike DELTAS whose primary diff parse is
expensive.

- **Primary group:** source the persisted commit(s) from the same data feeding today's header — the commit-related
  entries of `extract_meta_fields(step_output)` (message + sha, paired; preserves any existing multi-step `#N`
  behavior). Render only when present. Derive the primary repo display name from the agent's project basename (fallback:
  `primary`).
- **Linked groups:** `get_cached_linked_commit_groups(agent)`, in cache order (follows `agent.linked_repos`).
- **Layout** (reusing `WORKSPACE_GLYPH` / `COLOR_WORKSPACE_GLYPH` / `COLOR_WORKSPACE_NAME`, matching DELTAS):
  ```
  COMMITS:
    ▣ sase
      a1b2c3d  feat(tui): show linked repo diffs in file panel
    ▣ sase-core
      9f8e7d6  feat: add list_commits VCS hookspec
      4c3b2a1  test: cover commit log parsing
  ```
  Header `COMMITS:` in the shared header color; per-repo subheader `  ▣ <repo>` (2-space indent); per-commit row
  `    <short-sha> <subject>` (4-space indent), sha in a muted accent and subject in a readable foreground. The whole
  section is **omitted** when there are no primary commits and no linked groups (DELTAS-style).

### E. Drop the commit line from WORKFLOW VARIABLES (no duplication)

Add `COMMIT_META_KEYS = {"meta_commit_message", "meta_new_commit"}` in `_helpers.py` and exclude it from
`extract_meta_fields` (the agent-header path), the same way `SPECIAL_META_KEYS` is excluded — so WORKFLOW VARIABLES no
longer shows "Commit Message"/"New Commit" while every other `meta_*` field stays. `aggregate_meta_fields` (the separate
workflow-detail display) is intentionally left unchanged (out of scope); for leaf/single agents the header path is the
only one that surfaces these keys, so there is no regression.

## What explicitly does NOT change

- No new keybinding, mode, or config value; no CLI subcommand/option (the new `list_commits` is an internal provider
  method, not a CLI command — `memory/cli_rules.md` unaffected).
- Primary-repo commit _sourcing_ is unchanged (persisted `meta_commit_message`/`meta_new_commit`); only its render
  location moves.
- No change to the DELTAS/ARTIFACTS sections, the file panel, the linked-diff pages, or the linked-deltas caches.
- No `sase-core` / Rust change; no `sase-github` change (inherits the new git method via shared mixins).
- The workflow-detail snapshot path (`_workflow_data.py` / `aggregate_meta_fields`) is out of scope.

## Reliability / performance notes (per `memory/tui_perf.md`)

- Render path adds only in-memory work: persisted `step_output` reads + one zero-I/O cache read
  (`get_cached_linked_commit_groups`). **No subprocess/disk I/O on the event loop.**
- The git `log` shell-out happens only in the off-thread worker, only for the selected agent, coalesced and bounded by
  the 1s TTL — same envelope as linked deltas. Status-agnostic eligibility means selecting a Done agent now triggers one
  off-thread commit fetch (it did not for deltas); this is one-shot and cached, and skipped entirely when the workspace
  is gone.
- Rendering COMMITS on the cheap path is intentional (parity with the current always-rendered commit line) and safe
  because both sources are I/O-free.

## Verification

1. **VCS provider tests:** add `vcs_list_commits` git-impl coverage in `tests/test_vcs_provider_git_query.py` (mock
   `subprocess.run`: success → parsed `(sha, subject)` lines; empty range → `(True, None)`; failure → `(False, err)`), a
   plugin-manager dispatch test (`tests/test_vcs_provider_plugin_manager.py`), and a cross-provider contract case
   (`tests/test_vcs_provider_contract.py`), mirroring `get_description`.
2. **Linked-commits unit tests** (new `tests/.../test_linked_commits.py`): `_compute_repo_commit_group` populates
   `commits`/`fetched_at` from a mock provider; status-agnostic eligibility (Done agent still eligible);
   `get_cached_linked_commit_groups` is zero-I/O; empty range → no group.
3. **Metadata-panel render tests:** COMMITS renders primary + seeded linked groups with the `▣ <repo>` /
   `<sha> <subject>` layout; section omitted when no commits; the commit line no longer appears in WORKFLOW VARIABLES
   while other `meta_*` fields remain. **Update** the existing assertions in
   `tests/ace/tui/widgets/test_agent_display_step_metadata.py` (which currently expect `Commit Message:` / `New Commit:`
   under WORKFLOW VARIABLES) to assert the COMMITS section instead.
4. **Visual snapshot:** add a new PNG golden showing the metadata panel COMMITS section (primary + linked groups) under
   `tests/ace/tui/visual/snapshots/png/`, seeding the linked-commit cache directly with a future-pinned `fetched_at`/
   monotonic stamp so it is deterministic (per the linked-diff visual-test approach). Regenerate/eyeball any existing
   metadata-panel goldens affected by moving the commit line.
5. **Gate:** `just install` then `just check` (lint + mypy + tests incl. the visual suite).
6. **Manual end-to-end:** launch an agent on a project with a configured linked repo, make commits in both the primary
   and the linked repo, open `sase ace`, select the agent; confirm the COMMITS section lists both repos with all
   commits, that WORKFLOW VARIABLES no longer shows a Commit Message line, that a repo with no agent commits shows no
   group, and that a completed agent still shows its persisted primary commit.

## Files to change (sase repo only)

- `src/sase/vcs_provider/_hookspec.py` — add `vcs_list_commits` hookspec.
- `src/sase/vcs_provider/_base.py` — add `list_commits` default wrapper.
- `src/sase/vcs_provider/_plugin_manager.py` — add `list_commits` dispatch.
- `src/sase/vcs_provider/plugins/_git_query_ops.py` — implement `vcs_list_commits`
  (`git log --format=%h%x1f%s base..head`).
- `src/sase/ace/tui/widgets/file_panel/_linked_commits.py` — **new**: `CommitInfo`, `LinkedCommitGroup`, status-agnostic
  eligibility, caches, `compute_linked_commit_groups`, `get_cached_linked_commit_groups`,
  `should_refresh_linked_commit_groups`.
- `src/sase/ace/tui/widgets/file_panel/_linked_deltas.py` — factor the shared (status-agnostic) suffix/workspace
  eligibility helper reused by both modules.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_commits.py` — **new**: `append_agent_commits_section`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` — call `append_agent_commits_section` before DELTAS
  (both paths).
- `src/sase/ace/tui/widgets/prompt_panel/_helpers.py` — add `COMMIT_META_KEYS`; exclude from `extract_meta_fields`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_async.py` — `start_agent_linked_commit_refresh` +
  `_apply_agent_linked_commit_worker_result` + trigger.
- Tests + one new visual golden as above.

## Out of scope

- Persisting linked-repo commit messages at commit time (Q1 "persist" / "hybrid" alternatives were not chosen).
- Switching the primary repo to live-fetch.
- The workflow-detail snapshot display (`aggregate_meta_fields`).
- Refining the `base` revision beyond `origin/<default>` (merge-base / ChangeSpec parent).
- Any commit _action_ (reword/amend/etc.) — this is view-only.

```

```
