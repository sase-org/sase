# Dynamic Agent Families from XPrompt Workflow YAML

Status: consolidated research and design critique
Date: 2026-06-17

## Question

The proposal is to implement dynamic agent families using xprompt workflow YAML
files. Specifically, every xprompt skill command that kills the current agent
and sends a user request surfaced in the TUI would get its own xprompt workflow
YAML file.

This consolidates two independent research notes and verifies their claims
against the current Python runner, xprompt workflow executor, TUI notification
paths, and sibling Rust core wire contracts.

## Short Answer

The goal is good, but the literal "one ordinary workflow YAML per terminating
skill command" model is the wrong abstraction.

The terminating skills are not lifecycle owners. Today `/sase_plan` and
`/sase_questions` are small instruction shims over host commands. Those commands
emit a durable handoff marker, SIGTERM the runner process group, and let the
outer runner decide how to resume. The lifecycle owner is the family state
machine that knows the interrupted role, accumulated feedback/Q&A, suffix
allocation, response protocol, prompt reconstruction, SDD side effects, and
frontend status.

Recommended shape: define dynamic families as first-class YAML-backed
`agent_family` state machines, xprompt-adjacent but not executed as normal
`WorkflowStep` lists. Keep skills and host commands as small event emitters.
The runner should convert marker files into typed family events, normalize the
interrupted artifacts, and ask a family evaluator for the next gate, role,
prompt, suffix, metadata, and side effects.

If you want to reuse the existing xprompt workflow executor directly, first add
durable/coordinator-free gate semantics, richer gate choices, per-gate frontend
protocols, configurable wait policy, and a way to start a workflow at a gate with
the already-completed agent output supplied. Without those upgrades, porting
plan/questions onto workflow HITL would be a regression.

## Important Disambiguation: Two Family Concepts

SASE has two family-like concepts:

| Concept | Shape | Naming | Current owner |
| --- | --- | --- | --- |
| Plan-chain family | sequential handoff roles such as planner, question continuation, coder, epic, legend, commit | canonical `--` suffixes such as `foo--plan`, `foo--code`; legacy `.` and `-` forms still classify | `src/sase/plan_chain.py`, runner handoff code, TUI status/grouping |
| Dotted sibling family | parallel sibling agents from multi-agent prompts | `foo`, `foo.bar`, `foo.baz` | multi-agent xprompt expansion and agent name allocation |

The proposal most naturally targets the plan-chain family: a sequential,
human-gated role graph. Unifying dotted sibling groups with dynamic plan-chain
families would be a larger separate design.

## Verified Current State

### The skills are intentionally tiny

The editable skill sources live under `src/sase/xprompts/skills/` and are
generated into provider-specific `SKILL.md` files by `sase init-skills`.

Current kill-and-surface skills are:

- `/sase_plan`, which tells the agent to write `sase_plan_<name>.md` and run
  `sase plan propose <file>`.
- `/sase_questions`, which tells the agent to run `sase questions '<json>'`.

The skill text does not enforce lifecycle semantics. The host commands and
runner do.

### The commands are host-side interrupts

`sase plan propose` requires `SASE_AGENT` and `SASE_ARTIFACTS_DIR`, formats and
archives the plan, writes `.sase_plan_pending`, touches an ACE refresh pulse, and
kills the runner process group.

`sase questions` requires the same agent environment, validates the question
JSON, writes `.sase_questions_pending`, and kills the runner process group.

This is not a normal workflow step returning. It is an intentional process
interrupt that lets the outer runner continue from a new artifacts directory and
prompt.

### The runner is already marker-driven

`run_execution_loop()` wraps the current prompt in an anonymous workflow and
executes it. If SIGTERM was observed, `_handle_killed_iteration()`:

- checks explicit user-kill intent first;
- reads and deletes `.sase_plan_pending` and `.sase_questions_pending`;
- checks marker timestamps against the kill timestamp;
- dispatches to `handle_plan_marker()` or `handle_questions_marker()`;
- otherwise treats the kill as user-initiated.

That marker freshness check is important. A generic event system needs the same
race protection or it can mistake stale/unrelated markers for the cause of a
kill.

### Plan approval is a product protocol

