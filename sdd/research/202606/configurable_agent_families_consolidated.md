# Configurable Agent Families: Planner, Coder, Plan Feedback, and Questions

Status: Consolidated research
Date: 2026-06-02

This consolidates the prior research from:

- `sdd/research/202606/configurable_agent_families.md`
- `sdd/research/202606/configurable_agent_family_workflows.md`

The request is to make SASE's planner/coder handling, plan feedback, agent questions,
and user answers fully configurable so users can define their own agent family
configurations.

## Verified Current State

### Agent-family identity is fixed around plan-chain suffixes

`src/sase/plan_chain.py` owns the current role vocabulary:

- `-plan` for the planner.
- `-q` for a question phase.
- `-code` for the coder.
- `-epic`, `-legend`, and `-commit` for special approval outcomes.
- `-2`, `-3`, ... for feedback or question follow-up rounds.

`canonical_plan_chain_suffix()` only recognizes this closed set plus numeric
rounds, and `agent_family_role_for_suffix()` maps those suffixes to fixed role
strings. Follow-up artifacts then write `role_suffix`, `agent_family`, and
`agent_family_role` in `create_followup_artifacts()`.

This is not only Python-local. The Rust scanner wire in `../sase-core` already
contains `agent_family`, `agent_family_role`, `plan_chain_root`, and `role_suffix`
fields, and the scanner reads those from artifact metadata. The TUI also hardcodes
phase labels and status rules around these suffixes, for example prompt-panel labels
like `PLANNER` and `CODER`, and status overrides for "PLAN APPROVED", "TALE DONE",
epic follow-ups, and feedback children.

Implication: configurability cannot stop at the runner. Role identity and suffix
classification are a cross-frontend contract, and old artifacts must remain
classifiable.

### The runner is a marker-driven state machine

The runner loop in `src/sase/axe/run_agent_exec.py` executes the current prompt as
an anonymous xprompt workflow. If the agent process is killed, the loop checks for
special marker files:

- `.sase_plan_pending` routes to `handle_plan_marker()`.
- `.sase_questions_pending` routes to `handle_questions_marker()`.

`sase plan <file>` formats and archives the plan, writes `.sase_plan_pending`, and
SIGTERMs the agent runner process group. `sase questions '<json>'` validates a
fixed question schema, writes `.sase_questions_pending`, and SIGTERMs the runner.

Implication: the current lifecycle is not a normal linear workflow execution. It is
a resumable, human-gated state machine driven by marker files and follow-up artifact
directories.

### Plan approval is a hardcoded decision protocol

`src/sase/llm_provider/_plan_utils.py` creates a `plan_request.json`, sends a
`PlanApproval` notification, and polls for `plan_response.json`. The response is
parsed into `PlanApprovalResult` with:

- `action`
- `feedback`
- `commit_plan`
- `run_coder`
- `coder_prompt`
- `coder_model`

The TUI modal in `src/sase/ace/tui/modals/plan_approval_modal.py` hardcodes the
product choices and maps them to runner-facing fields:

- `approve`: `action=approve`, `commit_plan=false`, `run_coder=true`
- `tale`: `action=approve`, `commit_plan=true`, `run_coder=true`
- `epic`: `action=epic`, `commit_plan=true`, `run_coder=true`
- `legend`: `action=legend`, `commit_plan=true`, `run_coder=true`
- `feedback`, `reject`, `edit`, and `custom` are also hardcoded modal actions.

`handle_plan_marker()` then branches imperatively:

- `feedback` increments the feedback round, appends a feedback bullet, creates a
  numeric follow-up suffix, and rebuilds the prompt as original prompt plus merged
  Q&A plus an `### Additional Requirements` section.
- accepted plans write SDD prompt/plan files, decide whether to commit those files,
  and set plan metadata.
- `run_coder=false` terminates as `plan_committed`.
- `epic` or `legend` spawns `#bd/new_epic` or `#bd/new_legend`.
- otherwise the coder is spawned with `-code` and a fixed prompt shape:
  `@<plan_ref>` followed by "The above plan has been reviewed and approved.
  Implement it now.", plus optional custom coder text.

