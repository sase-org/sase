# Configurable Agent-Family Workflows (Planner / Reviewer / Coder)

Date: 2026-06-02

## Question

Today SASE hardcodes a single agent-family workflow: a *planner* agent produces a plan, the user gives feedback /
answers questions in a loop, and on approval a *coder* agent implements it (with `epic` / `legend` variants). We want
this to be **fully configurable** so users can:

1. Define their own agent-family pipelines (which phases run, in what order, with what prompts/models/gates).
2. Make small additive changes to the built-in pipeline — e.g. insert a **plan-review agent** that runs *after* the
   planner but *before* the coder to critique and improve the plan.

What architecture lets us externalize the planner→coder flow and its human-in-the-loop (HITL) gates without
rewriting the runner, while keeping today's behavior as the default?

## Current State

There are **two independent orchestration systems** in the repo, and the plan chain — the thing we want to make
configurable — is the one that is *not* declarative.

### 1. The declarative workflow engine (already configurable)

`src/sase/xprompt/workflow_models.py` defines a full step-DAG:

- `Workflow` (lines 130-160): ordered `steps`, `inputs`, `environment`, `xprompts`, `tags`.
- `WorkflowStep` (lines 60-107): a step is one of `agent` / `bash` / `python` / `prompt_part` / `parallel`, plus
  `condition` (`if:` Jinja2), `for_loop`, `repeat_config`/`while_config` (`LoopConfig`, lines 34-44), `parallel_config`
  (lines 47-57), `hitl: bool`, `hidden`, `on_error`.
- Executed by `execute_workflow()` (`src/sase/xprompt/workflow_runner.py`), with `StepStatus` /`WorkflowState`
  tracking (workflow_models.py:15-23, 293-313).

This engine already supports agent steps, conditions, loops, parallelism, and a `hitl` flag. It is loaded from `.yml`
files (`xprompt/workflow_loader.py`) and from the `xprompts:` config section. **It is the natural home for a
configurable pipeline**, but the plan chain does not currently run on it.

### 2. The hardcoded plan chain (what we want to configure)

The planner→coder flow is an **imperative loop driven by SIGTERM markers**, not a `Workflow`:

- **Phase names are literal constants** in `src/sase/plan_chain.py:8-27`: `-plan`, `-q`, `-code`, `-epic`,
  `-legend`, `-commit`, plus numeric feedback rounds `-2`, `-3`, … (`plan_chain_feedback_suffix`, lines 38-42). The
  set of known suffixes (`_KNOWN_SUFFIXES`, lines 20-27) and the suffix→role map (`agent_family_role_for_suffix`,
  lines 109-128) are closed/hardcoded.
- **The loop** lives in `src/sase/axe/run_agent_exec.py:run_execution_loop` (lines 147-210). Each iteration wraps the
  *current prompt* in an anonymous workflow and runs it (lines 178-191). When `sase plan` / `sase questions` fire,
  they write a marker file (`.sase_plan_pending` / `.sase_questions_pending`) and **SIGTERM the runner**
  (`main/plan_command_handler.py:61-88`, `main/questions_command_handler.py:81-89`). On wake, the loop reads the
  marker and dispatches (`_handle_killed_iteration`, lines 106-132).
- **The transition table is hardcoded** in `src/sase/axe/run_agent_exec_plan.py:handle_plan_marker` (lines 135-570):
  - mark planner with `-plan` (148-149);
  - `handle_plan_approval()` opens the HITL gate and polls for a response (`llm_provider/_plan_utils.py:108-262`);
  - `action == "feedback"` → bump feedback round, spawn `-2`/`-3`… planner with original prompt + merged Q&A +
    `### Additional Requirements` (lines 223-283);
  - `action in ("epic","legend")` → spawn `-epic`/`-legend` with a `#bd/new_epic`/`#bd/new_legend` xprompt
    (lines 402-490);
  - otherwise **approve → spawn `-code`** with `@<plan_ref>` + "Implement it now." (lines 491-568);
  - `run_coder == False` short-circuits to `"plan_committed"` with no coder (line 382).
  - `handle_questions_marker` (lines 573-698) is the analogous Q&A handoff.

