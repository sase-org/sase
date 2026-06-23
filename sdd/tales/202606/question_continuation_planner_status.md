---
create_time: 2026-06-23 08:09:02
status: done
prompt: sdd/prompts/202606/question_continuation_planner_status.md
---
# Plan: Fix status + runtime for a `%approve` question-continuation planner family

## Problem

When an agent is launched with the `%approve` directive and asks a question via its `/sase_questions` skill, the
question is auto-answered and the agent continues into planning. In this flow SASE produces a three-row family on the
Agents tab, and two of the rows render the **wrong status** (and one the wrong runtime).

Concrete failure captured in `.sase/home/tmp/screenshots/20260623_072913.png` (family `03w`):

| Row (display)                 | Role on disk                                                  | Current (wrong)                                                                        | Desired                                                                       |
| ----------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `03w--0` (the question asker) | family root, `role_suffix=--0`, asked the question            | **PLAN APPROVED**, runtime ticking `🏃 27m48s`                                         | **ANSWERED** (the question was auto-answered)                                 |
| `03w--1` (the plan approver)  | follow-up planner, `role_suffix=--plan`, approved a tale plan | **QUESTION**, frozen `07:05:50 · ✋ 0s` (paused marker, anchored at the question time) | **TALE APPROVED**, runtime **frozen** at plan submission, no `✋`/`🏃` marker |
| `03w--code`                   | coder                                                         | WORKING PLAN, ticking                                                                  | WORKING PLAN, ticking (already correct)                                       |

In other words the two non-coder rows have effectively **swapped** statuses: the asker shows the approver's
plan-approval state, and the approver shows the asker's (already-answered) question state.

This is a follow-on to the recently shipped "Freeze runtime for `PLAN APPROVED` / `TALE APPROVED` rows" change. That
change is correct; this plan fixes the remaining edge cases in how the status itself is _derived_ for the
question-continuation-planner shape, after which the existing runtime-freeze logic produces the right runtime for free.

## How this family is shaped on disk (the key to the bug)

The real `agent_meta.json` files for this run show an unusual but legitimate shape produced by `%approve` + a question:

- **`03w` (root)** — `agent_family_role=root`, `role_suffix=--0`, `plan_chain_root=true`, `approve=true`,
  `questions_submitted_at=<Q>`. It has **no plan metadata of its own** (no `plan_submitted_at`, no `plan_action`). It is
  the agent that called `/sase_questions`; with `%approve` the question was auto-answered and the family continued. By
  screenshot time the root's own process had finished (status `DONE`) while the coder kept the family alive.
- **`03w--1` (the continuation planner)** — `parent_timestamp=<root>`, `agent_family_role=q`, `role_suffix=--plan`,
  `plan_approved=true`, `plan_action=tale`, `plan_submitted_at=<P>`, **and** an _inherited_ `questions_submitted_at=<Q>`
  (identical to the root's value, recorded one second before this agent was even created). It is the question
  continuation that went on to draft and approve the plan. It was killed right after approval (no `done.json`), so it
  loads with a base status of `DONE`.
- **`03w--code` (the coder)** — `parent_timestamp=<root>`, `agent_family_role=code`, `role_suffix=--code`, running.

Two facts about this shape break the current status derivation:

1. The continuation child carries **both** an inherited question (`<Q>`) **and** its own approved plan (`<P>`).
2. Its effective family role is ambiguous: `agent_family_role=q` in meta, but `role_suffix=--plan`. The shared resolver
   `agent_family_role_for_suffix("--plan", agent_family_role="q")` returns **`"plan"`** — the suffix wins over the meta
   role.

## Root-cause diagnosis

All of the affected logic is Python TUI presentation code (status overrides + runtime formatting). The behavior was
reproduced exactly against the real on-disk metadata by reconstructing the screenshot-time family and running the real
`apply_status_overrides` + runtime helpers; the reproduction matched the screenshot row-for-row.

There are two independent derivation bugs (plus one related robustness gap):

### Bug A — the asker row (`03w--0`) shows PLAN APPROVED instead of ANSWERED

`03w--0` is the root's main planner row, whose status is synced from the root via `planner_child_status()` in
`src/sase/ace/tui/models/_agent_status_family.py`. That function consults `_approved_planner_status()` **before** the
"asked a question, never planned" branch. `_approved_planner_status()` treats the mere existence of a `code` descendant
as proof the family's plan was approved and returns `PLAN APPROVED` — even though _this_ root never submitted or
approved a plan (no `plan_times`, no approved `plan_action`); the plan was approved by the continuation child. The
intended status, `ANSWERED`, is only reached _after_ the approved check, so it never fires.

### Bug B — the approver row (`03w--1`) shows QUESTION (paused) instead of TALE APPROVED

There is **no derivation path** that gives a _follow-up_ agent its own approved-plan status. The existing TALE/PLAN
APPROVED path applies only to a root's synced **workflow-step** planner child (driven by the _root's_ `plan_action`).
`03w--1` is a concrete follow-up agent carrying its _own_ `plan_action=tale`, so it never gets TALE APPROVED, and falls
through with its base `DONE` status.

