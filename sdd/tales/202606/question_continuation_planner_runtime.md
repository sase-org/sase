---
create_time: 2026-06-23 10:14:49
status: done
prompt: sdd/prompts/202606/question_continuation_planner_runtime.md
---
# Plan: Pin the runtime for the `ANSWERED` asker and `*APPROVED` approver rows of a `%approve` question-continuation family

## Problem

This is a direct follow-on to the recently shipped "Fix status + runtime for a `%approve` question-continuation planner
family" change. That change made the **statuses** correct (asker ⇒ `ANSWERED`, continuation planner ⇒ `TALE APPROVED` /
`PLAN APPROVED`), but the **runtimes** on those two child rows are still wrong. The user's screenshot of family `046`
(captured while the family was still running) shows:

| Row (display)            | Status          | Current runtime (wrong)              | Desired runtime                                   |
| ------------------------ | --------------- | ------------------------------------ | ------------------------------------------------- |
| `046—0` (question asker) | `ANSWERED`      | `🏃 44m29s`, **ticking**             | **frozen** at the answer time, ≈ asker's true run |
| `046—1` (plan approver)  | `TALE APPROVED` | `08:57:58 · 0s` (frozen, but **0s**) | **frozen** at plan submission, ≈ approver's run   |
| `046—code` (coder)       | `WORKING PLAN`  | ticking                              | ticking (already correct)                         |

The user's requirement, verbatim: _the agent child rows with the `ANSWERED` and `PLAN APPROVED` statuses should each
have pinned runtimes that correspond with the length of time that that agent ran for before completing._

In other words: both non-coder rows must be **frozen** (pinned), and each frozen duration must equal how long that
specific agent actually ran before it finished its phase — not the elapsed wall-clock, and not the whole family's
lifetime.

## What the screenshot-time data really is (reproduced against the real on-disk metadata)

The behavior was reproduced exactly by loading the three real `agent_meta.json` directories of family `046` through the
production loader (`load_artifact_delta_agents`) and computing `compute_row_runtime` / `runtime_suffix_ticks` at the
screenshot time. The reproduction matched the screenshot row-for-row. The on-disk shape:

- **`046` root (`role_suffix=--0`, `agent_family_role=root`, `plan_chain_root`, `approve`)** — asked a question at
  `12:57:58Z` (08:57:58 local); has **no plan metadata of its own**. Its own `main` agent step completed
  (`workflow_state.json: "status": "completed"`) at the handoff; the family continued in a separate agent.
- **continuation planner (`role_suffix=--plan`, `agent_family_role=q`, `approve`, `plan_action=tale`,
  `plan_submitted_at=13:18:11Z`/09:18:11 local, inherited `questions_submitted_at=12:57:58Z`)** — launched one second
  after the question (`08:57:59`), drafted and approved a `tale` plan, then was killed (no `done.json`).
- **coder (`role_suffix=--code`)** — running.

The crucial structural fact the previous change missed: **the loader represents each anonymous planner workflow as TWO
rows that share one timestamp** — a top-level follow-up agent **and** an inner workflow-`main` step (`step_type=agent`,
`parent_workflow` set). The visible row's runtime is the **aggregate** of its `runtime_children`, and the inner
workflow-`main` step is exactly that aggregated child. So a row's _status_ can be correct on the top-level object while
its _displayed runtime_ is driven by the inner step.

This is also **why the previous fix passed its tests but failed live**: those regression tests reconstructed the family
as flat top-level agents and asserted only `status`. They never created the inner workflow-`main` step and never
asserted the computed runtime, so the real defect was invisible to them.

## Root-cause diagnosis

All affected logic is Python TUI presentation code (status overrides + runtime formatting). There are two independent
bugs.

### Bug A — the `TALE APPROVED` approver row freezes at the question time with `0s`

The displayed `046—1` row aggregates its runtime from `runtime_children`, which is the continuation planner's inner
workflow-`main` step. That inner step is stuck at base status **`QUESTION`**, so its runtime anchors at
`max(questions_times)` (08:57:58) and its elapsed (`question_time − run_start`) is negative, clamped to `0s`. The
aggregate therefore shows `08:57:58 · 0s`, frozen.

The inner step is never corrected because it falls through every override path:

- It is a workflow step (`parent_workflow` set), so the follow-up `QUESTION`/approved-status passes — gated on
  `not parent_workflow` — skip it.
- Its parent (the top-level continuation) is **excluded from `parent_by_suffix`**: `Agent.is_workflow_child` returns
  `True` for _any_ agent that has a `parent_timestamp`, and a follow-up continuation has one. So the main-workflow-step
  sync looks up `parent_by_suffix[<continuation-ts>]` and gets `None`, and does nothing.

