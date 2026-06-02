# Configurable Agent Families: Planner/Coder Chains, Plan Feedback, and Q&A

**Status:** Research / design proposal
**Date:** 2026-06-02
**Author:** Agent research (requested by Bryan)

## Goal

Make SASE's handling of **planner and coder agents**, **user feedback on plans**,
and **agent questions / user answers** entirely configurable, so users can define
their own *agent family configurations* — their own set of roles, the transitions
between them, the prompts each role runs, and the human decision points that drive
those transitions.

Today these are hardwired into a Python state machine. This document maps the
current implementation, derives the requirements for configurability, evaluates
design options, and ends with a recommended solution.

---

## 1. Current architecture (as-is)

### 1.1 The "plan chain" is a hardcoded state machine

The planner→feedback→coder/epic/legend/commit lifecycle is an implicit state
machine implemented in Python, **separate** from the general xprompt workflow
engine. Its vocabulary lives in `src/sase/plan_chain.py`:

| Constant | Value | Role |
|---|---|---|
| `PLAN_CHAIN_PLAN_SUFFIX` | `-plan` | planner |
| `PLAN_CHAIN_QUESTION_SUFFIX` | `-q` | question phase |
| `PLAN_CHAIN_CODER_SUFFIX` | `-code` | coder |
| `PLAN_CHAIN_EPIC_SUFFIX` | `-epic` | epic-bead creator |
| `PLAN_CHAIN_LEGEND_SUFFIX` | `-legend` | legend-bead creator |
| `PLAN_CHAIN_COMMIT_SUFFIX` | `-commit` | commit-only |
| feedback rounds | `-2`, `-3`, … | revised planner |

`agent_family_role_for_suffix()` (`plan_chain.py:109-128`) is a hardcoded
`if/elif` mapping suffix → role string (`plan`, `q`, `code`, `epic`, `legend`,
`commit`, `feedback`). The set of roles, their suffixes, and their semantics are
**closed** — there is no way for a user to add a role (e.g. `-review`, `-test`,
`-design`) without editing this module.

### 1.2 Data model

**Python** (`agent.py`) and **Rust wire** (`sase-core .../wire.rs`) both carry the
same family fields on agent metadata:

```
role_suffix:        e.g. "-plan" / "-code"   (authoritative for new artifacts)
agent_family:       base family name, e.g. "add-auth"
agent_family_role:  semantic role: "plan" | "code" | "q" | "epic" | ...
plan_chain_root:    bool — root of the chain
```

Higher-level grouping is `AgentFamily` (`_lookup.py`): `base_name`, `root`,
`members[]`. **Python writes** these fields into `agent_meta.json`; **Rust reads**
them during artifact scanning. The roles are an enumerated contract shared across
the boundary.

### 1.3 Transition logic (the part users want to control)

The transitions are spread across three hardcoded sites:

1. **Decision choices** — `plan_approval_modal.py` defines
   `_PLAN_APPROVAL_CHOICE_PROTOCOL`, a fixed dict mapping each product choice to
   `(action, commit_plan, run_coder)`:

   | choice | action | commit_plan | run_coder |
   |---|---|---|---|
   | `approve` | approve | false | true |
   | `tale` | approve | true | true |
   | `epic` | epic | true | true |
   | `legend` | legend | true | true |

   Plus `feedback` (reject with text), `reject` (kill), `edit`, and a `custom`
   options modal. The choice keys (`a`/`t`/`e`/`L`/`c`/`f`/`r`) and their
   semantics are all hardcoded in the TUI modal.

2. **Dispatch** — `run_agent_exec_plan.py` consumes the `PlanApprovalResult`
   (`action`, `feedback`, `commit_plan`, `run_coder`, `coder_prompt`,
   `coder_model`) and branches:
   - `action == "feedback"` → increment `feedback_round`, append feedback bullet,
     spawn a revised planner with suffix `-{round+1}` and a **reconstructed
     prompt**: `original_prompt + merged Q&A + "### Additional Requirements" +
     bullets` (`run_agent_exec_plan.py:223-283`).
   - `run_coder=True` → spawn coder with `-code`; optionally commit SDD files.
   - `epic` / `legend` → commit + spawn `-epic` / `-legend`.
   - `run_coder=False, commit_plan=True` → `-commit`, no coder.