It is then actively mislabeled `QUESTION` by the "unanswered completed question" override in
`src/sase/ace/tui/models/_agent_status_apply.py`. That override is supposed to be suppressed for inherited family
questions by `has_inherited_family_question()`, but that guard bails when the row's role is not `"q"` — and `03w--1`'s
resolved role is `"plan"` (suffix wins). So the inherited question is treated as a genuine pending question, the row
becomes `QUESTION`, the runtime anchors at the (already-answered) question time, and the renderer adds the `✋`
user-paused marker.

### Related gap C — the inherited-question guard keys on the wrong role signal

`has_inherited_family_question()` identifies question-continuations via the suffix-resolved role (`!= "q"` ⇒ bail). For
a continuation that also took the `--plan` suffix, the resolved role is `"plan"`, so the guard misses a genuinely
inherited question. The true "this is a question continuation" marker is the raw `agent.agent_family_role == "q"`
written at launch.

## Design

Keep all changes in the Python TUI status-derivation layer. No `sase-core` / `sase_core_rs` changes (the role resolver
and wire schema are shared and out of scope), no runtime-formatting changes, and no render-layer changes — once the
_status_ is correct, the existing runtime-freeze rule (`status ∈ APPROVED_PLAN_STATUSES and plan_times` ⇒ frozen, no
tick) and the existing marker rule (`✋` only for `AGENT_ASKING_STATUSES`) produce the desired runtime and markers
automatically. This was verified in the reproduction.

### Change A — asker with an answered question but no plan of its own reads as ANSWERED

In `planner_child_status()` (`_agent_status_family.py`), evaluate the "has a family follow-up child, asked a question,
submitted no plan of its own" → `ANSWERED` case **before** `_approved_planner_status()`. This stops a continuation's
coder from mislabeling the asker row as an approved-plan row. Gating on `questions_times and not plan_times` keeps every
existing case intact: a root that actually submitted/approved a plan (with or without an earlier question) still has
`plan_times`, so it skips the ANSWERED branch and resolves to its approved status as today.

### Change B — a follow-up planner that approved its own plan reads as TALE/PLAN APPROVED (and is therefore frozen)

Add a small helper (`approved_followup_planner_status()`) in `_agent_status_family.py` that returns the sticky approved
status for a concrete follow-up planner that approved its _own_ plan: role resolves to `plan`, it has `plan_times`, and
`plan_action` is an approved planner action (`tale` ⇒ `TALE APPROVED`, otherwise `PLAN APPROVED`).

