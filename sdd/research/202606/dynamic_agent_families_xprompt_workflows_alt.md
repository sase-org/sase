# Research: Dynamic Agent Families via XPrompt Workflow YAML

**Date:** 2026-06-17
**Author:** research agent (for Bryan)
**Status:** research / critique — no code changes

## The proposal (as I understand it)

> Implement **dynamic agent families** using xprompt workflow YAML files. Every
> command that is an xprompt *skill* that **kills an agent and surfaces a request
> to the user in the TUI** would get its own xprompt workflow YAML file.

Concretely, today exactly **two** skills fit "kills an agent + surfaces a
request": `/sase_plan` (→ `sase plan propose`) and `/sase_questions`
(→ `sase questions`). The "every" is forward-looking — the value of the idea is
proportional to how many *more* such interactions you expect to add (review
gates, commit approvals, "pick one of N", mentor sign-off, etc.).

The intended payoff is twofold and worth separating:

1. **Extensibility / DRY** — today each interaction is a bespoke state machine in
   the runner loop. Adding a third requires re-writing all of it. The user wants
   adding interaction #3, #4, #5 to be cheap (ideally: write a YAML).
2. **Declarative families** — the *family* that unfolds after the gate
   (planner → coder → commit; questioner → resumed agent) becomes data you can
   read, diff, and customize, instead of scattered imperative Python.

**My headline verdict:** the *goal* is sound and the codebase is genuinely
crying out for it (the plan/questions handlers are ~1,500 lines of nearly-
parallel bespoke logic). But the *literal mechanism* — "one workflow YAML per
skill, executed by the existing `WorkflowExecutor` HITL path" — has several
critical mismatches that would be **regressions** if shipped as-is. The fix is
not to abandon the idea but to (a) pick the right unit of YAML (the *family/
chain*, not the *skill*), (b) keep the skill as a *reactive trigger* that
*promotes* into a workflow rather than being launched up-front, and (c) close
~5 capability gaps in the workflow/HITL engine first. Details below.

---

## Two things named "family" — disambiguate first

This is the single most important clarification, because the codebase has **two
distinct "family" concepts** and the proposal only touches one of them.

| | **Plan-chain family** (in scope) | **Dotted-sibling family** (probably not) |
|---|---|---|
| Separator | `--` (`AGENT_FAMILY_SEPARATOR`) | `.` |
| Shape | **Sequential roles**: `foo--plan` → `foo--q` → `foo--code` → `foo--commit` | **Parallel siblings**: `foo`, `foo.1`, `foo.2` |
| Created by | the kill-respawn handlers (`run_agent_exec_plan*.py`, `run_agent_exec_questions.py`) | multi-agent xprompt split on `---` (`multi_agent_xprompt.py`, `multi_prompt_launcher.py`) |
| Defined in | `src/sase/plan_chain.py` (suffixes, `allocate_agent_family_child_suffix`) | `src/sase/agent/names/` (`reserve_repeat_name_base`) |
| TUI grouping | `agent_groups/_keys.py` understands both | same module |

"Dynamic agent families using xprompt workflow YAML" maps onto the **plan-chain
family** — sequential, role-suffixed handoffs gated by a user decision. The rest
of this doc assumes that. (If you actually meant unifying *both* concepts under
workflows, that's a much larger swing and should be its own discussion — flagged
in Open Questions.)

---

## How it works today: two parallel, overlapping mechanisms

### Mechanism A — the reactive skill-based "kill + respawn" family engine

This is what `/sase_plan` and `/sase_questions` actually use today. The flow:

1. A **running agent** (launched from a free-form user prompt — *not* a
   workflow) decides mid-run to invoke the skill, e.g. `sase plan propose
   plan.md`.
2. The command handler writes a **marker file** into `SASE_ARTIFACTS_DIR`
   (`.sase_plan_pending` / `.sase_questions_pending`) and then **kills the agent
   runner's whole process group** (`kill_agent_runner_group`,
   `src/sase/main/utils.py:51`). This tears down the expensive `claude`/LLM
   subprocess. (`plan_propose_handler.py:88`, `questions_command_handler.py:95`.)
