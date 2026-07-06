---
create_time: 2026-07-06 02:15:44
bead_id: sase-5g
tier: epic
status: done
prompt: sdd/prompts/202607/dynamic_agent_families_v2.md
---
# Implementation Plan: Dynamic Agent Families v2

## Product Context

v1 (epic `sase-5f`, complete) made family extension a _user-facing_ primitive: `%n(parent, suffix)` attaches a new
member to an existing `--` family from any launch surface, queues under running parents, and writes metadata
indistinguishable from runner-created follow-ups. v2 is the other half of the north star:

> **Lifecycle-initiated family extension.** Users can approve a plan with custom options that insert custom family
> members at select points in the family lifecycle — an `improve_plan` agent after the `plan` agent, a `tester` agent
> after the `code` agent — and agents themselves can request member spawns behind a `LaunchApproval` gate.

This is the family state-machine territory of the 2026-06-17 memo, staged so each phase is independently shippable and
the approval-options feature falls out of the middle phases rather than being bolted on.

Design sources (read before implementing any phase):

- `sdd/research/202607/dynamic_agent_families_v1_v2_design.md` — the v2 direction this plan implements ("Recommended v2
  shape (staged)" section), including critiques and open questions.
- `sdd/research/202606/dynamic_agent_families_xprompt_workflows_consolidated.md` — the family state-machine
  architecture: event adapters, family evaluator, compatibility renderers, edge-case catalog, validation checklist.
- `sdd/research/202606/agent_launch_ux_family_types_consolidated.md` — `LaunchApproval`, launch preview object,
  `/sase_run` generated skill (Phases 7–8 only implement the agent-initiated-spawn subset of this memo).
- `sdd/epics/202607/dynamic_agent_families_v1.md` — what v1 shipped; its metadata contract is v2's compatibility floor.

## Verified Current State (2026-07-06 reconnaissance)

The v2 design doc is one day old but three of its claims have already drifted; phase agents should trust the anchors
below over the doc where they disagree.

1. **The choice vocabulary is partially centralized already.** `approval_protocol_for_choice()`
   (`src/sase/ace/tui/modals/plan_approval_modal.py:53-57`, backed by `_PLAN_APPROVAL_CHOICE_PROTOCOL` at `:27-50`) is
   now the canonical choice→protocol mapping; `ApproveOptionsModal` and the TUI notification-response builder delegate
   to it. The _independently hard-coded_ sites that remain are: the response writer `_plan_response_json`
   (`src/sase/plan_approval_actions.py:97-154`), the CLI `--kind` choices tuple (`src/sase/main/parser_plan.py:62-73`),
   the status/persist inference branches in `src/sase/ace/tui/actions/agents/_notification_modals.py:216-341` (a fifth
   site the design doc does not list), and the display tables in
   `src/sase/ace/tui/modals/approve_options_modal.py:17-40`.
2. **The `"run"` choice is live, cross-repo, and half-broken.** The sase-telegram plugin's "✅ Approve" button emits
   choice `run` (`sase-telegram` repo, `src/sase_telegram/formatting.py:406-433`), which only `_plan_response_json`
   handles (`plan_approval_actions.py:118-123`). `run` is absent from `PLAN_APPROVAL_KINDS`
   (`plan_approval_actions.py:15`), so the archive side-effect gate (`plan_approval_actions.py:217`) silently skips for
   Telegram approvals — a suspected live bug, and untested. The mobile closed enum `PlanActionChoiceWire` also carries
   `Run` (sase-core linked repo, `crates/sase_core/src/notifications/mobile.rs:168-177`).
3. **The display-label split is cheaper than the doc feared.** Scan-wire statuses are opaque strings on both sides
   (`src/sase/core/agent_scan_wire_markers.py:229`; sase-core `crates/sase_core/src/agent_scan/wire.rs:375`), and all
   display-label derivation is Python/TUI-side. Custom family roles likewise need no sase-core changes —
   `agent_family_role` is an open string end to end. What _genuinely_ requires sase-core work: new pending-action kinds
   (`LaunchApproval`) and new mobile approval choices (closed enums + response planners + contract fixtures in
   `crates/sase_core/src/notifications/{mobile,pending_actions}.rs`).

Other verified anchors phases rely on:

- Runner poll loop and response schema: `src/sase/llm_provider/_plan_utils.py:152-318` (accepted actions
  `{approve, epic, legend, commit}`; `tale` is `approve + commit_plan=True`).
- Auto modes support **approve/tale/epic only** (`src/sase/main/plan_approve_handler.py:30,59-77`); auto-action is
  checked before notification and re-checked in the poll loop (`_plan_utils.py:179-188,311-316`).
- The transition seam: `handle_accepted_plan` (`src/sase/axe/run_agent_exec_plan_accept.py:222`) — commit-only terminal
  at `:331`, epic/legend spawn at `:350-437`, coder spawn at `:438-531`, embedded VCS refs reconstructed at `:340` and
  appended to follow-up prompts. **There is no post-coder chaining seam**: the exec loop breaks when a coder completes
  un-killed (`src/sase/axe/run_agent_exec.py:187-222`, break at `:214-215`).
- Prompt-assembly helpers extracted by v1 now live in `src/sase/main/feedback_prompt.py` and
  `src/sase/main/qa_prompt.py` (re-exported via `src/sase/axe/run_agent_helpers.py`).
- v1 family-attach machinery: `src/sase/agent/family_attach.py` (strict `%n` validation, prep-time enforcement via
  `prepare_family_attach_launch`, Rust `resolve_agent_family_parent` binding), metadata contract in
  `create_followup_artifacts` (`src/sase/axe/run_agent_helpers_artifacts.py:97-191`), identity-keyed wait deps +
  family-aware terminal detection (`src/sase/core/wait_dependency_resolution.py`), cancel-to-STOPPED
  (`src/sase/axe/run_agent_runner.py:98-158`).
- Closed status sets untouched by v1: `src/sase/agent/status_buckets.py` (`_TERMINAL_STATUSES` at `:80-90`).
- Config-defined workflow blocks are verifiably ignored by both catalogs (Rust test at
  `crates/sase_core/src/xprompt_catalog.rs:3072`); file-backed YAML loaders are the extension point
  (`src/sase/xprompt/workflow_loader.py:334-543`; sase-core `xprompt_catalog.rs:989-1061`).
- Generated-skill pipeline is pure Python (`src/sase/main/init_skills_handler.py`); adding a skill source under
  `src/sase/xprompts/skills/` rides the existing render/deploy/inventory flow.

## Locked Decisions (carried from design review — do not re-litigate)

1. **No `%!`, no root bash/python rows, no custom status strings** — in any version of this project.
2. **v1 metadata is the compatibility contract.** A v1 `%n(foo, reviewer)` member must classify, group, and status
   correctly under the v2 evaluator with **no metadata migration** (explicit parity tests, not assumptions).
3. **Existing renderers are the v2 gate protocol.** Custom options surface through the existing `PlanApproval` renderer
   with data-driven choices; a generic decision renderer is out of scope until parity is proven.
4. **The interim-shortcut floor is the choice registry.** No "post-approval insertion list" config ships without the
   evaluator; below Phase 2, decline shortcuts.
5. **Stages sequence as: harness → registry → evaluator → after-code seam → custom roles → gate options →
   agent-initiated spawning.** "After plan" must not wait for "after code"; agent-initiated spawning (Phases 7–8) must
   not block Phases 3–6.

## Proposed Decisions (answers to the design doc's open questions — challenge at plan review, not mid-phase)

1. **Definition surface:** custom members/options are defined in **file-backed `kind: agent_family` YAML** living in the
   existing xprompt directories, loaded by a new Python loader following the workflow-loader pattern. Config-only
   definitions are a non-goal. The built-in `standard_plan_chain` definition is compiled-in Python data, not YAML. Rust
   catalog visibility for `agent_family` files is deferred (non-goal for v2).
2. **Approval UX:** custom members appear as **toggles inside `ApproveOptionsModal`** (the existing `c` path) plus CLI
   flags; **per-project sticky defaults** in config. Telegram/mobile do not get member toggles in v2 — remote approvals
   apply the project's sticky defaults. This is the anti-option-explosion posture from the design critique.
3. **Re-review policy:** per-role `on_done: re_review | continue | terminate`. `improve_plan` defaults to `re_review`
   (its output re-enters the plan gate). Every role placed on a looping edge requires a `max_visits` loop cap (default
   3); the evaluator hard-stops and notifies at the cap.
4. **The after-code event:** `role_completed` is emitted from **runner finalize** (the exec-loop seam where a follow-up
   completes un-killed), uniformly for code, epic, and legend follow-ups; the evaluator decides whether it means
   anything. For the standard chain it maps to terminate — no behavior change.
5. **VCS-ref composition:** inserted post-code members run **after** the coder run completes, i.e. after the coder's
   reconstructed `#propose`/`#commit` post-steps. A v2 `tester` tests the proposed CL and reports; "tester blocks
   propose" (restructuring where VCS refs execute) is explicitly deferred with its failure policy limited to notify +
   record.
6. **Auto-mode policy:** every custom role **must declare `auto: run | skip`** (schema-required, no default), so
   `%auto:tale`-style flows have explicit, documented behavior. Sticky defaults apply under auto modes only when the
   role says `auto: run`.
7. **Agent-initiated spawning:** always a fresh `LaunchApproval` in v2. Bounded delegated budgets (max members, depth,
   expiry) are designed in the YAML schema as reserved fields but **not implemented**.
8. **Label/semantic split:** custom roles ship with generic RUNNING/DONE statuses until Phase 9, which adds **display
   labels derived from role definitions** (not launch-site kwargs — the dropped v1 kwargs stay dead). Semantic buckets
   stay closed-set.
9. **The `run` choice:** becomes a first-class registry entry in Phase 2 (it is the Telegram/mobile "Approve"), and the
   skipped-archive side effect is confirmed and fixed there.
10. **Sequencing with other work:** Phases 1–2 are pure hardening and can start immediately; Phase 7 can run in parallel
    with 3–6; Phase 8 lands only after both 5 and 7.

## Phasing Overview

Nine phases. Each phase is completed by a distinct agent instance, is independently landable (green `just check`,
committed), and leaves the product releasable. Every phase agent must run `just install` before other `just` commands
(ephemeral workspaces) and `just check` before finishing; phases touching TUI rendering also run `just test-visual`.

| Phase | Deliverable                                                          | Depends on |
| ----- | -------------------------------------------------------------------- | ---------- |
| 1     | Golden-equivalence harness for the plan/questions lifecycle          | —          |
| 2     | Data-driven plan-approval choice registry (+ `run` choice fix)       | 1          |
| 3     | Typed handoff events + built-in `standard_plan_chain` evaluator      | 1, 2       |
| 4     | `role_completed`: the after-code seam                                | 3          |
| 5     | `agent_family` YAML: custom roles as data (`improve_plan`, `tester`) | 3, 4       |
| 6     | Approval-gate member options + per-project sticky defaults           | 2, 5       |
| 7     | `LaunchApproval` pending action + launch preview infrastructure      | —          |
| 8     | `/sase_run` generated skill + agent-initiated launch gating          | 5, 7       |
| 9     | Display-label split for custom roles                                 | 5          |

Phase 7 may run in parallel with Phases 3–6. Phase 9 may run any time after Phase 5.

---

## Phase 1 — Golden-equivalence harness for the plan/questions lifecycle

**Goal:** pin the exact current behavior of every plan/questions flow so Phases 2–5 can restructure with proof of
equivalence. Tests only (plus minimal non-behavioral test hooks); no production behavior change.

**Why first:** this is the memo's step 1 and what makes every later stage safe. Existing coverage is already strong (see
the inventory below) — this phase fills gaps and organizes the whole set into a named harness later phases run.