In `apply_status_overrides()`, apply this to a finished (`DONE`) follow-up agent (`parent_timestamp` set,
`parent_workflow` is `None`) whose parent is a root plan workflow, **before** the QUESTION overrides. Setting the
approved status first means the row is no longer `DONE`, so the "unanswered completed question" override no longer fires
for it — fixing the mislabel at its source. The row then freezes at plan submission and drops the `✋` marker via the
existing rules. This path is scoped to follow-up agents, so the existing root-synced workflow-step planner behavior
(driven by the root's `plan_action`) is untouched.

### Change C — make the inherited-question guard recognize continuations by their launch-time role

In `has_inherited_family_question()`, treat a row as a question-continuation when **either** the resolved role is `"q"`
**or** the raw `agent.agent_family_role == "q"`. This closes the role-resolution gap for continuations that also carry a
planner suffix. It is safe because the function's real discriminator — `question_times ⊆ parent.questions_times` — still
guarantees the question was inherited (a continuation's _own_ new question has a timestamp the parent lacks, so the
subset test fails and a genuine pending question is never suppressed). This is defensive depth: Change B already
prevents the reported mislabel for approved planners; Change C additionally covers a continuation-planner that is `DONE`
with an inherited question but no approved plan.

### Why this is sufficient and contained

- Asker `03w--0`: question, no plan of its own, has follow-up children ⇒ `ANSWERED` (Change A). Runtime follows normal
  `ANSWERED` semantics; the user's freeze requirement is specifically about the approver row.
- Approver `03w--1`: own approved tale plan ⇒ `TALE APPROVED` (Change B) ⇒ runtime frozen at plan submission with no
  `🏃`/`✋` marker (existing freeze + marker rules). Verified: `('', '<plan-submit>') · <dur>`, `ticks=False`.
- Coder `03w--code` and the family root row are unchanged (root still mirrors the newest child ⇒ WORKING PLAN).
- Normal families where the **root** is the planner keep their current behavior: the root carries `plan_action`/
  `plan_times`, so Change A's ANSWERED branch is skipped and the root's synced workflow-step planner child still
  resolves to TALE/PLAN APPROVED through the existing path; Change B only targets follow-up (non-workflow-step) agents.

## Implementation

All edits are in `src/sase/ace/tui/models/`:

- `_agent_status_family.py`
  - Reorder `planner_child_status()` so the `ANSWERED` (question-without-own-plan, with follow-up) branch precedes
    `_approved_planner_status()` (Change A).
  - Add `approved_followup_planner_status(agent)` returning `TALE APPROVED` / `PLAN APPROVED` / `None` (Change B
    helper).
  - Broaden `has_inherited_family_question()` to also accept `agent.agent_family_role == "q"` (Change C).
- `_agent_status_apply.py`
  - In the follow-up-children pass (the one that currently applies the QUESTION override), set the approved status from
    `approved_followup_planner_status()` for a `DONE` follow-up agent under a root plan workflow, before the QUESTION
    override (Change B). Import the new helper.

No changes to `agent_time.py`, `_agent_list_render_layout.py`, the meta-enrichment loaders, or `status_buckets.py`.

## Tests

Add regression coverage (these data shapes have no existing tests):

- In `tests/test_agent_loader_status_override_questions.py` (or a sibling): the full reported family — root (answered
  question, no plan) + follow-up continuation planner (`role_suffix=--plan`, `agent_family_role=q`, `plan_action=tale`,
  `plan_times`, inherited `questions_times`, `DONE`) + running coder — asserts asker ⇒ `ANSWERED`, continuation planner
  ⇒ `TALE APPROVED`, coder ⇒ `WORKING PLAN`, root ⇒ `WORKING PLAN`.
- A `PLAN APPROVED` variant (`plan_action=approve`) of the continuation planner.
- Change C unit: a continuation with raw `agent_family_role=q` but `role_suffix=--plan` and an inherited question (no
  approved plan) is **not** forced to `QUESTION`; and the existing "new unanswered question round ⇒ QUESTION" case still
  holds (a continuation with a question timestamp the parent lacks stays blocked).
- A runtime assertion (in `tests/ace/tui/widgets/`) that the continuation planner row, once `TALE APPROVED` with
  `plan_times` and no `stop_time`, freezes at `max(plan_times)` and `runtime_suffix_ticks(...) is False`.

Confirm the existing suites stay green, especially the root-synced workflow-step planner tests
(`tests/test_agent_loader_status_override_tale.py::...keeps_planner_child_tale_approved`) and the answered-question
family tests (`tests/test_agent_loader_status_override_questions.py`), which exercise the paths adjacent to these
changes.

## Validation

- `just install` then `just check` (ruff + mypy + fast tests).
- `just test-visual`: the `agents_plan_handoff_status_colors_*` snapshots are expected to pass without regeneration
  (their rows do not use this question-continuation shape); regenerate only if an intended visual change appears.
- Manual smoke in `sase ace`: launch an agent with `%approve` that asks a `/sase_questions` question and then submits a
  plan; confirm the asker row shows `ANSWERED`, the approver row shows `TALE`/`PLAN APPROVED` with a frozen
  (non-ticking, no `✋`) runtime, and the coder row keeps ticking.

## Scope / boundary

- Pure Python TUI presentation layer; **no `sase-core` / `sase_core_rs` changes**. The shared role resolver
  (`agent_family_role_for_suffix`) precedence and the wire/meta schema are intentionally left as-is.

## Out of scope

- The runtime-freeze mechanism itself (already correct from the prior change) and runtime formatting/markers.
- The family **root aggregate** row's tick rate (not reported here; unchanged in character by these status fixes).
- `EPIC APPROVED` / `LEGEND APPROVED` / `PLAN COMMITTED` continuation planners (Change B is scoped to the `tale`/
  `approve` planner actions, matching the prior change's PLAN/TALE scope).
- Feedback-round children that approve plans (role `feedback`), which keep their existing handoff handling.