There is a subtle protocol split worth preserving: the user-facing `tale` choice
is stored as `action=approve` with `commit_plan=true`, then runner metadata derives
`plan_action=tale`. A configurable design should model product choices separately
from legacy runner response fields.

The modal-side result vocabulary is also wider than the runner branch names:
`feedback_requested` and `approve_prompt_edit` are modal actions that are converted
before the runner sees the final `plan_response.json`. `coder_prompt` and
`coder_model` are overrides attached to the same approval gesture, not a separate
phase.

### Agent questions use the same pause/resume pattern

The question path is analogous to plan approval:

- `handle_questions_flow()` writes `question_request.json`, sends a
  `UserQuestion` notification, records `pending_question.json`, and polls for
  `question_response.json`.
- `UserQuestionModal` renders the built-in question schema with options,
  multi-select, an "Other" answer, and a global note.
- The response writer stores `answers[]` and `global_note`.
- `handle_questions_marker()` appends a `QARound`, renders all accumulated Q&A
  through `build_merged_qa_markdown()`, creates a numeric follow-up, and rebuilds
  the next prompt as original prompt plus the merged Q&A block.

The Q&A renderer intentionally emits one `### Questions and Answers` block with
monotonic numbering and wraps it in `%xprompts_enabled:false` /
`%xprompts_enabled:true`. That behavior is part of the prompt contract and should
not drift across frontends.

### There are three separate human-gate protocols

Plan approval, user questions, and workflow HITL are not one abstraction today.
Workflow HITL has its own `HITLResult` actions (`accept`, `reject`, `edit`,
`feedback`, `rerun`), `hitl_request.json` / `hitl_response.json` files, and
`sender="hitl"` notifications. Plan approval uses `sender="plan"` and
`PlanApproval`; questions use `sender="question"` and `UserQuestion`.

Those notifications are also mirrored into pending-action files used by external
transports such as mobile and Telegram integrations. A configurable family design
therefore has to define gates once while preserving the existing IPC shapes and
notification action names until every client can understand the new payloads.

The notification wire itself does not need redesign for new gate kinds. The Rust
core already carries a generic envelope —
`NotificationWire { action: Option<String>, action_data: BTreeMap<String, _>, … }`
in `../sase-core/crates/sase_core/src/notifications/wire.rs`. Plan and question
notifications already fit it by setting `action` to `"PlanApproval"` /
`"UserQuestion"` and stashing `response_dir`/`session_id` in `action_data`, so
adding user-defined gate kinds costs nothing at the wire layer; the IPC concern
is at the *sender/payload-shape* and modal-renderer layers above it.

### Existing extensibility assets are useful but incomplete

SASE already has useful primitives:

- A mature config merge stack: package defaults, plugin defaults, user config,
  overlays, and local `./sase.yml`.
- xprompts and xprompt workflow YAML.
- A workflow model with agent, bash, python, prompt_part, parallel, conditions,
  repeat/while loops, and `hitl: true`.
- TUI and CLI HITL support for workflow steps.

However, the plan chain does not run as a declared workflow. Workflow HITL today is
an accept/reject/edit review of a completed step output, while plan approval needs
multi-choice routing, feedback loops, SDD side effects, role suffixes, follow-up
artifact creation, and artifact-compatible status reconstruction.

Two more existing knobs that a family schema must subsume rather than rediscover:

- `SASE_CODER_INHERIT_PLANNER_CHAT=1` (`run_agent_exec_plan.py:548`) prepends
  `#fork:<base>-plan ` to the coder prompt so the coder reuses the planner's
  chat transcript rather than starting cold from the plan file alone. Off by
  default. A configurable family should expose this as a per-role flag (e.g.
  `inherits_chat_from: plan`); reviewer/test roles often want planner context
  for the same reason coders sometimes do.
- The headless auto-approve path returns the closed literal
  `PlanAutoApprovalAction` (`"approve"` | `"epic"`) and consults
  `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION`, `SASE_AGENT_AUTO_PLAN_ACTION`,
  `agent_meta.auto_approve_plan_action`, then
  (`SASE_AGENT_AUTO_APPROVE` or `agent_meta.approve`) → `"approve"`
  (`plan_approve_handler.py:43-61`). Today's auto-pilot therefore knows only
  two terminal targets; the configurable `auto_pilot` block in §"Requirements"
  must widen the return type to whatever choices a family declares, and must
  preserve this precedence so CI/batch flows do not regress.

