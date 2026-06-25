---
create_time: 2026-06-25
updated_time: 2026-06-25
status: research
---

# Epic `sase bead work` PR Migration Research

## Question

Today, `sase bead work <epic>` launches one agent per epic phase plus a land agent, and recent normal epic runs have
landed each phase agent's commit directly on `master`. The target shape is one PR per epic, with one commit per phase
bead and one final commit from the land agent that closes the epic.

This note explains how the current process works, what recent runs show, and what should change to make epic work
PR-backed by default.

## Sources Reviewed

- Current source: `src/sase/bead/cli_work_handler.py`, `src/sase/bead/work.py`,
  `src/sase/bead/cli_work_launch.py`, `src/sase/agent/launch_cwd_bead_work.py`,
  `src/sase/agent/multi_prompt_launcher.py`, `src/sase/agent/multi_prompt_vcs.py`,
  `src/sase/bead/sync.py`, `src/sase/bead/cli_work_commit.py`, `src/sase/commit_instructions.py`,
  `src/sase/llm_provider/commit_finalizer.py`, and the built-in xprompts in `src/sase/default_config.yml` and
  `src/sase/xprompts/`.
- Current docs: `docs/beads.md` and `docs/commit_workflows.md`.
- Current tests: especially `tests/test_bead/test_cli_work_epic_launch.py`,
  `tests/test_bead/test_cli_work_epic_lifecycle.py`, and ChangeSpec/rendering tests.
- Recent git history for `sase-54`, `sase-55`, and `sase-56`.
- Recent chat transcripts found with `sase chat list -q 'sase-56'`, `sase chat list -q 'sase-55'`, and
  `sase chat list -q 'sase-54'`.
- Bead state for `sase-56` via `sase bead search 'sase-56' --format full`.
- ChangeSpec lookup for `sase-56` via `sase changespec search 'sase-56' -f markdown`, which returned no matches.

## Current Epic Work Flow

### Entry point and eligibility

`sase bead work` only proceeds for plan beads. `handle_bead_work()` dispatches epic-tier plan beads to
`_handle_epic_bead_work()` and legend-tier plan beads to `_handle_legend_bead_work()`
(`src/sase/bead/cli_work_handler.py:58`). The CLI exposes only `--dry-run`, `--no-push`, and `--yes` for
`sase bead work`; ChangeSpec metadata is accepted at bead creation time through `sase bead create -c/--changespec`
and `-b/--bug-id` (`src/sase/main/parser_bead.py:49`, `src/sase/main/parser_bead.py:202`).

For epic beads, `_handle_epic_bead_work()`:

1. Resolves the phase and land xprompts by tag (`bd/work_phase_bead`, `bd/land_epic`).
2. Builds an `EpicWorkPlan` from the bead store.
3. If the epic issue has `changespec_name`, resolves a `ChangeSpecLaunchContext`; otherwise resolves a plain
   `VCSLaunchContext` from the current project (`src/sase/bead/cli_work_handler.py:140`).
4. Renders a `---`-separated multi-prompt (`src/sase/bead/cli_work_handler.py:155`).
5. On live runs, force-reuses deterministic agent names, marks the epic ready, preclaims the phase beads as
   `status=in_progress` with `assignee=<phase_agent_name>`, launches the agents, then commits the launch-state bead
   mutation (`src/sase/bead/cli_work_handler.py:178`, `src/sase/bead/cli_work_handler.py:189`,
   `src/sase/bead/cli_work_handler.py:201`, `src/sase/bead/cli_work_handler.py:219`,
   `src/sase/bead/cli_work_handler.py:248`).

The docs describe the same flow: the command builds Kahn waves, preclaims each phase bead, emits one phase segment per
open child plus one land segment, and commits/pushes the launch-state mutation after successful launch
(`docs/beads.md:300`, `docs/beads.md:357`, `docs/beads.md:368`, `docs/beads.md:375`).

### Prompt rendering

`EpicWorkPlan` is a wave-partitioned list of `_PhaseAssignment`s plus a land agent name and waits
(`src/sase/bead/work.py:27`). `render_multi_prompt()` turns that plan into one segment per phase, followed by the land
segment (`src/sase/bead/work.py:298`).

For each phase segment, the renderer emits:

- the VCS prefix, if any;
- `%name:!<phase_bead_id>` for deterministic force reuse;
- `%group:<epic_id>`;
- `%model:<stored model>` or `%model:worker`;
- `%auto`;
- `%w:<dependency_agent_names>` when the phase bead has dependencies;
- `#bd/work_phase_bead:<phase_id>`.

The land segment uses `%name:!<epic_id>`, the same group, optional land model, `%auto`, `%w` on all launched phase
agents, and `#bd/land_epic:<epic_id>` (`src/sase/bead/work.py:333`, `src/sase/bead/work.py:351`).