3. **Coder prompt** — fixed xprompt `src/sase/xprompts/coder.md`:
   `@{{ plan_file }}` + "The above plan has been reviewed and approved. Implement
   it now." The only per-run knobs are `coder_prompt` / `coder_model` overrides
   passed through the approval response.

### 1.4 The plan + question request/response IPC

Both flows use the same file-based IPC pattern between the agent subprocess and
the TUI:

**Plan** (`plan_command_handler.py`, `_plan_utils.py`):
1. Agent runs `sase plan <file>` → archives plan, writes `.sase_plan_pending`
   marker, **SIGTERMs its own process group** to pause.
2. Runner detects marker, writes `plan_request.json` to
   `~/.sase/plan_approval/<session>/`, sends a `Notification`
   (`sender="plan"`, `action="PlanApproval"`).
3. TUI modal writes `plan_response.json`; runner polls (0.5 s) and resumes.

**Questions** (`questions_command_handler.py`, `run_agent_helpers_questions.py`):
1. Agent runs `sase questions '<json>'` → writes `.sase_questions_pending`,
   SIGTERMs.
2. Runner writes `question_request.json` to `~/.sase/user_question/<session>/`,
   sends `Notification` (`sender="question"`, `action="UserQuestion"`).
3. TUI `UserQuestionModal` writes `question_response.json`
   (`answers[]` + `global_note`); runner polls and resumes.
4. Answers are merged into the next prompt via `build_merged_qa_markdown()` /
   `merge_qa_for_prompt()` (`qa_markdown.py`) and accumulated in
   `LoopState.qa_rounds`.

The **schema** of questions (list of `{question, options?, multiSelect?}`), the
**markdown rendering**, the **modal keybindings**, and the **way answers are
folded back into the prompt** are all hardcoded.

**Precise field map** (not captured in §1.3):

- `PlanApprovalResult.action` is wider than the four product choices imply. Its
  declared values (`plan_approval_modal.py:95`) are
  `approve | reject | epic | legend | feedback_requested | approve_prompt_edit`.
  `feedback_requested` is the runner-facing form of the `f` choice;
  `approve_prompt_edit` re-opens the modal after the user edited the coder prompt
  in-place. The product-level `tale` choice is *not* a distinct `action` — it
  collapses to `approve` with `commit_plan=True`. Any configurable schema must
  preserve this two-layer mapping (product choice → action + flags), not just the
  action enum.
- `coder_prompt` and `coder_model` on `PlanApprovalResult` are *override knobs*
  on the same approval result, not a separate phase. A configurable engine that
  splits "decide" from "prompt-assemble" needs to preserve the modal's ability to
  set these in the same gesture as choosing `approve`/`tale`.
- The question response carries `selected: [option_label, ...]` plus an optional
  `custom_feedback`/`global_note` (`questions_command_handler.py:15-39`,
  `user_question_modal.py`). The request/response live under
  `~/.sase/user_question/<session_id>/`, *not* `~/.sase/sase_plan/` — the two
  flows have separate root directories and that separation should be retained.

### 1.4.1 The workflow engine has its *own* HITL decision vocabulary

`src/sase/xprompt/workflow_hitl.py` ships a `TUIHITLHandler` whose
`HITLResult.action` is `accept | reject | edit | feedback | rerun`
(`workflow_hitl.py:123-237`). This is a **second, parallel decision system** with
its own file-based IPC (`hitl_request.json` / `hitl_response.json` in the
workflow artifacts dir) and its own notification sender
(`sender="hitl"`, action `HITL`).

So today SASE actually has *three* human-gate vocabularies — plan approval, user
questions, and workflow HITL — each with its own request/response shape, its own
notification sender, and its own modal. Any configurability proposal must
explicitly choose between (a) unifying them under one decision/IPC abstraction or
(b) keeping them separate and giving family configs a way to *select* which
gate-kind to open at each role boundary. The recommendation in §4 picks (a) at
the schema level and (b) at the IPC level (preserve the existing JSON shapes for
backward compatibility, but generate them from a single declared gate).

### 1.4.2 Family discovery and the reserved-hyphen contract

`src/sase/agent/names/_lookup.py:195-242` discovers families by joining sibling
artifact directories whose `agent_meta.json` shares an `agent_family` base name
and tracing `parent_timestamp` lineage to a `plan_chain_root`. "Completeness"
(used by TUI status mirroring and notification gating) requires every member to
report `outcome == "completed"`. Two consequences for configurability:

1. **Suffixes are not free-form.** `src/sase/agent/launch_validation.py:67-85`
   reserves the hyphen for family suffixes — user-launched agent names cannot
   contain `-`. A user-defined family that introduces `-review` therefore
   implicitly carves out a new reserved suffix; the loader must validate
   uniqueness against built-in suffixes (`-plan`, `-q`, `-code`, `-epic`,
   `-legend`, `-commit`, numeric feedback rounds) and against the workspace's
   active families to avoid collisions.
2. **Lineage, not enumeration, defines the family.** The family is rebuilt by
   walking `parent_timestamp` pointers, so adding a phase in the middle of the
   chain works as long as each new member writes a correct `parent_timestamp` to
   its predecessor's artifact dir. The configurable engine does not need a
   separate registry file; `agent_meta.json` remains the source of truth.

### 1.4.3 `agent_meta.json` fields already in use

Beyond the four family fields in §1.2, `agent_meta.json` also carries decision
state that today's auto-pilot consults
(`plan_approve_handler.py:43-61`,
`core/agent_scan_wire_markers.py`):

| Field | Meaning |
|---|---|
| `approve` | bool — short-circuit the modal, treat as `approve` choice |
| `auto_approve_plan_action` | one of `approve`/`epic`/`legend` (normalized lowercase) |
| `sdd_plan_path` | path to the committed plan file (set by `commit_sdd_files_for_exec_plan`) |
| `plan_committed` | bool — was SDD commit run |
| `parent_timestamp` | string — links the member to its predecessor's artifact dir |

There is **no `SASE_PLAN` environment variable** set by the runner today; the
original draft of this note incorrectly named one. Plan path persistence is via
the metadata field above. A configurable engine should preserve these field
names so already-running agents in older workspaces continue to scan correctly,
and should add new fields under a `family_state:` sub-object rather than
flattening more keys into the top level.

### 1.5 Existing extensibility primitives (what we can build on)

- **xprompt workflow YAML** (`workflow.schema.json`): already a rich, declarative,
  user-authorable workflow language. It supports `agent` steps, `prompt`/`bash`/
  `python`/`prompt_part`, `hitl` (human-in-the-loop) gates, `output` JSON-schema
  validation, `if`/`for`/`while`/`repeat` control flow, `parallel`, per-workflow
  `environment`, and embedded local xprompts. **This is the single most important
  asset for this project** — it is already a general agent-orchestration DSL.
- **xprompts** (`.md`/`.yml` in `xprompts/` dirs or `sase.yml`), with
  `xprompt_aliases`.
- **`default_config.yml`** — layered config (`ace:`, `axe:`, `llm_provider:`,
  `sdd:`, `xprompts:`, …) overridable in `~/.config/sase/sase.yml`.
- **Auto-approval hooks** — env vars `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION` and
  `SASE_AGENT_AUTO_PLAN_ACTION` (both accept `approve`/`epic`/`legend`,
  case-insensitive) and `SASE_AGENT_AUTO_APPROVE` (any truthy value collapses to
  `approve`), plus `SASE_CODER_INHERIT_PLANNER_CHAT=1` (prepends
  `#fork:<base>-plan` to the coder prompt, `run_agent_exec_plan.py:548`). Workflow
  HITL has its own switch via the `hitl_override` parameter on
  `execute_workflow`. A configurable `auto_pilot` block must generalize *both*
  vocabularies, not just the plan-chain env vars.
- **Notification transports** — `src/sase/notifications/senders.py` writes plan,
  question, and HITL notifications to `notifications.jsonl`; the same payload is
  mirrored into `pending_actions.json` for external transports
  (`pending_actions.py:45-48`, used by sase-telegram and any future mobile/web
  consumer). The transports key off `sender` (`plan`/`question`/`hitl`) and the
  `action_data.response_dir`/`session_id` fields; any new gate kind a family
  introduces must round-trip through this layer if it is to be answerable
  off-host. This makes the *gate schema* — not just the modal — a shared backend
  concern.

### 1.6 Where the logic lives (Python vs Rust core)