3. The runner installed a **soft** SIGTERM handler (`runner_utils.py`), so it
   doesn't die — it notices `was_killed()`, reads-and-deletes the marker, and
   dispatches (`run_agent_exec.py` → `handle_plan_marker` /
   `handle_questions_marker`).
4. The handler creates a **notification** (`PlanApproval` / `UserQuestion`),
   mirrors it into `pending_actions.json`, and **polls a response file**
   (`plan_response.json` / `question_response.json`) with `while True` — **no
   timeout** (`_plan_utils.py:200`).
5. On a response, it **spawns the next family member** with a freshly
   *reconstructed* prompt and a role suffix (`--code`, `--q`, `--epic`, …),
   allocating the family child name (`allocate_agent_family_child_suffix`), then
   the current runner exits. **There is no persistent coordinator** — each phase
   is an independent process that spawns the next and dies.

Key properties of Mechanism A:
- **Reactive**: the family materializes because the *agent decided* to propose a
  plan. You cannot know at launch whether any given agent will do this.
- **Coordinator-free / crash-tolerant**: state lives in files + notifications,
  not in a long-lived process. The TUI re-derives "you still owe an answer"
  purely from on-disk markers (`DONE → PLAN` / `DONE → QUESTION` in
  `_agent_status_overrides.py`), so even if the polling process dies the request
  stays visible.
- **Rich, branchy approval**: plan approval actions are
  `approve | tale | epic | legend | commit | run | reject | feedback`, carrying
  `commit_plan` / `run_coder` booleans (`plan_approval_actions.py:15,108`). The
  *action chosen determines which family member spawns next* (coder vs
  epic-agent vs legend-agent vs commit-only vs nothing).
- **Sophisticated handoff**: model/runtime is derived from the planner's
  concrete provider/model (`_resolve_followup_model`,
  `run_agent_exec_plan_accept.py:93`); questions accumulate across *rounds*
  (`QARound`, merged Q&A re-appended to the prompt) — it's a self-loop, not a
  linear pipeline.
- **Reject = write response + kill** (the `telegram_plan_reject_kill`
  invariant); **feedback ≠ reject** (feedback respawns a replanner and keeps the
  family alive).

### Mechanism B — the declarative `WorkflowExecutor` + HITL

This is the machinery the proposal wants to lean on. A workflow YAML is a list of
typed steps (`agent` / `bash` / `python` / `prompt_part` / `parallel`) with
control flow (`if`, `for`, `repeat`, `while`, `join`, `finally`) and `hitl: true`
gates. Data model: `src/sase/xprompt/workflow_models.py`; executor:
`src/sase/xprompt/workflow_executor*.py`; schema:
`src/sase/xprompts/workflow.schema.json`.

How HITL works (`TUIHITLHandler.prompt`, `src/sase/xprompt/workflow_hitl.py`):
the executor runs the agent step to completion, then **the executor process
itself blocks**, writing `hitl_request.json`, sending a generic
`notify_hitl_request` notification, and polling for `hitl_response.json` for **up
to `_TUI_HITL_TIMEOUT = 3600` seconds (1 hour), after which it auto-rejects**.
HITL result actions are `accept | edit | reject | rerun | feedback`
(`workflow_executor_types.py:61`). The whole workflow runs inside **one
long-lived coordinator process** (`run_workflow_runner.py`) that holds the
workspace claim for the entire lifetime.

Key properties of Mechanism B:
- **Predetermined**: the steps are fixed when the workflow is launched.
- **Persistent coordinator**: one process runs all steps sequentially; if it
  dies mid-wait the workflow stalls (there's `workflow_state.json` for display
  and a stub for resume, but no automatic recovery — see
  `xprompt_workflow_best_practices.md`, "Temporal / durable execution" gap).
- **Generic, shallow HITL**: 1-hour timeout, 5 fixed actions, a single generic
  notification + modal.

### Side-by-side