Plan approval is not just generic HITL. The current plan path creates
`plan_request.json`, sends a `PlanApproval` notification, blocks on
`plan_response.json`, and maps product choices into runner behavior:

- `approve` runs a coder by default;
- `run` is a product alias for approve-without-commit;
- `tale` serializes as `approve` with `commit_plan=true` and `run_coder=true`;
- `commit` serializes as `approve` with `commit_plan=true` and
  `run_coder=false`;
- `epic` and `legend` are their own runner actions;
- `feedback` serializes as `reject` with feedback text, but the runner treats it
  as a feedback replan loop;
- plain reject terminates the family.

Accepted plans also perform curated side effects: write SDD prompt/plan files,
initialize/commit SDD storage when needed, set `SASE_PLAN` to the right plan
path, resolve the coder worker lane from the planner's concrete model, preserve
custom `%model` behavior, and optionally inherit planner chat with
`#fork:<planner>`.

### Questions are contextual interrupts

Questions can interrupt the root agent, planner, feedback replanner, coder,
epic/legend setup, or future custom phases. The runner therefore has to preserve
the interrupted role and rebuild the follow-up prompt from the right phase base.

Current question behavior:

- normalizes/finalizes the interrupted artifacts as completed;
- persists request/response paths so the TUI does not leave rows visually stuck;
- appends a `QARound`;
- renders accumulated Q&A as one monotonic section;
- wraps Q&A in `%xprompts_enabled:false` / `%xprompts_enabled:true`;
- allocates the next suffix from the interrupted role;
- inherits the interrupted phase's concrete model/provider for follow-up.

This is why command-owned YAML is risky. `sase questions` is the same command in
all phases, but the next prompt and suffix are family-state dependent.

### Workflow HITL is separate and weaker for this use case

XPrompt workflows support `hitl: true`, but current workflow HITL is a
completed-step review protocol:

- request file: `hitl_request.json`;
- response file: `hitl_response.json`;
- notification action: `HITL`;
- result actions: `accept`, `edit`, `reject`, `rerun`, `feedback`;
- TUI wait timeout: one hour, then reject;
- bash/python rerun handling is still incomplete in executor paths.

Workflow HITL does register pending actions, so it is not invisible to the TUI.
But it is still a different closed action kind, response schema, modal, timeout
policy, and execution model. It does not model plan feedback loops, question
continuations, SDD side effects, or plan-specific mobile choices.

### The shared Rust core contract is already involved

The sibling Rust core mirrors agent metadata fields such as `agent_family`,
`agent_family_role`, `plan_chain_root`, `role_suffix`,
`question_request_path`, and `question_response_path`.

Core notification/mobile code also has closed pending action kinds and mobile
action details for `PlanApproval`, `HITL`, and `UserQuestion`. A dynamic family
implementation that changes roles, gates, choices, or pending-action state is
not purely Python/TUI local. Shared schema, classification, and mobile/editor
contracts need corresponding Rust core support.

### Catalog/discovery storage matters

Python and Rust both load file-backed workflow YAML from xprompt directories.
Config-defined markdown xprompts are cataloged, but config-defined workflow
blocks are intentionally ignored by Python workflow loading and Rust core
removed config workflow support from its xprompt catalog.

Therefore "dynamic" should start with file-backed definitions if editor/mobile
catalog visibility matters. Config-only family definitions need explicit new
Python and Rust support.

## Critique of the Proposed Plan

### What is right

The plan targets real duplication. Current plan and questions handling repeats a
common shape: marker, kill, normalize artifacts, notify, wait for response,
interpret response, allocate suffix, create follow-up artifacts, reconstruct
prompt, and resume or terminate.

It is also reasonable to put the declarative source of truth near xprompts and
skills. That keeps prompts, skills, workflows, catalogs, LSP/editor support, and
project/plugin overrides in one conceptual extension surface.

### Critical flaw: command is the wrong unit

A terminating command is an event inside a family, not the family itself.

If every command gets a standalone ordinary workflow YAML, each file will either
duplicate family state logic, assume the standard planner/coder chain, or become
a thin wrapper over Python state-machine code. The third outcome is honest, but
then the file is not really a normal workflow. It is an event adapter.