| Concern | Today | Boundary verdict |
|---|---|---|
| Family role enum, suffix mapping | Python `plan_chain.py`; Rust `wire.rs` only carries the *fields* (`agent_family`, `agent_family_role`, `plan_chain_root`) as opaque strings/bools — no enum, no transition logic | **Core** — every frontend (web, CLI, editor) must agree on role identity, and today only the wire shape is shared |
| Transition state machine | Python `run_agent_exec_plan.py` | **Core-ish** — the *rules* are backend; the *execution* (subprocess spawning) is host-specific |
| Plan/question request/response IPC | Python + markers; notification store in Rust | Mixed — IPC mechanics are host glue; notification persistence already in core |
| Approval modal, question modal | Python/Textual TUI | **Presentation** — stays in this repo |
| Prompt reconstruction / Q&A markdown | Python | **Core** — a web frontend would need identical merging |

Per `memory/short/rust_core_backend_boundary.md`: the *definition* and *evaluation*
of an agent family (roles, transitions, prompt assembly) is shared backend behavior
— a web app or CLI driving the same family would need it to match the TUI. The
*rendering* of the approval/question modals and the *subprocess mechanics* are
presentation/host glue that stays in Python.

---

## 2. Requirements for "configurable agent families"

A user-defined agent family configuration must be able to express:

1. **Roles** — an open set, each with: an id/role name, a name suffix, an
   optional model override, an optional runtime override, and a **prompt
   template** (an xprompt ref or inline content).
2. **Entry point** — which role starts the family (today always `-plan`), and the
   condition that promotes a plain prompt into a family (today: agent calls
   `sase plan`).
3. **Decision points** — at a role boundary, a set of **human choices** (the
   approval-modal buttons), each mapping to a transition. Must support:
   - "loop back with feedback" (revise current role, accumulate feedback),
   - "advance to role X" (e.g. coder),
   - "advance to role X **and** run side-effects" (e.g. commit SDD then coder),
   - "terminate" (commit-only / reject).
4. **Prompt assembly rules** — how the next role's prompt is built from: the
   original prompt, the produced artifact (plan file), accumulated Q&A,
   accumulated feedback bullets, and arbitrary custom text.
5. **Question handling** — the question schema, how answers render, and how they
   fold into subsequent prompts (today fixed; should be at least
   family-overridable).
