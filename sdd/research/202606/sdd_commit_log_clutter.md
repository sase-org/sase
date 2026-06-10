---
create_time: 2026-06-09
updated_time: 2026-06-09
status: research
---

# Reducing SDD Commit Clutter in the Git Log

## Question

A large share of commits on `master` exist only to version-control SDD plan/prompt/research files under `sdd/`
(messages like `chore: Add SDD prompt and plan for <name>`, `chore: Mark SDD plan done`, bead and research commits).
Keeping these files version controlled is desirable; the clutter they add to the commit log is not. What are the
options for keeping the version control while cleaning up the log?

## Measurements (as of 2026-06-09, 7,916 commits on master)

| Category                                  | Count | Share of non-merge commits |
| ----------------------------------------- | ----- | -------------------------- |
| Commits touching **only** `sdd/` files    | 1,816 | 23.2%                      |
| Mixed commits (sdd/ + code)               | 1,300 | 16.6%                      |
| Commits touching no sdd/ files            | 4,699 | 60.1%                      |

Filter effectiveness against current history:

- **Pathspec exclusion** (`git log -- . ':(exclude)sdd'`): shows 6,056 of 7,916 commits — hides all sdd-only commits
  while keeping mixed commits. Complete and retroactive.
- **Message filtering** (`--invert-grep` on `SDD prompt and plan`, `SDD plan done`, `TYPE=sdd`): hides only ~836
  commits. Incomplete because the `TYPE=sdd` trailer exists on just 204 commits (it is recent), and many sdd-only
  commits (research, infographics, bead bookkeeping) have free-form messages with no machine-readable marker.

## How These Commits Get Created (Constraints)

- `commit_sdd_files_for_exec_plan()` (`src/sase/axe/run_agent_exec_plan_sdd.py:14`) builds the
  `chore: Add SDD prompt and plan for <name>` message, appends a `TYPE=sdd` trailer via `apply_auto_commit_type_tag()`
  (`src/sase/workflows/commit/runtime_tags.py:73`), and shells out to `sase commit`. Triggered from the plan-approval
  flow in `src/sase/axe/run_agent_exec_plan.py` (~line 358).
- **Durability constraint**: the docstring at `run_agent_exec_plan_sdd.py:22` records that the `#gh` workflow pre-step
  runs `git checkout . && git clean -fd`, which wipes uncommitted files. SDD files must therefore be committed (and
  pushed) *before* the worker agent launches. Any solution that delays or folds the SDD commit into later work commits
  breaks this guarantee.
- Research/bead/mark-done commits are made by agents through plain `sase commit` and do **not** consistently get the
  `TYPE=sdd` trailer today.
- `sdd.version_controlled: false` already exists (`src/sase/sdd/beads.py:18`): SDD files then live in a local git repo
  at `.sase/sdd/` in the primary workspace. This fully removes the clutter but loses GitHub backup/sharing and is
  forced to `true` for bare-git workspaces.
- Releases use release-please with conventional commits; sdd commits are `chore:` so they already stay out of
  changelogs. The clutter is a *log-reading* problem, not a release problem.

## Options

### A. View-level filtering (no history or workflow change)

**A1. Pathspec-exclusion alias (recommended first step).** Hides every sdd-only commit, past and future, with zero
risk:

```bash
git config --global alias.lgx "log --oneline -- ':(exclude)sdd' ."
git config --global alias.lg1x "log --graph --abbrev-commit --decorate \
  --format=format:'%C(bold blue)%h%C(reset) - %C(bold green)(%ar)%C(reset) %C(auto)%s%C(reset)' -- ':(exclude)sdd' ."
```

Verified against this repo: mixed commits still appear; only sdd-only commits disappear. Caveats: pathspec filtering
triggers git's history simplification (graph shapes can change slightly around merges), and `git log -p` with the
pathspec also strips sdd hunks out of mixed-commit diffs (arguably a feature). Does **not** clean the GitHub web UI,
which has no path-exclusion view.

**A2. Trailer-based filtering** (`git log --invert-grep --grep='TYPE=sdd'`). Currently catches only 204 commits;
becomes viable for *future* history only if B1 below is done. Useful in tools that filter by message but cannot take
pathspecs.

### B. Make machine commits uniformly machine-recognizable (small sase change, high leverage)

