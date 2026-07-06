---
create_time: 2026-07-05 21:16:53
bead_id: sase-5f
tier: epic
status: done
prompt: sdd/prompts/202607/dynamic_agent_families_v1.md
---
# Implementation Plan: Dynamic Agent Families v1

## Product Context

SASE agents already form `--`-separated families through the plan-chain runner (`foo--plan`, `foo--code`, `foo--plan-2`,
...), but family extension is runner-internal today: only the plan/questions handoff machinery in `src/sase/axe/` can
attach a new member, and only along the hard-coded plan → code / epic / legend transitions. v1 turns family extension
into a user-facing primitive:

> A user can manually attach a new member to an existing agent's `--` family by writing `%n(parent, suffix)` in an
> ordinary `sase run` prompt. If the parent is still running, the member queues as a WAITING child row under the parent
> in the `sase ace` Agents tab and starts when the parent finishes.

Motivating user stories:

1. Manual feedback / Q&A rounds on finished agents, e.g. `%n(foo, @) #with_feedback:: <feedback text>`.
2. Arbitrary named members attached to an existing family, e.g. `%n(foo, reviewer)`, `%n(foo, tester)`.
3. (v2, out of scope here) lifecycle-initiated members — plan-approval options that insert members, and agent-initiated
   spawning. v1's family metadata is the compatibility contract v2 builds on, so v1 members must be indistinguishable
   from runner-created members at the metadata level.

Design sources (read before implementing any phase):

- `sdd/research/202607/dynamic_agent_families_v1_v2_design.md` (the v1 design this plan implements; includes the v2
  direction that constrains v1 choices).
- `sdd/research/202607/dynamic_agent_families_note_critique.md` (background).
- `sdd/research/202606/with_q_and_a_xprompt_consolidated.md` (Phase 2 spec for `#with_q_and_a`).

## Locked Decisions

These were decided during design review; do not re-litigate them:

1. **Running parents are in scope.** `%n` may target a still-running parent; the new member queues as a waiting child.
2. **Role-derived statuses only.** No custom status strings, no `run_status=` / `done_status=` kwargs, no changes to the
   closed status sets in `src/sase/agent/status_buckets.py` or `src/sase/ace/tui/models/agent_status.py`.
3. **No `%!` inline-shell directive and no root-level bash/python rows** — in any version of this project.
4. **TUI root/child normalization is a prerequisite** and is built first.
5. **Custom-suffix policy: open set.** Reserved suffixes (`plan`, `q`, `code`, `epic`, `legend`, `commit` — see
   `src/sase/plan_chain.py`) select the corresponding built-in role and statuses. `@` auto-allocates the next free
   suffix. Any other word (e.g. `reviewer`) is allowed with a generic role: standard RUNNING/DONE statuses,
   `agent_family_role` recorded as the custom word so the future v2 evaluator can interpret it without migration.
6. **Parent-failure policy: cancel.** A queued child whose parent terminates in failure (`FAILED`/`STOPPED`/killed) is
   cancelled to `STOPPED` and a notification is sent. It does not run and does not wait forever.
7. **Inheritance contract.** Project and workspace ref inherit from the parent. Model/effort come from the launch site
   via normal directive resolution. No chat/session inheritance unless the user explicitly forks. `SASE_PLAN` is set
   only for `code`-role members whose parent family has a committed/archived plan (mirroring
   `src/sase/axe/run_agent_exec_plan_accept.py`).
8. **Remote surfaces honored.** `%n` works from Telegram/mobile exactly like any other user-typed `sase run` prompt (it
   is user-initiated, so no `LaunchApproval` gate). Constraints are checked at launch-preparation time and failures are
   reported on the launching surface.

## Phasing Overview

Five phases. Each phase is completed by a distinct agent instance, is independently landable (green `just check`,
committed), and leaves the product in a coherent state. Every phase agent must run `just install` before other `just`
commands (ephemeral workspaces), and `just check` before finishing.

| Phase | Deliverable                                                              | Depends on              |
| ----- | ------------------------------------------------------------------------ | ----------------------- |
| 1     | TUI child-row normalization + WAITING child rows                         | —                       |
| 2     | Prompt-assembly helpers + `#with_feedback` / `#with_q_and_a` xprompts    | —                       |
| 3     | `%n(parent, suffix)`: grammar, parent resolution, terminal-parent attach | — (renders best with 1) |
| 4     | Queued children under running parents                                    | 1, 3                    |
| 5     | Cross-surface verification, composition, docs                            | 2, 3, 4                 |