The built-in phase xprompt tells the phase agent to complete and close exactly its phase bead, not the parent epic
(`src/sase/default_config.yml:495`). The built-in land xprompt tells the land agent to inspect source and commits
associated with the bead ID, check child bead notes, close the epic, run `just pyvision` when available, and mark the
epic plan frontmatter `status: done` (`src/sase/default_config.yml:358`).

### VCS and PR selection

The crucial branch decision is already represented in `render_multi_prompt()`:

- With a plain `VCSLaunchContext`, every segment is prefixed with the project ref, for example `#git:sase` or
  `#gh:sase` (`src/sase/bead/work.py:319`, `src/sase/bead/work.py:469`).
- With a `ChangeSpecLaunchContext`, the first phase targets the project ref and adds `#pr`; later phases and the land
  segment target the ChangeSpec ref directly (`src/sase/bead/work.py:320`, `src/sase/bead/work.py:476`,
  `src/sase/bead/work.py:486`).

The test suite captures both behaviors. A normal epic dry run renders every phase and the land segment with `#git:sase`
(`tests/test_bead/test_cli_work_epic_launch.py:308`). A ChangeSpec-attached epic renders the first phase as
`#git:sase #pr(name=feature_epic, bug_id=12345)`, and later phase/land segments as `#git:feature_epic`
(`tests/test_bead/test_cli_work_epic_launch.py:359`).

The launch adapter uses the fast planned path whenever there is a VCS or ChangeSpec launch context
(`src/sase/bead/cli_work_launch.py:12`). That path preserves the rendered VCS refs and passes each segment to the
multi-prompt launcher (`src/sase/agent/launch_cwd_bead_work.py:49`). The multi-prompt launcher then resolves VCS context
per segment rather than once for the whole bundle (`src/sase/agent/multi_prompt_launcher.py:328`,
`src/sase/agent/multi_prompt_vcs.py:81`).

### How phase commits are created

The spawned agent does not manually commit during its first response. The VCS xprompt/rollover path sets commit
environment, and the post-completion finalizer enforces it when the worktree is dirty:

- `#commit` sets `SASE_COMMIT_METHOD=create_commit` (`src/sase/xprompts/commit.yml:4`).
- `#pr` sets `SASE_COMMIT_METHOD=create_pull_request`, `SASE_PR_NAME`, `SASE_PR_STATUS`, and `SASE_BUG_ID`
  (`src/sase/xprompts/pr.yml:17`).
- `build_commit_details()` reads `SASE_COMMIT_METHOD` and `SASE_BEAD_ID` and builds the follow-up instruction
  (`src/sase/commit_instructions.py:42`, `src/sase/commit_instructions.py:106`).
- For PR mode, `build_name_instruction_text()` forces a named PR/branch payload
  (`src/sase/commit_instructions.py:76`).
- `run_commit_finalizer()` detects dirty work after the agent returns and invokes the model with the commit follow-up
  until the workspace is clean or max passes are exhausted (`src/sase/llm_provider/commit_finalizer.py:126`).

`docs/commit_workflows.md` documents the downstream semantics: `#commit` creates and pushes a git commit on the current
branch (`docs/commit_workflows.md:233`), while `#pr` creates a new branch, commits, pushes, and creates a PR
(`docs/commit_workflows.md:271`).

So the direct-to-master behavior is not caused by `sase bead work` itself calling `git commit` for each phase. It is
caused by normal epic phase segments being rendered against the project ref with normal commit mode. The agent finalizer
then closes the phase bead and runs the commit skill, which pushes a normal commit to the branch backing that project
workspace.

### Launch-state commit is separate from phase commits

After agents launch, `commit_successful_work_launch()` commits the parent process's bead-state mutation and usually
pushes it (`src/sase/bead/cli_work_commit.py:38`). The underlying commit stages only bead-state files and uses the
subject `chore: mark bead work launched for <id>` with `TYPE=bead_work`
(`src/sase/bead/sync.py:49`, `src/sase/bead/sync.py:93`). The default config is `bead.push_after_commit: true`
(`src/sase/default_config.yml:338`).

This launch-state commit is not a phase work commit. It records `is_ready_to_work` and preclaim state. For a strict
"one commit per phase plus one land commit" PR history, this launch-state commit either needs to disappear from the
final PR stack or become local-only operational state.

## Recent Instances

### `sase-56`

Recent visible history shows the current shape:

| Time | Commit | Subject |
| --- | --- | --- |
| 2026-06-23 18:43 | `4c2f1d630` | `chore: mark bead work launched for sase-56` |
| 2026-06-23 19:21 | `4b224219c` | `feat(directives)!: add %tale directive and repurpose %plan for plan auto-approval (sase-56.1)` |
| 2026-06-23 19:38 | `b44dda18d` | `feat(ace): add Auto-Approve menu modal and rewire approve keymap (sase-56.2)` |
| 2026-06-23 20:01 | `52cbe00d5` | `feat(ace): polish auto-approve presentation in agent list, footer, and help (sase-56.3)` |
| 2026-06-23 20:07 | `f3144e633` | `chore: Add SDD prompt and plan for sase_56_completion (sase-56)` |
| 2026-06-23 20:25 | `d605ae511` | `docs(ace): update auto-approve docs for the Auto-Approve menu (sase-56)` |

The `sase-56` chat list shows the launch source and phase prompts:

- The bead creation run was `%model:codex/gpt-5.5 #gh:sase #bd/new_epic:sdd/epics/202606/auto_approve_menu_and_tale_directive.md`.
- Phase prompts were `#gh:sase %name:sase-56.1 ...`, `#gh:sase %name:sase-56.2 ... %w:sase-56.1`, and
  `#gh:sase %name:sase-56.3 ... %w:sase-56.1,sase-56.2`.
- The land prompt was `#gh:sase %name:sase-56 %group:sase-56 ... %w:sase-56.1,sase-56.2,sase-56.3 ...`.

There was no `#pr` in these prompt snippets. `sase changespec search 'sase-56' -f markdown` returned no matching
ChangeSpecs.

`sase bead search 'sase-56' --format full` shows each phase closed with assignee set to its phase agent name, and the
parent epic closed. The bead notes contain `COMMIT:` entries, but for this run they do not exactly match the current
visible commit hashes, which means landing verification should search commits by bead ID and ChangeSpec metadata rather
than relying only on note hashes.

The `sase-56.1` phase response also showed the normal direct commit workflow in practice: the phase agent closed
`sase-56.1`, encountered an `origin/master` sync conflict because the remote advanced, fast-forwarded/reapplied its work,
then committed and pushed. That is expected for normal `#gh:sase` phase work, but it is exactly the contention we do not
want on `master`.

### `sase-55`

The same pattern appears for `sase-55`:

| Time | Commit | Subject |
| --- | --- | --- |
| 2026-06-23 11:51 | `c40682a86` | `chore: mark bead work launched for sase-55` |
| 2026-06-23 12:22 | `9b5a715f2` | `feat(xprompt): parse reasoning-effort levels in directives (sase-55.1)` |
| 2026-06-23 12:38 | `88bc7f126` | `feat(llm_provider): add default_effort config field (sase-55.2)` |
| 2026-06-23 13:01 | `b979c54bb` | `test(core): cover model@effort suffix stripping in agent-launch fanout (sase-55.5)` |
| 2026-06-23 13:10 | `7535d98b7` | `feat(llm_provider): translate reasoning effort into per-run CLI args (sase-55.3)` |
| 2026-06-23 13:22 | `85ebbe673` | `docs: document reasoning-effort directive and default_effort config (sase-55.6)` |
| 2026-06-23 13:53 | `d6b9ebe1b` | `feat(ace): persist and display reasoning effort uniformly (sase-55.4)` |

The `sase-55` chat prompts were likewise `#gh:sase` phase prompts with `%name`, `%group`, `%model:worker`, `%approve`,
and dependency `%w` directives. There was no PR context in the phase prompts.

### `sase-54`

`sase-54` also used the same launch-state commit plus direct phase commits:

| Time | Commit | Subject |
| --- | --- | --- |
| 2026-06-23 08:43 | `01625dba6` | `chore: mark bead work launched for sase-54` |
| 2026-06-23 09:16 | `8b1b5b9ab` | `chore(beads): close sase-54.1 phase 1 rust config backend` |
| 2026-06-23 09:24 | `9a3230396` | `feat(tui): add Config Center modal and migrate XPrompt Browser (sase-54.3)` |
| 2026-06-23 10:06 | `618c27537` | `feat(config): add Python config backend and write execution (sase-54.2)` |
| 2026-06-23 10:38 | `8792e87dc` | `feat(config): add read-only config browser to Config Center (sase-54.4)` |
| 2026-06-23 11:35 | `710d8a104` | `feat(config): add edit, validate, and write to Config Center (sase-54.5)` |
| 2026-06-23 11:53 | `f21ce64f7` | `chore(beads): close sase-54` |

## What Already Exists for PR-Backed Epics

There is already a partial ChangeSpec-backed epic mode:

- The bead data model stores `changespec_name` and `changespec_bug_id`.
- `sase bead create` can attach those fields to a plan bead.
- `bd/new_epic` passes `-c/--changespec` and `-b/--bug-id` only when the xprompt caller supplies that metadata
  (`src/sase/default_config.yml:390`, `src/sase/default_config.yml:416`).
- `sase bead work` detects existing `issue.changespec_name` and renders a `#pr` first phase plus ChangeSpec-targeted
  later phase/land segments.

