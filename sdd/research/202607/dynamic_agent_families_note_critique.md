---
create_time: 2026-07-05
updated_time: 2026-07-05
status: research
---

# Critique: "Dynamic Agent Families" Project Note (`~/bob/sase_dyn_agent_fam.md`)

## Scope

This reviews the WIP Obsidian project note `sase_dyn_agent_fam.md` (created
2026-06-18) and answers three questions: is the idea good, what should change,
and what must be answered before implementation.

Inputs verified against the current codebase and prior research:

- The note itself (requirements sketch, four open tasks, five crossed-out
  ideas).
- `sdd/research/202606/dynamic_agent_families_xprompt_workflows_consolidated.md`
  (2026-06-17) — family state-machine architecture recommendation.
- `sdd/research/202606/agent_launch_ux_family_types_consolidated.md`
  (2026-06-04) — agent-initiated launches, `/sase_run`, `LaunchApproval`.
- `sdd/research/202606/with_q_and_a_xprompt_consolidated.md` (2026-06-18) —
  `#with_q_and_a` parity design.
- Code exploration of the directive parser, xprompt/workflow system, launch
  paths, plan-chain family helpers, dismissal state, and the ace Agents-tab
  row model (references inline below).

## The Proposal, Reconstructed

The note is terse, so this is the reading the critique is based on:

1. A launch-time directive `%n(foo, bar)` (extending the existing `%name`/`%n`
   directive) declares the new agent as a member of existing agent `foo`'s
   family (i.e. it becomes `foo--bar`). Launch fails loudly if `foo` does not
   exist or has been dismissed from the Agents tab.
2. Variants: `%n(foo, code, run_status="WORKING TALE", done_status="TALE DONE")`
   for coder-type members with custom status labels, and `%n(foo, @)` for
   feedback/Q&A members (`@` presumably meaning "auto-allocate the next
   numeric suffix", matching the existing `"--plan-@"` template in
   `src/sase/axe/run_agent_exec_plan.py:182`).
3. New `#with_feedback` and `#with_q_and_a` xprompts assemble the prompt
   bodies for those family members.
4. Xprompt support for running shell commands, possibly via a `%!` syntax.
5. Agents-tab work: normalize root rows with child rows, support "waiting"
   agent child rows, and support python/bash commands as root rows.

Rejected ideas (crossed out in the note): naming-convention-triggered family
membership (`foo--bar` in `%name` value), a `models` config field with
`if_default: @coder`, model-directive kwargs per phase, plan-proposed hooks,
and an agent-termination/status/notify requirement.

## Verdict

**Yes, the core idea is good — with a narrowed v1.** Reifying what the runner
already does internally (allocate a family child suffix, build a follow-up
prompt from feedback/Q&A, write family metadata) into explicit user-facing
primitives is the right direction, and it is the same direction both June
research memos endorse. Today only the runner's marker-driven handoff can
extend a family; a user who wants to manually add a feedback round, a
reviewer, or a follow-up coder to an existing (possibly finished) agent has no
supported path. `%n(parent, suffix)` + prompt-assembly xprompts is a clean,
explicit way to provide one.

The note also makes two demonstrably correct calls:

- **Rejecting the naming-convention trigger** (crossed-out item). Making `--`
  in a `%name` value silently change launch behavior is exactly the "hidden
  coupling" failure mode the 2026-06-04 memo warns against ("family type
  selection is an explicit launch property... not hidden behavior found during
  ordinary xprompt expansion"). An explicit directive with loud failure is
  right.
- **Rejecting the `models`/`if_default` config idea.** `model_aliases` with
  implicit `@coder`/`@default` role aliases already covers this
  (`src/sase/config/sase.schema.json:694`, `src/sase/xprompt/model_completion.py`).

However, three of the five live requirements need significant modification
(custom status strings, `%!` shell support, and the xprompts-"trigger"-launches
phrasing), and the note is missing its Requirements section — the actual user
stories — which several design decisions depend on.

## Verified Current State (what the design lands on)

