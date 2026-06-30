---
create_time: 2026-06-30 08:50:55
status: done
prompt: sdd/prompts/202606/answered_continuation_asker_status.md
---
# Plan: Question-continuation askers should show ANSWERED, not DONE

## Problem

In the `sase ace` TUI **Agents** tab, when an agent asks the user a question and the user answers it, the agent's row
should transition **QUESTION → ANSWERED**. This works for the _family root's_ original asker, but **not** for a non-root
_question-continuation_ row that asks its _own_ question.

Observed in the `0am` agent family:

| Row                                       | Role         | Question it asked                 | Status shown | Status expected |
| ----------------------------------------- | ------------ | --------------------------------- | ------------ | --------------- |
| `0am` / `0am--0` (root asker / main step) | `root` / `q` | Q1 (session `2a936c36`), answered | `ANSWERED` ✓ | `ANSWERED`      |
| `0am--1`                                  | `q`          | Q2 (session `ec63c5f6`), answered | **`DONE`** ✗ | `ANSWERED`      |
| `0am--2`                                  | `q`          | (inherited Q2 session), running   | `RUNNING` ✓  | `RUNNING`       |

`0am--1` asked its own follow-up question, the user answered it (which spawned the `0am--2` continuation), yet `0am--1`
shows `DONE`. It should show `ANSWERED` (and, symmetrically, while its question was still unanswered it should read
`QUESTION`).

## Root cause

The QUESTION/ANSWERED status machinery is wired **only for the family root's asker**.

1. **Family shape is flat.** Question continuations are _siblings_, all children of the family root: `0am--1` and
   `0am--2` both have `parent_timestamp = <root>`. The "handoff" from one continuation to the next is encoded by a
   _shared `question_session_id`_ (the answerer's continuation inherits the asker's session) and ordering — **not** by a
   parent/child link between `--1` and `--2`.

2. **The root's asker gets ANSWERED via a dedicated path.** `planner_child_status()` (in
   `src/sase/ace/tui/models/_agent_status_family.py`) returns `ANSWERED` for the root's main/synthetic planner child
   when the root has `questions_times`, no plan, and a follow-up child exists. This path applies to the `--0` asker
   only.

3. **No symmetric ANSWERED path exists for non-root continuations.** In
   `src/sase/ace/tui/models/_agent_status_apply.py`, the only override that touches a continuation's question state is
   the DONE→QUESTION catch-all (`has_unanswered_completed_question`), which fires _only while the question is
   unanswered_ (no `question_response_path`). Once the user answers, `question_response_path` is set, that predicate
   returns `False`, and **nothing** promotes the row to `ANSWERED` — so it falls through every branch and stays `DONE`.

In short: a `q`-role continuation that asks its own question, gets it answered, and hands off to a further continuation
is never assigned `ANSWERED`.

### Reproduction (confirmed)

Loading the real family through the TUI agent loader reproduces it: `0am--0 → ANSWERED`, `0am--1 → DONE` (should be
`ANSWERED`), `0am--2 → RUNNING`. A standalone reconstruction of the override pass reproduces the same result, and a
prototype of the fix below produces the correct statuses across the reported case, the before-answer (unanswered) case,
the final-continuation case, and a 3-deep question chain.

### Note on the "before answer was DONE too" observation

The reporter also noted `0am--1` looked `DONE` _before_ the answer (when it should have been `QUESTION`). With the
persisted data, the existing DONE→QUESTION catch-all does correctly yield `QUESTION` in the unanswered state, so the
pre-answer `DONE` was most likely a brief transient (the row is only a plain `DONE` row in the short window before its
question marker / response is recorded). The fix below makes the QUESTION↔ANSWERED pair symmetric and robust for
continuation askers, which covers this concern regardless of the exact pre-answer timing. No separate change is required
for the QUESTION side, but a regression test will pin it.

## Proposed fix

Add an **"answered, handed-off continuation asker → ANSWERED"** override that mirrors, for non-root continuations, what
`planner_child_status()` already does for the root asker.

### Detection rule

A family row `R` should be promoted `DONE → ANSWERED` when **all** hold:

- `R.status == "DONE"`.
- `R` is a genuine follow-up continuation, not a workflow step: `R.parent_timestamp` set and `R.parent_workflow` is
  falsy.
- `R`'s **resolved** family role is `"q"` (use `agent_family_role(R)`, so plan-phase continuations like
  `--plan`/`--code`, which resolve to `plan`/`code` and have their own approved-plan handling, are excluded — even
  though their raw `agent_family_role` may be `q`).
- `R` asked its own question that was answered: `R.questions_times` is non-empty **and** `R.question_response_path` is
  set.