That means the migration should not invent a second PR concept. The existing ChangeSpec field should become the durable
epic PR identity.

However, this existing path is not sufficient as-is:

1. It is opt-in at epic creation. Normal epics have no `changespec_name`, so they render project-ref prompts and commit
   directly to the project branch.
2. The launch-state commit still commits/pushes from the parent workspace after launch. If the parent workspace is on
   `master`, that still creates a `master` bookkeeping commit.
3. The first phase lazily creates the PR. If an epic has more than one independent root phase, later root phases could be
   rendered against the ChangeSpec ref before the first phase has created the branch/PR.
4. Multiple phase agents committing concurrently to one PR branch will create branch-stack contention. Today's direct
   master flow already sees agents resolving `origin/master` races; putting every phase onto one branch makes that
   contention part of the epic's own commit stack.
5. The final PR history target has no room for a separate `chore: mark bead work launched` commit.

## Migration Options

### Option A: Keep ChangeSpec PR mode opt-in and document it

This is the smallest change: tell users to create epics with `--changespec` or `#bd/new_epic(..., changespec=...)`.

This does not meet the target. It leaves normal epics direct-to-master, leaves the launch-state commit behavior
unchanged, and does not handle multi-root phase/branch-order issues.

### Option B: Make existing ChangeSpec rendering the default

On `sase bead work <epic>`, if the epic has no `changespec_name`, generate a stable epic PR name, store it on the epic
bead, and render as ChangeSpec-backed work.

This reuses the right primitives and is the best foundation, but it needs additional branch/order and launch-state
changes before it satisfies the requested final shape.

### Option C: Add an epic branch coordinator

Phase agents could work in parallel on isolated workspaces or proposal branches, then a coordinator could apply each
phase result sequentially to the epic PR branch, producing one commit per phase and one final land commit.

This preserves parallel work and produces the cleanest branch stack, but it is a larger system: it needs patch capture,
conflict handling, deterministic commit ordering, and agent result validation. It is the right long-term shape if phase
parallelism is essential, but it is heavier than needed for a first migration.

## Recommended Solution

Implement PR-backed epic work by promoting the existing ChangeSpec path to the default for epic `sase bead work`, but
make the first version intentionally serialized and remove the permanent launch-state commit from the final PR history.

Concretely:

1. Add an epic PR mode for `sase bead work`, defaulting to `pr` for Git/GitHub project work and keeping a legacy escape
   hatch such as `--direct` or `bead.epic_work_mode: direct`.
2. When PR mode starts, derive a stable ChangeSpec/branch name from the epic ID and title and reuse it on retries. Use
   the existing `changespec_name` and `changespec_bug_id` fields as the durable PR identity, but persist newly generated
   metadata on the PR branch rather than on `master`; the first PR-creating phase commit can include the epic bead
   metadata update along with that phase's closeout.
3. Render the first phase with `#pr(name=<epic_pr_name>, status=draft)` and all later phase plus land segments with
   `#<vcs>:<epic_pr_name>`. Do not add `#pr` to every phase.
4. In PR mode, add a synthetic commit-order wait chain across phases in deterministic topological order, even when the
   bead DAG would allow a wider wave. This ensures the first phase creates the PR branch before any later phase resolves
   it and prevents concurrent agents from racing to push the same branch. It sacrifices phase parallelism, but it is the
   simplest reliable path to a clean one-commit-per-phase branch stack.
5. Stop pushing the parent launch-state commit to `master` in PR mode. The cleanest implementation is to move launch
   preclaim/ready bookkeeping out of permanent git history for PR-backed epics and into local launch metadata or an
   explicitly temporary overlay. If any launch metadata must become durable, fold it into the first phase commit or the
   land commit on the PR branch. The final PR should contain phase-close commits and the land-close commit, not
   `chore: mark bead work launched for <epic>`.
6. Have each phase agent close only its phase bead and commit normally on the epic branch after the first phase has
   created the PR. Each commit message should include its phase bead ID, preserving the current land-agent verification
   model.
7. Have the land agent run on the same epic branch, verify commits by bead ID and ChangeSpec metadata, close the epic
   bead, update the plan frontmatter to `status: done`, run the expected validation, and create the final epic commit.
   Extend the land path to mark the PR ready or update the PR description/checklist once the final commit is pushed.
8. Add tests for default PR rendering, retry with an existing stored ChangeSpec, no direct `master` launch-state push in
   PR mode, synthetic wait serialization, and the legacy direct mode.

This approach keeps the migration small enough to implement with the current xprompt, ChangeSpec, and finalizer
machinery, while satisfying the important behavioral goal: normal epic work no longer lands phase commits directly on
`master`; it produces one reviewable PR per epic with a readable phase-by-phase commit stack and a final land commit.