The unit that should be declarative is the family graph: roles, gates,
transitions, prompts, response mappings, suffix policy, loop state, and curated
side effects.

### Critical flaw: normal workflows do not own kill/resume semantics

Current xprompt workflows are ordered step executions inside a runner process.
Plan/questions intentionally kill the current LLM/tool process and let the outer
runner continue. Encoding this directly as normal `WorkflowStep` records would
require at least:

- interrupting step/event semantics;
- durable resumption after SIGTERM;
- marker freshness and user-kill disambiguation;
- gate response files and frontend notifications;
- role/suffix allocation;
- prompt reconstruction from family state;
- artifact metadata persistence;
- synthetic chat history for killed planner/question phases;
- cross-process environment propagation.

That is a state-machine executor. It should be designed explicitly rather than
hidden inside per-command workflow files.

### Critical flaw: frontend contracts are closed

TUI, mobile, and pending-action code know concrete request files, response
files, renderers, and choices for `PlanApproval`, `UserQuestion`, and `HITL`.
YAML can name arbitrary choices, but frontends still need to know what to render
and what JSON to write.

V1 should use existing renderers as compatibility protocols:
`plan_approval`, `user_question`, and `hitl`. Add a generic decision/form
renderer only after the built-in protocols are data-driven and parity-tested.

### Critical flaw: old artifacts must remain self-describing

If a user edits family YAML after a run, old artifacts cannot be interpreted by
reloading the current YAML. Persist enough metadata to make rows durable:

- family id, version, source path, and hash;
- role id and role suffix;
- active gate id and renderer/protocol id;
- choice id after response;
- family-state snapshot or references for counters, accumulated Q&A, feedback,
  and prompt base.

Without this, ACE can misgroup rows, show stale statuses, route responses to the
wrong phase, or fail revive/wait/fork behavior.

### Critical flaw: YAML drift can get worse

Today the CLI command and generated skill source must stay synchronized. Adding
a hand-maintained workflow/family YAML makes that three artifacts. Prefer one
descriptor or generator source that produces or validates:

- the CLI/event adapter contract;
- the skill instructions;
- the family/gate protocol documentation;
- tests for examples and response schemas.

## Edge Cases to Design For

1. User kill vs handoff kill. SIGTERM can mean "user killed it" or "agent
   submitted a plan/question." Preserve marker and freshness checks.
2. Stale marker files. Event markers must be consume-once and scoped to the
   interrupted artifacts directory.
3. Marker race windows. Marker timestamps near SIGTERM need tolerance.
4. Duplicate responses. TUI, mobile, Telegram, or future web can race to write a
   response. Keep write-once/conflict semantics.
5. Request consumed before UI opens. Pending actions need stale/already-handled
   detection per request protocol.
6. Planner output lost to SIGTERM. Synthetic chat history from the plan file
   needs to survive.
7. Questions during non-root phases. Follow-up prompt and suffix must come from
   the interrupted role, not a global questions workflow.
8. Q&A plus feedback interleaving. Accumulated Q&A and feedback must not
   duplicate or reorder prompt sections.
9. Xprompt expansion in answers. User-provided Q&A text must not accidentally
   expand `#refs`.
10. Suffix collisions. Dynamic suffixes must avoid built-ins, legacy dotted/dash
    forms, numeric feedback/question suffixes, and reserved names.
11. Legacy artifacts. Existing `.plan`, `.code`, `-plan`, `-code`, numeric, and
    `--` artifacts still need classification.
12. Product choice vs runner protocol. Product choices like `tale`, `run`, and
    `commit` are compatibility mappings, not always runner actions.
13. Commit-only approval. An accepted plan can be terminal (`run_coder=false`).
14. Epic/legend side effects. SDD commits are intentional because follow-up VCS
    workflows can wipe uncommitted SDD files.
15. Worker lane drift. Resolve follow-up worker model at handoff time from the
    planner's concrete provider/model.
16. Custom `%model` in coder prompts. Embedded model directives override the
    inherited model prefix and metadata rewrite.
17. `SASE_PLAN` semantics. The code phase needs the committed SDD plan when it
    exists, otherwise the archived plan.