Phases 1, 2, and 3 are mutually independent and could run in parallel; 4 and 5 are sequential integration phases.

---

## Phase 1 — TUI child-row normalization + WAITING child rows

**Goal:** one unified child-linkage model in the ace TUI Agents tab, capable of rendering a WAITING child row under a
running parent.

**Why first:** Phase 4's queued children render through this. Today the TUI has two disjoint child-attachment mechanisms
and a root-only WAITING status.

**Current state (verified):**

- Workflow step children link via `parent_workflow` + `parent_timestamp` and carry `step_type`
  (`src/sase/ace/tui/models/agent.py`, fields around lines 116–138; `is_workflow_child` around line 528).
- Follow-up family children link via `parent_timestamp` _only_ and are attached to `Agent.followup_agents` in
  `src/sase/ace/tui/models/_agent_status_apply.py` (the loop that appends when
  `agent.parent_timestamp and not agent.parent_workflow`, around line 269).
- Ordering/grouping of roots and children: `src/sase/ace/tui/models/_agent_ordering.py`.
- `WAITING` status comes from a `waiting.json` marker during meta enrichment
  (`src/sase/ace/tui/models/_loaders/_meta_enrichment_filesystem.py`, around lines 194–220) and today only ever appears
  on root rows because only root runners write the marker.

**Scope:**

1. Introduce a single, documented child-linkage concept on `Agent` (e.g. a derived classification: _workflow-step child_
   vs _family-member child_) that both existing mechanisms feed. No user-visible behavior change for existing rows:
   ordering, status propagation/mirroring (`_agent_status_family.py`), dismissal grouping, and hood/neighbor navigation
   must be preserved.
2. Make family-member child attachment work while the parent is still RUNNING (today follow-ups only appear after the
   runner hands off; verify and fix ordering/attachment assumptions that presume a terminal parent).
3. Allow `WAITING` on child rows: a child with a `waiting.json` marker renders under its parent with WAITING status and
   buckets into the Waiting bucket. Include `waiting_for` display parity with root waiting rows.
4. Scope cut (locked decision 3): do **not** add root bash/python rows; bash/python remain workflow children only.
5. Assess whether the Rust scan wire (`src/sase/core/agent_scan_facade.py`, `src/sase/core/agent_scan_wire.py`) already
   carries everything needed (`parent_timestamp`, `agent_family`, `agent_family_role`, `role_suffix`, waiting marker
   fields). Expected: yes, since plan-chain follow-ups already render. If a wire field is genuinely missing, the
   `sase-core` linked repo change is in scope for this phase (follow the repo instructions for the linked-repository
   workspace flow).

**Constraints:** Read `memory/tui_perf.md` via the `/sase_memory_read` skill before touching loaders. No new synchronous
I/O in loader hot paths — derive the unified linkage from data already loaded.

**Acceptance:**

- Unit tests for the unified linkage classification and for WAITING child bucketing/ordering.
- A PNG visual snapshot showing a WAITING child row under a RUNNING parent (`just test-visual`; goldens in
  `tests/ace/tui/visual/snapshots/png/`).
- Existing agents-tab snapshots unchanged (or intentionally updated with justification).

---

## Phase 2 — Prompt-assembly helpers + `#with_feedback` / `#with_q_and_a`

**Goal:** the two family-round prompt bodies (feedback replan, answered-Q&A follow-up) become reusable, user-invocable
xprompts. Pure prompt assembly — these xprompts never launch agents (per the 2026-06 memo); the `%n` directive (Phase 3)
is the launcher.

**Current state (verified):**

- Q&A follow-up prompt assembly lives inline in `handle_questions_marker` (`src/sase/axe/run_agent_exec_questions.py`,
  ~lines 75–238; helpers in `src/sase/axe/run_agent_helpers_questions.py`).
- Feedback replan prompt assembly (original prompt + accumulated "### Additional Requirements" bullets) lives inline in
  the feedback branch of `handle_plan_marker` (`src/sase/axe/run_agent_exec_plan.py`, ~lines 169–238).
