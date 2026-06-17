# Dynamic Agent Families from XPrompt Workflow YAML

Status: Research and design critique
Date: 2026-06-17

## Question

The proposal is to implement dynamic agent families using xprompt workflow YAML
files. In particular, every xprompt skill command that terminates the current
agent and sends a user request surfaced in ACE should get its own xprompt
workflow YAML file.

This research checks that plan against the current runner, skill, workflow,
notification, TUI, mobile, and Rust-core boundaries.

## Short Answer

The direction is good, but the literal implementation is too command-centric.
The commands are not the real lifecycle owners. They are host-side interrupt
signals inside a longer-lived family state machine.

Use YAML for the declarative family/role/gate definitions, but do not model
each terminating skill command as an ordinary executable xprompt workflow. The
workflow executor currently lacks the semantics that make `sase plan propose`
and `sase questions` work: process-group termination, marker race handling,
artifact handoff, role suffix allocation, plan/question notification protocols,
SDD side effects, and prompt reconstruction across restarts.

Recommended shape: first-class `agent_family` definitions, loaded through the
xprompt/config discovery system and allowed to reference normal xprompt workflow
steps/templates. Keep the current host commands as small event emitters. Have the
runner convert marker files into typed family events, then let a family evaluator
decide the next role, gate, prompt, suffix, metadata, and side effects.

## Verified Current State

### The generated skills are instruction shims

The relevant bundled skills live under `src/sase/xprompts/skills/` and are
rendered into provider-specific `SKILL.md` files by `sase init-skills`. The
long-memory note for generated skills says the checked-in skill source files are
the editable source of truth, not the deployed `SKILL.md` files.

Current terminating skills are small:

- `/sase_plan` tells the agent to write `sase_plan_<name>.md` and run
  `sase plan propose <file>`.
- `/sase_questions` tells the agent to run `sase questions '<json>'`.

The skill text does not enforce lifecycle behavior. The enforcement lives in
host commands and the runner.

### The commands kill the runner by design

`sase plan propose`:

- requires `SASE_AGENT` and `SASE_ARTIFACTS_DIR`;
- formats and archives the plan file;
- writes `.sase_plan_pending` into the current artifacts directory;
- touches an ACE refresh pulse;
- SIGTERMs the agent runner process group.

`sase questions`:

- requires the same agent environment;
- validates the question JSON schema;
- writes `.sase_questions_pending`;
- SIGTERMs the agent runner process group.

This is not a normal workflow step completing. It is an intentional interrupt
that causes the outer runner to stop the current LLM/tool process and resume from
a new prompt/artifact directory.

### The runner is already a marker-driven state machine

`run_execution_loop()` wraps the current prompt in an anonymous workflow and calls
`execute_workflow()`. If the process was killed, `_handle_killed_iteration()`:

- treats explicit user-kill intent as terminal;
- reads and deletes `.sase_plan_pending` and `.sase_questions_pending`;
- ignores markers that appear newer than the SIGTERM timestamp;
- dispatches to `handle_plan_marker()` or `handle_questions_marker()`.

The marker timestamp check is important. A dynamic implementation needs the same
race protection or it can accidentally treat stale/new marker files as the cause
of the kill.

### Plan approval is a product protocol, not just HITL

`handle_plan_marker()` normalizes the interrupted artifacts, marks the interrupted
workflow/step as completed despite the SIGTERM, records metadata, and calls
`handle_plan_approval()`.

`handle_plan_approval()` creates:

- `plan_request.json`;
- a `PlanApproval` notification with `response_dir` and `session_id`;
- a blocking poll for `plan_response.json`.

The response protocol is fixed today:

- `approve`, with `commit_plan` and `run_coder` booleans;
- `epic`;
- `legend`;
- legacy `commit`, mapped to `approve` with `run_coder=false`;
- feedback text, mapped to a feedback replan.

The TUI modal has a product-level vocabulary that is wider than the runner
protocol. For example, "Tale" is serialized as `action=approve`,
`commit_plan=true`, `run_coder=true`, then runner metadata derives
`plan_action=tale`.

Accepted plans also run curated side effects:

- write SDD prompt/plan files;
- initialize and commit SDD storage when needed;
- force commits for epic/legend paths;
- set `SASE_PLAN` to either the committed plan path or archived plan path;
- resolve the coder model, including worker-lane inheritance;
- optionally prepend `#fork:<planner>` when
  `SASE_CODER_INHERIT_PLANNER_CHAT=1`;
- create follow-up artifacts for `--code`, `--epic`, or `--legend`.

An ordinary `hitl: true` workflow step does not model these semantics.

### Questions are contextual interrupts

`handle_questions_marker()` has to know which phase was interrupted. A question
can happen during the root prompt, the plan phase, a feedback replan, the code
phase, epic/legend setup, or a future custom phase.

Current behavior:

- normalize/finalize the interrupted artifacts;
- persist request and response paths on the interrupted row so it does not stay
  visually stuck on `QUESTION`;
- append a `QARound`;
- render all accumulated Q&A as one monotonic block with xprompt expansion
  disabled;
- allocate a follow-up suffix based on the interrupted role;
- rebuild from `state.question_base_prompt`, not always the original prompt.

This is exactly why "one workflow per command" is risky: the `questions` command
does not know the role graph by itself. It emits an event inside whatever family
phase is active.

### Workflow HITL is not the same abstraction

XPrompt workflows support `hitl: true`, but current HITL is a completed-step
review:

- request file: `hitl_request.json`;
- response file: `hitl_response.json`;
- notification action: `HITL`;
- accepted bash/python steps get `approved=true`;
- agent-step output can be edited or rejected.

Docs note that some interfaces may show feedback/rerun controls, but the current
executor only treats accept/edit/reject as workflow-control actions. The code
confirms that feedback is not a plan-style re-generation loop and bash/python
rerun is still a future hook.

Plan approval and user questions are different protocols with different request
files, response files, modal capabilities, status overrides, mobile actions, and
artifact metadata.

### Agent family identity is already a cross-frontend contract

`plan_chain.py` owns today's fixed suffix vocabulary:

- `--plan`;
- `--q`;
- `--code`;
- `--epic`;
- `--legend`;
- `--commit`;
- dynamic feedback/question suffixes such as `--plan-@`, `--@`, and
  `<phase>-@`.

Artifact metadata stores `agent_family`, `agent_family_role`, `role_suffix`,
`plan_chain_root`, and parent timestamps. ACE grouping/status code, prompt-panel
labels, file-panel behavior, revive/wait behavior, and Rust scanner wires all
consume these fields.

The sibling `sase-core` Rust repo already mirrors these fields in
`AgentMetaWire`, and its mobile notification code has closed action kinds for
`PlanApproval`, `HITL`, and `UserQuestion`. Any configurable/dynamic family that
changes role identity or action choices needs a shared contract, not a
Python-only YAML interpretation.

### Rust catalog discovery matters

Rust xprompt catalog loading currently parses file-backed workflow YAML files,
but tests explicitly assert that config-defined workflows do not appear in the
catalog. Config-defined markdown xprompts still do.

That means "dynamic" needs a careful storage decision:

- file-backed family definitions are naturally visible to Rust catalog/LSP
  paths;
- config-only family definitions need new Rust/Python catalog support;
- generated in-memory workflows would be invisible to editor/mobile/core paths
  unless new wires are added.

## Critique of the Proposed Plan

### What is right

The plan correctly targets the hardest part of SASE's current planner/coder
implementation: too much behavior is hardcoded in Python branches and TUI action
handlers. A declarative source of truth for roles, gates, transitions, prompts,
and side effects would make custom planner/coder/reviewer/question flows much
easier to reason about.

It is also right to put the source of truth near xprompts and skills. This keeps
the user-facing extension surface coherent: prompts, generated skills, workflow
definitions, and family definitions can share discovery, validation, LSP
support, documentation, and project/plugin override rules.

### Main flaw: the command is the wrong unit of ownership

A terminating command is an event, not a workflow family.

`sase questions` is the clearest example. The same command can interrupt a root
agent, a planner, a feedback replanner, a coder, or an epic/legend follow-up.
The next prompt and suffix depend on the interrupted role, accumulated Q&A,
feedback bullets, current model directive, `SASE_PLAN`, SDD state, and family
metadata.