- **"Family" already means two things.** Plan-chain families use `--`
  (`AGENT_FAMILY_SEPARATOR = "--"`, `src/sase/plan_chain.py:9`, with reserved
  role suffixes `--plan`, `--q`, `--code`, `--epic`, `--legend`, `--commit`
  and legacy `.`/`-` spellings). Dotted names (`foo.bar`) are a *separate* TUI
  concept — hoods/neighbors (`src/sase/ace/tui/models/agent_hoods.py`). The
  repo glossary currently describes families as dot-separated, which matches
  hoods, not `plan_chain.py`. The note's `%n(foo, bar)` → `foo--bar` clearly
  targets plan-chain families; the design doc must say so explicitly and the
  glossary should be reconciled.
- **`%name`/`%n` exists but is single-valued.** The directive table lives in
  `src/sase/xprompt/_directive_types.py:20-31` (aliases at `:63-72`).
  `%name(foo, bar)` today keeps only the first positional; extra positionals
  and *all* keyword args are silently dropped for `%name`
  (`src/sase/xprompt/directives.py:359-380`). The proposed forms are new
  syntax layered onto an existing directive, with a small backward-compat
  surface and a real silent-typo hazard unless kwargs become strictly
  validated.
- **No mechanism exists for attaching a launch to another agent's family.**
  The only family extension today is the runner's in-process handoff
  (`allocate_agent_family_child_suffix`, `create_followup_artifacts` in
  `src/sase/axe/run_agent_exec_plan.py:169-229`). The nearest "program
  launches an agent" precedent is the axe chop runner
  (`src/sase/axe/chop_runner_agent.py:105`). Low-level launch is already
  Rust-backed (`prepare_agent_launch`/`spawn_prepared_agent_process`/
  `plan_agent_launch_fanout` in `src/sase/core/agent_launch_facade.py`).
- **No name-keyed "exists and undismissed" API.** Dismissal is keyed by
  `(AgentType, cl_name, raw_suffix)` in `~/.sase/dismissed_agents.json`
  (`src/sase/ace/dismissed_agents.py`), with revive bundles alongside. The
  constraint check the note wants must be built, and agent names are not
  unique across time/projects, so "an agent named foo MUST exist" needs a
  resolution rule.
- **Status strings are closed sets.** `WORKING TALE`, `TALE DONE`, etc. are
  centralized in `src/sase/agent/status_buckets.py` and consumed by hard-coded
  bucket/terminal/dismissable/needs-input sets there and in
  `src/sase/ace/tui/models/agent_status.py`. There is no per-agent status
  label storage. Free-form `run_status=`/`done_status=` strings would fall out
  of every classification (filtering, dismissability, mobile wire).
- **Xprompt workflows already run shell.** `bash` is an existing workflow step
  type (`src/sase/xprompt/workflow_loader_parse.py:88-108`,
  `workflow.schema.json`), executed via
  `workflow_executor_steps_script.py`, and bash/python steps already render as
  child rows in the TUI. `%!` is unclaimed, but `#!` is the *standalone
  xprompt marker* (`src/sase/xprompt/_parsing_references.py:47-51`) — a
  near-collision. The `%` directive grammar also only matches word-character
  names, so `%!` needs parser changes, not just a new table entry.
- **The TUI row split is real.** Workflow children hang off `parent_workflow`
  + `step_type`; follow-up agent children hang off `parent_timestamp` only
  (`src/sase/ace/tui/models/agent.py:116-138,528-530`,
  `_agent_status_apply.py:269-274`). `WAITING` is a root-only, pre-run state
  driven by `waiting.json` from `%wait` (`src/sase/axe/run_agent_wait.py`);
  no pre-launch waiting *child* rows exist. Bash/python rows can only be
  workflow children. The note's normalization item names a genuine gap.