6. **Auto-pilot policy** — per-role/per-decision auto-approve rules for headless
   runs (generalizing today's env-var auto-approve).
7. **Backwards compatibility** — the existing plan/tale/epic/legend/commit family
   must be expressible as the *default* configuration with byte-for-byte
   equivalent behavior.

---

## 3. Design options

### Option A — Parameterize the existing state machine (config knobs)

Add `agent_family:` config blocks to `default_config.yml`/`sase.yml` that override
the existing constants: suffix strings, coder xprompt path, coder model, the
approval-choice→protocol table, and the feedback-prompt template.

- **Pros:** smallest change; no new engine; immediate wins (custom coder prompt,
  custom suffixes, extra approval choices).
- **Cons:** still a fixed *shape* (plan→feedback→one-of-{coder,epic,legend,
  commit}). Users can't add genuinely new roles or multi-step chains
  (plan→review→coder→test). The transition rules stay in Python. Doesn't unify
  with the workflow engine — two parallel orchestration systems persist.

### Option B — Express families as xprompt workflows (reuse the DSL)

Model an agent family as a workflow YAML, leaning on `agent` steps + `hitl` gates
+ loops. A "decision point" becomes an `hitl` step whose `output` schema captures
the chosen action; `if`/`while` route to the next `agent` step.

- **Pros:** reuses a mature, user-authorable DSL and its tooling; one orchestration
  system instead of two; loops/conditionals already exist (feedback rounds map to
  `while`/`repeat`).
- **Cons:** the current `hitl` boolean is far less expressive than the plan
  approval modal (multi-choice, edit-in-place, custom options, feedback text).
  The workflow engine is step-sequential, whereas the plan chain has rich,
  artifact-driven branching and per-role agent identity (suffixes, family
  metadata). Bridging requires extending the workflow schema (richer `hitl`
  decisions, role/suffix metadata on `agent` steps) — non-trivial, and risks
  contorting the workflow DSL.

### Option C — A dedicated declarative "Agent Family" schema, executed by a core state-machine engine (recommended)

Introduce a first-class, declarative **agent-family definition** (its own schema,
sibling to `workflow.schema.json`) that names roles, decisions, transitions, and
prompt-assembly rules. The *current plan chain becomes the built-in default
instance of this schema*. A small **state-machine evaluator** in `sase-core`
consumes (family-def, current-state, decision) → (next-role, prompt-assembly
directives, side-effects); Python remains the **host** that spawns subprocesses,
runs the modals, and performs side-effects (SDD commit, etc.).

- **Pros:** directly matches the requirements; open role set; arbitrary chains;
  evaluation lives in core so every frontend agrees; default family preserves
  today's behavior exactly; decisions are richer than `hitl` without distorting
  the workflow DSL.
- **Cons:** most design + implementation effort; needs a new schema, a core
  engine, and a migration of `run_agent_exec_plan.py` to drive the engine instead
  of hardcoded branches.

---

## 4. Recommended solution

**Adopt Option C, delivered in phases, with Option A as the Phase-1 down payment.**

The plan chain is not really "a workflow" in the linear xprompt sense — it is a
**human-gated state machine over agent roles with artifact-driven branching**. It
deserves its own declarative schema rather than being shoehorned into the workflow
DSL (Option B) or left as frozen Python (Option A alone). But we can ship value
immediately by first extracting the hardcoded constants into config (Option A),
then grow that config into the full schema (Option C).

### 4.1 The Agent Family definition schema (sketch)

A new `~/.config/sase/families/*.yml` (and a built-in `default` shipped in-repo),
validated by a new `agent_family.schema.json`:

```yaml
# families/default.yml  — reproduces today's plan chain
name: default
entry: plan                      # starting role
roles:
  plan:
    suffix: "-plan"
    # the planner is just "the user's prompt"; it ends by calling `sase plan`
    produces: plan_file          # the artifact this role yields at its gate
    gate: plan_review            # decision shown when this role finishes
  code:
    suffix: "-code"
    prompt: "#coder plan_file={{ plan_file }}"   # xprompt ref, fully overridable
    model: "{{ decision.coder_model | default(parent.model) }}"
  epic:
    suffix: "-epic"
    prompt: "#bd/new_epic ..."
  legend:
    suffix: "-legend"
    prompt: "#bd/new_legend ..."

gates:
  plan_review:                   # → renders the approval modal
    choices:
      - key: a
        label: Approve
        goto: code
        side_effects: []
      - key: t
        label: Tale
        goto: code
        side_effects: [commit_sdd]
      - key: e
        label: Epic
        goto: epic
        side_effects: [commit_sdd]
      - key: L
        label: Legend
        goto: legend
        side_effects: [commit_sdd]
      - key: f
        label: Feedback
        loop: self               # revise current role
        accumulate: feedback     # append decision.text to feedback bullets
        suffix_series: "-{n}"    # -2, -3, ...
      - key: c
        label: Commit only
        side_effects: [commit_sdd]
        terminate: true
      - key: r
        label: Reject
        terminate: kill

prompt_assembly:                 # how a goto/loop builds the next prompt
  base: original_prompt
  include: [qa_rounds, feedback_bullets]
  feedback_section: "### Additional Requirements"

questions:                       # optional; defaults to built-in behavior
  render: default_qa_markdown
  fold_into_prompt: true

auto_pilot:                      # generalizes SASE_AGENT_AUTO_APPROVE_*
  plan_review: { choice: a }     # when running headless, auto-pick Approve
```

A user wanting plan→**review**→code→**test** simply adds `review` and `test`
roles and points the relevant `goto`s at them — no Python change.

### 4.2 Event model and metadata

The most stable insertion point is the existing marker restart boundary, not the
initial prompt launch. `sase plan` and `sase questions` are already
runtime-neutral: every supported provider can call those tools, the command
writes a durable marker, and the runner resumes from `_handle_killed_iteration()`.
A configurable family engine should normalize that restart into typed events and
then ask the family definition what to do next.

Minimum event vocabulary:

- `plan_submitted` — a role produced a plan and needs review.
- `plan_feedback_received` — the user supplied feedback and the family should
  choose the next revision role/prompt.
- `plan_approved` — the user selected an approval-style choice.
- `questions_submitted` — a role asked the user for structured answers.
- `questions_answered` — answers are available and should be folded into the
  next prompt.

The current response JSON can remain backward-compatible while this rolls out.
For plan review, keep writing `action`, `feedback`, `commit_plan`, `run_coder`,
`coder_prompt`, and `coder_model`; add optional `family_id`, `gate_id`, and
`choice_id` fields once ACE, mobile, and external clients understand them. The
runner can prefer `choice_id` and fall back to today's `action` plus flags.

Do not overload the existing `agent_family` field, which is the stable runtime
family/root name. Add metadata that identifies the configured policy and the
event that launched each phase:

- `agent_family_config`: configured family id, e.g. `default` or
  `security_review_chain`.
- `agent_family_role_kind`: normalized kind such as `planner`, `question`,
  `feedback`, `implementer`, `container_creator`, or `terminal`.
- `agent_family_round`: repeat index for feedback/revision roles.
- `agent_family_event`: event that launched the phase, e.g.
  `plan_feedback_received`.

This preserves today's grouping model (`agent_family`, `agent_family_role`,
`role_suffix`, `plan_chain_root`) while giving status projection, notifications,
and future frontends enough information to classify user-defined roles without
parsing hardcoded suffixes.