The result type `PlanApprovalResult` (`_plan_utils.py:17-27`) is effectively the **transition payload**: `action`
(`approve`/`epic`/`legend`/`feedback`), plus `run_coder`, `coder_prompt`, `coder_model`, `commit_plan`. The TUI
approval modal (`ace/tui/modals/plan_approval_modal.py`) and question modal
(`ace/tui/modals/user_question_modal.py`) are the gate UIs; responses are routed back via JSON files
(`ace/tui/actions/agents/_notification_modals.py`).

### What is already configurable vs. hardcoded

| Aspect | Today |
|---|---|
| Auto-approve / auto-action | Configurable via `SASE_AGENT_AUTO_APPROVE[_PLAN_ACTION]` env + `agent_meta.approve` (`main/plan_approve_handler.py:45-61`) |
| Coder model / extra prompt / commit | Per-approval fields in `PlanApprovalResult` (user-set in modal) |
| Coder inherits planner chat | `SASE_CODER_INHERIT_PLANNER_CHAT=1` (`run_agent_exec_plan.py:548`) |
| **Phase sequence & set of phases** | **Hardcoded** (plan_chain.py constants + if/else in handle_plan_marker) |
| **Prompt templates per phase** | **Hardcoded** f-strings (e.g. coder prompt at lines 563-568) |
| **HITL gate placement / actions** | **Hardcoded** (gate only after planner; action vocab fixed) |
| **Inserting a new phase (e.g. review)** | **Not possible** |

### Constraints any solution must respect

- **SIGTERM-marker handoff**: phases hand off by killing the runner and resuming; the loop, not a synchronous call
  graph, drives transitions. A config schema must feed *this* loop.
- **Unbounded, user-driven feedback loop**: feedback rounds repeat until the user approves — not a fixed
  `max_iterations`. This doesn't map cleanly onto `LoopConfig`'s `until:`/`max_iterations`.
- **Agent-family naming is load-bearing**: family discovery, TUI grouping, completeness
  (`agent/names/_lookup.py:195-242`) all parse the suffix. New phases need real, parseable suffixes/roles.
- **SDD side effects**: approval writes/commits SDD spec+plan files and sets `SASE_PLAN`
  (run_agent_exec_plan.py:292-380, 498-501). These are coupled to the approve transition.
- **Config plumbing exists**: 5-layer YAML merge (`config/core.py:289-363`) and Jinja2 templating (used throughout
  the workflow engine) are already available — no new config infrastructure needed.
- **Rust boundary**: agent orchestration is currently **Python-only**; `sase_core_rs` only owns low-level
  path/process/scan primitives (`memory/short/rust_core_backend_boundary.md`, `agent/launch_spawn.py`). By the
  litmus test ("would a web/CLI frontend need the phase sequence to match the TUI?") the *phase-sequence model* is
  arguably core backend, but the SIGTERM loop is a TUI/runner concern. See "Rust boundary" below.

## Options Considered

### Option A — Config-driven phase list consulted by the existing loop

Add an `agent_family:` (or `plan_chain:`) config section: a named, ordered list of **phase definitions**
(suffix, role, kind, prompt template, gate, model, condition). Replace the if/else in `handle_plan_marker` with a
**transition table lookup** keyed by `(current_phase, gate_action)`. The SIGTERM-marker loop is unchanged; only the
"what comes next and with what prompt" decision is externalized.

- **Pros**: Smallest change to the runtime; preserves the marker/feedback/SDD semantics exactly; back-compat by
  shipping the current flow as the default pipeline; inserting a review phase = one list entry. Reuses existing
  config layering + Jinja2.
- **Cons**: A second declarative format alongside the `Workflow` engine (some conceptual duplication); the transition
  semantics (feedback loop, epic/legend) still need first-class modeling, not just a flat step list.

### Option B — Migrate the plan chain onto the `Workflow` engine

Express planner→review→coder as a real `Workflow` with `agent` steps and `hitl` gates; let `execute_workflow` drive
it.