- `R` was superseded by a later continuation in the same family: some sibling `S` (same `parent_timestamp`, not a
  workflow step) has a later launch time than `R` (`child_launch_time(S) > child_launch_time(R)`).

The "later sibling exists" condition is what distinguishes the **asker** (`--1`, which handed off) from the
**final/active continuation** (`--2`, which has no later sibling and keeps its own status). It is robust to deeper
chains: in `--1 → --2 → --3`, both `--1` and `--2` have a later sibling and become `ANSWERED`, while the running `--3`
does not.

### Runtime freeze (consistency with the root asker)

When promoting `R` to `ANSWERED`, freeze its runtime by setting `R.stop_time = max(R.questions_times)`, mirroring
`_answered_asker_freeze_time()` for the root asker. A handed-off asker should not keep ticking; this matches the
existing `test_apply_status_overrides_question_continuation_asker_runtime_freezes` behavior for `--0`.

### Where the code goes

- **`src/sase/ace/tui/models/_agent_status_family.py`** — add two small helpers:
  - `has_later_family_continuation(agent, children_by_parent)` — "a non-workflow sibling launched after `agent`" (reuse
    `child_launch_time`; same pattern as `feedback_child_progressed_past_review` / `superseded_by_feedback_round`).
  - `is_answered_continuation_asker(agent, children_by_parent)` — the full predicate above.
- **`src/sase/ace/tui/models/_agent_status_apply.py`** — in `apply_status_overrides()`, add a loop (over `all_agents`,
  reusing the already-computed `children_by_parent`) that applies the ANSWERED promotion + stop-time freeze. Place it
  **after** the DONE→QUESTION catch-all (`has_unanswered_completed_question`) and **before** the family-root mirroring
  step, so the root still mirrors its newest child correctly. Export the new helper(s) through the
  `_agent_status_overrides.py` facade if needed for tests, matching the existing re-export style.

This keeps the change additive: existing branches for `code`/`epic`/feedback/plan-approval roles and the root asker are
untouched, and the new rule only fires on pure `q` continuations that meet every condition.

## Out of scope / non-goals

- No change to how continuations are spawned or how `question_session_id` / `question_response_path` are recorded (the
  underlying data is already correct).
- No change to status **bucketing** — `ANSWERED` already buckets as `Running` in `src/sase/agent/status_buckets.py`,
  which is the desired placement.
- The inner hidden `main` workflow step of a continuation is not required to change for the visible-row fix; revisit
  only if the detail/zoom panels look inconsistent.

## Backend boundary

The QUESTION/ANSWERED **derivation** is presentation logic that lives entirely in the Python TUI models
(`_agent_status_apply.py`, `_agent_status_family.py`, `_agent_status_overrides.py`); it is **not** present in the Rust
`sase_core` crate, and the raw inputs it consumes (`question_session_id`, `question_response_path`, `parent_timestamp`,
`questions_times`) already flow through the existing agent-meta wire. No Rust core or binding change is needed.

## Testing

Add cases to **`tests/test_agent_loader_status_override_questions.py`** (it already exercises `_apply_status_overrides`
over constructed families):

1. **Reported case** — root + main step (`--0`) + `--1` (own answered question, `q`) + `--2` (`q`, running): assert
   `--0 == ANSWERED`, `--1 == ANSWERED`, `--2 == RUNNING`, root mirrors `--2` (`RUNNING`). Assert
   `--1.stop_time == max(--1.questions_times)`.
2. **Before answer** — same family without `--2` and with `--1.question_response_path = None`: assert `--1 == QUESTION`
   (pins the symmetric unanswered behavior).
3. **Final continuation** — `--2` completes (`DONE`) with no later sibling: assert `--1 == ANSWERED` and `--2 == DONE`.
4. **Question chain** — `--1` (Q2) → `--2` (its own Q3) → `--3` (running): assert `--1` and `--2` are `ANSWERED`,
   `--3 == RUNNING`.
5. Confirm the existing single-question test (`test_apply_status_overrides_answered_question_only_family_is_done`) still
   passes unchanged (`--1` there has no answered response and no later sibling, so it correctly stays `DONE`).

## Verification

- `just install` then `just check` (lint + mypy + tests) must pass.
- Run the targeted suite: `just test` (or `pytest tests/test_agent_loader_status_override_questions.py`), plus the ACE
  PNG snapshot suite (`just test-visual`) since an agent row's status glyph/label changes; update goldens only if an
  intentional visual change appears.
- Manual spot-check: with the real `0am` family present, the loader yields `0am--1 == ANSWERED`.
