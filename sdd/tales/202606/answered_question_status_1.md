---
create_time: 2026-06-19 13:14:42
status: done
prompt: sdd/prompts/202606/answered_question_status_1.md
---
# Plan: Fix `sase-4z.5` family showing `QUESTION` after its question was answered

## Symptom

On the `sase ace` Agents tab, the `sase-4z.5` agent family displays the wrong statuses:

| Row                               | Current (buggy) | Expected   |
| --------------------------------- | --------------- | ---------- |
| `sase-4z.5` (root)                | `QUESTION`      | `DONE`     |
| `sase-4z.5--0` (the asker)        | `DONE`          | `ANSWERED` |
| `sase-4z.5--1` (the continuation) | `QUESTION`      | `DONE`     |

The family asked the user a question (a memory-file-edit approval), the question was answered, the work was completed
and committed, yet the family still reads as blocked on user input.

## Diagnosis (root cause confirmed)

I reproduced the exact buggy statuses two ways: against the live loader (`load_all_agents()`) and deterministically by
constructing `Agent` objects from the on-disk metadata and running `_apply_status_overrides`. The on-disk artifacts live
at `~/.sase/projects/sase/artifacts/ace-run/202606/19/`:

- `20260619100217/agent_meta.json` → the **asker** `sase-4z.5` (`role_suffix="--0"`, `plan_chain_root=true`,
  `agent_family_role="root"`). It has `questions_submitted_at` set but **no** `question_response_path`.
- `20260619114616/agent_meta.json` → the **continuation** `sase-4z.5--1` (`role_suffix="--1"`, `agent_family_role="q"`,
  `source_plan_agent_name="sase-4z.5--0"`). It **inherited the identical `questions_submitted_at`**
  (`2026-06-19T15:46:14.861080`) but also has **no** `question_response_path`.

Both agents share `pid=774928` and the same `stopped_at`, so this was a single live workflow run — the asker phase asked
a question and the run continued into the continuation phase after the answer.

### The causal chain

1. The family runs with `%approve` (auto-approve). `agent_meta.json` has `"approve": true`.
2. The asker calls `sase questions`. In `handle_questions_flow()` (`src/sase/axe/run_agent_helpers_questions.py:33-45`),
   when auto-approve is active the question is auto-answered by selecting the first option and the function **returns
   early**:
   ```python
   if is_auto_approve_active():
       ...
       return {"answers": answers, "global_note": ""}
   ```
   This early return never populates `_question_request_path`, `_question_response_path`, or `_question_session_id`
   (those are only set on the normal polling path at lines 107-109), and never writes a `question_response.json`.
3. In `run_agent_exec_questions.py` the `question_relationships` dict is therefore built with
   `question_response_path=None`, and that same dict is recorded on both the asker (`record_workflow_metadata`) and the
   continuation (`create_followup_artifacts`, which also adds `source_plan_agent_name`). So the continuation inherits
   `questions_submitted_at` but **never gets a `question_response_path`**.
4. In the TUI status pass (`_agent_status_overrides.py`), `_has_unanswered_completed_question()` treats a `DONE` row
   that has `questions_times`, no `question_response_path`, and no follow-up children of its own as "still blocked on
   user input" → it sets the continuation `--1` to `QUESTION`.
5. The family root mirrors its newest child (`apply_status_overrides`, final mirroring loop). The newest child is `--1`,
   so the root also shows `QUESTION`.

### Key insight from existing tests

`tests/test_agent_loader_status_override_questions.py` already encodes the intended contract: a continuation child with
`questions_times` reads as `DONE` **iff** it carries a `question_response_path` (see
`test_apply_status_overrides_root_numeric_question_is_not_feedback_done`), and as `QUESTION` without one
(`test_apply_status_overrides_numeric_unanswered_continuation_is_question`). The defect is that the auto-approve path
never produces the `question_response_path` "answered" signal, so an _answered_ continuation is indistinguishable from a
genuinely _unanswered_ one.

The crucial distinction the current logic misses: on the continuation `--1`, the `questions_times` value is
**inherited** from its parent (the asker) — it is the exact same timestamp. The continuation exists _because_ the
question was answered; its inherited question is, by construction, already answered.

### Boundary check (Rust core)

The agent-row status-display logic (`apply_status_overrides`) is Python/TUI-only presentation state derived from
artifacts. The Rust `sase-core` `status` module is the **ChangeSpec** state machine (WIP→Draft→Ready→Mailed→Submitted),
which is unrelated to agent-row `QUESTION`/`ANSWERED`/`DONE` display. No Rust changes are required; this fix stays in
this repo per `rust_core_backend_boundary.md`.

## Why fix at the status-override layer (not only the runner)