### 4.3 Core engine (sase-core)

Add a `agent_family` module to `crates/sase_core` exposing a pure function:

```
advance(family_def, state, decision) -> Transition
  Transition = { next_role | terminate, suffix, side_effects[], prompt_directives }
```

- Owns the **role/suffix/role-name contract** (replacing the hardcoded
  `plan_chain.py` mapping and the mirrored `wire.rs` enum) so the TUI, a future
  web app, and the CLI all classify family members identically.
- Performs **prompt assembly** (original + Q&A + feedback) so frontends match.
- Is exposed to Python through the existing `sase_core_rs` binding.

Python keeps: subprocess spawning, the marker/IPC mechanics, the Textual modals
(now *rendering choices the engine provided* rather than a hardcoded dict), and
executing `side_effects` like `commit_sdd`.

### 4.4 Decisions, not just `hitl`

The approval modal becomes a **generic decision renderer**: given the gate's
`choices[]` (label, key, whether it needs feedback text / edit / model picker), it
builds the UI. This subsumes today's fixed
`_PLAN_APPROVAL_CHOICE_PROTOCOL` and the question modal is similarly driven by the
family's `questions` config. The `plan_response.json` / `question_response.json`
IPC payloads stay the same shape (`action`, `feedback`, `commit_plan`,
`run_coder`, …) so the wire is backward-compatible — `action` just becomes "the
chosen `goto`/`loop` target" rather than a closed enum.

### 4.5 Backwards compatibility

- Ship `families/default.yml` reproducing the current chain; if no user families
  exist, behavior is identical. `_LEGACY_SUFFIX_MAP` handling in `plan_chain.py`
  stays for old artifacts.
- The metadata fields (`role_suffix`, `agent_family`, `agent_family_role`,
  `plan_chain_root`) are unchanged; `agent_family_role` now comes from the family
  def instead of the hardcoded mapping.
- Existing env-var auto-approve maps onto `auto_pilot`.

### 4.6 Phased delivery

1. **Phase 1 (Option A foothold, in this repo):** Extract the hardcoded constants
   into a `agent_family:` config block — coder xprompt path, coder model, suffix
   strings, and the approval-choice→protocol table. Drive the modal and
   `run_agent_exec_plan.py` from that config. *Ships custom coder prompts/models
   and extra approval choices immediately; introduces no new engine.*
2. **Phase 2 (schema + loader):** Define `agent_family.schema.json` and a loader
   that reads `families/*.yml`; have Phase-1 config be the `default` family.
   Generalize the approval modal into a decision renderer.
3. **Phase 3 (core engine):** Move role/suffix classification and prompt assembly
   into `sase-core::agent_family`; replace `plan_chain.py`'s hardcoded mapping
   with binding calls. Add multi-role chains (arbitrary `goto` targets).
4. **Phase 4 (questions + auto-pilot):** Make Q&A rendering/folding and auto-pilot
   policy family-configurable.

---

## 4a. Worked example — inserting a plan-review phase

The motivating use case ("a reviewer between planner and coder") under the
recommended schema is a single inserted role plus one extra `goto`:

```yaml
# ~/.config/sase/families/plan_review_coder.yml
extends: default
roles:
  review:
    suffix: "-review"
    model: "claude-opus-4-7"
    prompt: |
      @{{ plan_file }}

      Critically review the approved plan above. Tighten scope, surface risks
      and missing edge cases, and rewrite it in place via `sase plan` if you can
      materially improve it. Otherwise call `sase plan` with the file unchanged
      to signal "no rewrite needed".
    gate: plan_review    # reuse the same gate — calling `sase plan` re-enters it
gates:
  plan_review:
    choices:
      - { key: a, label: Approve,  goto: review }   # was: goto: code
      - { key: t, label: Tale,     goto: review, side_effects: [commit_sdd] }
      - { key: A, label: Skip review (approve direct), goto: code }
      # epic/legend/feedback/commit/reject unchanged
```

End-to-end flow with the above:

1. Planner emits a plan, hits `plan_review` gate. User picks `a` (Approve).
2. Engine resolves `goto: review` → spawns `<base>-review` with the rendered
   prompt. The role's prompt calls `sase plan` again when finished.
3. `sase plan` re-fires the same marker → runner re-opens `plan_review`. Choosing
   `a` this time goes to `review` *again* — to avoid an infinite loop, either
   (a) the engine tracks which roles have already run in this lineage and skips
   them on re-entry, or (b) the schema declares `once: true` on the `review`
   role. Recommendation: track *visited roles per lineage* in the family-state
   sub-object on `agent_meta.json` (`family_state.visited_roles[]`) and have the
   engine prefer the first `goto` whose target hasn't run yet, falling through
   to `code`. This keeps the schema simple and the loop-detection behavior
   inspectable in artifacts.

Critically, this whole change is **a YAML file** — no Python edits, no new
suffix added to `plan_chain.py`, no modal change. The validator does need to
accept `-review` as a reserved suffix for the duration the family is active
(see §5).

## 4b. Testing strategy

The risk profile of this work is "we silently regress the default plan chain
for thousands of existing users." A configurable engine should land with:

1. **Golden-equivalence harness.** For the default family, replay representative
   transcripts (planner → feedback → planner → approve → coder; planner →
   epic; planner → question round → approve) through *both* the legacy
   `handle_plan_marker` path and the new engine and assert byte-identical
   `plan_response.json`/`question_response.json` payloads, prompt strings,
   suffix sequences, and `agent_meta.json` writes. The existing test files
   (`tests/test_axe_run_agent_exec_retry.py`,
   `tests/test_agent_loader_status_override_questions.py`) already encode the
   artifact-mutation contract — extend them rather than replacing them.
2. **Schema-level unit tests.** Pure-function tests of
   `advance(family_def, state, decision)` covering every built-in choice
   (approve/tale/epic/legend/feedback/commit/reject), feedback-round
   accumulation, prompt assembly with and without Q&A rounds, auto-pilot
   resolution from env vars + `agent_meta.json`, and rejection of malformed
   families (dangling `goto`, missing entry, suffix collision with reserved
   list).
3. **Custom-family integration test.** Ship the `plan_review_coder.yml` example
   above as a test fixture and assert (a) the `-review` suffix is accepted by
   `launch_validation`, (b) family discovery in `_lookup.py` correctly groups
   the four members (`plan` / `q?` / `review` / `code`), (c) the `visited_roles`
   loop-detection prevents an infinite `review → review` cycle.
4. **PNG snapshot coverage.** The approval modal becomes a generic decision
   renderer; the existing TUI snapshot suite (`just test-visual`) must be
   extended with goldens for at least one custom-choice set so layout
   regressions are caught.
5. **Notification round-trip.** A dedicated test that, given a custom gate,
   verifies `notifications.jsonl` + `pending_actions.json` carry the
   `choices[]` payload so out-of-band transports (sase-telegram, future mobile)
   can render it without a TUI in the loop.

## 5. Risks & open questions

- **Schema vs workflow DSL overlap.** Two declarative systems (workflow YAML and
  family YAML) could confuse users. Mitigation: share primitives (xprompt refs,
  Jinja templating, input types) and document when to use which — workflow =
  linear scripted steps; family = human-gated role state machine. Consider whether
  a family role's prompt can itself *be* a workflow (it can, via an xprompt ref).
- **Side-effect catalog.** `side_effects` (commit_sdd, create_epic_bead, …) must
  stay a curated, code-backed set — users configure *which* effects fire at *which*
  gate, not arbitrary code. Keeps the security/blast-radius bounded.