- xprompt definitions live in `src/sase/xprompts/` (`.md` = single `prompt_part`; `.yml` = multi-step workflow with
  hidden `python` steps supported — see `src/sase/xprompts/workflow.schema.json`).

**Scope:**

1. Extract `assemble_question_followup_prompt(...)` into a public helper module; the runner path calls it; byte-parity
   tests prove the runner output is unchanged.
2. Extract the feedback-replan assembly the same way (`assemble_feedback_replan_prompt(...)`), with parity tests against
   the existing `handle_plan_marker` feedback branch.
3. Ship `#with_q_and_a` per the consolidated memo: an embeddable xprompt whose hidden python step calls the shared
   helper; `qa_file` input contract as specified in the memo.
4. Ship `#with_feedback`: takes the feedback text (shorthand `:: text` form) plus an explicit `parent` input naming the
   family/agent whose original prompt and prior feedback rounds are being extended; the hidden python step reads the
   parent's artifacts through existing read paths and emits the same body the runner's replan produces. (Deriving
   `parent` from a co-occurring `%n` directive is Phase 5 sugar, not required here.)
5. Register both in the xprompt catalog; `sase xprompt explain` renders them.

**Acceptance:** parity tests (runner output byte-identical before/after extraction); xprompt expansion tests for both
prompts including error cases (missing `qa_file`, unknown parent); catalog/explain coverage.

---

## Phase 3 — `%n(parent, suffix)`: grammar, resolution, terminal-parent attach

**Goal:** `%n(parent, suffix)` in a user prompt launches the new agent as a member of `parent`'s family, for
**terminal** parents. (Running parents are Phase 4; in this phase a running parent produces a clear, actionable error.)

**Current state (verified):**

- `%name`/`%n` is a single-value directive: grammar in `src/sase/xprompt/_directive_types.py`, parsing in
  `src/sase/xprompt/directives.py`. Today extra positionals and all keyword args are **silently dropped** (~lines
  359–380).
- Family naming/roles: `src/sase/plan_chain.py` — `AGENT_FAMILY_SEPARATOR = "--"`, reserved suffixes and roles,
  `agent_family_base`, `allocate_agent_family_child_suffix` (~line 419, `@` template semantics).
- Launch-name validation deliberately **rejects user names containing `--`** unless an internal bypass is set:
  `validate_launch_name_requests` / `validate_user_agent_name` in `src/sase/agent/launch_validation.py` (~line 118),
  called from `src/sase/agent/launch_cwd_agents.py`.
- The follow-up metadata contract is `create_followup_artifacts` (`src/sase/axe/run_agent_helpers_artifacts.py`, ~line
  97): inherits `model`, `llm_provider`, `workspace_dir`, `cl_name`, bead ids, etc. from the parent meta and writes
  `agent_family`, `agent_family_role`, `role_suffix`, `parent_timestamp`.
- Dismissal state is keyed by `(AgentType, cl_name, raw_suffix)` in `~/.sase/dismissed_agents.json`
  (`src/sase/ace/dismissed_agents.py`); there is **no** name-keyed "exists and undismissed" helper today.
- Launch preparation is Rust-delegated via `src/sase/core/agent_launch_facade.py` (`prepare_agent_launch`,
  `plan_agent_launch_fanout`).

**Scope:**

1. **Grammar + strict validation.** Extend `%name`/`%n` to accept two positionals: `%n(name)` keeps today's meaning;
   `%n(parent, suffix)` means family attach; `%n(parent, @)` auto-allocates the next free suffix using the same template
   semantics as `allocate_agent_family_child_suffix`. Reject loudly: three or more positionals, _any_ keyword argument,
   and legacy `.`/`-` family spellings in the suffix (canonical `--` only). This converts today's silent-drop behavior
   into errors — a small deliberate breaking change; error messages must say what was wrong and show the fix.
2. **Parent resolution helper.** A name-keyed "resolve to newest matching undismissed root agent in the current project
   scope" helper, backed by the artifact index (`src/sase/core/agent_scan_facade.py`). Errors: absent parent, ambiguous
   parent (list candidates), dismissed parent (name the revive path). Per the Rust-core boundary rule, the pure
   classification ("given these candidate records + dismissal set, which one wins / why does resolution fail") belongs
   in the `sase-core` linked repo behind the existing facade pattern, with a thin Python adapter; follow the repo
   instructions for the linked-repository workspace flow.