18. Chat inheritance. `SASE_CODER_INHERIT_PLANNER_CHAT=1` should become a role
    property or policy, not hidden global-only behavior.
19. Auto-approval and headless runs. Gate schemas need explicit auto policies
    before custom blocking gates are safe.
20. TUI status overrides. Data-driven roles need labels, progress states, and
    root/child routing keys.
21. TUI performance. New gate/status handling must not add synchronous disk I/O
    or JSON parsing on the Textual event loop; use existing background refresh
    and tracked-task patterns.
22. Mobile action support. New gate kinds or choices require Rust/mobile wire
    updates, not just YAML.
23. Config-only visibility. Families in `sase.yml` will be invisible to current
    workflow catalogs unless catalog support is added.
24. Workflow HITL feedback is not plan feedback. Existing HITL feedback does not
    regenerate plan-family agents with accumulated state.
25. Crash recovery while gated. A later ACE session or CLI action must still be
    able to finish a pending gate.
26. Family YAML edits mid-run. Active runs should use a snapshot/hash of the
    compiled definition they started with.
27. Nested families. A coder spawned from one family can itself ask questions or
    propose a plan; naming, grouping, and sub-family depth need explicit policy.
28. Security of side effects. Family YAML should select curated side-effect ids,
    not run arbitrary Python/bash for privileged bookkeeping.

## Recommended Architecture

### 1. Keep skills and commands small

Generated skills should continue to instruct the agent how to submit structured
requests. Host commands should remain the enforcement point.

Represent terminating commands as event adapters:

```yaml
kind: handoff_command
schema_version: 1
id: plan_propose
cli: "sase plan propose"
emits: plan_submitted
marker_file: ".sase_plan_pending"
request_schema: plan_proposal_v1
requires_agent_env: true
kill_runner_group: true
```

This adapter can live near xprompt sources and be discoverable, but it should
not pretend to be a normal workflow step graph.

### 2. Add first-class family definitions

Define a dedicated `agent_family` schema. It can be YAML and share xprompt
discovery/catalog infrastructure, but it should be compiled and executed by a
family evaluator.

Sketch:

```yaml
kind: agent_family
schema_version: 1
id: standard_plan_chain
version: 1
entry_role: root

roles:
  root:
    default_plan_suffix: "--plan"
    on_event:
      plan_submitted: plan_review
      questions_submitted: user_questions

  code:
    suffix: "--code"
    label: "CODER"
    model_policy: worker_for_interrupted_primary
    prompt_template: standard_coder_prompt
    on_event:
      questions_submitted: user_questions

gates:
  plan_review:
    renderer: plan_approval
    request_protocol: plan_request_v1
    response_protocol: plan_response_v1
    choices:
      approve:
        compatibility_response: { action: approve, commit_plan: false, run_coder: true }
        goto: code
      tale:
        compatibility_response: { action: approve, commit_plan: true, run_coder: true }
        side_effects: [write_sdd, commit_sdd, set_sase_plan_env]
        goto: code
      commit:
        compatibility_response: { action: approve, commit_plan: true, run_coder: false }
        side_effects: [write_sdd, commit_sdd]
        terminate: plan_committed
      feedback:
        compatibility_response: { action: reject }
        accumulate: feedback_bullets
        loop_to: root

events:
  questions_submitted:
    gate: user_questions
    renderer: user_question
    return_to: interrupted_role
    answer_fold: default_qa_markdown
```

The exact schema can change. The key is to keep roles, events, gates,
transitions, compatibility response mappings, prompt templates, and side effects
as separate concepts.

### 3. Normalize markers into typed events

Keep `.sase_plan_pending` and `.sase_questions_pending` for compatibility, but
convert them immediately into typed events such as `plan_submitted` and
`questions_submitted`.

Longer term, add one generic marker envelope:

```json
{
  "schema_version": 1,
  "event": "questions_submitted",
  "command_id": "questions",
  "payload": {},
  "timestamp": 1781712000.0
}
```

Preserve current ordering: detect user kill, consume markers, reject stale
markers, normalize interrupted artifacts, then evaluate the family transition.

### 4. Use existing renderers first