If every command gets its own ordinary workflow YAML, each command workflow will
either:

- duplicate role/family state logic;
- silently assume the standard planner/coder chain;
- become a thin wrapper over Python state-machine code anyway.

The third outcome is the honest one, but then the YAML file is not really an
xprompt workflow. It is an event adapter.

### Main flaw: existing workflows do not own kill/resume semantics

The xprompt workflow executor is built for ordered step execution inside one
runner process. The plan/question lifecycle intentionally kills that process and
then asks the outer loop to continue with a new artifacts directory and prompt.

Trying to encode this directly as normal `WorkflowStep` records would require
new workflow semantics:

- an interrupting step type;
- durable event resumption after SIGTERM;
- marker freshness and user-kill disambiguation;
- role/suffix allocation;
- follow-up artifact creation;
- prompt reconstruction from family state;
- response-file polling with frontend notifications;
- synthetic chat history for killed planner/question steps;
- cross-process environment propagation.

That is effectively a new state-machine executor. It should be designed as one
rather than hidden inside per-command workflow files.

### Main flaw: gate UI and transport contracts are currently closed

ACE, mobile, pending-action storage, and Telegram-style external handlers know
specific action names and response files. Adding arbitrary gate choices in YAML
is not enough. The frontends need to know:

- what request file to read;
- what renderer/modal to use;
- which buttons/choices are valid;
- what response JSON to write;
- how to detect stale or already-handled requests;
- how to update status before the runner consumes the response.

The current `NotificationWire` envelope is generic enough, but the action
handlers are not. A dynamic family implementation must either use existing
renderers (`plan_approval`, `user_question`, `hitl`) or add a generic decision
renderer and update mobile/Rust/pending-action support.

### Main flaw: artifact compatibility can break silently

If users edit family YAML after agents have run, old artifacts cannot be
interpreted by looking up the current family definition. Persisted artifacts need
enough metadata to remain self-describing:

- family id;
- family schema version;
- family definition hash/source;
- role id;
- role suffix;
- gate id;
- choice id where applicable;
- family state snapshot or at least counters/visited roles needed to reconstruct
  status.

Without this, the TUI can misgroup rows, show stale statuses, route question
responses to the wrong phase, or fail to revive/wait on family members.

## Edge Cases to Design For

1. **User kill vs handoff kill.** A SIGTERM may mean "user killed the agent" or
   "the agent submitted a plan/question." The marker protocol and freshness check
   currently distinguish these.

2. **Marker race windows.** A marker can be written just before or after the kill
   timestamp. The current `_marker_predates_kill()` tolerance prevents accidental
   handoff from unrelated marker writes.

3. **Stale marker files.** The runner deletes marker files after reading. A new
   generic event marker must preserve this consume-once behavior.

4. **Duplicate responses.** TUI/mobile/Telegram can all write a response. Current
   host-side actions use write-once behavior in several paths. Generic gates need
   conflict handling.

5. **Request consumed before UI opens.** Pending actions are marked stale or
   already handled when `plan_request.json`, `question_request.json`, or
   `hitl_request.json` disappears. Generic gates need equivalent state tests.

6. **Planner response is lost to SIGTERM.** The plan phase saves synthetic chat
   history from the plan file. This behavior must survive configurability.

7. **Questions during non-root phases.** Questions must resume from the exact
   interrupted prompt, including code/epic/legend model directives and embedded
   workflow refs.

8. **Q&A plus feedback interleaving.** Feedback replans include accumulated Q&A;
   question follow-ups include accumulated Q&A but must not duplicate per-round
   sections.

9. **XPrompt expansion in user answers.** Current Q&A markdown is wrapped in
   `%xprompts_enabled:false` / `%xprompts_enabled:true`. A family prompt template
   must not accidentally expand user answer text.

10. **Suffix collisions.** Dynamic suffixes must not collide with built-ins,
    legacy dotted/dashed suffixes, numeric feedback/question suffixes, or existing
    reserved agent names.