3. **Prep-time enforcement.** Constraint checks run during launch preparation (the `prepare_agent_launch` seam), not
   just at parse time, narrowing the dismiss-between-check-and-spawn race and surfacing failures on the launching
   surface (CLI stderr, TUI toast, Telegram reply all already render launch-preparation failures).
4. **Name composition + collision.** The final agent name is `<parent-base>--<suffix>`. Route it through launch-name
   validation as a sanctioned family attach — do **not** blanket-allow `--` in user names; the reserved-separator guard
   stays for plain `%n(name)`. If the composed name already exists in the family, fail loudly and suggest `@`.
5. **Metadata.** Write the same family metadata `create_followup_artifacts` writes (`agent_family`, `agent_family_role`,
   `role_suffix`, `parent_timestamp` = the resolved parent's artifact timestamp, inherited project/workspace fields per
   the inheritance contract). Reserved suffixes get their built-in role; custom words get the generic role with the word
   recorded. Statuses are purely role-derived.
6. **`SASE_PLAN` rule.** Only `code`-role members whose parent family has a committed/archived plan get `SASE_PLAN`,
   mirroring the handoff rules in `run_agent_exec_plan_accept.py`.
7. **Running parent → error** (this phase only): a clear message that the parent is still running and queued attach
   arrives in Phase 4's release.

**Acceptance:**

- Directive parsing tests: all accepted forms, all strict-rejection cases, back-compat for `%n(name)` / `%name:value`.
- Resolution tests: absent / ambiguous / dismissed / terminal parents; newest match wins; project scoping.
- Launch integration test: `%n(foo, reviewer)` against a terminal `foo` produces an agent whose `agent_meta.json` is
  indistinguishable (same fields) from a runner-created follow-up, and which renders as a family child row in the TUI,
  groups with the family, and resolves via the existing family lookup (`src/sase/agent/names/_lookup.py`) — this is the
  explicit v1→v2 compatibility test.
- Collision and reserved-suffix role-mapping tests.

---

## Phase 4 — Queued children under running parents

**Goal:** `%n(parent, suffix)` against a **running** parent launches the child immediately into the existing wait
barrier; it renders as a WAITING child row (Phase 1) and starts when the parent terminates successfully, or cancels to
`STOPPED` with a notification when the parent fails.

**Current state (verified):**

- The wait barrier: the runner writes a `waiting.json` marker and blocks until dependencies resolve
  (`src/sase/axe/run_agent_wait.py`; `wait_for_dependencies` ~line 84).
- Resolution: `src/sase/core/wait_dependency_resolution.py`. `WaitDependencyIndex.is_resolved(name)` requires the newest
  candidate to be both `is_resolved` **and** `is_done`, where `is_done` means `done.json` outcome == `"completed"`.
  Consequences: a parent that ends `FAILED` / `STOPPED` never resolves (queued child waits forever), and resolution is
  **name-keyed** (name reuse across time can mis-target).

**Scope:**

1. **Implicit wait attach.** When Phase 3's resolution finds a running parent, the child launches with an implicit wait
   dependency on that parent instead of erroring. Reuse the `%wait` barrier machinery; do not invent a second queue.
2. **Identity-keyed dependency.** The dependency should reference the resolved parent's artifact identity (timestamp),
   not just its name, so a same-named later launch cannot satisfy or steal the wait. Extend the dependency index / wait
   names format minimally to support this (design point for this phase; keep `%wait(for=name)` behavior unchanged).
3. **Family-aware terminal detection with outcome.** Extend resolution so the barrier distinguishes three parent states:
   still running (keep waiting), terminal-success (start the child), terminal-failure (`FAILED`, `STOPPED`, killed →
   apply the cancel policy). Reuse the terminal set semantics from `src/sase/agent/status_buckets.py`; note plan-chain
   parents may terminate in `PLAN DONE` / `TALE DONE` / `EPIC CREATED`, which count as success.
4. **Cancel path.** On parent failure the queued child transitions to `STOPPED` (already a terminal, dismissable status
   — no new status strings), its artifacts record why, and a notification is sent through the existing notification
   senders (`src/sase/notifications/senders.py`).