- **Pros**: One orchestration system; immediately inherits `condition`/`for_loop`/`parallel`/`hitl`.
- **Cons**: Large, risky rewrite. The current workflow executor runs steps synchronously in-process; the plan chain
  resumes across SIGTERM kills with fresh agent processes and per-phase artifact dirs. The unbounded user-driven
  feedback loop, the SDD commit side effects, and family-suffix naming don't map onto today's `WorkflowStep`/
  `LoopConfig` without substantial engine changes. High blast radius for the "insert a review agent" use case.

### Option C — Hybrid: declarative pipeline schema, executed by the existing loop, designed to converge on the Workflow engine

Introduce a small **agent-family pipeline schema** (Option A's config) but model it deliberately as a thin,
forward-compatible subset of `WorkflowStep` (agent prompt + `condition` + `hitl` + model), with an explicit
**transition map** for gate actions. Keep the SIGTERM loop as the executor for now. Later, the same schema can be
lowered onto the `Workflow` engine (Option B) once that engine learns kill-resumption + family naming — without a
second config migration for users.

- **Pros**: All of Option A's low-risk wins, plus a migration path to a single engine. Phase definitions reuse the
  vocabulary (`agent:`, `if:`, `hitl:`, `%model:`) users already know from xprompts/workflows.
- **Cons**: Requires care to keep the schema a true subset of `WorkflowStep` so the future lowering is real, not
  aspirational.

## Recommended Solution

**Adopt Option C.** Externalize the plan chain into a declarative, layered-config **agent-family pipeline** that the
existing `run_execution_loop` consults, ship today's behavior as the built-in default pipeline, and shape the schema
as a forward-compatible subset of `WorkflowStep`.

### 1. Pipeline schema (new dataclasses, Python; loaded via the existing config merge)

```yaml
# default_config.yml — new section; users override/extend in ~/.config/sase/sase.yml or ./sase.yml
agent_family:
  default_pipeline: standard
  pipelines:
    standard:
      phases:
        - name: plan          # suffix "-plan", role "plan"
          kind: planner        # the root prompt; emits a plan via `sase plan`
          gate: plan_approval  # HITL gate after this phase
        - name: code          # suffix "-code", role "code"
          kind: coder
          when: "gate.action == 'approve' and gate.run_coder"
          prompt: |
            @{{ plan_ref }}

            The above plan has been reviewed and approved. Implement it now.
            {{ coder_extra }}
        - name: epic
          kind: bead
          when: "gate.action == 'epic'"
          prompt: "#bd/new_epic:{{ plan_ref }}"
        - name: legend
          kind: bead
          when: "gate.action == 'legend'"
          prompt: "#bd/new_legend:{{ plan_ref }}"
      gates:
        plan_approval:
          modal: plan_approval        # which TUI gate to open
          actions: [approve, epic, legend, feedback, commit]
          feedback_action: feedback   # action that loops back to the planner phase
```

Each **phase** is a dataclass mirroring a `WorkflowStep` subset:
`name`, `kind`, `prompt` (Jinja2 template, optional for built-in kinds), `when` (`condition`/`if:` equivalent),
`gate` (HITL gate id), `model` (→ `%model:` prefix). The **gate** declares which modal opens, the allowed action
vocabulary, and which action loops back vs. advances. This makes `PlanApprovalResult.action` a *configured*
transition key rather than a hardcoded `if action ==`.

Template context exposes what `handle_plan_marker` already computes: `plan_ref`/`plan_file`, `prompt`,
`original_prompt`, `qa` (merged Q&A), `feedback` bullets, `gate` (the approval payload), `coder_extra`, model.

### 2. Executor changes (minimal, localized)

- Replace the if/else ladder in `handle_plan_marker` (`run_agent_exec_plan.py:382-568`) with: resolve the active
  pipeline → after the gate, pick the **next phase** whose `when` evaluates true under the gate result → render its
  `prompt` template → `create_followup_artifacts` with that phase's suffix/role. The feedback loop becomes the phase
  whose gate `action == feedback_action` and whose target is the planner phase again (preserving the `-2`/`-3`
  numeric round suffixes via `plan_chain_feedback_suffix`).
- Keep the SDD-commit block and `SASE_PLAN` wiring tied to the `approve` transition initially; expose them as
  per-phase booleans (`commit_sdd: true`, `sets_sase_plan: true`) so they're configurable but default to current
  behavior.
- `plan_chain.py` keeps the built-in suffixes but its `_KNOWN_SUFFIXES`/role map should be **seeded from the active
  pipeline's phase names** so user-defined phases (e.g. `-review`) become first-class family members for discovery,
  TUI grouping, and completeness (`agent/names/_lookup.py:195-242`). This is the one change that touches family
  naming and must land carefully (validate suffixes are unique, hyphen-safe, and don't collide with reserved ones in
  `agent/launch_validation.py:74`).

### 3. The motivating use case — insert a plan-review agent

With this schema, "review and improve the plan after the planner, before the coder" is a single inserted phase:

```yaml
- name: review
  kind: agent
  when: "gate.action == 'approve'"   # runs only on approval, before the coder phase
  # optional: gate: review_approval   # add a second HITL gate to review the improved plan
  prompt: |
    @{{ plan_ref }}

    Critically review the approved plan above. Tighten scope, surface risks and missing
    edge cases, and rewrite it in place via `sase plan` if you can materially improve it.
```

Because phases are an ordered list filtered by `when`, the review phase slots between `plan` and `code` with no code
change. If the reviewer calls `sase plan` again, it re-enters the existing plan gate — giving plan→review→(re-approve)
→code "for free" from the marker loop. Users wanting a non-gated reviewer simply omit `gate:`.

### 4. Backward compatibility & rollout

1. **Phase 1 (schema + default pipeline)**: add dataclasses + loader + a `standard` pipeline that reproduces today's
   exact transitions; route `handle_plan_marker` through it behind a feature flag; assert byte-identical coder/epic/
   legend prompts via the existing test suite + PNG/snapshot tests.
2. **Phase 2 (custom phases)**: allow user pipelines to add phases with new suffixes; extend family-naming to accept
   pipeline-declared suffixes; add validation + `just check` coverage.
3. **Phase 3 (gates configurable)**: make the gate action vocabulary and modal selection config-driven; keep
   `plan_approval`/`user_question` as built-in gates.
4. **Phase 4 (optional, later)**: lower the pipeline schema onto the `Workflow` engine once it supports
   kill-resumption + family naming, retiring the bespoke loop without a user-facing config migration.

### 5. Rust boundary call

The **phase-sequence model and transition rules** are core backend by the litmus test (a future web/CLI frontend
would need the same plan→review→code semantics). Recommendation: define the **pipeline/phase/gate schema and the
"next phase" resolution** in `sase-core` (`crates/sase_core`) with a `sase_core_rs` binding, so all frontends share
one definition; keep the **SIGTERM-marker loop, artifact-dir creation, and TUI modals** in Python as presentation/
runner glue. If that's too large for a first cut, implement the schema in Python now but **keep it a pure data model
with no TUI/runner imports**, so it can be hoisted into Rust later without churn.

## Open Questions / Risks

- **Family-suffix explosion**: user-defined suffixes interact with discovery, completeness, and reserved-suffix
  validation. Needs strict validation and tests (`agent/names/_lookup.py`, `agent/launch_validation.py`).
- **Feedback loop modeling**: confirm the loop-back phase + numeric round suffixes survive arbitrary pipelines
  (what if the planner phase isn't first?). May need an explicit `loops_to:` on the feedback gate.
- **SDD/commit coupling**: per-phase `commit_sdd`/`sets_sase_plan` flags need a clear default and ordering contract
  so a custom reviewer phase doesn't strand `SASE_PLAN`.
- **Gate UI generality**: today modals are bespoke (`plan_approval_modal`, `user_question_modal`). Fully
  user-defined gates would eventually need a generic action-driven modal; scope this out of the first cut.
- **Schema/Workflow convergence**: keeping the pipeline schema a true `WorkflowStep` subset is what makes Phase 4
  cheap — review each new field against the workflow model before adding it.