- **`#with_q_and_a` is already designed;** the 2026-06-18 memo specifies an
  embeddable YAML workflow with a hidden python step calling a shared
  `assemble_question_followup_prompt()` helper for byte parity with
  `handle_questions_marker()` — and explicitly says the xprompt must NOT
  launch agents itself. `#with_feedback` has no equivalent memo yet.
  `#research_swarm` (referenced by a task in the note) was removed as a
  packaged xprompt in commit `bc6a9cc87` ("feat!: remove packaged research
  xprompts") — that task needs a user-level xprompt or an update.

## Critique and Recommended Modifications

### 1. Keep `%n(parent, suffix)`, but tighten its contract

The directive is the right trigger. Modifications:

- **Strict validation.** With family syntax enabled, `%name`/`%n` must reject
  unknown keyword args and >2 positionals loudly. Today's parser silently
  drops both — a misspelled `done_stats=` would otherwise vanish. This also
  contains the backward-compat change: `%name(a, b)` currently means "name =
  a"; decide whether the two-positional form is an error without family
  context or always means family attach.
- **Reserved-suffix policy.** `bar` must be validated against reserved role
  suffixes (`plan`, `q`, `code`, `epic`, `legend`, `commit`), numeric
  feedback-round forms, and legacy `.`/`-` spellings, or explicitly map onto
  them (e.g. `%n(foo, code)` *is* a code-role member). Collision behavior for
  an existing `foo--bar` needs a rule (fail vs. auto-number). The `@`
  placeholder should reuse the existing suffix-template semantics from
  `allocate_agent_family_child_suffix`.
- **Metadata compatibility with the bigger architecture.** The 2026-06-17 memo
  recommends a family state-machine (roles/gates/events) as the eventual
  shape. `%n` should be built as thin sugar over the existing `plan_chain.py`
  helpers and write the same metadata (`agent_family`, `agent_family_role`,
  `role_suffix`, `plan_chain_root`) so a later family evaluator can interpret
  manually-attached members without migration. Do not invent a parallel
  lineage scheme.
- **Surface policy.** Prompts arrive from CLI, TUI, Telegram, and mobile. A
  remote Telegram message containing `%n(...)` grafts an agent onto an
  existing family — that should compose with the `LaunchApproval` design from
  the 2026-06-04 memo rather than bypass it.

### 2. Define the parent constraint precisely (it is currently underspecified)

"`foo` MUST exist and MUST NOT be dismissed" hides most of the design:

- **Resolution rule.** Names recur across time and projects. Propose: newest
  matching root in the current project's scan scope; error if ambiguous or
  absent. (The artifact index queries in `agent_scan_facade.py` can back
  this.)
- **A name-keyed visibility helper must be built** — membership in
  `load_dismissed_agents()` keyed by identity tuple, plus panel-visibility
  logic. Put the pure classification part behind the Rust facade if mobile or
  other frontends will ever need the same check (rust-core boundary litmus
  test).
- **Dismissed-with-bundle parents.** Revive bundles exist
  (`has_dismissed_bundle`). Decide: hard fail (simplest, matches the note) or
  offer revive. Recommend hard fail in v1 with an error message that names the
  revive path.
- **TOCTOU.** The user can dismiss `foo` between check and spawn. The check
  should happen inside the launch-preparation step (ideally the Rust
  `prepare_agent_launch` path), not only at prompt parse time, and the failure
  must surface on the launching surface (CLI stderr, TUI toast, Telegram
  reply) — "good logging" alone is not enough for remote surfaces.
- **Running parents.** Decide whether `%n` may target a still-running `foo`.
  If yes, that implies a queued/waiting child (see §5) and interacts with
  `%wait(for=foo)`; if no, v1 is simpler: parent must be in a terminal,
  undismissed state.

### 3. Replace free-form `run_status`/`done_status` with role-derived or enum statuses

Arbitrary status strings break the closed sets in `status_buckets.py` and
`agent_status.py` (bucketing, terminal detection, dismissability,
needs-input), and the status vocabulary is mirrored in the sase-core wire for
mobile/TUI consumers. Two acceptable shapes:

- **v1 (recommended):** drop the kwargs; derive statuses from the member's
  role (`%n(foo, code)` gets the existing code-phase statuses — the note's own
  example values `WORKING TALE`/`TALE DONE` are already exactly the built-in
  tale statuses, suggesting the real need is role selection, not free text).
- **v2:** a semantic-status + display-label split, where the semantic value
  stays in the closed enum and a cosmetic label overrides rendering only. This
  needs sase-core wire support and is what the 2026-06-17 memo's "TUI status
  overrides" edge case anticipates.

### 4. Clarify the xprompt/launch division of labor

The note says the new xprompts should "trigger corresponding family member
agent launches". Keep the June `#with_q_and_a` memo's boundary instead: the
**directive (or runner) launches; the xprompt only assembles the prompt
body.** So the composed usage is
`%n(foo, @) #with_q_and_a(qa_file=...):: <base prompt>`. Making prompt-part
xprompts spawn agents would reproduce suffix allocation, artifact mutation,
and notification bookkeeping outside the runner — the exact anti-pattern that
memo rejects.

Additionally:

- Implement `#with_q_and_a` per the existing memo (shared
  `assemble_question_followup_prompt()`; `qa_file` contract; parity tests).
- Write the missing parity spec for `#with_feedback` first: its target is the
  feedback-replan prompt construction (accumulated feedback bullets) in the
  plan-marker path, and it should share the runner's helper the same way. The
  feedback prompt-assembly code needs to be extracted into a public helper
  just as the Q&A renderer was.

### 5. Do the TUI normalization as its own tracked project

The gap is real (two child-attachment mechanisms; no pre-launch waiting child
rows; bash/python only as workflow children), but it is a sizable model/loader
refactor with its own risks:

- Unifying `parent_workflow` children and `parent_timestamp` followups touches
  ordering, grouping, status mirroring, and dismissal bundles.
- New row sources must respect the TUI performance rules (no added sync I/O in
  loaders — read `memory/tui_perf.md` before implementation).
- New linkage/marker fields ride the Rust scan wire, so sase-core changes are
  in scope.
- "Waiting agent child rows" only becomes a requirement if `%n` may target
  running parents — which is why §2's decision should precede this work.
- "Python/bash as root rows" is the least motivated item in the note: a
  single-step workflow already gives a bash/python root today (the root
  workflow row). Recommend cutting it unless a concrete use case exists.

### 6. Drop or radically constrain `%!`

Shell-in-xprompt already exists via YAML `bash` steps. Inline `%!` adds:

- **A security regression path.** Xprompt expansion is currently pure;
  `sase xprompt expand`, TUI previews, editor tooling, and multi-agent
  splitting all assume it. Inline shell makes expansion side-effectful, and if
  honored in raw prompt text it gives any remote launch surface (Telegram,
  mobile) command execution on the host. The 2026-06-17 memo's guidance
  applies: curated side-effect ids, not arbitrary shell from declarative
  surfaces.
- **Syntax confusion** with the `#!` standalone xprompt marker, plus a
  directive-grammar change (`%` names are word-characters only).

If inline ergonomics are truly wanted, make `%!` pure sugar that desugars to a
hidden `bash` workflow step (so it executes only where workflow steps execute,
never during preview/expand), restrict it to file-backed local xprompt
definitions (never raw prompt text), and pick a spelling that is not one
character away from `#!`. Otherwise cut it from this project — it is
orthogonal to dynamic families.

### 7. Fill in the Requirements section before anything else

The note's first open task (write Requirements) is the right next step, and
several open questions below cannot be answered without it. The one-line user
stories that would most sharpen the design: "As a user, I want to add a
feedback round to a finished agent from the TUI/Telegram", "As a user, I want
to launch a reviewer beside a coder in the same family", "As an agent, I want
to spawn my own family member" (this last one changes everything — it pulls in
the `/sase_run`/`LaunchApproval` design and should probably be out of scope
for v1).