**Current coverage worth reusing (verified):** modal/choice mapping (`tests/test_plan_rejection_response.py`,
`tests/test_plan_approval_modal_title.py`, `tests/test_approve_options_modal_state.py` et al.), CLI kinds end-to-end
(`tests/test_plan_approve_cli.py`, `tests/main/test_parser_plan.py`), poll loop + auto modes + killed
(`tests/test_plan_utils.py`, `tests/test_axe_run_agent_exec_killed_iteration.py`), accepted-plan seam
(`tests/test_axe_run_agent_exec_plan_followup_approvals.py`, `..._coder_prompt.py`, `..._model_selection.py`,
`..._epic_refs.py`, `..._chat_paths.py`, `tests/test_epic_approval.py`), feedback/questions
(`tests/test_followup_prompt_helpers.py`, `tests/test_axe_run_agent_exec_plan_followup_questions.py`,
`tests/test_axe_run_agent_helpers_questions.py`).

**Scope:**

1. Define the harness as a discoverable suite (e.g. a `tests/plan_chain_golden/` package or a pytest marker such as
   `-m plan_chain_golden` that also tags the existing files above) with a README saying exactly what invariants it pins
   and how later phases must run it.
2. Close the verified coverage gaps:
   - the `run` choice through `execute_plan_approval_response` / `_plan_response_json` (pin _current_ behavior,
     including the skipped archive side effect — Phase 2 changes it deliberately);
   - the `result.choice is None` fallback branches in `_notification_modals.py`
     (`_plan_approval_protocol_fields:243-246`, `_plan_approval_choice_for_status:333-341`);
   - a loop-level test asserting a normally-completing coder **breaks** the exec loop (the "no post-coder seam"
     invariant Phase 4 will deliberately relax);
   - `handle_plan_marker` → `"killed"` outcome when the poll returns None after a kill;
   - negative tests: auto mode rejects `legend`/`commit` values.
