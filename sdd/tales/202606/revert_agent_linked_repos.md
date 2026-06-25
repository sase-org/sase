---
create_time: 2026-06-25 07:54:17
status: done
---
# Plan: Revert ALL of an agent's commits, including linked-repo commits (`,r` keymap)

## Problem / Product Context

The Agents-tab leader keymap `,r` ("Revert agent commits") is supposed to revert **every commit an agent created**.
Today it only reverts commits in the agent's **primary** repository. When an agent also commits to a **linked
repository** (e.g. `sase-core`, `sase-github`, `sase-telegram`, `sase-nvim`), those linked-repo commits are silently
left in place. The reverted badge (`↺`) then appears even though real changes the agent made survive — a correctness bug
that can leave a half-reverted multi-repo change on disk and, after push, on the remotes.

This affects both `,r` flows:

- **Single selected agent** revert.
- **Bulk marked-agents** revert.

### Why this happens (root cause)

The revert backend operates on exactly **one** workspace directory:

- The action layer resolves a single primary `workspace_dir` (`resolve_revert_workspace_dir`).
- Discovery (`discover_agent_commits`) scans `git log` for `AGENT=<name>` provenance tags **only in that one
  workspace**.
- Execution (`_apply_revert_transaction`) runs `git revert` **only in that one workspace** and pushes that one repo's
  `origin`.

Linked repos live in **separate** workspace directories (suffix-strategy workspaces keyed off the agent's workspace
number). The revert path never enumerates them, never scans their history, and never reverts there.

### Key enabling fact

Linked-repo commits **carry the same `AGENT=<name>` trailing tag** as primary-repo commits. When an agent commits to a
linked repo it `cd`s into that workspace and re-runs the same commit workflow with the same `SASE_AGENT_NAME`
environment, so the same provenance tag is written. **This means the exact same tag-based discovery logic already works
per-repo — we just need to point it at each repo.**

### Hard constraint (why this is not a trivial change)

`git revert` is inherently **per-repository**. A single revert transaction cannot be atomic across multiple git
repositories. The existing **bulk** path even rejects marked agents that "span multiple workspaces" for exactly this
reason. So extending revert to linked repos requires moving from a **single atomic transaction** model to an
**atomic-per-repo, aggregated-result** model, with explicit partial-failure semantics and reporting. This is the central
design decision of this plan.

## Goal

When `,r` is invoked on a done/failed agent (single or bulk), discover and revert that agent's `AGENT=<name>`-tagged
commits across **the primary repo and every eligible linked repo**, reporting a clear per-repo outcome.

## Current Behavior (reference)

Relevant modules (all Python; there is no CLI entrypoint and no Rust counterpart for revert today):

- `src/sase/ace/revert_agent.py` — two-phase backend: `preview_agent_revert` / `execute_agent_revert` (single) and
  `preview_agents_revert` / `execute_agents_revert` (bulk); `_apply_revert_transaction`, `_push_revert_commit`,
  `_write_revert_result`, `agent_is_reverted`.
- `src/sase/ace/revert_agent_discovery.py` — `discover_agent_commits` / `discover_bulk_commits` (tag-based `git log`
  scan, per workspace).
- `src/sase/ace/revert_agent_git.py` — git subprocess helpers (`run_git`, `is_git_worktree`, `worktree_is_clean`,
  `commit_exists`, `current_head`, `commit_subject`).
- `src/sase/ace/revert_agent_models.py` — `RevertCommit`, `RevertPreview`, `RevertResult`, `RevertTarget`,
  `BulkRevertPreview`, `BulkRevertResult`.
- `src/sase/ace/revert_agent_resolution.py` — resolves agent name / primary workspace dir / family base.
- `src/sase/ace/tui/actions/agents/_revert.py` — the `,r` action mixin (single + bulk orchestration).
- `src/sase/ace/tui/modals/confirm_revert_agent_modal.py` — confirmation modal.

The linked-repo metadata we need already exists on the model:

- `Agent.linked_repos: tuple[LinkedRepoMetadata, ...]` where `LinkedRepoMetadata` has `name`, `workspace_dir`,
  `workspace_strategy` (`src/sase/ace/tui/models/agent.py`).

There is already a **precedent pattern** for eligibility in `_linked_deltas.py` (`_suffix_workspace_linked_repos`,
`_existing_workspace_dir`) and for **status-agnostic linked-repo sourcing** in the COMMITS panel (`_agent_commits.py`).

## Critical Design Decisions

### 1. Repo set = primary ∪ eligible linked repos (status-agnostic linked eligibility)

The revert acts on a list of repos: the primary repo plus each eligible linked repo. Eligibility for a linked repo
**must mirror the COMMITS panel, not the linked-DELTAS feature**:

- Eligible iff `workspace_strategy == "suffix"` **and** its `workspace_dir` exists on disk (and is a git worktree).
- **Do NOT reuse `_linked_deltas._eligible_linked_repos`**, which gates out `Done`/`Failed` agents. Revert targets are
  _exactly_ done/failed agents, so that gate would exclude every repo we care about. (This is a known trap recorded in
  project memory `commits-section-sourcing`: COMMITS sourcing is deliberately status-agnostic; linked-DELTAS is
  status-gated.) Status is already enforced at the action level via `is_revertable_agent_status`.

Source of the linked-repo list: `Agent.linked_repos` (already parsed from `agent_meta.json` and already the source the
COMMITS panel uses). No new metadata plumbing required.

### 2. Atomic per repo, aggregated across repos (partial-failure model)

Each repo is reverted as its own single revert commit, internally atomic (rolled back to its captured `HEAD` on
failure), reusing the existing `_apply_revert_transaction` / `_rollback_to`. Across repos the operation is
**best-effort**: we attempt every revertable repo and report a per-repo outcome. A failure in one repo does **not** roll
back already-completed repos (git cannot do this). Pushing is naturally per-repo (each workspace resolves its own
`origin`).

The confirmation modal warning text changes from "a single revert commit" / "rolls back the whole operation on failure"
to language reflecting per-repo reverts (one revert commit per repo; a failure in one repo does not undo the others).

### 3. Don't let a dirty/un-revertable linked workspace silently drop commits — surface it

Linked workspaces are reused across agents, so when reverting an _old_ agent a linked workspace may be dirty or at an
unrelated `HEAD`. Per-repo handling:

- A repo with matching commits but a blocking condition (dirty worktree, not a git worktree, status unreadable, or a
  discovered SHA that no longer exists) is recorded with a **blocked reason** and **skipped** during execution — it does
  not abort the other repos.
- The preview/modal must show these blocked repos **prominently** (commit count + reason), so the user can see exactly
  what will and will not be reverted and clean up if they want full coverage.
- The primary repo keeps its existing strictness expectation (clean worktree); the difference is that a benign dirty
  _linked_ workspace no longer blocks reverting the primary, and vice-versa.

Safety checks (`commit_exists`, clean-worktree precondition) are preserved **per repo**, so revert-by-SHA remains safe
in each workspace.

### 4. Overall success / "no commits" semantics

- Preview is `ok` iff at least one repo has matching commits and is revertable, and there is no fatal top-level error.
- If **no** repo has any matching commit, fail with the existing "No commits tagged…" message.
- Per-repo "zero matching commits" is normal (agent only touched some repos) and simply omits that repo from the plan.

### 5. Reverted marker / badge

`_write_revert_result` is extended to record **per-repo** detail (repo label, workspace_dir, reverted SHAs, push
status/error) plus a `complete` flag (true iff every repo-with-commits was fully reverted). A flattened top-level
`reverted_shas` is retained for backward compatibility. `agent_is_reverted` stays "marker file exists ⇒ reverted," so
the `↺` badge appears once any repo was reverted; partial state is captured inside the marker. (Optionally surface
partial state in the badge later — out of scope for this fix.)

### 6. Bulk path interaction