11. **Legacy artifacts.** Old `.plan`, `.code`, `-plan`, `-code`, and numeric
    suffix artifacts still need classification.

12. **Product choice vs runner protocol.** "Tale" is not a runner action today;
    it is `approve + commit_plan + run_coder`. Dynamic choices need a product id
    separate from compatibility response fields.

13. **Commit-only approval.** Current `"commit"` compatibility maps to
    `approve/run_coder=false`. A schema that treats every accepted plan as "next
    role" will miss this terminal path.

14. **Epic/legend SDD side effects.** Epic/legend paths force SDD commits because
    follow-up VCS workflows can wipe uncommitted files.

15. **Model picker and custom prompt model directives.** A custom coder prompt
    containing `%model` suppresses the inherited model prefix and changes the
    metadata written for the follow-up.

16. **Worker lane resolution drift.** Current coder handoff resolves the worker
    lane from the planner's concrete provider/model. Deferring that lookup until
    follow-up launch can change behavior.

17. **`SASE_PLAN` semantics.** The code phase receives the committed SDD plan
    only when that file was actually committed; otherwise it receives the archived
    plan path.

18. **Chat inheritance.** `SASE_CODER_INHERIT_PLANNER_CHAT=1` changes the coder
    prompt with `#fork:<planner>`. A role schema should expose this as a role
    property, not leave it as a global-only special case.

19. **Auto-approval and unattended jobs.** Current auto-plan behavior has
    environment and `agent_meta` precedence and only supports `approve`/`epic`.
    Dynamic gates need a generalized auto policy before any new blocking path is
    enabled.

20. **TUI transient status overrides.** ACE currently sets immediate statuses
    like `PLAN`, `QUESTION`, `ANSWERED`, `PLAN APPROVED`, `TALE APPROVED`, and
    `EPIC APPROVED` from notification actions and family metadata. Dynamic roles
    need data-driven labels and progress rules.

21. **Root vs child notification routing.** Question notifications carry both
    phase and root timestamps so ACE can mark multiple visible rows. Generic
    gates need equivalent routing keys.

22. **Mobile action support.** Rust mobile action details currently expose closed
    choices for `PlanApproval`, `HITL`, and `UserQuestion`. New gate kinds or
    choices require Rust/mobile contract updates.

23. **Config-only workflows are invisible to Rust catalog.** If family YAML lives
    only in `sase.yml`, editor/mobile/core paths will not see it without new
    catalog support.

24. **Workflow HITL feedback is not plan feedback.** The current workflow executor
    does not regenerate an agent step from HITL feedback. Do not assume
    `hitl: true` can replace plan-feedback loops.

25. **Crash recovery during a gate.** If the runner or TUI dies while a request is
    pending, artifacts, pending-action state, and response dirs need enough state
    for a later ACE session or CLI action to finish the gate.

26. **Family config edits mid-run.** A running family should use the definition
    hash it started with, or persist enough of the compiled graph to avoid
    changing transitions under an active agent.

27. **Nested agent launches.** If future `/sase_run` launches agents from inside
    a dynamic family, launch approval and family transition approval are separate
    gates and should not be conflated.

28. **Security of side effects.** Family YAML should select from curated
    code-backed side effects, not run arbitrary bash/python for plan approval
    bookkeeping.

## Recommended Architecture

### 1. Keep skills and host commands small

Generated skills should continue to document how agents submit structured
requests. Host commands should remain the enforcement point.

For terminating skills, define a small command/event adapter:

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

This adapter can live near xprompt sources and be discoverable, but it should not
pretend to be a normal `WorkflowStep` graph.

### 2. Add first-class family definitions

Create a dedicated declarative family schema. It can be YAML and share xprompt
discovery, but it should be validated/executed by a family evaluator, not by the
existing workflow executor.

Sketch:

```yaml
kind: agent_family
schema_version: 1
id: standard
version: 1
entry_role: plan

roles:
  plan:
    suffix: "--plan"
    label: "PLANNER"
    prompt: "{{ original_prompt }}"
    on_event:
      plan_submitted: plan_review

  code:
    suffix: "--code"
    label: "CODER"
    inherit_chat_from: null
    model_policy: worker_for_primary
    prompt: |
      {{ model_prefix }}{{ resume_prefix }}{{ vcs_prefix }}@{{ coder_plan_ref }}

      The above plan has been reviewed and approved. Implement it now.{{ coder_extra }}
      {{ embedded_refs }}

gates:
  plan_review:
    renderer: plan_approval
    request_protocol: plan_request_v1
    response_protocol: plan_response_v1
    choices:
      approve:
        label: "Approve"
        compatibility_response: { action: approve, commit_plan: false, run_coder: true }
        goto: code
      tale:
        label: "Tale"
        compatibility_response: { action: approve, commit_plan: true, run_coder: true }
        side_effects: [write_sdd, commit_sdd, set_sase_plan_env]
        goto: code
      feedback:
        label: "Feedback"
        compatibility_response: { action: reject }
        accumulate: feedback_bullets
        loop_to: plan
      commit:
        label: "Commit plan"
        compatibility_response: { action: approve, commit_plan: true, run_coder: false }
        side_effects: [write_sdd, commit_sdd]
        terminate: plan_committed

events:
  questions_submitted:
    gate: user_questions
    return_to: interrupted_role
    answer_fold: default_qa_markdown
```

The exact schema can change. The key properties are:

- roles, gates, events, transitions, and side effects are separate concepts;
- compatibility response fields are explicit adapters, not the product model;
- side effects are named and curated;
- prompt templates use validated context variables;
- questions are modeled as an interrupt event that returns to the interrupted
  role.

### 3. Normalize marker handling into typed events

Keep `.sase_plan_pending` and `.sase_questions_pending` for compatibility, but
convert them into typed events inside the runner:

- `plan_submitted`;
- `questions_submitted`;
- later `launch_requested`, `memory_review_requested`, or other events if needed.

Longer term, add one generic marker envelope:

```json
{
  "schema_version": 1,
  "event": "questions_submitted",
  "command_id": "questions",
  "gate_id": "user_questions",
  "payload": {},
  "timestamp": 1781712000.0
}
```

The runner should preserve the existing event order:

1. detect user kill first;
2. consume marker files;
3. reject stale/new markers that do not correspond to the kill;
4. normalize interrupted artifacts;
5. ask the family evaluator what happens next.

### 4. Preserve current PlanApproval/UserQuestion renderers first

Do not start with a fully generic form renderer. Start by making the current
renderer protocols data-driven:

- `renderer: plan_approval` uses current `plan_request.json` /
  `plan_response.json`, current modal, current mobile action, and current
  side-effect adapters;
- `renderer: user_question` uses current `question_request.json` /
  `question_response.json`, current modal, current answer folding;
- `renderer: hitl` stays workflow-step HITL.

After default behavior is equivalent, add a generic `decision` renderer for
simple custom choices.

### 5. Persist family identity and state on artifacts

Add metadata fields before enabling custom families:

- `agent_family_config_id`;
- `agent_family_config_version`;
- `agent_family_config_hash`;
- `agent_family_role`;
- `role_suffix`;
- `active_gate_id` when blocked;
- `family_state` object for counters, visited roles, accumulated feedback/Q&A
  references, and current prompt base.

Do not rely on reloading the user's current YAML to interpret old rows.

### 6. Move pure semantics into `sase-core` after Python parity

Python should remain responsible for subprocesses, marker files, Textual modals,
filesystem side effects, and prompt execution.

Shared semantics should move or mirror into Rust once stable:

- family schema validation;
- role/suffix classification;
- transition resolution;
- pending-action kind and state modeling;
- scan wire fields;
- mobile action detail choices;
- editor/catalog discovery for family definitions.

This follows the existing Rust-core boundary: if CLI, TUI, mobile, editor, and a
future web UI must agree, it belongs in core.

## Implementation Sequence

1. **Golden-equivalence harness.** Build tests that replay current approve, tale,
   commit-only, epic, legend, feedback, question-before-plan, question-during-code,
   and auto-approve flows through a compiled `standard` family and assert the same
   prompts, suffixes, metadata, response JSON, and side effects.