## Requirements For Configurable Families

A real agent-family configuration needs to express:

1. Roles: an open set of role ids, suffixes, display labels, model/runtime
   overrides, prompt templates, and whether the role emits a plan, asks questions,
   or runs ordinary agent work.
2. Gates: human decision points with labels, keybindings, response payloads, input
   requirements, and optional UI capabilities such as edit, feedback text, model
   choice, or custom prompt.
3. Transitions: mappings from gate outcome to next role, loop target, termination,
   and curated side effects.
4. Prompt assembly: rules for combining original prompt, plan file, committed SDD
   path, Q&A rounds, feedback bullets, custom user instructions, model prefixes,
   VCS workflow refs, and embedded workflow refs.
5. Question handling: how question payloads are rendered, how answers are merged,
   and which role receives the follow-up after answers are submitted.
6. Auto-pilot policy: a general version of the current auto-approve environment and
   metadata flags, not limited to `approve` and `epic`.
7. Artifact compatibility: persisted `role_suffix`, `agent_family_role`, family id,
   `parent_timestamp`, `sdd_plan_path`, `plan_committed`, `SASE_PLAN` propagation,
   and preferably family version/hash so old artifacts remain interpretable after a
   user edits the family config.
8. Frontend consistency: a CLI, TUI, mobile action, or future web client must agree
   on transition semantics and prompt assembly.
9. Safe side effects: users configure which built-in side effects run, not arbitrary
   code execution from a family YAML file.

## Options Considered

### Option A: Parameterize the existing Python state machine

This extracts today's constants into config: suffixes, coder prompt, coder model,
approval choice table, feedback prompt template, and question rendering knobs.

This is the smallest useful first step and would quickly unlock custom coder
prompts/models and maybe extra approval choices. It is not enough by itself because
the lifecycle shape remains fixed around planner -> feedback -> coder/epic/legend/
commit.

### Option B: Move the plan chain directly onto xprompt workflows

This would reuse `WorkflowStep`, `hitl`, conditions, loops, and prompt templating.
It is attractive because users already have a workflow DSL.

The problem is that today's workflow engine does not model the hard parts of the
plan chain: kill/resume handoff, multi-choice gates, family role suffixes,
artifact-driven branching, SDD commit side effects, and unbounded feedback/Q&A
rounds that create new family members. Forcing all of that into the existing
workflow engine would be a large rewrite and would likely distort the workflow DSL.

### Option C: Dedicated agent-family schema with a state-machine evaluator

This introduces a first-class agent-family definition that names roles, gates,
transitions, side effects, and prompt assembly. The current planner/coder flow
becomes the built-in default family. The existing marker loop remains the first
executor, but it asks the family evaluator what to do next instead of branching on
hardcoded actions.

This best fits the domain. The prior notes differed mostly on timing: one favored
putting the evaluator in `sase-core`, while the other favored a Python pipeline
schema executed by the current loop first. These are compatible. Define the schema
and pure transition model now, execute it through the current Python loop at first,
and move or mirror pure evaluation/classification into `sase-core` as the shared
backend contract.

## Proposed Shape

The schema should live in the existing layered config system, either under
`agent_family:` in `default_config.yml` and user `sase.yml`, or as named
`families/*.yml` files loaded into that section. Plugins can contribute defaults
through the same config path.

Sketch:

```yaml
agent_family:
  default: standard
  families:
    standard:
      entry: plan

      roles:
        plan:
          suffix: "-plan"
          label: "PLANNER"
          prompt: "{{ original_prompt }}"
          emits: plan_file
          gate: plan_review

        code:
          suffix: "-code"
          label: "CODER"
          prompt: |
            {{ model_prefix }}{{ resume_prefix }}{{ vcs_prefix }}@{{ coder_plan_ref }}

            The above plan has been reviewed and approved. Implement it now.{{ coder_extra }}
            {{ embedded_refs }}

        epic:
          suffix: "-epic"
          label: "EPIC"
          prompt: "{{ model_prefix }}{{ vcs_prefix }}#bd/new_epic:{{ epic_plan_ref }}"

        legend:
          suffix: "-legend"
          label: "LEGEND"
          prompt: "{{ model_prefix }}{{ vcs_prefix }}#bd/new_legend:{{ legend_plan_ref }}"

      gates:
        plan_review:
          kind: plan_approval
          choices:
            approve:
              key: "a"
              protocol: {action: approve, commit_plan: false, run_coder: true}
              goto: code

            tale:
              key: "t"
              protocol: {action: approve, commit_plan: true, run_coder: true}
              metadata: {plan_action: tale}
              side_effects: [write_sdd, commit_sdd, record_plan_metadata, set_sase_plan_env]
              goto: code

            epic:
              key: "E"
              protocol: {action: epic, commit_plan: true, run_coder: true}
              side_effects: [write_sdd, commit_sdd, ensure_beads]
              goto: epic

            legend:
              key: "L"
              protocol: {action: legend, commit_plan: true, run_coder: true}
              side_effects: [write_sdd, commit_sdd, ensure_beads]
              goto: legend

            feedback:
              key: "f"
              protocol: {action: feedback}
              loop_to: plan
              accumulate: feedback_bullets
              suffix_series: feedback_round

            commit:
              protocol: {action: commit, commit_plan: true, run_coder: false}
              side_effects: [write_sdd, commit_sdd]
              terminate: plan_committed

            reject:
              protocol: {action: reject}
              terminate: plan_rejected

      questions:
        kind: user_question
        response_suffix: "-q"
        followup_suffix_series: feedback_round
        fold_answers_into_prompt: default_qa_markdown
        return_to: previous_role

      auto_pilot:
        plan_review:
          default_choice: approve
```

This is not a final schema. The important split is:

- Product choices are configurable (`tale`, `epic`, custom names).
- Legacy response fields can be preserved while old clients still write
  `plan_response.json`.
- Roles and suffixes come from the family definition.
- Side effects are a finite, named catalog implemented in code.
- Prompt assembly is templated but uses explicit, validated context variables.

With this shape, a user can insert a plan-review agent by adding a `review` role
with suffix `-review`, routing `approve` to `review`, and routing `review` success
to `code`. If the reviewer itself calls `sase plan`, the same plan gate can run
again, producing a review -> re-approval -> code loop without changing the runner.
The engine must still prevent accidental `review -> review` loops, either with an
explicit `once: true` role flag or persisted `family_state.visited_roles`.

The most stable executor boundary is the existing marker restart, so the engine
should normalize restarts into typed events:

- `plan_submitted`
- `plan_feedback_received`
- `plan_approved`
- `questions_submitted`
- `questions_answered`

Current JSON can remain compatible while rollout happens. Add optional `family_id`,
`gate_id`, and `choice_id`; prefer those when present, and fall back to today's
`action` plus flags for old clients.

## Implementation Plan

### Phase 1: Extract the default behavior into config-backed data

Add Python dataclasses and a loader for the default `standard` family. Keep
`handle_plan_marker()` and `handle_questions_marker()` as the executor, but replace
the hardcoded approval table, coder prompt shape, model choice, and basic transition
selection with loaded config.

This phase should preserve the existing response JSON and marker names. It should
ship tests proving that the default family produces the same prompts, suffixes, SDD
commit choices, and metadata as today's code for approve, tale, commit-only, epic,
legend, feedback, and question-answer rounds.

Use a golden-equivalence harness for the default family: replay representative
planner, feedback, question, approve, tale, epic, legend, and commit-only flows
through the legacy path and the new engine, and assert identical prompts, suffix
sequences, response payloads, metadata writes, and follow-up artifact relationships.

### Phase 2: Allow custom roles and gates in the existing loop

Generalize follow-up artifact creation so role suffix and role name are supplied by
the active family. Add validation for unique suffixes, reserved suffix collisions,
dangling transitions, invalid side effects, unknown prompt variables, and missing
entry roles.