The bulk "marked agents span multiple **workspaces**" rejection stays — it is about different agents' **primary**
workspaces and is still correct. Multi-repo is orthogonal: all marked agents share one primary workspace (enforced), and
with suffix strategy they therefore share the same linked workspace dirs. Bulk takes the **union** of eligible linked
repos across all targets (dedup by workspace_dir) and discovers the combined, deduped commit set **per repo** against
all targets.

### 7. Rust core boundary note (explicit, deliberate)

Project guidance (`memory/rust_core_backend_boundary.md`) says cross-frontend backend behavior belongs in the Rust core.
The entire revert subsystem is currently pure Python in this repo with **no** Rust counterpart, no CLI entrypoint, and
only the TUI as a consumer. Porting it to Rust is a separate, larger effort and out of scope for this bug fix.
**Decision: extend the existing Python module** (consistent with the established pattern), keeping the
discovery/execution core cleanly factored so a future Rust extraction (if a CLI/web revert ever needs parity) is
feasible. This tension is called out so it is a conscious choice, not an oversight.

## Proposed Approach (high-level technical design)

Unify single and bulk around a **per-repo plan/outcome** core. The action layer resolves the repo set; the backend
previews and executes each repo independently and aggregates.

### Models (`revert_agent_models.py`)

Add:

- `RevertRepo` — input descriptor: `label` (`"primary"`/project name or linked repo name), `workspace_dir`,
  `is_primary`.
- `RepoRevertPlan` — per-repo preview: `repo_label`, `workspace_dir`, `is_primary`, `commits: tuple[RevertCommit, ...]`,
  `blocked_reason: str | None`; `revertable` property (`blocked_reason is None and commits`).
- `RepoRevertOutcome` — per-repo execution result: `repo_label`, `workspace_dir`, `success`, `reverted_shas`, `pushed`,
  `error`, `skipped_reason`.

Extend:

- `RevertPreview` / `BulkRevertPreview` with `repos: tuple[RepoRevertPlan, ...]`; keep `commits` / `commit_count` /
  `sdd_paths` as flattened aggregates over revertable repos (preserves modal compatibility) and add helpers like
  `revertable_repos`, `blocked_repos`. `ok` becomes "≥1 revertable repo and no fatal error."
- `RevertResult` / `BulkRevertResult` with `repo_outcomes: tuple[RepoRevertOutcome, ...]`; keep flattened
  `reverted_shas`/`pushed` aggregates and a clear aggregated `message`.

### Backend (`revert_agent.py`)

- Add internal per-repo helpers:
  - `_preview_repo(repo, targets) -> RepoRevertPlan` — validate worktree; on a blocking condition record
    `blocked_reason`; otherwise discover commits for the target(s) via the existing discovery functions.
  - `_execute_repo(plan, message_builder) -> RepoRevertOutcome` — re-validate (clean + `commit_exists`), run
    `_apply_revert_transaction`, then `_push_revert_commit`; map results to an outcome (including `skipped_reason` when
    blocked or empty).
- Rework public entrypoints to take the repo set and iterate:
  - `preview_agent_revert(repos, agent_name, *, family_base=None) -> RevertPreview`
  - `preview_agents_revert(targets, repos) -> BulkRevertPreview`
  - `execute_agent_revert(preview, *, artifacts_dir=None) -> RevertResult` (executes exactly what was previewed;
    iterates `preview.repos`)
  - `execute_agents_revert(preview) -> BulkRevertResult`
- Extend `_write_revert_result` to the per-repo payload + `complete` flag (§Design 5).
- Keep `discover_agent_commits` / `discover_bulk_commits`, `_apply_revert_transaction`, `_rollback_to`,
  `_push_revert_commit` essentially as-is (now called once per repo).

### Resolution helper (`revert_agent_resolution.py`)