Do not start by inventing a generic form renderer. First make current protocols
data-driven while preserving behavior:

- `renderer: plan_approval` uses current `plan_request.json`,
  `plan_response.json`, PlanApproval modal/mobile action, and side-effect
  adapters.
- `renderer: user_question` uses current `question_request.json`,
  `question_response.json`, UserQuestion modal/mobile action, and Q&A folding.
- `renderer: hitl` remains workflow-step review.

Only after parity should a new generic `decision` renderer be added.

### 5. Persist family identity and state

Before enabling custom families, add artifact metadata like:

- `agent_family_config_id`;
- `agent_family_config_version`;
- `agent_family_config_hash`;
- `agent_family_role`;
- `role_suffix`;
- `active_gate_id`;
- `active_gate_renderer`;
- `family_state`.

The state can store compact references rather than huge prompt bodies, but it
must be enough to interpret old rows and resume pending gates after definition
edits.

### 6. Put shared semantics in Rust core

Python should continue owning subprocesses, marker files, Textual modals,
filesystem side effects, and prompt execution.

Shared semantics should move to or be mirrored in `sase-core` once stable:

- family schema validation;
- role/suffix classification;
- transition resolution;
- pending-action kind/state modeling;
- mobile action details;
- scan wire fields;
- editor/catalog discovery.

This matches the existing Rust-core boundary: if CLI, TUI, mobile, editor, or a
future web UI must agree, treat it as core domain behavior.

## Workflow-Executor Option: Reactive Promotion

If you still want the xprompt workflow executor to own more of this, use
reactive promotion rather than pre-launching workflows.

The agent has already run when it calls `sase plan propose` or `sase questions`.
On the marker event, the runner could instantiate a workflow/family at the
approval or question gate, supplying the interrupted phase output as an
already-completed step. The existing implicit step-input mechanism is adjacent
to this idea.

This path needs prerequisites:

- start-at-gate or supplied-step-output support;
- coordinator-free gates, or real durable resume of the workflow runner;
- unbounded/configurable gate timeout;
- custom action sets and branch conditions;
- per-gate notification/modal/mobile protocol selection;
- runtime sub-family/spawn semantics for nested families;
- workspace handoff behavior that does not release a workspace needed by the
  follow-up agent.

Until those exist, workflow YAML should describe family definitions and prompt
templates, not directly replace the marker-driven handoff loop.

## Implementation Sequence

1. Build a golden-equivalence harness for current plan/question flows:
   approve, run, tale, commit-only, epic, legend, feedback replan, questions
   before plan, questions during feedback/code, auto-approval, and killed runs.
2. Extract a Python `InteractionGate` or event-adapter layer with no YAML yet:
   marker name, request/response schema, notification action, renderer id,
   stale/handled checks, response mapping, and family callback.
3. Add a built-in `standard_plan_chain` family definition and evaluator, but
   keep existing marker files, response files, and frontend protocols.
4. Route plan/question markers through typed events and the built-in evaluator,
   proving byte/metadata/prompt equivalence with the harness.
5. Persist family id/version/hash and `family_state`; update Python scan,
   Rust scan wire, and TUI/mobile consumers.
6. Make plan choices and question continuation labels data-driven behind the
   existing renderers.
7. Enable custom file-backed family YAML with validated suffixes, role ids,
   prompt templates, loop limits, and curated side-effect ids.
8. Add generic decision gates only after PlanApproval/UserQuestion parity is
   proven.
9. Move pure validation/classification/transition pieces into `sase-core` with
   parity tests.

## Validation Checklist

Minimum coverage before custom families are enabled:

- marker freshness and stale marker rejection;
- explicit user kill with marker files present;
- duplicate response conflict across transports;
- response compatibility for approve/run/tale/commit/epic/legend/feedback;
- feedback round suffix allocation with reserved names;
- questions in root, plan, feedback, code, epic, legend, and custom roles;
- Q&A markdown wrapping with xprompt expansion disabled;
- SDD write/commit behavior for version-controlled and non-version-controlled
  SDD dirs;