3. Golden response-JSON snapshots for every choice/kind on every writer path (modal result, CLI kind, `run`), and golden
   prompt-body snapshots for feedback-replan and Q&A follow-up rounds (byte-level, extending
   `tests/test_followup_prompt_helpers.py` patterns).
4. Cover the memo's validation checklist items not yet pinned: marker freshness/stale rejection and user-kill-wins
   ordering (extend the existing `killed_iteration` tests if gaps remain), duplicate-response conflict semantics,
   `SASE_PLAN` committed vs archived selection, `SASE_CODER_INHERIT_PLANNER_CHAT`.

**Non-scope:** no production code changes beyond inert test seams; no new statuses, choices, or events.

**Acceptance:** harness runs green as a named unit; a short doc section (in the harness README) maps each pinned
invariant to the phase that relies on it; coverage gaps listed above each have at least one test.

---

## Phase 2 — Data-driven plan-approval choice registry

**Goal:** one source of truth for the approval-choice vocabulary, consumed by every surface that currently hard-codes
it. Behavior change is limited to the deliberate `run`-choice fix.

**Scope:**

1. Introduce a registry module (e.g. `src/sase/plan_approval_choices.py`) of choice records: id, modal key, display
   label, consequence text, protocol fields (`action`, `commit_plan`, `run_coder`), CLI kind name, response message,
   archive/side-effect participation, auto-mode eligibility. Fold the existing canonical
   `_PLAN_APPROVAL_CHOICE_PROTOCOL` into it.