Also update the stale task: `#research_swarm` no longer ships (removed by
"feat!: remove packaged research xprompts"), so the critique-swarm task needs
a user-level xprompt or a different mechanism.

## Open Questions Before Implementation

1. **Which family concept is "dynamic"?** Plan-chain `--` families only
   (recommended), or also dotted hoods? Related: reconcile the glossary
   (dot-separated) with `plan_chain.py` (`--`).
2. **What are the driving user stories?** Manual feedback/Q&A rounds on
   finished agents? Arbitrary named members (reviewer, tester)? Agent-initiated
   member spawning? Each pulls the design differently (the last requires
   launch-approval integration).
3. **Parent resolution:** what scope (project? all projects?), what happens on
   name ambiguity, and may the parent be still running?
4. **Inheritance contract:** which of model/provider (worker-lane resolution),
   workspace, `SASE_PLAN`, chat history (`#fork:<parent>`), and artifacts
   lineage come from the parent vs. the launch site? (The runner's internal
   handoff inherits all of these; `%n` from a fresh `sase run` must define
   each.)
5. **Suffix semantics:** exact meaning of `@`; interaction with reserved role
   suffixes; collision policy for an existing `foo--bar`; do custom suffixes
   get an `agent_family_role`, and if so which?
6. **Status model:** role-derived statuses in v1, or is a label/semantic split
   required immediately (and thus sase-core wire changes)?