**B1. Auto-tag every sdd-only commit at the `sase commit` layer.** Instead of relying on each call site to apply
`apply_auto_commit_type_tag(..., "sdd")`, have `sase commit` detect that the staged file set lives entirely under
`sdd/` (or `.sase/sdd/`) and auto-append `TYPE=sdd`. This closes the gap for agent-authored research/bead/mark-done
commits and makes trailer filtering (A2) complete going forward. Per the rust-core boundary rule, if the commit flow's
shared behavior lives in `sase-core`, the detection belongs there.

**B2. Adopt a `chore(sdd):` conventional-commit scope** for all generated sdd messages. Purely cosmetic, but it groups
visually in `--oneline` output, is trivially greppable, and keeps release-please behavior unchanged (still `chore`).

### C. Reduce the number of commits (partial relief)

- **Batch per-run bookkeeping**: "Add SDD prompt and plan" + "Mark SDD plan done" + bead-launch updates can be 2–3
  commits per task today. The trailing bookkeeping (mark-done + bead state) could be combined into one commit at
  finalize time. Modest win (~hundreds of commits over time), no durability impact.
- **Folding the plan into the first work commit is NOT viable** as-is: the pre-launch commit exists precisely because
  `git clean -fd` in the `#gh` pre-step would destroy uncommitted plans, and a failed/abandoned run would otherwise
  lose the approved plan entirely.

### D. Move sdd history out of `master` (structural; the only way to clean the GitHub UI)

**D1. Orphan `sdd` branch maintained via a dedicated worktree.** sase would commit sdd files to a parallel branch
(like a `gh-pages` pattern); `master` stays clean everywhere, including GitHub's commits page. Costs: plan-file
references from ChangeSpecs/prompts (`sdd/tales/...` paths resolved relative to the workspace) would need a resolution
layer; ephemeral `sase_<N>` workspaces are full clones and would need the branch checked out into a worktree on
launch; mixed commits would split into two commits on two branches (loss of atomicity); meaningful work in
`run_agent_exec_plan_sdd.py`, `sdd/_commit.py`, `sdd/files.py`, and likely `sase-core`.

**D2. Separate repo or submodule for `sdd/`.** Total separation, but a submodule pointer would either generate its own
bump commits on master (clutter returns) or float unpinned; a fully separate repo breaks the "one clone has
everything" property of ephemeral workspaces. Strictly worse than D1 for this codebase.

**D3. Existing `sdd.version_controlled: false` mode.** Already implemented; zero clutter; but plans live only in the
local `.sase/sdd/` repo — no GitHub backup, no cross-machine sharing, and unavailable for bare-git workspaces. Listed
for completeness as the existing escape hatch.

### Rejected

- **History rewrite (`git filter-repo`) of the existing 1,816 commits**: would invalidate every clone, release-please
  tags, and PR references. Not worth it for a cosmetic problem.
- **`git notes` / custom refs for plan storage**: notes annotate existing commits; they are the wrong shape for
  standalone plan documents and have poor push/fetch ergonomics.
- **Merge-bubble + `--first-parent` discipline**: incompatible with the direct-to-master trunk flow, and GitHub's
  default commit view ignores first-parent anyway.

## Recommendation

Layered, in order of effort:

1. **Today (no code)**: add the A1 pathspec-exclusion alias for day-to-day log reading. It is the only retroactive,
   complete filter and carries zero risk.
2. **Small change**: implement B1 (path-based `TYPE=sdd` auto-tagging in `sase commit`) plus B2 (`chore(sdd):` scope)
   so every future machine commit is filterable by message as well as by path.
3. **Only if the GitHub web UI clutter matters enough**: pursue D1 (orphan `sdd` branch via worktree) as a dedicated
   epic — it is the sole option that cleans `github.com/sase-org/sase/commits`, and it touches the plan-reference,
   workspace-provisioning, and durability machinery, so it should not be bundled into anything else.

## Code Pointers

- `src/sase/axe/run_agent_exec_plan_sdd.py:14` — `commit_sdd_files_for_exec_plan()`, message construction, durability
  rationale.
- `src/sase/axe/run_agent_exec_plan.py` (~358) — plan-approval trigger; epics/legends always commit.
- `src/sase/sdd/_commit.py:13` — non-version-controlled `.sase/sdd/` commit path.
- `src/sase/workflows/commit/runtime_tags.py:73` — `apply_auto_commit_type_tag()` (`TYPE=sdd` trailer).
- `src/sase/sdd/beads.py:18` — `get_effective_sdd_config()` / `sdd.version_controlled` semantics.