- `SASE_PLAN` for committed and uncommitted approvals;
- coder model picker, worker lane resolution, and custom prompt `%model`;
- `SASE_CODER_INHERIT_PLANNER_CHAT`;
- auto-approval precedence;
- TUI status overrides and root/child notification routing;
- TUI performance under refresh/navigation;
- mobile pending-action states and choices;
- Rust/Python wire parity;
- old artifact compatibility.

## Key References

- Skills: `src/sase/xprompts/skills/sase_plan.md`,
  `src/sase/xprompts/skills/sase_questions.md`,
  `memory/long/generated_skills.md`.
- Command interrupts: `src/sase/main/plan_propose_handler.py`,
  `src/sase/main/questions_command_handler.py`,
  `src/sase/main/utils.py`.
- Runner handoff: `src/sase/axe/run_agent_exec.py`,
  `src/sase/axe/run_agent_exec_plan.py`,
  `src/sase/axe/run_agent_exec_plan_accept.py`,
  `src/sase/axe/run_agent_exec_questions.py`,
  `src/sase/axe/run_agent_helpers_questions.py`.
- Plan/question protocol: `src/sase/llm_provider/_plan_utils.py`,
  `src/sase/plan_approval_actions.py`,
  `src/sase/notifications/pending_actions.py`.
- Workflow/HITL: `src/sase/xprompt/workflow_models.py`,
  `src/sase/xprompt/workflow_loader.py`,
  `src/sase/xprompt/workflow_hitl.py`,
  `src/sase/xprompt/workflow_executor_types.py`,
  `src/sase/axe/run_workflow_runner.py`.
- Family metadata: `src/sase/plan_chain.py`,
  `src/sase/core/agent_scan_wire_markers.py`,
  `../sase-core/crates/sase_core/src/agent_scan/wire.rs`,
  `../sase-core/crates/sase_core/src/notifications/mobile.rs`,
  `../sase-core/crates/sase_core/src/notifications/pending_actions.rs`.
- Prior research:
  `sdd/research/202603/unified_plan_mode_and_qa.md`,
  `sdd/research/202603/xprompt_workflow_best_practices.md`.

## Recommended Solution

Do not implement "one ordinary xprompt workflow YAML per terminating skill
command" as the primary model.

Implement dynamic agent families as a dedicated YAML-backed family state-machine
layer:

1. Generated skills stay short and provider-uniform.
2. Terminating host commands emit typed handoff events and kill the runner.
3. The runner consumes markers, normalizes interrupted artifacts, and passes an
   event plus persisted family state to a family evaluator.
4. Family YAML declares roles, gates, transitions, prompt templates, renderer
   ids, compatibility response mappings, auto policies, suffix rules, and
   curated side effects.
5. Current PlanApproval and UserQuestion protocols remain the first
   compatibility renderers.
6. Artifacts persist family id/version/hash and family state so old rows are
   self-describing.
7. Shared validation, suffix classification, transition semantics, and mobile
   action contracts move to `sase-core` after Python parity is proven.

This keeps the valuable part of the plan - an xprompt-adjacent declarative
extension surface - while avoiding the architectural mistake of making each
command YAML file pretend to be a durable family executor.

## Open Questions

- Does "dynamic agent families" mean only plan-chain `--` families, or should it
  eventually include dotted sibling families too?
- Is the main goal unifying built-in plan/questions, enabling many new built-in
  gates, or allowing user/plugin-authored custom families?
- What is the first custom family to support: planner -> reviewer -> coder,
  multi-reviewer consensus, research synthesis, mentor sign-off, or something
  else?
- Should v1 support only file-backed family definitions, or must config-defined
  families in `sase.yml` work from the start?
- Should active runs snapshot the full compiled family definition, or is source
  path plus hash plus compact state enough?
- Should custom gates in v1 only use existing PlanApproval/UserQuestion/HITL
  renderers, or should a generic decision renderer be a prerequisite?
- What auto-approval policy is acceptable for arbitrary custom gates?
- How strict should loop detection be: mostly acyclic graphs with explicit
  feedback loops, or dynamic max-visit counters per role?
- How much prompt assembly should be core-owned/schema-owned versus Python
  template-owned?
- Is a persistent workflow coordinator acceptable for any family, or must all
  human-gated families remain coordinator-free like plan/questions today?
