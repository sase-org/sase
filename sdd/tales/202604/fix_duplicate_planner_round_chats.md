---
create_time: 2026-04-17 17:10:01
status: done
prompt: sdd/prompts/202604/fix_duplicate_planner_round_chats.md
---

# Plan: Fix Duplicate PLANNER (round 2+) Agent Reply in `sase ace` TUI

## Problem

In the `sase ace` TUI's AGENT REPLY panel, when a plan+feedback workflow runs with multiple feedback rounds, both the
`PLANNER` and `PLANNER (round 2)` sections display **the same chat history content**, even though each round is a
separate agent with its own artifacts directory.

Example from a live snapshot:

```
─── PLANNER ─── 16:33:26 ─────────────
# Chat History - ace-run (g.plan)
**Timestamp:** 2026-04-17 16:57:03 EDT
...
─── PLANNER (round 2) ─── 16:45:16 ───
# Chat History - ace-run (g.plan)    <- identical content, same title!
**Timestamp:** 2026-04-17 16:57:03 EDT
...
```

## Root Cause

In `src/sase/axe/run_agent_exec_plan.py`, `handle_plan_marker()` saves a chat file every time it is invoked (once per
plan submission). At line 209:

```python
planner_agent = f"{ctx.agent_name}.plan" if ctx.agent_name else None
```

The agent suffix is **hardcoded to `.plan`** regardless of which feedback round is active. `ctx.timestamp` (the initial
agent's timestamp) and `ctx.agent_name` are both unchanged across rounds, so `save_chat_history()` produces the same
filename on every round:

- Round 1: `<branch>-ace_run-<name>.plan-<ts>.md`
- Round 2: `<branch>-ace_run-<name>.plan-<ts>.md` (same filename — overwrites round 1)

After round 2 completes:

- Round 1's `agent_meta.json` has `chat_path` = the overwritten file (now holding round 2's content).
- Round 2's `agent_meta.json` has `chat_path` = the same file path.

When the TUI's `render_agent_reply_content()` (in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`) falls
through to `get_chat_response_content()` (in `src/sase/ace/tui/models/agent_artifacts.py` lines 239–264), both the
parent PLANNER agent and the round 2 followup load the same file and render identical content.

The fix-side variable is already computed correctly a few lines down:

```python
_planner_suffix = state.current_role_suffix or ".plan"   # line 220
```

- Initial call: `current_role_suffix == ""` → `_planner_suffix = ".plan"` ✓
- After feedback: `current_role_suffix == ".2"` → `_planner_suffix = ".2"` ✓

The fix is to compute `_planner_suffix` **before** the `save_chat_history()` call and use it to build `planner_agent`
instead of hardcoding `.plan`.

The same bug exists in `handle_questions_marker()` at line 456 (`_q_agent = f"{ctx.agent_name}.q"`): repeated question
rounds would overwrite each other's chat files for the same reason.

## Design

### Behavior change

`save_chat_history()` receives the actual `state.current_role_suffix` as the `agent` parameter's suffix component. This
produces unique chat filenames per round:

- Round 1 (`current_role_suffix=""` → fallback to `.plan`): `<branch>-ace_run-<name>.plan-<ts>.md`
- Round 2 (`current_role_suffix=".2"`): `<branch>-ace_run-<name>.2-<ts>.md`
- Round 3 (`current_role_suffix=".3"`): `<branch>-ace_run-<name>.3-<ts>.md`

Each round's `agent_meta.json` then stores a distinct `chat_path`, and the TUI renders distinct content per phase
divider.

### Downstream consumers (all unchanged, but verified correct after fix)

- `state.saved_chat_paths` / cross-linking via `append_links_to_chat` in `_finalize_loop` (`run_agent_exec.py` lines
  153–168): each round gets a distinct path, so the `## Linked Chats` table will now list separate entries per round
  (which is the intended behavior of that feature).
- `update_meta_field(state.current_artifacts_dir, "chat_path", ...)` and `update_step_marker_chat_path(...)`: already
  scoped to the per-round artifacts dir; they'll now point to per-round distinct files.
- TUI's `get_chat_response_content()`: unchanged — just reads `chat_path` from each agent's own `agent_meta.json`, which
  now holds the correct per-round path.

### Chat file title

Line 229–232 of `chat.py` composes the chat file header:

```python
content_parts.append(f"# Chat History - {workflow}")
if agent:
    content_parts.append(f" ({agent})")
```

With the fix, round 2's chat header becomes `# Chat History - ace-run (g.2)` instead of `(g.plan)`, which correctly
identifies which round the chat is for.

## Changes