- **Boundary churn.** Moving the role enum into core touches `wire.rs` and the
  binding; must be done with a compat shim so old `agent_meta.json` still scans.
- **Modal expressiveness.** Generalizing the approval modal must preserve current
  niceties (edit-in-place, custom options modal, model picker). These become
  declared *capabilities* of a choice rather than hardcoded branches.
- **Validation & errors.** A malformed user family (dangling `goto`, missing entry
  role) must fail loudly at load with a clear message, and fall back to `default`.
- **Discoverability.** Need `sase` CLI/skill support to list/validate families,
  and TUI affordance to show which family an agent belongs to.
- **Three decision systems vs. one.** Plan approval, user questions, and workflow
  HITL each have their own IPC shape, notification sender, and modal (§1.4.1).
  Unifying their declaration in the family schema while keeping their wire
  payloads stable is necessary for back-compat with sase-telegram and any
  external transport already keyed off `sender="plan"`/`"question"`/`"hitl"`.
  Open: do we deprecate `sender="hitl"` in favor of family-named senders, or
  keep it and route family gates through it?
- **Suffix-collision validation.** Reserved-hyphen enforcement
  (`launch_validation.py:67-85`) currently treats *all* hyphens as family-only.
  When a user-defined family declares `-review`, the loader must (a) register
  the suffix globally so `validate_user_agent_name` does not reject internal
  `-review` spawns, and (b) reject the family if `-review` collides with a
  built-in suffix or another active family. Multi-family workspaces complicate
  this — two families both wanting `-test` need a per-family namespace or
  unambiguous prefixing.
- **Loop-detection on multi-role chains.** As shown in §4a, naively re-entering
  the same gate from a non-planner role can loop. The `family_state.visited_roles`
  approach must survive workspace restarts (it lives in `agent_meta.json`) and
  not lock users out of legitimate re-runs (e.g. an explicit "re-review" choice).
- **Skill contract is CLI-shaped, not metadata-shaped.** `sase plan` and
  `sase questions` are CLI subcommands consumed by `/sase_plan` / `/sase_questions`
  skills; the skill files are generated against the CLI surface, not against the
  family schema. Adding family-defined gate kinds therefore does not auto-create
  new skills — either the schema declares which existing CLI command its gate
  uses (`gate.cli: sase plan`) or we keep gate-kind to one of a curated set
  (`plan_approval`, `user_question`, `generic_decision`) backed by existing CLIs.
  Curated set is simpler and matches the side-effect catalog approach.

### Key code references

- `src/sase/plan_chain.py` — suffix constants, role mapping (the closed enum).
- `src/sase/axe/run_agent_exec_plan.py` — the transition dispatch + feedback prompt
  reconstruction (`:223-283`).
- `src/sase/ace/tui/modals/plan_approval_modal.py` — `_PLAN_APPROVAL_CHOICE_PROTOCOL`
  (the hardcoded decision table).
- `src/sase/xprompts/coder.md` — the fixed coder prompt.
- `src/sase/main/plan_command_handler.py`, `src/sase/llm_provider/_plan_utils.py` —
  plan IPC.
- `src/sase/main/questions_command_handler.py`,
  `src/sase/axe/run_agent_helpers_questions.py`, `src/sase/main/qa_markdown.py` —
  question IPC + Q&A merge.
- `src/sase/xprompts/workflow.schema.json` — the existing workflow DSL to reuse.
- `../sase-core/crates/sase_core/src/.../wire.rs` — mirrored family metadata fields.

---

## 6. Summary recommendation

Treat the planner/coder/feedback/Q&A lifecycle as a **declarative, human-gated
agent-family state machine** (Option C), not as frozen Python and not as a linear
workflow. Define a dedicated `agent_family` schema whose built-in `default`
reproduces today's plan chain exactly; normalize `sase plan` / `sase questions`
marker restarts into typed handoff events; evaluate the configured transition in
`sase-core` so all frontends agree on roles, transitions, and prompt assembly; and
keep the Textual modals and subprocess mechanics in this repo as the
host/presentation layer. Ship it in phases, beginning with a config-extraction
down payment (Option A) that already unlocks custom coder prompts/models and
additional approval choices, then growing that config into the full schema and
core engine.