5. **TUI integration.** The queued child renders as a WAITING child row under the running parent (Phase 1 machinery);
   after parent completion it transitions to normal RUNNING/role statuses; after cancel it shows STOPPED.

**Acceptance:**

- Wait-resolution unit tests: running / success / each failure outcome / plan-chain terminal statuses; identity-keyed
  targeting with a same-named newer agent present.
- An integration test covering queue → parent completes → child starts, and queue → parent fails → child STOPPED +
  notification recorded.
- Visual snapshot: WAITING child under RUNNING parent (may extend Phase 1's golden).

---

## Phase 5 — Cross-surface verification, composition, and docs

**Goal:** the composed v1 experience works end-to-end on every launch surface, and the feature is documented.

**Scope:**

1. **Composition tests.** `%n(foo, @) #with_feedback:: <text>` and `%n(foo, @) #with_q_and_a(qa_file=...)` end-to-end:
   directive + xprompt in one prompt produce a queued/attached family member with the assembled body. Add the optional
   sugar of defaulting `#with_feedback`'s `parent` input from a co-occurring `%n` directive if it is cheap; otherwise
   document the explicit form.
2. **Surface checks.** Verify prep-time constraint failures (absent / ambiguous / dismissed parent, collision) surface
   correctly from: CLI (stderr + exit code), TUI prompt bar (toast/error), Telegram (reply via the `sase-telegram`
   plugin's existing launch-failure reply path), and that multi-agent `---` prompts with `%n` segments behave sanely
   (`src/sase/agent/multi_prompt.py` splitting).
3. **Docs.** User-facing documentation for `%n(parent, suffix)`, `@` allocation, custom suffix roles, queueing
   semantics, the cancel policy, and both xprompts; update directive help/completion surfaces
   (`src/sase/xprompt/directive_edit.py`, `model_completion.py` analogues for name completion if applicable) and the CLI
   rules memory if new CLI surface was added (via the documented memory-read flow first).
4. **Glossary reconciliation (flag, don't fix).** The repo glossary defines "agent family" as dot-separated while this
   feature (and `plan_chain.py`) uses `--`; memory files must not be modified without user approval, so this phase
   produces a short proposed rewording for the user to approve rather than editing the glossary directly.

**Acceptance:** e2e tests green across surfaces; docs merged; a short summary of any behavior differences discovered
between surfaces, and the proposed glossary wording, reported back to the user.

---

## Non-Goals (all versions or v2)

- `%!` and any inline-shell xprompt support; root-level bash/python rows.
- Custom status strings or status-label kwargs (v2's label/semantic split).
- Agent-initiated `%n` (requires `LaunchApproval` — v2).
- Approval-option member insertion, family YAML definitions, the family state-machine evaluator (v2).
- Any change to the plan-approval choice tables or runner transition seams.

## Risks and Mitigations

1. **Strictness is a behavior change.** Prompts that today silently misuse `%name` args will start erroring. Mitigation:
   precise error messages with the corrected form; call it out in the commit/changelog.
2. **Reserved-separator guard erosion.** `%n(parent, suffix)` must not become a loophole for arbitrary `--` names.
   Mitigation: compose the name only after parent resolution succeeds; plain `%n(name)` keeps the existing guard; tests
   assert the guard still rejects raw `foo--bar` names.
3. **Name-reuse races.** Name-keyed resolution can drift between check and spawn. Mitigation: prep-time re-check
   (Phase 3) + identity-keyed wait dependencies (Phase 4).
4. **TUI performance.** Loader changes are hot-path. Mitigation: the `tui_perf.md` memory is required reading in Phase
   1; no new synchronous I/O; visual + perf-sensitive tests.
5. **v2 compatibility drift.** If v1 metadata diverges from the runner's follow-up contract, v2's evaluator inherits a
   migration. Mitigation: the explicit metadata-parity acceptance test in Phase 3.
6. **Cross-repo scope creep.** `sase-core` changes (resolution classification, any wire additions) should stay minimal
   and phase-scoped; each phase that touches `sase-core` must update its tests there too, per the boundary rule.

## Verification (every phase)

- `just install` first (ephemeral workspace), then `just check` green before finishing; `just test-visual` when TUI
  rendering is touched.
- Each phase ends with a commit of its own scope (via the sanctioned commit flow), leaving `master` releasable.