The top-level continuation object itself already gets `TALE APPROVED` (and its own leaf runtime would correctly freeze
at plan submission), but the displayed row uses the aggregate of the broken inner step instead of the top-level leaf.

### Bug B — the `ANSWERED` asker row ticks (and, after completion, freezes at the wrong, family-wide time)

The asker row `046—0` is the root's synced planner/main child; its status is `ANSWERED`. `ANSWERED` is treated as an
active leaf status, so while the family is alive the row **ticks** (44m29s in the screenshot). The asker actually handed
off at the answer time (08:57:58) after running ~10 minutes and did nothing afterward — a separate continuation took
over — so a ticking runtime is wrong.

After the family later completes on disk, the loader assigns this `main` step the **entire** anonymous workflow's
completion time (e.g. 09:46:07, which is really when the last descendant — the coder — finished), so the row then
freezes at ~58m. That equally overstates the asker's true run. The asker's `main` step itself completed at the handoff,
not when its grandchildren finished.

### Why the prior runtime-freeze rule wasn't enough

The prior change's freeze rule (`status ∈ APPROVED_PLAN_STATUSES and plan_times ⇒ freeze at max(plan_times)`) is correct
and stays. It only ever fired on the _top-level_ approved object, never on the inner workflow-`main` step that actually
drives the aggregate (Bug A), and there is no approved-plan anchor at all for the asker, which never planned (Bug B).

## Design

Keep all changes in the Python TUI status-derivation / family layer. **No `sase-core` / `sase_core_rs` changes** (the
role resolver and wire/meta schema are shared and out of scope) and **no runtime-formatting changes** — once each row's
_status_ and _terminal anchor_ are right, the existing freeze rules in `agent_time.py` produce the desired runtime and
markers automatically. Both fixes were verified against the real metadata (see "Verification" below).

### Change A — give an orphaned approved planner's inner workflow-step its own approved status

In `apply_status_overrides()` (`_agent_status_apply.py`), in the main-workflow-step pass, when a `main` workflow-step
agent has no syncing root parent in `parent_by_suffix` (i.e. it is the inner step of a follow-up continuation) **and**
it is itself an approved follow-up planner — `approved_followup_planner_status(agent)` returns non-`None` (role resolves
to `plan`, has `plan_times`, `plan_action ∈ {tale, approve}`) — set its status to that approved status.

Effect: the inner step becomes `TALE APPROVED` / `PLAN APPROVED`, so its leaf runtime freezes at plan submission via the
existing `APPROVED_PLAN_STATUSES` rule, and the visible row's aggregate becomes `09:18:11 · 20m11s`, frozen, no tick.

This is tightly scoped: it only fires for `main` workflow steps whose parent is absent from `parent_by_suffix` (an
orphaned continuation inner step) and that carry their own approved `tale`/`approve` plan. Normal root `main` steps have
their root registered as a parent and continue to flow through the existing sync path untouched. The asker's own inner
step is unaffected (`approved_followup_planner_status` returns `None` for it — it has no plan).

### Change B — freeze a handed-off `ANSWERED` asker at the answer time