### Phase 1: Fix `handle_plan_marker` in `run_agent_exec_plan.py`

**File:** `src/sase/axe/run_agent_exec_plan.py`

Current code (lines 202–223):

```python
# Save a chat file for the planner step (the LLM response was lost
# to SIGTERM, so we use a plan-file preview as the synthetic response).
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.history.chat_links import format_plan_as_response

plan_response = format_plan_as_response(plan_result.plan_file)
planner_agent = f"{ctx.agent_name}.plan" if ctx.agent_name else None
_planner_extra = format_extra_sections(state.current_artifacts_dir)
_planner_chat = save_chat_history(
    prompt=state.current_prompt,
    response=plan_response,
    workflow="ace-run",
    agent=planner_agent,
    timestamp=ctx.timestamp,
    extra_sections=_planner_extra,
    branch_or_workspace=ctx.cl_name,
)
_planner_suffix = state.current_role_suffix or ".plan"
state.saved_chat_paths.append((_planner_suffix, _planner_chat))
update_meta_field(state.current_artifacts_dir, "chat_path", _planner_chat)
update_step_marker_chat_path(state.current_artifacts_dir, _planner_chat)
```

Change: move the `_planner_suffix` computation up and use it in `planner_agent`:

```python
# Save a chat file for the planner step (the LLM response was lost
# to SIGTERM, so we use a plan-file preview as the synthetic response).
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.history.chat_links import format_plan_as_response

plan_response = format_plan_as_response(plan_result.plan_file)
_planner_suffix = state.current_role_suffix or ".plan"
planner_agent = f"{ctx.agent_name}{_planner_suffix}" if ctx.agent_name else None
_planner_extra = format_extra_sections(state.current_artifacts_dir)
_planner_chat = save_chat_history(
    prompt=state.current_prompt,
    response=plan_response,
    workflow="ace-run",
    agent=planner_agent,
    timestamp=ctx.timestamp,
    extra_sections=_planner_extra,
    branch_or_workspace=ctx.cl_name,
)
state.saved_chat_paths.append((_planner_suffix, _planner_chat))
update_meta_field(state.current_artifacts_dir, "chat_path", _planner_chat)
update_step_marker_chat_path(state.current_artifacts_dir, _planner_chat)
```

### Phase 2: Fix `handle_questions_marker` in the same file

Current code (lines 452–470):

```python
# Save a chat file for the questions step
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections

_q_agent = f"{ctx.agent_name}.q" if ctx.agent_name else None
_q_extra = format_extra_sections(state.current_artifacts_dir)
_q_chat = save_chat_history(
    prompt=state.current_prompt,
    response=format_qa_for_prompt(response),
    workflow="ace-run",
    agent=_q_agent,
    timestamp=ctx.timestamp,
    extra_sections=_q_extra,
    branch_or_workspace=ctx.cl_name,
)
_q_suffix = state.current_role_suffix or ".q"
state.saved_chat_paths.append((_q_suffix, _q_chat))
update_meta_field(state.current_artifacts_dir, "chat_path", _q_chat)
update_step_marker_chat_path(state.current_artifacts_dir, _q_chat)
```

Change: move `_q_suffix` up and use it for `_q_agent`:

```python
# Save a chat file for the questions step
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections

_q_suffix = state.current_role_suffix or ".q"
_q_agent = f"{ctx.agent_name}{_q_suffix}" if ctx.agent_name else None
_q_extra = format_extra_sections(state.current_artifacts_dir)
_q_chat = save_chat_history(
    prompt=state.current_prompt,
    response=format_qa_for_prompt(response),
    workflow="ace-run",
    agent=_q_agent,
    timestamp=ctx.timestamp,
    extra_sections=_q_extra,
    branch_or_workspace=ctx.cl_name,
)
state.saved_chat_paths.append((_q_suffix, _q_chat))
update_meta_field(state.current_artifacts_dir, "chat_path", _q_chat)
update_step_marker_chat_path(state.current_artifacts_dir, _q_chat)
```

Note: `state.current_role_suffix += ".q"` (line 430) happens before this code runs, so `_q_suffix` already includes the
accumulated `.q` suffix.

### Phase 3: Add regression tests

**File:** `tests/test_axe_run_agent_exec_plan.py`

Extend the existing `TestModelInheritance` pattern (which already uses `_PLAN_PATCHES` and `_patch_plan_deps`) with a
new `TestFeedbackRoundChatPath` class. We need to capture the `agent` argument passed to `save_chat_history` and assert
it reflects `state.current_role_suffix` for each round.