- Add `resolve_revert_repos(agent) -> tuple[RevertRepo, ...]`: primary repo (from `resolve_revert_workspace_dir`) +
  eligible linked repos (status-agnostic: suffix strategy + existing workspace dir + git worktree). Factor the
  eligibility predicate so it is unit-testable and clearly distinct from the status-gated linked-DELTAS predicate. For
  bulk, provide a way to take the union of eligible linked repos across targets (dedup by workspace_dir).

### Action layer (`tui/actions/agents/_revert.py`)

- Single path: resolve `repos = resolve_revert_repos(agent)` and pass to `preview_agent_revert`; pass the resulting
  preview to `execute_agent_revert`. Refresh on complete if any repo produced a revert commit.
- Bulk path: keep the primary-workspace-span rejection; resolve the union of repos across targets and pass to
  `preview_agents_revert` / `execute_agents_revert`. Surface the aggregated notification.

### Confirmation modal (`confirm_revert_agent_modal.py`)

- Render a **per-repo breakdown**: each repo's label, commit count, and (collapsed) commits, plus a clearly-labeled
  "Blocked (will be skipped)" section listing repos that have commits but a `blocked_reason`.
- Update the warning text to the per-repo-revert semantics (§Design 2).

## Files to Change

- `src/sase/ace/revert_agent_models.py` — new + extended dataclasses.
- `src/sase/ace/revert_agent.py` — per-repo preview/execute orchestration, marker payload.
- `src/sase/ace/revert_agent_resolution.py` — `resolve_revert_repos` + eligibility predicate.
- `src/sase/ace/revert_agent_discovery.py` — reuse as-is (verify call sites).
- `src/sase/ace/tui/actions/agents/_revert.py` — pass repo sets; aggregate results.
- `src/sase/ace/tui/modals/confirm_revert_agent_modal.py` — per-repo rendering + warning text.

## Docs / Sync (per `src/sase/ace/AGENTS.md`)

- Help popup `src/sase/ace/tui/modals/help_modal/agents_bindings.py`: update the `revert_agent` description to convey
  "across primary + linked repos."
- Command catalog `src/sase/ace/tui/commands/catalog.py`: revisit the `"revert_agent"` description.
- The `,r` keymap binding itself does not change (no `default_config.yml` change needed).

## Testing Strategy

Extend existing suites (`tests/ace/test_revert_agent.py`, `tests/ace/tui/test_revert_agent_action.py`,
`tests/ace/tui/test_confirm_revert_agent_modal.py`, `tests/ace/tui/models/test_done_agent_reverted.py`):

- **Multi-repo happy path:** primary + one linked repo, both with `AGENT=<name>`-tagged commits → preview lists both
  repos; execute reverts both; marker records both with `complete: true`.
- **Linked-only commits:** agent committed only to a linked repo → that repo is reverted; primary shows no commits.
- **No linked repos / no metadata:** behavior identical to today (regression guard).
- **Blocked linked repo:** linked workspace dirty / missing / SHA gone → primary reverts; linked repo reported
  blocked/skipped; `complete: false`; primary not blocked by the linked failure.
- **Eligibility:** a linked repo with `workspace_strategy != "suffix"` or a non-existent workspace_dir is excluded;
  confirm done/failed agents are **not** gated out (the linked-DELTAS-vs-COMMITS trap).
- **Bulk:** combined dedup per repo across marked targets; union of linked repos across targets; primary-workspace-span
  rejection preserved.
- **Push semantics:** per-repo push success/skip/failure mapped into per-repo outcomes and the aggregated message.
- **Modal:** renders per-repo breakdown and a blocked section; updated warning text.

Run `just check` before completion (this repo's standard gate; note ephemeral-workspace `just install` first). Consider
whether the confirm-modal change needs a visual-snapshot update (`just test-visual`).

## Out of Scope

- Porting revert to the Rust core or adding a CLI revert entrypoint (boundary note §Design 7).
- Reworking how linked-repo commits are _persisted_ (this plan uses live tag-based `git log` discovery per repo,
  consistent with the existing revert design).
- A distinct "partially reverted" badge state (marker records partial state; badge stays binary).