7. **Remote surfaces:** is `%n` honored in Telegram/mobile prompts, and how
   does it compose with the planned `LaunchApproval` gate?
8. **Failure UX:** where exactly does the loud failure surface per launch
   surface, and does it happen at parse time, preparation time, or both?
9. **Is `%!` in scope at all**, and if yes, which execution contexts run it
   and what is the per-surface trust policy?
10. **Does `#with_feedback` have a byte-parity target** (the feedback-replan
    prompt), and can the runner be refactored to share its assembly helper the
    way the Q&A memo prescribes?
11. **TUI normalization sequencing:** prerequisite for `%n` (only if running
    parents/queued children are in v1) or an independent follow-up project?
12. **Rust-core split:** which pieces (parent existence/visibility
    classification, suffix validation/allocation, family metadata) go behind
    `sase_core_rs` in v1, given launch preparation is already Rust-backed?
13. **Timing:** this lands deep in runner/TUI/core code while the public
    launch-readiness work (202607 blog audit) is in flight — should v1 wait or
    be staged behind it?

## Suggested v1 Slice (if the answers come back favorable)

1. Write the Requirements section; decide questions 1-5.
2. Extract the feedback-prompt assembly helper; implement `#with_q_and_a` and
   `#with_feedback` per the existing memo pattern (pure prompt assembly,
   parity tests). This is independently useful even if `%n` changes shape.
3. Implement `%n(parent, suffix)` for terminal, undismissed, unambiguous
   parents only: strict kwarg/positional validation, reserved-suffix rules,
   plan-chain-compatible metadata, name-keyed visibility helper, failure
   surfaced on the launching surface.
4. Defer: custom status strings (use role-derived), running-parent/waiting
   child rows, python/bash root rows, `%!`, and agent-initiated `%n` (needs
   `LaunchApproval`).
5. Fold the TUI root/child normalization into its own bead with
   `memory/tui_perf.md` review and sase-core wire planning.

## Key References

- The note: `~/bob/sase_dyn_agent_fam.md`.
- Prior research:
  `sdd/research/202606/dynamic_agent_families_xprompt_workflows_consolidated.md`,
  `sdd/research/202606/agent_launch_ux_family_types_consolidated.md`,
  `sdd/research/202606/with_q_and_a_xprompt_consolidated.md`,
  `sdd/research/202607/blog_launch_xprompts_agents_tui_consolidated.md`.
- Directives: `src/sase/xprompt/_directive_types.py`,
  `src/sase/xprompt/directives.py`, `src/sase/xprompt/_directive_alt.py`.
- Families: `src/sase/plan_chain.py`, `src/sase/agent/names/_lookup.py`,
  `src/sase/ace/tui/models/agent_hoods.py`.
- Launch: `src/sase/agent/launch_cwd.py`, `src/sase/agent/launch_spawn.py`,
  `src/sase/core/agent_launch_facade.py`, `src/sase/axe/chop_runner_agent.py`.
- Handoff/status: `src/sase/axe/run_agent_exec_plan.py`,
  `src/sase/axe/run_agent_exec_questions.py`,
  `src/sase/agent/status_buckets.py`,
  `src/sase/ace/tui/models/agent_status.py`.
- Dismissal: `src/sase/ace/dismissed_agents.py`,
  `src/sase/ace/tui/actions/agents/_dismissing.py`.
- TUI rows: `src/sase/ace/tui/models/agent.py`,
  `src/sase/ace/tui/models/_agent_status_apply.py`,
  `src/sase/ace/tui/models/_loaders/_workflow_step_loaders.py`,
  `src/sase/axe/run_agent_wait.py`.
- Xprompt steps: `src/sase/xprompt/workflow_loader_parse.py`,
  `src/sase/xprompt/_parsing_references.py`,
  `src/sase/xprompts/workflow.schema.json`.