The existing patch at `"sase.history.chat.save_chat_history": lambda **kw: "/fake/chat"` needs replacement with a spy
that records kwargs. Simplest approach: use `patch(..., side_effect=...)` with a closure that appends to a list, or use
`patch.object(...)`-returned `Mock` and assert on `.call_args`.

New tests to add:

1. **`test_handle_plan_marker_round1_uses_plan_suffix_in_agent_name`**
   - Setup `state.current_role_suffix = ""` (initial value).
   - Spy on `save_chat_history` kwargs.
   - Assert the `agent` kwarg equals `f"{ctx.agent_name}.plan"`.

2. **`test_handle_plan_marker_round2_uses_round_suffix_in_agent_name`**
   - Setup `state.current_role_suffix = ".2"` (mid-feedback round).
   - Spy on `save_chat_history`.
   - Assert the `agent` kwarg equals `f"{ctx.agent_name}.2"` (NOT `.plan`).

3. **`test_handle_plan_marker_uses_distinct_agent_per_round`**
   - Call `handle_plan_marker` twice with different suffixes (`""` then `".2"`) and assert the two `agent` kwargs are
     different.

4. **`test_handle_plan_marker_no_agent_name_preserves_none`**
   - `ctx.agent_name = None`; assert `agent` kwarg passed to `save_chat_history` is `None` (regression check for the
     existing fallback).

For `handle_questions_marker`:

5. **`test_handle_questions_marker_uses_suffix_in_agent_name`** — parallel to test 2 but for the questions handler.
   Requires setting up minimal patching/mocking for `handle_questions_flow` (which polls for a response file); easiest
   path is to return a canned answer dict directly via
   `patch("sase.axe.run_agent_exec_plan.handle_questions_flow", return_value={"answers": [], "global_note": ""})`.

All tests follow the pattern of `TestModelInheritance._run(...)` for fixture/mock wiring so we avoid duplicating
plumbing.

### Phase 4: Manual verification

Once automated tests pass, perform a manual walkthrough to confirm the TUI fix:

1. Run a plan+feedback workflow in a test project:
   ```bash
   sase run -m 'some prompt %plan' <changespec>
   ```
2. When the plan surfaces, submit feedback (so round 2 starts).
3. Once round 2 submits its plan, submit more feedback (optional round 3).
4. Open `sase ace`, select the parent agent.
5. Verify each `─── PLANNER (round N) ───` section shows **distinct** chat content with the correct round-specific
   `Additional Requirements`.
6. Verify each chat file in `~/.sase/chats/` has a unique filename with the round suffix (`-<name>.plan-`, `-<name>.2-`,
   `-<name>.3-`).
7. Verify `## Linked Chats` at the top of each chat file lists all rounds with distinct paths.

## Edge Cases

- **Single-round plan (no feedback):** `state.current_role_suffix == ""` → falls back to `.plan`. Behavior matches
  today. ✓
- **Epic / coder follow-up after round 2:** `state.current_role_suffix` gets set to `.code` or `.epic` AFTER
  `handle_plan_marker` writes the chat. The coder chat is saved later in `_finalize_loop` (run_agent_exec.py), which
  already uses `state.current_role_suffix or ".code"`. No change needed there.
- **Agent has no `agent_name`:** `planner_agent` becomes `None` (unchanged); `save_chat_history` generates a filename
  without the agent component. Still unique per round via timestamp (single-round only in practice — multi-round
  feedback requires a named agent). Preserved by the conditional expression.
- **Repeated questions in the same run:** `state.current_role_suffix` becomes `.q`, then `.q.q`, etc. (pre-existing
  accumulation behavior on line 430). Each round now gets a unique filename. Pre-existing oddness of the stacked `.q.q`
  is orthogonal to this fix.

## Files Changed

| File                                    | Change                                                          |
| --------------------------------------- | --------------------------------------------------------------- |
| `src/sase/axe/run_agent_exec_plan.py`   | Use `state.current_role_suffix` in `planner_agent` / `_q_agent` |
| `tests/test_axe_run_agent_exec_plan.py` | Add `TestFeedbackRoundChatPath` class with 5 regression tests   |

## Out of Scope

- The pre-existing `state.current_role_suffix += ".q"` accumulation in `handle_questions_marker` (line 430) produces
  `.q.q.q…` across rounds. That's ugly but functionally unique and not related to the reported bug. Leave as-is.
- Visual improvements to the phase divider (e.g., showing chat filename in the divider) are not part of this fix.
- Cleanup of existing incorrectly-overwritten chat files on disk (for users who already experienced this bug) is not
  automated — those chat files will naturally age out or can be deleted manually.