2. Convert the independent sites to consume it: `_plan_response_json` + `PLAN_APPROVAL_KINDS`
   (`src/sase/plan_approval_actions.py`), CLI `--kind` choices (`src/sase/main/parser_plan.py`), the
   `_notification_modals.py` status/persist inference branches, `ApproveOptionsModal` display tables, modal
   `BINDINGS`/footer strings.
3. Make `run` a first-class registry entry (Telegram/mobile "Approve"); confirm and fix the skipped plan-archive side
   effect for `run`, updating the Phase 1 golden deliberately and adding a regression test.
4. Contract tests that assert registry ↔ external-surface agreement where the consumer lives in another repo: the mobile
   `PlanActionChoiceWire` variants and the Telegram callback choice strings are asserted as a pinned snapshot list in
   this repo, with a comment naming the sase-core/sase-telegram anchors, so vocabulary drift fails a test here even
   though those repos are not imported.
5. No new choices, keys, or kinds in this phase.

**Acceptance:** Phase 1 harness green except the one deliberate `run`-archive golden update (called out in the commit);
grep-level assertion (test or lint) that the retired tables are gone; registry docstring documents that Phase 6 will
extend it with member options.

---

## Phase 3 — Typed handoff events + built-in `standard_plan_chain` evaluator

**Goal:** the runner's marker-driven dispatch routes through typed events and a family evaluator executing a compiled-in
`standard_plan_chain` definition — with byte/metadata/prompt equivalence proven by the harness.

**Why:** this is the architectural core of v2. After this phase, "what happens next in a family" is answered by data (a
family definition) instead of hard-coded branches, which is what makes Phases 4–6 config-level work.