When the root's synced/synthetic planner child resolves to `ANSWERED` **and** the family has a follow-up continuation
(the handoff actually happened) **and** the root has `questions_times`, set the child's `stop_time` to
`max(questions_times)` (the asker's handoff/completion instant). The existing terminal-time rule then freezes the row at
the answer time, the duration becomes `run_start → answer` (≈ the asker's true ~10-minute run), and the row stops
ticking. The `ANSWERED` status itself is preserved.

Apply this in both planner-child entry points so the behavior is uniform:

- `sync_planner_child_from_parent()` — the concrete root `main`-step asker (our reported case).
- `ensure_synthetic_planner_children()` — the synthetic asker created when no concrete `main` step exists.

via a small shared helper that returns the freeze instant for a handed-off answered asker (and `None` otherwise).

Why gating on the follow-up continuation matters: a genuinely live, single-agent post-answer resume is also `ANSWERED`
but has **no** follow-up continuation, so it is excluded and keeps ticking. Only a true handoff (a continuation exists)
freezes.

Why `stop_time` is the right carrier and is safe:

- It is the most accurate value available for the asker `main` step's actual completion; the loader's full-workflow
  completion time is an over-assignment for that step.
- `ANSWERED` + a set `stop_time` is **not a new combination** — the loader already produces exactly that for these rows
  after the family completes. So no invariant is introduced.
- Status bucketing (`status_bucket_for_values`) is **status-based**, so the row stays in the Running group; the bucket
  is unaffected. The only other `stop_time` readers are the sibling-time display, the unread cutoff, and a sort fallback
  — all minor and, for the asker, arguably more correct (it really did stop at the answer time). The family root mirrors
  the _newest child's status_ (not `stop_time`) and its aggregate stays alive via the running coder, so the family-level
  runtime/grouping is unchanged.

### Why this is sufficient and contained

- Approver `046—1`: inner step ⇒ `TALE APPROVED` (Change A) ⇒ aggregate frozen at plan submission. Verified
  `(('', '09:18:11'), '20m11s')`, `ticks=False`.
- Asker `046—0`: handed-off `ANSWERED` ⇒ `stop_time` = answer time (Change B) ⇒ frozen at the answer instant. Verified
  `(('', '08:57:58'), '9m57s')`, `ticks=False`, status still `ANSWERED`.
- Coder and the family root row are unchanged; both fixes are correct in the active window and after the family
  completes.
- A live, no-handoff `ANSWERED` resume keeps ticking (Change B's follow-up gate excludes it).

## Implementation

All edits in `src/sase/ace/tui/models/`:

- `_agent_status_apply.py`
  - In the main-workflow-step branch, when the syncing root parent is absent (orphaned inner step) and
    `approved_followup_planner_status(agent)` is non-`None`, set `agent.status` to it (Change A). Keep the existing
    root-sync and feedback branches intact.
- `_agent_status_family.py`
  - Add a small helper (e.g. `answered_asker_freeze_time(parent)`/equivalent) returning `max(parent.questions_times)`
    when the resolved planner-child status is the handed-off `ANSWERED` case (follow-up continuation present, has
    `questions_times`), else `None` (Change B helper).
  - In `sync_planner_child_from_parent()` and `ensure_synthetic_planner_children()`, set `child.stop_time` from that
    helper when it returns a value (Change B).

No changes to `agent_time.py`, the render layer, the meta-enrichment loaders, `status_buckets.py`, or the Rust core.

## Tests

The previous tests' blind spot — flat top-level agents, status-only assertions — must be closed. New coverage:

- **Aggregate-runtime regression for the approver** (in `tests/test_agent_loader_status_override_*` or a runtime sibling
  under `tests/ace/tui/widgets/`): build the realistic two-row continuation shape — a top-level follow-up planner
  **and** its inner workflow-`main` step (`parent_workflow` set, `step_type=agent`, `plan_action=tale`, own
  `plan_times`, inherited `questions_times`) attached as the top-level's `runtime_children` — run
  `_apply_status_overrides`, then assert `compute_row_runtime(top_level)` freezes at plan submission with duration
  `run_start → plan` and `runtime_suffix_ticks(...) is False`. Add a `plan_action=approve` (`PLAN APPROVED`) variant.
- **Runtime regression for the asker**: the full reported family (answered-question root with a concrete `main` step +
  continuation planner + running coder) ⇒ assert the asker row freezes at `max(questions_times)` with duration
  `run_start → answer`, `runtime_suffix_ticks(...) is False`, and the status is still `ANSWERED`.
- **Guard for live resume**: a root-question planner child that is `ANSWERED` with **no** follow-up continuation still
  ticks (its `stop_time` is not pinned to the answer time).
- Keep the existing status suites green, especially the question-continuation status tests added previously and the
  root-synced workflow-step planner tests (`tests/test_agent_loader_status_override_tale.py`).

## Validation

- `just install` then `just check` (ruff + mypy + fast tests).
- `just test-visual`: the `agents_plan_handoff_status_colors_*` snapshots are expected to pass without regeneration
  (their rows don't use this shape); regenerate only for an intended visual change.
- Manual smoke in `sase ace`: launch a `%approve` agent that asks a `/sase_questions` question and then submits a plan;
  confirm the asker row shows `ANSWERED` with a frozen (non-ticking) runtime ≈ its real run, the approver row shows
  `TALE`/`PLAN APPROVED` frozen at plan submission with a real (non-`0s`) duration, and the coder row keeps ticking —
  both while the family is still running and after it completes.

## Scope / boundary

- Pure Python TUI presentation layer; **no `sase-core` / `sase_core_rs` changes**. The shared role resolver precedence
  and the wire/meta schema are intentionally left as-is.

## Out of scope

- The runtime-freeze mechanism and runtime formatting/markers themselves (correct from the prior change; reused here).
- The family **root aggregate** row's tick behavior (unchanged; it stays alive via the running coder).
- `EPIC APPROVED` / `LEGEND APPROVED` / `PLAN COMMITTED` continuation planners (Change A reuses
  `approved_followup_planner_status`, already scoped to the `tale`/`approve` actions).
- Feedback-round children that approve plans (role `feedback`), which keep their existing handoff handling.