2. **Family dataclasses and loader.** Load only the built-in `standard` family.
   Keep current marker files and response files.

3. **Event adapter layer.** Convert plan/question markers into typed events, then
   route through the default family evaluator while preserving legacy behavior.

4. **Persist family metadata.** Add config id/version/hash and `family_state` to
   artifacts. Update Python and Rust scan wires.

5. **Data-driven plan choices.** Move the hardcoded TUI/mobile plan choice table
   behind the family/gate definition while keeping current labels and shortcuts.

6. **Custom roles/gates.** Allow additional roles such as `review`, with validated
   suffixes, prompt templates, transitions, loop limits, and side-effect ids.

7. **Generic decision renderer.** Add only after the built-in plan/question
   renderers are data-driven and equivalent.

8. **Core migration.** Move pure validation/classification/transition pieces into
   `sase-core`, updating bindings and parity tests.

## Validation Checklist

Minimum tests before custom families are enabled:

- marker freshness and stale marker rejection;
- explicit user kill with marker files present;
- duplicate response conflict;
- plan approval response compatibility for approve/tale/commit/epic/legend;
- feedback round suffix allocation with reserved names;
- question in root, plan, feedback, code, epic, and custom roles;
- Q&A markdown wrapping with xprompt expansion disabled;
- SDD write/commit behavior for version-controlled and non-version-controlled
  SDD dirs;
- `SASE_PLAN` value for committed and uncommitted approvals;
- coder model picker, worker lane resolution, and custom prompt `%model`;
- `SASE_CODER_INHERIT_PLANNER_CHAT`;
- auto-approval precedence;
- TUI root/child status overrides;
- mobile pending-action states;
- Rust/Python scan wire parity;
- old artifact compatibility.

## Recommended Solution

Do not implement "one ordinary xprompt workflow YAML per terminating skill
command" as the primary model. That would make commands own lifecycle logic that
actually belongs to the agent family, and it would overload the existing workflow
executor with kill/resume semantics it does not have.

Instead, implement dynamic agent families as a dedicated YAML-backed family
state-machine layer:

1. Generated skills remain short instructions.
2. Terminating host commands emit typed handoff events and kill the runner.
3. The runner consumes markers, normalizes interrupted artifacts, and asks the
   family evaluator what to do next.
4. Family YAML declares roles, gates, transitions, prompt templates, renderer ids,
   compatibility response mappings, and curated side effects.
5. Existing `PlanApproval` and `UserQuestion` protocols remain compatibility
   renderers for the first release.
6. Artifacts persist family id/version/hash and `family_state` so old rows are
   self-describing.
7. Pure validation, suffix classification, transition semantics, and frontend
   action contracts migrate to `sase-core` after Python parity is proven.

This keeps the good part of the plan, a declarative xprompt-adjacent extension
surface, while avoiding the critical flaw of making command YAML files pretend to
be durable family executors.

## Open Questions

- Should family definition files live under `xprompts/families/*.yml`,
  `agent_families/*.yml`, or regular `xprompts/*.yml` with `kind: agent_family`?

- Should config-defined families be supported in `sase.yml` v1, knowing Rust
  catalog support currently ignores config-defined workflows?

- What is the first custom family you want to support: planner -> reviewer ->
  coder, multi-reviewer consensus, research synthesis, or something else?

- Should custom gates be allowed to add new TUI keybindings/buttons in v1, or
  should v1 only remap existing plan/question renderer choices?

- What side effects should be exposed as curated ids beyond current SDD write,
  commit, `SASE_PLAN`, bead initialization, and chat inheritance behavior?

- How strict should loop detection be for custom role graphs: static acyclic
  except explicit feedback loops, or dynamic max-visit counters per role?

- Should dynamic family definitions be snapshot-copied into each root artifact
  directory, or is storing source path plus hash enough?

- Should auto-approval policies be family-wide, gate-specific, or both?

- How much of prompt assembly should be pure/core-owned versus Python/Jinja-owned?

- Should a generic `DecisionApproval` notification action be added before custom
  gates, or should all v1 custom behavior be expressed through `PlanApproval` and
  `UserQuestion` compatibility renderers?