**Current state:** `_handle_killed_iteration` (`src/sase/axe/run_agent_exec.py:118-144`) reads/deletes
`.sase_plan_pending` / `.sase_questions_pending` with freshness checks and dispatches to `handle_plan_marker` /
`handle_questions_marker`; those functions own gate blocking, response interpretation, suffix allocation, follow-up
artifact creation, and prompt reconstruction inline.

**Scope:**

1. **Event adapter layer.** Convert markers into typed events (`plan_submitted`, `questions_submitted`) carrying the
   interrupted role, artifacts dir, and payload. Preserve exactly: user-kill-wins ordering, marker freshness windows,
   consume-once semantics (the memo's edge cases 1–3).
2. **Family evaluator + built-in definition.** A `standard_plan_chain` definition (Python data) declaring roles
   (root/plan/q/code/epic/legend/commit/feedback), gates (plan_review → the Phase 2 choice registry; user_questions),
   transitions, prompt-template hooks (delegating to the existing helpers in `src/sase/main/feedback_prompt.py` and
   `src/sase/main/qa_prompt.py`), and curated side-effect ids (write_sdd, commit_sdd, set_sase_plan_env, …). The
   evaluator consumes an event + persisted family state and returns the next gate/role/prompt/suffix/metadata/side
   effects; `handle_plan_marker` / `handle_questions_marker` / `handle_accepted_plan` become thin executors of evaluator
   decisions. Existing request/response files, notification actions, and renderers are untouched.
3. **Family state persistence.** Persist `agent_family_config_id`, `agent_family_config_version`,
   `agent_family_config_hash`, active gate id, and a compact `family_state` (feedback bullets refs, QA round refs, visit
   counters) additively in agent artifacts, so old rows stay self-describing and gates are resumable after definition
   edits. Runner-local only — no scan-wire additions in this phase (the TUI needs nothing new while behavior is
   identical).
4. **v1→v2 compatibility parity test:** a `%n(foo, reviewer)`-attached member and a runner-created follow-up both
   classify/group/status correctly under the evaluator with no metadata migration (extend
   `tests/test_dynamic_agent_family_attach.py`).
5. Auto modes route through the same evaluator path (auto-action short-circuits remain semantically identical).

**Constraints:** the largest parity-risk phase — the Phase 1 harness is the acceptance gate, not a nice-to-have. Keep
the evaluator pure (no I/O) so its classification can later move behind the Rust boundary; do not move it to sase-core
in this phase.

**Acceptance:** full harness green with zero golden changes; parity test from scope item 4; evaluator unit tests for
every standard-chain transition including feedback loops and questions-in-every-phase; family-state fields present on
new artifacts and absent-tolerated on old ones.

---

## Phase 4 — `role_completed`: the after-code seam

**Goal:** a new lifecycle event at follow-up finalize, giving the evaluator a decision point after `code` (and
epic/legend) members complete — with no behavior change for the standard chain.

**Current state:** the exec loop breaks unconditionally when a follow-up completes un-killed
(`src/sase/axe/run_agent_exec.py:214-215`); Phase 1 pinned this invariant.

**Scope:**

1. Emit `role_completed` (role, outcome, artifacts ref) from the runner finalize seam for family follow-ups — uniformly
   for code, epic, and legend branches (proposed decision 4).
2. The evaluator consumes it; `standard_plan_chain` maps every `role_completed` to terminate, so the loop still breaks —
   update the Phase 1 loop-level test to assert the break now happens _via_ the evaluator decision.
3. Define the composition rule with embedded VCS refs in the definition schema: post-code members sequence after the
   coder's reconstructed `#propose`/`#commit` post-steps (proposed decision 5). Document this on the event.
4. Failure semantics groundwork: the event carries outcome (success/failed/stopped) so Phase 5 role placements can
   branch on it; the standard chain ignores it.

**Acceptance:** harness green (loop-level test updated as described, everything else byte-identical); unit tests for
event emission on coder, epic, and legend completion, and for kill-during-follow-up NOT emitting `role_completed` (the
existing marker path must win).

---

## Phase 5 — `agent_family` YAML: custom roles as data

**Goal:** users can define custom family members declaratively — `improve_plan` placed after `plan`, `tester` placed
after `code` — and the evaluator runs them at the declared lifecycle points.

**Scope:**

1. **Schema + loader.** A `kind: agent_family` YAML schema (id, version, extends `standard_plan_chain`, roles with:
   suffix, prompt template as xprompt reference, placement `after: <role>` bound to gate-insertion or `role_completed`,
   `on_done: re_review | continue | terminate`, `max_visits`, `on_failure: notify_and_continue | notify_and_stop`,
   required `auto: run | skip`; reserved-but-unimplemented fields for delegated budgets). File-backed loader following
   the workflow-loader pattern (`src/sase/xprompt/workflow_loader.py` analogues) with the same precedence order; schema
   validation with loud, specific errors (suffixes validate against the reserved set in `src/sase/plan_chain.py`; legacy
   `.`/`-` spellings rejected). Python-only catalog visibility (`sase xprompt explain`-style listing); Rust catalog
   support is a non-goal.
2. **Evaluator execution.** Definition-placed members spawn through the existing follow-up machinery
   (`create_followup_artifacts`) with the v1 metadata contract, plus the Phase 3 family-config identity fields.
   `improve_plan`: runs after plan approval when placed, its output re-enters the plan gate per `on_done: re_review`,
   visit counters enforce `max_visits` with a hard-stop notification. `tester`: runs on `role_completed(code)`, after
   VCS post-steps; failure follows `on_failure`.
3. **Flagship definitions.** Ship `improve_plan` and `tester` example definitions (with prompt-template xprompts) as
   documented, tested examples — the acceptance vehicles for the schema.
4. **v1 interop.** A `%n(foo, improve_plan)` manual attach where `improve_plan` is a defined role: the member gets the
   role's placement-independent properties (role id recorded identically); parity test that manually-attached and
   evaluator-inserted members are indistinguishable to the TUI (grouping, statuses, dismissal).
5. **Auto-mode enforcement.** Definitions failing to declare `auto:` are rejected at load; `%auto` flows honor the
   declared value (tested both ways).
6. Loop/edge tests: definition edited mid-run (snapshot hash keeps the active run coherent), suffix collisions, unknown
   xprompt reference, cap exhaustion.

**Constraints:** custom roles display generic RUNNING/DONE statuses in this phase (labels arrive in Phase 9). No
approval-UX changes yet — placement is definition-driven; gate-time opt-in is Phase 6.

**Acceptance:** both flagship roles work end-to-end in integration tests (improve_plan loop with cap; tester after code
with both failure policies); harness green for projects with no custom definitions (zero-cost default); loader
validation test matrix; the interop parity test from scope item 4.

---

## Phase 6 — Approval-gate member options + per-project sticky defaults

**Goal:** the north-star UX — at plan approval time the user toggles which defined custom members run, with sticky
per-project defaults, without exploding the modal or remote surfaces.

**Scope:**

1. **Registry extension.** Phase 2's registry gains a member-options section populated from loaded `agent_family`
   definitions applicable to the project; the plan-approval request payload (`plan_request.json`) carries the available
   options and their defaults.
2. **TUI.** `ApproveOptionsModal` renders member toggles ("also run: improve_plan, tester") inside the existing `c`
   path; no new top-level modal keys.
3. **CLI.** `sase plan approve --with <role> / --without <role>` (repeatable) against the registry vocabulary.
4. **Response + runner.** `plan_response.json` carries the selected member set; the evaluator treats gate-selected
   members exactly like definition-placed members (same spawn path, caps, policies). Selection overrides defaults for
   that gate only.
5. **Sticky defaults.** Per-project config (`sase.yml` project scope) for default-on members; documented precedence:
   explicit gate selection > project default > definition default.
6. **Remote surfaces.** Telegram/mobile approvals apply sticky defaults (proposed decision 2); the request payload
   already names what will run so remote users can see it in the preview text. No remote toggles; no sase-core or
   sase-telegram code changes expected — assert via a payload-compat test that existing remote responders remain valid.
7. **Auto modes.** `%auto` flows consult sticky defaults filtered by each role's `auto:` declaration; covered by
   explicit tests (the critique's "testers that never ran" bug class).

**Constraints:** read `memory/tui_perf.md` via `/sase_memory_read` before touching the modal/loader paths. If new CLI
surface is added, follow the documented memory-read flow for `memory/cli_rules.md`.

**Acceptance:** end-to-end test: approve with tester toggled on → coder → tester runs; approve from a simulated remote
response (no member fields) → sticky defaults applied; CLI flags round-trip; harness green with no definitions present.

---

## Phase 7 — `LaunchApproval` pending action + launch preview infrastructure

**Goal:** the approval _infrastructure_ for agent-initiated spawning: a shared launch preview/request object and a
first-class `LaunchApproval` pending action across CLI/TUI/wire — with **no surface routed through it by default** (pure
additive capability; behavior-compatible).

**Why parallel-safe:** this touches launch planning and the notification/pending-action stack, not the plan-chain
evaluator; it can proceed alongside Phases 3–6.

**Scope:**

1. **Launch preview object.** A read-only preview/request builder covering the already-planned fanout (slots, planned
   names, prompt snippets/hashes, models, workspace refs, wait/defer, fanout counts, source surface, request id), shared
   by `launch_agents_from_cwd()` and the TUI launch path — per the 2026-06-04 memo's "shared service, not a call-site
   patch" rule. Files: `launch_request.json`, `launch_preview.md`, `launch_response.json`.
2. **Pending action kind (sase-core work).** Add `LaunchApproval`: Python mapping + per-kind branches
   (`src/sase/notifications/pending_actions.py:26-31,307-344`), sender in `src/sase/notifications/senders.py` modeled on
   `notify_plan_approval`; in the sase-core linked repo: `MobileActionKindWire` variant, string mappings, pending-action
   gate, label, a `MobileActionDetailWire` variant + choices enum (Approve/Reject, reject-with-feedback)
   - response planner, gateway route support, contract fixture updates, and the relevant `*_SCHEMA_VERSION` bumps
     (`mobile.rs`, `pending_actions.rs`). Follow the linked-repository workspace flow and update sase-core tests there.
3. **Surfaces.** TUI modal (approve/reject + preview render) and CLI (`sase launch approve/reject <request-id>` or
   equivalent under an existing namespace) for resolving a pending request.
4. **Auto-approve precedence** (env + agent-meta, mirroring the plan-approval precedence chain) wired **before** any
   blocking policy exists, so headless flows can never deadlock.
5. All-or-nothing batch semantics for multi-slot requests; revalidation on approval (the approved graph is the spawned
   graph).

**Non-scope:** no Telegram free-form launch policy changes; no `/sase_run`; nothing routes through the gate yet.

**Constraints:** follow `memory/cli_rules.md` flow for new CLI surface; sase-core changes via the linked-repository
workspace flow; keep old mobile clients safe (schema-version guards are per-boundary — bump the ones you touch).

**Acceptance:** unit + integration tests for request→approve→dispatch and request→reject→no-spawn; auto-approve
precedence tests; sase-core contract fixtures updated with round-trip tests; a smoke test proving default launch
behavior on every surface is byte-identical to before (nothing gated).

---

## Phase 8 — `/sase_run` generated skill + agent-initiated launch gating

**Goal:** agents request member spawns instead of spawning; agent-initiated launches route through `LaunchApproval`.

**Scope:**

1. **Host-side request command.** A thin launch-request entry point (e.g. `sase run request <json>` or flags on
   `sase run`) that builds the Phase 7 preview/request, registers the pending action, and returns the request id — never
   spawning directly. Schema per the memo (`schema_version`, `prompt`, `reason`, `approval`, `max_slots`).
2. **Generated skill.** `src/sase/xprompts/skills/sase_run.md` teaching agents to submit structured launch requests
   (including family attach via `%n(parent, suffix)` in the requested prompt) and to poll/handle the approved/rejected
   outcome. Deployed via the existing `sase skill init` pipeline; read `memory/generated_skills.md` via
   `/sase_memory_read` first; keep CLI/skill examples synchronized.
3. **Gating rule.** Launch requests originating from a running agent context (`SASE_AGENT` set) require an approved
   `LaunchApproval` before dispatch; user-typed surfaces (CLI/TUI/Telegram user prompts) remain ungated — v1's decision
   that user-initiated `%n` needs no gate is preserved verbatim.
4. **Telegram rendering** of `LaunchApproval` (approve/reject buttons + compact preview) in the sase-telegram linked
   repo via its existing actionable-notification path; mobile support rides the Phase 7 wire work.
5. **Delegated budgets:** not implemented (reserved schema fields only); every agent-initiated request is a fresh
   approval (proposed decision 7).

**Acceptance:** end-to-end test: agent-context request → pending action → approve → member spawns with correct family
metadata; reject → no spawn + on-surface reply; user-typed `%n` prompts still launch ungated (regression tests from
`tests/test_dynamic_agent_family_attach.py` stay green); skill-generation tests updated; Telegram formatting/callback
tests in the plugin repo.

---

## Phase 9 — Display-label split for custom roles

**Goal:** custom roles get human display labels (`improve_plan` deserves better than `RUNNING`) without touching the
closed semantic status sets.

**Current state (recon correction):** wire statuses are opaque strings and all label derivation is Python/TUI-side —
this phase is Python-local, cheaper than the design doc assumed. Only mobile's closed `action_label` set would need
sase-core work, and that is out of scope here.

**Scope:**

1. Role definitions (built-in and YAML) gain optional `label` / `done_label` display strings; validation bounds
   length/charset.
2. The TUI status pipeline (`src/sase/ace/tui/models/_agent_status_apply.py`, `_agent_status_family.py`,
   `agent_status.py`) renders role-derived labels for custom-role members while **bucketing them through the existing
   closed sets** (`status_buckets.py` untouched) — label is presentation, bucket is semantics. Dismissal, mirroring,
   ordering, and waiting behavior key off buckets, never labels.
3. Launch-site label kwargs remain rejected (`%n` strictness unchanged) — labels come only from role definitions.
4. PNG visual snapshots for an `improve_plan` and `tester` member showing custom labels under a family root.

**Constraints:** read `memory/tui_perf.md` first; no new synchronous I/O in loaders; `just test-visual` required.

**Acceptance:** visual snapshots; unit tests proving bucket/label independence (a labeled custom role still buckets,
dismisses, and mirrors exactly like a generic one); existing agents-tab snapshots unchanged except intentional
additions.

---

## Non-Goals (v2)

- Generic decision/form renderer; per-slot launch approval; delegated launch budgets (schema-reserved only).
- Telegram free-form launch approval overhaul and `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` policy evolution.
- `agent_family_type` horizontal classification (the 2026-06-04 memo's broader scope).
- Config-defined (non-file-backed) family definitions; Rust catalog visibility for `agent_family` YAML.
- Remote (Telegram/mobile) member toggles at the approval gate.
- Changes to closed semantic status sets; launch-site status/label kwargs.
- Dotted sibling-family unification; `%!`; root bash/python rows.

## Risks and Mitigations

1. **Parity regressions during restructuring (Phases 2–4).** The Phase 1 harness is the acceptance gate for every
   restructuring phase; any golden change must be deliberate, singular, and called out in the commit.
2. **The `run`-choice fix changes remote behavior.** Telegram "Approve" gains plan archiving. Mitigation: explicit
   regression test + changelog callout in Phase 2.
3. **Loop runaway (`improve_plan` re-review).** Required `max_visits` with hard-stop notification; evaluator unit tests
   for cap exhaustion (Phase 5).
4. **Auto-mode silent skips.** `auto:` is schema-required with no default; load-time rejection plus behavior tests both
   ways (Phases 5–6).
5. **Wire contract churn (Phase 7).** New pending-action kind crosses Python/Rust/gateway/mobile; per-boundary schema
   versions bumped, contract fixtures snapshot-locked, old-client tolerance tested in sase-core.
6. **Option explosion in approval UX.** Members live only inside `ApproveOptionsModal` + sticky defaults; remote
   surfaces never grow per-member buttons in v2.
7. **Definition drift vs running families.** Family config id/version/hash snapshotted into artifacts (Phase 3); active
   runs evaluate against their snapshot, tested by the mid-run-edit case (Phase 5).
8. **Cross-repo scope creep.** sase-core work is isolated to Phases 7 (pending action) and nothing else; sase-telegram
   work is isolated to Phase 8. Each cross-repo change updates that repo's tests per the boundary rule and uses the
   linked-repository workspace flow.
9. **TUI performance.** Phases 6 and 9 touch hot paths; `memory/tui_perf.md` is required reading there, and no new
   synchronous I/O is allowed in loaders.

## Verification (every phase)

- `just install` first (ephemeral workspaces), then `just check` green before finishing; `just test-visual` when TUI
  rendering is touched.
- Phases 2–5: the Phase 1 golden harness is part of the definition of done.
- Each phase ends with a commit of its own scope via the sanctioned commit flow, leaving `master` releasable.