| Axis | A: kill+respawn (plan/questions today) | B: WorkflowExecutor HITL |
|---|---|---|
| Trigger | **reactive** (agent decides mid-run) | **predetermined** (launched up-front) |
| Coordinator | **none** (chain of independent procs) | **one persistent process** |
| Crash during human gate | request stays visible; re-derived from markers | workflow stalls; manual resume |
| Wait timeout | **none** (`while True`) | **1 hour → auto-reject** |
| Approval actions | 8, with family-branch semantics | 5, generic |
| Per-frontend (Telegram) | bespoke `PlanApproval`/`UserQuestion` formatting + actions | generic HITL only |
| Model handoff | derived from planner's provider/model | static `%model` in template |
| Multi-round accumulation | yes (QARound merge loop) | only via `repeat:` + manual state |
| Durable "you owe an answer" | yes (`DONE→PLAN/QUESTION` re-derive) | no |

**The proposal is essentially "replace A with B (one YAML per skill)." The table
is the list of things you'd lose.** None are fatal, but each must be
deliberately addressed.

---

## The core architectural tension

Two mismatches sit underneath every edge case:

**1. Reactive trigger vs. predetermined workflow.** Plan/questions fire *because
the LLM chose to*, mid-conversation, inside an agent that the user launched with
a free-form prompt. A workflow's steps are fixed at launch. You cannot "launch
the plan workflow up front" for every agent, because you don't know which agents
will plan. So a naive "`/sase_plan` *is* a workflow you run" doesn't fit — the
planner has *already run* by the time the gate is needed.

**Resolution (recommended): reactive promotion.** Keep the skill as the reactive
trigger. When the agent invokes `sase plan propose`, the runner — instead of the
bespoke handler — *instantiates the family workflow starting at the approval
gate*, grafting the already-completed planner in as the family root and its plan
file as the gate's input. The YAML then declaratively describes *what unfolds
after the gate* (HITL → branch on action → spawn coder/epic/legend/commit). This
is faithful to "each kill+surface skill gets a workflow YAML": the YAML encodes
the *family*, the skill stays the *trigger*. The executor already has the
building block for "start from step N with step 1's output pre-supplied" — the
**implicit step-input** mechanism (`InputArg.is_step_input`,
`workflow_loader.py:206`).

