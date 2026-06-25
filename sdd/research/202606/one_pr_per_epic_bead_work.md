# One PR per Epic for `sase bead work`

**Date:** 2026-06-25
**Status:** Research / recommendation
**Goal:** Migrate `sase bead work <epic>` away from "every phase agent pushes its commit to
`master`" toward **one PR per epic**, containing **one commit per phase bead** plus **one commit
for the land agent**.

---

## TL;DR

The machinery to do this **already exists and is fully wired** — it is just gated behind an
opt-in field that epics almost never carry in practice. `render_multi_prompt()` in
`src/sase/bead/work.py` has two modes:

- **Regular epic (today's default):** every phase segment and the land segment is prefixed with
  the project VCS ref `#gh:<project>` (e.g. `#gh:sase`). Each agent checks out `master`, and the
  default commit method (`create_commit`) commits + pushes the *currently checked-out branch* —
  so **every phase lands straight on `master`.**
- **ChangeSpec-attached epic (opt-in, ~never used):** the **first** phase is prefixed
  `#gh:<project> #pr:<changespec_name>` (creates a branch + Draft PR and commits onto it); **every
  later phase and the land segment** is prefixed `#gh:<changespec_name>` (checks out the PR branch
  and stacks its commit there). The result is **exactly the desired shape**: one PR, one commit
  per phase, one land commit.

So the migration is **not** new VCS plumbing — it is (1) routing regular epics through the
existing ChangeSpec path by **auto-synthesizing a ChangeSpec** when an epic has none, and
(2) closing a **wave-0 concurrency race** in that path. Two open product decisions remain: the
**land-agent merge policy** and **multi-repo PRs**.

The recommended solution is at the bottom: [Recommended Solution](#recommended-solution).

---

## 1. How `sase bead work <epic>` works today

Entry point: `handle_bead_work()` → `_handle_epic_bead_work()` in
`src/sase/bead/cli_work_handler.py`.

1. **Open project + validate** the target is a PLAN-tier EPIC bead (`cli_work_handler.py:58-99`).
2. **Build the work plan** from the bead dependency DAG via the Rust core
   (`build_epic_work_plan_from_beads_dir`, `work.py:132`). Non-closed phase children are layered
   Kahn-style into **waves**: wave 0 = phases with all in-epic blockers already closed; wave *k* =
   phases whose remaining blockers fall in earlier waves. The plan also carries a single **land
   agent** that waits on every phase (`EpicWorkPlan`, `work.py:38-48`).
3. **Resolve VCS context** (`cli_work_handler.py:140-153`):
   - if `issue.changespec_name` is set → `resolve_changespec_launch_context(...)` →
     `ChangeSpecLaunchContext`;
   - else → `resolve_vcs_launch_context()` → plain `VCSLaunchContext` (project ref). **This is
     the branch the migration must flip.**
4. **Render the multi-prompt** (`render_multi_prompt`, `work.py:298-362`) — a `---`-separated
   string, one segment per phase plus a land segment (see §2 for the exact shape).
5. **Confirm / force-reuse cleanup / mark epic ready / pre-claim phases**
   (`cli_work_handler.py:174-217`). Pre-claim sets each phase `in_progress` + assignee so agents
   start on an already-claimed bead.
6. **Launch all agents at once** through the planned bead-work launcher
   (`launch_bead_work_agents`, `cli_work_launch.py`).
7. **Commit the bead-state metadata** to `master` (`commit_successful_work_launch` →
   `commit_bead_work_launch`, `sync.py:49-105`) as
   `chore: mark bead work launched for <epic_id>`, then push (sync/async/off per
   `bead.push_after_commit`). **Important:** this commit is *bead-tracking metadata* (JSONL state),
   **not** the phase agents' code. The code commits come later, from each agent's finalizer.

### The rendered multi-prompt (regular epic, today)

```
#gh:sase
%name:!sase-56.1
%group:sase-56
%model:worker
%auto
#bd/work_phase_bead:sase-56.1
---
#gh:sase
%name:!sase-56.2
%group:sase-56
%model:worker
%auto
%w:sase-56.1
#bd/work_phase_bead:sase-56.2
---
... (one segment per phase) ...
---
#gh:sase
%name:!sase-56
%group:sase-56
%auto
%w:sase-56.1,sase-56.2,sase-56.3
#bd/land_epic:sase-56
```

Every segment targets `#gh:sase` (the **project** ref) → every agent works on `master`.

---

## 2. How a phase agent actually commits (the crux)

The two bead xprompts that drive these agents say **nothing** about committing, branches, PRs, or
`master`. They are deliberately minimal (`src/sase/default_config.yml`):

- **`bd/work_phase_bead`** (tag `work_phase_bead`, `default_config.yml:495-502`):
  > "Can you complete the work for bead `{{ bead_id }}`? The bead has already been claimed for you
  > (status=in_progress, assignee set). Read its description and design file, do the work, and
  > close the bead. Do NOT close the parent epic. Do NOT create new beads."
- **`bd/land_epic`** (tag `land_epic`, `default_config.yml:358-377`):
  > "...verify that all the work associated with the bead ... is complete? Actually read through
  > the source code and the git commits ... close the bead using `sase bead close` ... run
  > `just pyvision` AFTER closing the epic bead ... a `status` field should be ... `done`."

All commit/branch/PR behavior is injected by **two independent levers** that the renderer prepends
to each segment, plus a post-completion finalizer:

1. **The VCS tag `#<workflow>:<ref>`** decides *which branch the workspace is checked out on*
   before the agent runs. In `sase-github/src/sase_github/xprompts/gh.yml` (the `#gh` workflow,
   `wraps_all: true`), the `checkout` step (`gh.yml:56-113`) branches on the ref kind:
   - a **project/repo ref** (`#gh:sase`) checks out the default branch, falling back through
     `master`/`main` (`gh.yml:84-88`) → the agent works on `master`;
   - a **ChangeSpec ref** (`#gh:<name>`) resolves the ChangeSpec name to its branch via
     `provider.resolve_revision(...)` (`gh.yml:74-82`) → the agent works on the PR branch.
2. **The `#pr` directive** (`src/sase/xprompts/pr.yml`) sets `SASE_COMMIT_METHOD=create_pull_request`
   (and `SASE_PR_STATUS=draft`) in the agent's environment. It does **not** create anything at
   render time.
3. **The post-completion commit finalizer** (`src/sase/llm_provider/commit_finalizer_*`, the
   `sase_git_commit` skill) runs *after* the agent and performs the actual commit, choosing the
   method from `SASE_COMMIT_METHOD` (default `create_commit`). The xprompts even tell the agent:
   "make file changes but do NOT commit/branch/PR yourself unless a finalizer instructs you."

The two commit methods (`src/sase/vcs_provider/plugins/_git_commit_dispatch.py`) are where it all
lands:

- **`create_commit`** (`_git_commit_dispatch.py:227-275`): `git add` → merge `origin/<default>` →
  `git commit` → **push the *current* branch** (`git symbolic-ref --short HEAD`). On a `master`
  checkout, this commits + pushes **straight to `master`**.
- **`create_pull_request`** (`_git_commit_dispatch.py:291-334`): `git checkout -b <name>` →
  commit → push the new branch; the GitHub subclass then runs `gh pr create` (Draft) and writes a
  ChangeSpec record (`sase-github/src/sase_github/plugin.py:103-121`).

**Net:** regular epics hit `master` because **no segment ever carries `#pr`**, so every agent
defaults to `create_commit` on its `master` checkout. The ChangeSpec path funnels into one PR
because only the **first** phase carries `#pr` (opens exactly one branch + PR), and every
**later** segment retargets the ChangeSpec ref so its default `create_commit` stacks onto that one
branch.

### The rendered multi-prompt (ChangeSpec-attached epic — the desired shape)

```
#gh:sase #pr:my_epic            <- first phase: opens branch "my_epic" + Draft PR, commits onto it
%name:!sase-56.1
...
#bd/work_phase_bead:sase-56.1
---
#gh:my_epic                     <- later phases: check out the PR branch, stack a commit
%name:!sase-56.2
%w:sase-56.1
...
#bd/work_phase_bead:sase-56.2
---
#gh:my_epic                     <- land agent: also commits onto the PR branch
%name:!sase-56
%w:sase-56.1,sase-56.2,sase-56.3
#bd/land_epic:sase-56
```

`_segment_prefix()` / `_pr_reference()` (`work.py:469-489`) and the `is_first_phase` flag are what
choose project-ref-+-`#pr` vs ChangeSpec-ref. The `#pr` form is `#pr:<name>` or, with a bug id,
`#pr(name=<name>, bug_id=<id>)`. Four unit tests already pin this exact rendering
(`tests/test_bead/test_work_rendering.py::TestChangeSpecRendering`, e.g.
`test_independent_phases_only_first_gets_pr` asserts `rendered.count("#pr:feature_epic") == 1`).

---

## 3. Evidence from real runs (why this migration is worth doing)

Reviewing recent `master` history and chat transcripts of actual epic runs (e.g. `sase-56`
*auto_approve_menu_and_tale_directive*, 2026-06-23; `sase-4m`, `sase-4j`) surfaced concrete pain
points that a per-epic PR directly fixes:

1. **No pre-merge gate → revert commits.** Because agent work lands on `master` immediately,
   unwanted work is undone with `git revert` after the fact. Recent examples:
   `7b82b54eb "Revert 1 commit(s) from agent '06e'"` and
   `2bb084529 "Revert 2 commit(s) from agent '062'"` — the latter was immediately **re-done** as a
   fresh pair of commits (a revert-then-redo cycle that only exists because the first attempt had
   already shipped). These come from the `sase ace` "revert agent" TUI feature
   (`008972df4 feat(ace): revert agent changes across linked repos`).
2. **Phase commits interleave with unrelated work on `master`.** All three epics reviewed had
   unrelated commits landing *between* their phase commits (sase-56's phases interleaved with
   prompt-history / dot-repeat / vim-visual work; sase-4j had `chore(master): release 0.1.4` cut
   mid-epic). An epic is **not** a contiguous, atomic unit in history today — you cannot
   `git log` a clean range for one epic; you must reconstruct it from `(<epic_id>.N)` message tags.
3. **Concurrent-push races on `master`.** The `sase-56.1` transcript shows its commit failing
   because `origin/master` advanced (another agent touched the same `docs/ace.md`), forcing a
   stash → fast-forward → re-commit dance.
4. **Cross-phase integration bugs ship before they're caught.** Phase 1 of sase-56 left a drifted
   duplicate alias table in `sase-core`; the land agent only found and fixed it *after* phases 1–3
   had already landed on `master`. On a PR branch that fix would be a pre-merge commit.
5. **Confusing partial / out-of-order states.** The sase-56 land agent found the epic bead already
   closed by a predecessor, with a `COMMIT:` note pointing at a hash absent from the log.

History is confirmed **linear on `master`** (`git log --graph` is a single column; a phase commit
`git branch --contains` shows only `master`/`origin/master`) — there are no epic branches today.

---

## 4. Gaps to close before per-epic PRs can be the default

| # | Gap | Detail | Seam |
|---|-----|--------|------|
| 1 | **No auto-attach of a ChangeSpec** | An epic only gets `changespec_name` via manual `sase bead create -c/--changespec`. A low-level update setter exists in `project.py`/Rust but **no CLI exposes it on update**, and nothing populates it automatically. In practice epics never carry one. | `cli_work_handler.py:140-153`; field at `bead/model.py:55-56` |
| 2 | **Wave-0 concurrency race** | Only the *first* phase gets `#pr`; `waits_on` comes purely from the bead DAG. If wave 0 has independent phases A,B,C, then B,C target `#gh:<name>` whose branch A hasn't created yet. For a ChangeSpec ref the `gh.yml` checkout has **no `master` fallback** and failure is a **non-fatal stderr warning** (`gh.yml:89-93`) — so B,C silently degrade to the base branch and their commits can leak to `master`. **No mechanism serializes wave 0 or pre-creates the branch.** | `work.py:333-349`; `gh.yml:73-93` |
| 3 | **Untested concurrency / unproven path** | The ChangeSpec render path has unit tests for *rendering* only — no concurrency tests — and shows **no evidence of a real production run**. The race in #2 has likely never fired because nobody attaches ChangeSpecs to epics. | `tests/test_bead/test_work_rendering.py` |
| 4 | **Land semantics are verification-only** | `bd/land_epic` verifies, closes the epic bead, and marks the plan `done`. It has **no notion of "open/mark-ready/merge a PR."** The migration must decide what "land" means once a PR exists (see §5). | `default_config.yml:358-377` |
| 5 | **Multi-repo epics** | Epics routinely touch both `sase` and `sase-core` (sase-56.1 produced one commit in each repo). "One PR per epic" implies one PR **per affected repo**, sharing the ChangeSpec name. ChangeSpecs already span linked repos (the COMMITS drawer tracks per-repo commits; the revert feature spans repos), so this is conceptually covered — but it must be verified end-to-end, not assumed. | `sase-github` workspace plugin; ChangeSpec COMMITS drawer |
| 6 | **Bead state lives in-repo** | Phase agents close their beads (`sase bead close`), mutating JSONL bead state that the finalizer commits **into the phase commit**. With per-epic PRs those closures live on the PR branch until merge, so `sase bead list` on `master` shows phases still in-progress until the PR merges. This mirrors how any PR works (the world doesn't see the change until merge) but is a behavior change worth calling out. | `sync.py`; phase `close` path |

### Prior design intent

The per-epic-PR machinery was built as **deliberately opt-in**:

- `sdd/epics/202604/epic_changespec_beads.md` (bead `sase-1l`, *done*) is the canonical design:
  "When an epic has a ChangeSpec attachment: the first phase agent should be launched against the
  normal project VCS ref ... and should also include `#pr:<changespec_name>` ... Every later phase
  agent, plus the final land agent, should be launched against the ChangeSpec ref." It is
  explicitly VCS-plugin-neutral and stores the attachment once on the plan bead. It says **nothing
  about concurrent wave-0 ordering** — gap #2 is unaddressed in the original design.
- `sdd/tales/202605/epic_phase_vcs_prompts.md` (*done*) added the plain `VCSLaunchContext` sibling
  so non-ChangeSpec epics also get a `#<workflow>:<project>` prefix.
- `sdd/epics/202602/git_change_specs_v3.md` established the foundational model this migration
  inverts: "...directly to master, and changes are auto-pushed. ChangeSpecs are only created when a
  PR is explicitly requested via `#pr:<name>`."

**No existing doc proposes making per-epic PR the default — that is a genuinely new decision**,
building on a fully-implemented opt-in renderer.

---

## 5. The two product decisions

### Land-agent merge policy

The user's stated target is "one PR per epic with one commit per phase **and one commit for the
land agent**" — i.e. the land agent still *adds a commit to the PR*; it is not required to merge.
Given the pain points in §3 (reverts, no review gate), the recommendation is to **stop short of
auto-merge by default** and leave a reviewable PR:

- **(Recommended) Land → mark the ChangeSpec `Ready`** (PR ready-for-review) and stop. A human (or
  a separate, explicit step) merges. This restores the pre-merge gate the current model lacks.
- *(Alternative)* Land → mark `Mailed` / request review. Same gate, more ceremony.
- *(Opt-in only)* Land → `gh pr merge` (auto-merge). Fully hands-off, but discards the review gate;
  expose behind a config flag (`bead.epic_pr.auto_merge`, default `false`).

This requires extending `bd/land_epic` to finalize the PR (today it only verifies/closes/marks the
plan done).

### Multi-repo PRs

Decide whether an epic touching N repos opens N PRs (one per repo, shared ChangeSpec name) or is
constrained to single-repo. The ChangeSpec model already spans repos, so N PRs is the natural
answer — but it must be tested.

---

## Recommended Solution

Make **per-epic PR the default** for `sase bead work`, behind a config flag for staged rollout,
by reusing the existing ChangeSpec render path and closing its two gaps. Concretely:

### A. Auto-synthesize a ChangeSpec for every epic that lacks one

In `_handle_epic_bead_work` (`cli_work_handler.py:140-153`), when `issue.changespec_name` is empty
and the new flag is on, synthesize a `ChangeSpecLaunchContext` instead of falling through to the
plain `VCSLaunchContext`:

- **Name:** derive a readable, branch-safe ChangeSpec name from the epic — prefer the epic's plan
  slug (`sdd/epics/YYYYMM/<slug>.md`), falling back to `epic-<epic_id>`. The existing `_<N>`
  suffix mechanism already de-collides concurrent names (`_git_query_ops.py:106`).
- **Persistence:** write the synthesized name back onto the epic bead (the
  `changespec_name`/`changespec_bug_id` setter already exists in `project.py`/Rust) so reruns and
  the land agent resolve the same ChangeSpec. This also gives the TUI/ChangeSpec tooling a real
  record.
- **`bug_id`:** optional; pass through if the epic was created with one.

### B. Eliminate the wave-0 race by pre-creating the branch + Draft PR up front

This is the key robustness improvement over the as-built opt-in path. Rather than relying on "the
first phase's `#pr` opens the branch" (which races against independent wave-0 siblings), have the
**orchestrator** create the branch and Draft PR *before launching any agents*, then render **every**
segment — first phase included — against the ChangeSpec ref `#gh:<name>` with **no `#pr` anywhere**.

- Reuse the existing launch-marker commit as the PR's seed: redirect
  `commit_bead_work_launch` (`sync.py:49-105`) to commit
  `chore: open epic PR for <epic_id>` onto the **new epic branch** instead of `master`, push it,
  then open the Draft PR via the VCS provider's `vcs_create_pull_request` (plugin-neutral; bare-git
  degrades to "branch only", GitHub adds `gh pr create`). Return the orchestrator workspace to
  `master` afterward.
- Because the branch exists on `origin` before any agent launches, every phase's `#gh:<name>`
  checkout succeeds and its default `create_commit` stacks cleanly — **no segment needs `#pr`, and
  the race in gap #2 disappears.**
- Trade-off: the PR carries a small leading `chore: open epic PR` seed commit in addition to the
  N phase commits + 1 land commit. This is a minor, honest deviation from "exactly N+1 commits";
  if undesired, the land agent (or a `--squash` merge) can absorb it.

> **Smaller v1 alternative (if up-front PR creation is too large a first step):** keep the as-built
> `#pr`-on-first-phase render path and instead **inject a synthetic `waits_on`** from every
> non-PR-creating wave-0 phase onto the PR-creating phase (in the Rust plan builder or
> `render_multi_prompt`). This is a smaller diff that reuses the tested renderer verbatim, at the
> cost of (a) serializing wave 0 behind the first phase and (b) relying on the unproven `#pr`
> concurrency path. **Prefer option B** for correctness; this is the fast path if a minimal change
> is wanted first.

### C. Make "land" finalize the PR, not push to master

Extend `bd/land_epic` (`default_config.yml:358-377`) so that, after verifying/closing the epic and
marking the plan `done`, it **marks the ChangeSpec `Ready`** (default) rather than implying a push
to `master`. Do **not** auto-merge by default — that is the review gate the current model is
missing (§3). Gate auto-merge behind `bead.epic_pr.auto_merge` (default `false`).

### D. Roll out behind a config flag, mirroring `bead.push_after_commit`

Add `bead.epic_pr` (e.g. `true` | `false`, default `false` initially → flip to `true` after
soak). This lets the change land dark, be validated on a real epic, and be reverted instantly if
the concurrency or multi-repo behavior misbehaves. The existing `_resolve_push_mode` pattern in
`cli_work_commit.py:13-35` is the template for reading it.

### E. Add the missing concurrency + multi-repo tests

The current tests cover *rendering* only. Add:

- a wave-0 concurrency test (independent phases) proving every phase commits to the epic branch and
  **nothing leaks to `master`** under the chosen design;
- a multi-repo test proving an epic touching `sase` + `sase-core` opens a PR (or branch) in each,
  sharing the ChangeSpec name;
- a land-agent test proving the PR ends `Ready` (not merged, not pushed to `master`).

### Why this is the right shape

- **Minimal new surface area:** the funnel (`#pr` first / ChangeSpec ref later → one branch, one
  PR, stacked commits) is already implemented, unit-tested, plugin-neutral, and matches the
  canonical `epic_changespec_beads.md` design. The migration mostly *routes* existing epics into
  it and *pre-creates* the branch to remove the one real concurrency hazard.
- **Directly fixes the §3 pain points:** an epic becomes one reviewable, atomic PR (no
  interleaving, no `master` push-races, a real pre-merge gate that removes the revert-then-redo
  cycle, cross-phase fixes happen pre-merge).
- **Reversible & observable:** the config flag allows a dark launch and instant rollback; writing
  the synthesized ChangeSpec back gives the TUI a real record to watch.

### Key implementation seams (file:line)

- `src/sase/bead/cli_work_handler.py:140-153` — the VCS-context branch to flip (synthesize a
  `ChangeSpecLaunchContext` when none attached).
- `src/sase/bead/work.py:298-362`, `:469-489` — `render_multi_prompt` / `_segment_prefix` /
  `_pr_reference` (the funnel; for option B, render all segments against the ChangeSpec ref).
- `src/sase/bead/sync.py:49-105` — `commit_bead_work_launch` (redirect the launch-marker commit
  onto the epic branch + open the Draft PR).
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py:227-334` — `create_commit` vs
  `create_pull_request` (the branch-landing mechanism).
- `sase-github/src/sase_github/xprompts/gh.yml:56-113` — ChangeSpec-ref checkout (the race site;
  becomes safe once the branch is pre-created).
- `src/sase/default_config.yml:358-377`, `:495-502` — `bd/land_epic` / `bd/work_phase_bead`
  xprompts (extend land to finalize the PR).
- `src/sase/bead/model.py:55-56` and the `project.py`/Rust update setter — `changespec_name` /
  `changespec_bug_id` persistence.
- `src/sase/bead/cli_work_commit.py:13-35` — `bead.*` config pattern for the new `bead.epic_pr`
  flag.

### Prior art to read before implementing

- `sdd/epics/202604/epic_changespec_beads.md` (canonical ChangeSpec-aware epic design)
- `sdd/tales/202605/epic_phase_vcs_prompts.md` (the `VCSLaunchContext` sibling)
- `sdd/epics/202602/git_change_specs_v3.md` (foundational "commit to master, PR only on `#pr`" model)

---

## Open questions for the user

1. **Merge policy:** land agent stops at `Ready` (recommended), or auto-merges (flag)?
2. **Seed commit:** is a leading `chore: open epic PR` commit acceptable (option B), or must the PR
   be exactly N phase commits + 1 land commit (then prefer the wave-0-serialization v1 alternative,
   or have land squash the seed)?
3. **Multi-repo:** confirm that an epic touching multiple linked repos should open one PR per repo
   (shared ChangeSpec name).
4. **Scope of first cut:** ship the smaller wave-0-serialization v1 first to de-risk, then move to
   up-front PR creation — or go straight to up-front creation?