Hyphenated names are currently reserved for internal family phases, so a custom
suffix such as `-review` must be registered by the family loader and validated
against built-in suffixes, numeric feedback suffixes, and other active families.

Update the TUI surfaces that currently hardcode plan-chain roles:

- phase labels in the prompt panel
- status override rules
- agent grouping and family completeness
- plan/question notification action handlers
- mobile or external action routing that writes response files

Persist at least `agent_family`, `agent_family_role`, `role_suffix`, and a
`agent_family_config_id` or version/hash in artifact metadata. Put new dynamic
state such as visited roles, current gate, and repeat counters under a
`family_state` object rather than flattening more top-level fields. Relying on the
current user config to interpret historical artifacts will break once users edit
family definitions.

### Phase 3: Move pure semantics to `sase-core`

Move or mirror the pure pieces into `sase-core`:

- family schema validation that does not depend on the TUI
- role/suffix classification
- transition resolution
- prompt assembly directives, or prompt assembly itself if templating is available
  in a controlled way

Keep Python responsible for host mechanics: marker files, subprocess spawning,
artifact directory creation, Textual modals, and executing curated side effects.
The Rust wire already carries the relevant family metadata, so this phase is a
natural extension of the existing backend boundary rather than a new architectural
direction.

### Phase 4: Make questions and generic decision UIs configurable

After the plan gate is data-driven, make the question flow configurable:

- family-specific question renderers or renderer ids
- answer folding policy
- target role after answers
- generic gate modal for configured choices
- compatibility adapters for existing `plan_response.json` and
  `question_response.json`

Do not start by trying to make every UI field arbitrary. Preserve the current plan
approval modal and user-question modal as built-in gate renderers, then add a
generic decision renderer only once the data model has stabilized.

### Phase 5: Optional workflow convergence

Keep the family schema vocabulary close to `WorkflowStep` where it makes sense:
`prompt`, `when`/`condition`, model directives, xprompt refs, and HITL concepts.
That gives SASE a path to lower family phases onto the workflow engine later.

Do not make that the first implementation. The current workflow engine would need
kill-resumption, family naming, multi-choice gates, and side-effect routing before
it could own this lifecycle.

## Risks

- Schema overlap with workflow YAML could confuse users. Mitigate by documenting
  the difference: workflows are scripted step orchestration; families are
  long-lived, human-gated role state machines.
- Configurable side effects can become unsafe if they allow arbitrary commands.
  Keep them as a curated code-backed catalog.
- Dynamic suffixes can break agent grouping and old artifact scanning. Store role
  metadata and family version/hash with each artifact.
- Dynamic suffixes also collide with the reserved-hyphen contract for user agent
  names. Multi-family workspaces need either per-family suffix namespaces or a
  clear rule that rejects duplicate suffixes.
- Status reconstruction is a hidden migration cost. The runner, TUI models, prompt
  panel, notifications, mobile actions, and revive paths all know plan-chain terms.
- Gate configuration has to bridge three existing decision systems: plan approval,
  user questions, and workflow HITL. Preserve current notification senders and
  response files while generating them from one declared gate model.
- Multi-role chains need loop detection. A reviewer that calls `sase plan` can
  re-enter the same gate; the family state must support intentional reruns without
  accidental infinite review loops.
- Generic gates can balloon in scope. Start with configured choices rendered by the
  existing plan/question modals before building a fully generic form system.

## Recommended Solution

Build a dedicated declarative `agent_family` schema for human-gated agent role
state machines, and make today's planner/coder flow the built-in `standard`
family. Do not force this lifecycle directly into the existing workflow engine, and
do not stop at simple suffix/config knobs.

Implement it in phases: first load the default family through the existing config
stack and have the current marker-driven Python loop consult that data for choices,
transitions, prompts, and side effects. Then allow custom roles and gates, update
all TUI/status surfaces to render from family metadata, and persist a family
config id/version with artifacts. Finally, move pure validation, role/suffix
classification, transition resolution, and prompt assembly semantics into
`sase-core` so every frontend agrees while Python remains the host for subprocesses,
markers, modals, artifacts, and curated side effects.