**2. Coordinator-free chain vs. persistent coordinator.** This is the deeper one.
Today a plan chain survives machine reboots, deploys, OOM kills, and overnight
waits *because there is no single process that must stay alive*. Moving to
Mechanism B as-is makes the family depend on one long-lived `run_workflow_runner`
process surviving a multi-hour, human-gated lifecycle while holding a workspace
claim. That is a **robustness regression** unless you either (a) make workflow
gates coordinator-free (write request, *exit*, let a fresh process resume on
response — i.e. teach the executor Mechanism A's trick), or (b) add real durable
execution / resume (the Temporal-style gap called out in
`xprompt_workflow_best_practices.md`). I'd treat (a) as a prerequisite, not a
nice-to-have.

---

## Critical mismatches (regressions to fix before mapping plan→workflow)

These are the concrete things that would break if `/sase_plan` were ported onto
`WorkflowExecutor` HITL today:

1. **1-hour auto-reject.** Plans routinely wait overnight; plan approval has *no*
   timeout (`while True`). The workflow HITL hard-rejects at 1h. → Make HITL
   timeout configurable per gate, default unbounded (or very long), and make the
   timeout action configurable (reject vs hold).

2. **Approval action set + family branching.** `accept/reject/edit/feedback/
   rerun` cannot express `epic | legend | commit-only | tale | run`, each of
   which spawns a *different* downstream family member. → Extend `HITLResult`
   to carry a richer, skill-defined action set, and let the YAML branch on it
   (`if: "{{ gate.action == 'epic' }}"`). This couples the gate's UI vocabulary
   to the workflow's branch matrix — needs a clean contract.

3. **Notification + modal + Telegram parity.** Plan/questions use specific
   notification `action`s (`PlanApproval`, `UserQuestion`) that the TUI's rich
   modals *and* the Telegram formatter key on; generic HITL uses
   `notify_hitl_request` + a generic modal. A straight port loses the rich
   plan/question UX and breaks Telegram accept/reject. → The gate must be able to
   declare *which* notification kind / modal it raises, per frontend.

4. **Durable re-surfacing.** The `DONE→PLAN`/`DONE→QUESTION` re-derivation and
   the `pending_actions.json` mirror are what keep an unanswered request alive
   after a process dies. Generic HITL has none of this. → Either generalize the
   pending-action store to arbitrary gate kinds, or keep gates on the durable
   marker protocol.

5. **Model/runtime handoff + multi-round accumulation.** The planner→coder model
   derivation and the questions QARound accumulation are real behaviors, not
   incidental. → The render context for post-gate steps must receive the
   resolved provider/model and any accumulated Q&A; the questions "family" is a
   *loop with growing state*, which maps to `repeat:` only awkwardly.

---

## Edge cases you may not be considering

Beyond the five regressions above:

1. **Nested families.** A coder (spawned from a plan) can itself call
   `/sase_plan` or `/sase_questions`. Families nest arbitrarily. If the coder is
   now a *workflow step*, you get a workflow step that launches another
   workflow that surfaces HITL — runtime sub-workflow spawning, which
   `xprompt_workflow_best_practices.md` explicitly lists as a *missing*
   capability ("we have embedding but not runtime sub-workflow spawning"). Depth,
   naming, and TUI nesting all need answers.

2. **Two naming schemes collide in the TUI.** Workflow children are named
   `workflow-{base}-{step}` and rendered as a workflow tree; plan-chain children
   are `<base>--plan`/`--code` and rendered as a dotted/role family group
   (`agent_groups/_keys.py`). If plan chains *become* workflows, the clean
   family grouping in the Agents tab changes shape unless you reconcile the two.
   `appears_as_agent` (a single-visible-step workflow shown as one agent row)
   partially helps but won't cover a 3-member family.

3. **`%wait` / `@name` / `#fork` / resume resolution.** These resolve against
   the agent-family lookup (`agent/names/_lookup.py`). Any change to how families
   are named/created must keep these working.

4. **Auto-approval / headless / CI.** `get_auto_plan_approval_action` and
   `hitl_override` skip the gate in non-interactive contexts. The declarative
   gate needs a clean way to express "auto-approve with action X under policy Y."

5. **Reject-kill semantics must be preserved exactly.** Reject writes the
   response *and kills the agent*; feedback does *not* kill; approve keeps it
   alive (`telegram_plan_reject_kill.md`). A workflow "reject" currently *aborts
   the workflow* — you must ensure it kills the right process group and that
   "feedback" maps to "re-run the planner step" (which, encouragingly, the
   workflow `feedback` action already roughly does).

6. **Workflow discovery precedence = footgun.** Workflow YAMLs have a deep
   search-path precedence (CWD `./xprompts` > project > plugins > internal). A
   stray user-local `plan.yml` could silently *shadow the core plan chain*. These
   system families need namespacing/protection (e.g. a reserved `sase/` prefix or
   an "internal, non-overridable" flag).

7. **Generation/sync now spans THREE artifacts.** Today the CLI command + the
   `SKILL.md` source must stay in sync (`generated_skills.md`). Add a workflow
   YAML and it's three. The generator (`init_skills_handler.py`) would need to
   emit/sync the YAML too, or you get a new drift class. Prefer **one source of
   truth → generate all three** over hand-maintaining the YAML.

8. **The planner already spent tokens/context.** Reactive promotion grafts a
   *completed* agent as the workflow root. The executor must treat step 1 as
   "already done, output supplied" rather than re-running it — otherwise you
   double-run the planner.

9. **Workspace lifecycle.** `run_workflow_runner` releases the workspace on exit
   (even on SIGTERM). A plan chain *wants* the coder to reuse the planner's
   workspace. Coordinator-free gates + workspace handoff must be reconciled so a
   gate-wait doesn't release a workspace the next family member needs.

---

## Critique of the plan as a whole

- **The goal is right; the codebase wants this.** `run_agent_exec_plan*.py` +
  `run_agent_exec_questions.py` are ~80% the same shape (marker → kill → notify →
  durable pending → poll → branch → respawn child with reconstructed prompt +
  model handoff). That shared shape *should* be one engine. Extracting it is the
  highest-leverage, lowest-risk win and is independent of YAML.

- **"One YAML per *skill*" is the wrong granularity.** The skill is a single
  reactive *action* ("propose + pause"); the thing worth making declarative is
  the *family/chain* it initiates. Model the **family** as the YAML, with the
  kill+surface skill as the *gate step* inside it. Questions especially is a
  *loop with accumulation*, not a linear step list, so "questions.yml as a step
  pipeline" is a poor fit unless `repeat:`+state is first-classed.

- **Don't adopt `WorkflowExecutor` HITL wholesale.** As the table shows, generic
  HITL is strictly weaker than plan approval on timeout, actions, durability,
  frontend parity, and model handoff. Porting onto it as-is is a regression.
  Either upgrade the workflow engine to match (preferred long-term) or keep gates
  on the durable marker protocol and use workflows only to describe the
  *post-gate chain* (faster, safer).

- **Value scales with count.** Only two such interactions exist today. If you
  foresee 2–3 total, a shared-abstraction refactor (no YAML) is sufficient and
  full YAML-ization is over-engineering. If you foresee many — *especially if you
  want users/plugins to define their own families* — the declarative route earns
  its keep. Decide this first; it changes the design.

- **Prior art agrees.** `unified_plan_mode_and_qa.md` already evaluated
  "Option C: Skill-Based Plan Mode" as a workflow and flagged exactly the cons
  that bite here: "loses the agent's session/context between phases," "planning
  agent and implementing agent are separate invocations," "workflow overhead for
  a simple two-phase flow." The current architecture deliberately evolved *past*
  provider-hook plan mode into the skill-based kill-respawn model — the proposal
  is the logical next step, but it should *absorb* the kill-respawn model's
  strengths, not discard them.

---

## Recommended solution (phased)

A strangler-fig migration, not a big bang:

**Phase 0 — Decide scope (blocking).** Confirm: (a) plan-chain family only
(assumed); (b) primary goal = extensibility, unification, or user-customizable
families; (c) how many interactions you realistically expect. These determine
how far to go.

**Phase 1 — Extract one `InteractionGate` abstraction (no YAML yet).** Unify the
~80% shared logic of plan + questions into a single engine parameterized by a
small descriptor: marker name, notification kind, request/response schema,
response→action mapping, and a "spawn next family child" callback (prompt
reconstruction + model handoff + role suffix). Re-implement today's plan and
questions *on top of it* with zero behavior change. **This alone delivers most of
the "add interaction #3 cheaply" value** and is safe, testable, and
frontend-neutral. Per `rust_core_backend_boundary.md`, the gate *state machine
and descriptor schema* are cross-frontend domain logic and likely belong in
`sase-core` (like `frontmatter_schema` already does), with Python adapters here.

**Phase 2 — Make the post-gate family declarative.** Represent the chain that
unfolds after a gate as data. If you want that data to *be* an xprompt workflow
YAML, first close the engine gaps: unbounded/configurable HITL timeout; rich
skill-defined HITL actions + `if:` branching; per-gate notification/modal
selection (incl. Telegram); coordinator-free (write-request-then-exit) gates with
durable re-derivation; resolved model + accumulated Q&A threaded into the render
context. Use **reactive promotion**: skill fires → kill → instantiate the family
workflow at the gate with the completed planner grafted as root.

**Phase 3 — Generation & safety.** Extend `init_skills_handler` so the CLI
command, `SKILL.md`, and family YAML are generated from one source (no
hand-maintained YAML drift). Namespace/protect system family workflows from
user-local shadowing.

**Validate on a NEW interaction first.** Pick a brand-new gate (e.g. "approve
this diff" or "pick one of N") and build it *only* on the new engine, leaving
plan/questions on the proven path until the engine has matched their behavior.
This de-risks the whole migration.

---

## Open questions (hard for me to answer without you)

1. **Which "family"?** Plan-chain (`--`, sequential) only, or also the
   dotted-sibling (`.`, parallel) families? Unifying both is a much bigger swing.
2. **Primary goal?** Extensibility (add gates cheaply), unification (collapse
   plan+questions into one engine), or **user/plugin-defined families** (people
   author their own family YAMLs)? Each implies a different design and a
   different amount of the engine work above.
3. **How many gates do you actually foresee?** If ~3 total, skip YAML (Phase 1
   only). If many / user-authored, do Phases 2–3.
4. **Coordinator model — the big fork.** Are you willing to accept a persistent
   coordinator process per family (with the crash/robustness cost), or must
   families remain coordinator-free (requiring me to teach the workflow engine
   the write-request-then-exit trick)? This is the highest-impact decision.
5. **Wait policy.** Is the current unbounded plan wait the desired behavior, or
   do you want per-gate timeouts/escalation? What should timeout *do*?
6. **Frontend parity bar.** Must the new mechanism preserve bespoke
   plan/question formatting and accept/reject across *all* frontends (TUI +
   Telegram + future web) from day one, or is TUI-first acceptable?
7. **Nested/recursive families.** First-class (a coder may plan/ask, arbitrarily
   deep) or bounded? This drives whether you need runtime sub-workflow spawning.
8. **Rust boundary.** Should the gate state machine + descriptor schema live in
   `sase-core` (shared) now, or stay Python here until a second frontend forces
   it? (My lean: schema in core, orchestration in Python — matches the existing
   `frontmatter_schema` split.)

---

## Key file reference

**Mechanism A (reactive kill + respawn):**
- `src/sase/main/plan_propose_handler.py` · `src/sase/main/questions_command_handler.py` — write marker + kill
- `src/sase/main/utils.py:51` (`kill_agent_runner_group`), `src/sase/axe/runner_utils.py` (soft SIGTERM)
- `src/sase/axe/run_agent_exec.py` (loop), `run_agent_exec_plan.py` / `run_agent_exec_plan_accept.py` / `run_agent_exec_questions.py` (handlers + respawn)
- `src/sase/llm_provider/_plan_utils.py` (`handle_plan_approval`, `while True` poll)
- `src/sase/plan_chain.py` (suffixes, `allocate_agent_family_child_suffix`), `src/sase/agent/names/_lookup.py` (family lookup)
- `src/sase/plan_approval_actions.py` (8-action approval matrix)
- `src/sase/notifications/senders.py` (`notify_plan_approval`, `notify_user_question`), `notifications/pending_actions.py` (durable mirror)
- `src/sase/ace/tui/models/_agent_status_overrides.py` (`DONE→PLAN/QUESTION` re-derive)

**Mechanism B (workflow + HITL):**
- `src/sase/xprompt/workflow_models.py`, `workflow_loader*.py`, `src/sase/xprompts/workflow.schema.json`
- `src/sase/xprompt/workflow_executor*.py`, `workflow_hitl.py` (`TUIHITLHandler`, 1h timeout), `workflow_executor_types.py` (`HITLResult`)
- `src/sase/axe/run_workflow_runner.py` (persistent coordinator, workspace release)
- `src/sase/xprompt/models.py:204` (`xprompt_to_workflow`), `prompt_frontmatter.py` (YAML serialize)

**Generation / skills:**
- `src/sase/main/init_skills_handler.py`, `src/sase/xprompts/skills/*.md`, `memory/long/generated_skills.md`

**Prior research (read these):**
- `sdd/research/202603/unified_plan_mode_and_qa.md` — already weighed "skill-as-workflow" plan mode and its cons
- `sdd/research/202603/xprompt_workflow_best_practices.md` — durable-execution / sub-workflow-spawning / exit-handler gaps
- `sdd/research/202603/unified_vcs_commit_workflows.md`, `unified_vcs_commit_prompt_questions.md`, `slash_command_migration.md` — adjacent unification efforts