The reported family is **already on disk** with no `question_response_path`; the runner has already completed and will
not re-record it. Therefore the fix that actually corrects the reported display must live in the TUI status-derivation
layer (`_agent_status_overrides.py`), which re-derives status from artifacts on every load. This also fixes every past
and future family with the same shape, regardless of how the answer was delivered.

## Fix design

Two contained changes in `src/sase/ace/tui/models/_agent_status_overrides.py`:

### 1. Don't flag an _inherited_ question as unanswered

Add a helper that detects when an agent's `questions_times` are entirely inherited from its family parent (the asker):

- An agent is "inherited" when it has a non-workflow family parent (`parent_timestamp` resolves in `parent_by_suffix`)
  and `set(agent.questions_times)` is non-empty and a subset of the parent's `questions_times`.

In the two `QUESTION`-flagging spots in `apply_status_overrides` (the follow-up loop and the catch-all loop), skip the
`QUESTION` override for agents whose question is inherited. The continuation `--1` and the synthetic `--0` child both
match, so neither is wrongly flagged. The subset check is important: a continuation that asks its _own new_ question (a
timestamp not present in the parent) is **not** inherited and still flags `QUESTION` if left unanswered — preserving the
existing contract and the genuine-unanswered case.

This change is inert for every existing test, because in those fixtures the parents have empty `questions_times`, so
nothing is ever classified as inherited.

### 2. Show `ANSWERED` on the asker row for an answered question-only family

In `_planner_child_status()`, when the family root has a follow-up child (proving the question was answered) **and** the
family is question-only (`parent.questions_times` non-empty and `not parent.plan_times`), return `ANSWERED` instead of
`DONE`.

- This drives the `--0` row (whether produced as a synthetic planner child by `_ensure_synthetic_planner_children` or as
  a real promoted workflow step synced by `_sync_planner_child_from_parent` — both call `_planner_child_status`) to
  `ANSWERED`.
- The `not parent.plan_times` guard scopes the change to pure question families, so plan/feedback/tale families are
  untouched (they keep `DONE`/`PLAN DONE`/etc.).
- The root continues to mirror its newest child (`--1`, now `DONE`) → root `DONE`.
- The genuinely-unanswered case is unaffected: with no follow-up child, `_has_family_followup_child` is false and the
  asker still resolves to `QUESTION`.

### Validated outcome

A prototype of both changes, run against `Agent` objects reconstructed from the real metadata, produces exactly:

```
sase-4z.5      role_suffix='--0'  status='DONE'
sase-4z.5--0   role_suffix='--0'  status='ANSWERED'
sase-4z.5--1   role_suffix='--1'  status='DONE'
```

### `ANSWERED` bucketing note

`ANSWERED` buckets as `Running` and `agent_is_asking("ANSWERED")` is `False`, so the `--0` row will **not** be
miscounted as a "needs input"/Stopped row or raise a false notification. It is a child under a `DONE` root, so it does
not affect top-level Done grouping. This matches the user's requested labeling.

## Tests

Extend `tests/test_agent_loader_status_override_questions.py`:

1. **Answered question-only family (the reported bug).** Root `--0` (`plan_chain_root`, `questions_times=[T]`, no
   `question_response_path`) + continuation `--1` (`agent_family_role="q"`, `questions_times=[T]` inherited, no
   `question_response_path`). Assert: continuation → `DONE`, root → `DONE`, and the synthetic `--0` planner child →
   `ANSWERED`.
2. **Inherited-question subset guard.** A continuation whose `questions_times` include a _new_ timestamp not present in
   the parent, left unanswered, still resolves to `QUESTION` (no regression of the genuine case).
3. **Genuinely unanswered, no continuation.** A lone asker with `questions_times` and no follow-up child still →
   `QUESTION` (unchanged).
4. Confirm the 12 existing tests in the file still pass unchanged.

## Optional follow-up (separate, not required for the fix)

Harden the source: make the auto-approve branch of `handle_questions_flow()` write the
`question_request.json`/`question_response.json` pair and populate the `_question_*` paths, so auto-approved answers
record a real `question_response_path` like the manual path does. This improves data fidelity for future runs but is
**not needed** to fix the reported display (the status-layer change already handles existing and future data) and can be
deferred.

## Verification

- `just install` then run the targeted test file and the broader agent-loader status-override suite.
- `just check` (file changes are in `src/`, so the check is required).
- Re-derive the `sase-4z.5` family statuses with the deterministic reproduction to confirm root `DONE` / `--0`
  `ANSWERED` / `--1` `DONE`.

## Files

- `src/sase/ace/tui/models/_agent_status_overrides.py` — both logic changes.
- `tests/test_agent_loader_status_override_questions.py` — new regression tests.
