---
create_time: 2026-05-06 03:42:44
status: done
prompt: sdd/prompts/202605/agents_tab_non_agent_step_runtimes.md
---
# Plan: Hide Agents-Tab Runtimes For Non-Agent Workflow Steps

## Problem

The Agents tab renders a right-aligned runtime suffix for every row that has `start_time`, including workflow child rows
whose `step_type` is a non-agent implementation step such as `python` or `bash`. In collapsed workflow views this makes
setup-style steps (`setup`, `prepare`, `checkout`) look like agent activity even though they are not agents. The desired
behavior is narrower:

- Keep runtimes for top-level agent/workflow entries.
- Keep runtimes for workflow child rows that are actual agent steps.
- Do not render runtimes for non-agent workflow child rows.

## Current Shape

- `format_agent_option()` builds each Agents-tab row and delegates the right-side suffix to `build_runtime_suffix()`.
- `build_runtime_suffix()` calls `compute_row_runtime(agent, now=...)`.
- `compute_row_runtime()` currently gates only on time availability and WAITING state; it does not distinguish workflow
  child step kinds.
- Workflow step loaders populate `Agent.is_workflow_child` implicitly via `parent_workflow` and set `Agent.step_type`
  from prompt-step marker data.
- The snapshot and filesystem workflow-step loaders both use the same `Agent` shape, so a model-level or `agent_time.py`
  eligibility helper will cover both load paths.
- `runtime_suffix_ticks()` drives the one-second row patch path and should match the visible-suffix policy, otherwise
  the TUI can waste patch work on rows whose suffix is intentionally hidden.

## Design

1. Add an explicit runtime-display eligibility helper in `src/sase/ace/tui/models/agent_time.py`.
   - Return `True` for top-level entries (`not agent.is_workflow_child`), preserving current behavior for manual agents,
     workflow parents, and appears-as-agent workflow rows.
   - Return `True` for workflow children only when `agent.step_type == "agent"`.
   - Return `False` for workflow children with non-agent step types (`python`, `bash`, prompt/meta/setup-like steps, and
     unknown non-agent types).
   - Keep this as presentation logic in the TUI model layer; no Rust core change is needed.

2. Apply the helper at the start of `compute_row_runtime()`.
   - If a row is not eligible, return `(None, None)` before duration math.
   - This makes `build_runtime_suffix()` naturally return an empty `Text` and preserves right-alignment behavior for
     rows that still have suffixes.

3. Apply the same helper in `runtime_suffix_ticks()`.
   - Rows with hidden suffixes should not participate in per-second patching.
   - Follow-up recursion should still allow an otherwise non-ticking parent row with active follow-ups to tick only when
     the parent row itself is eligible and would render a suffix.

4. Export the helper if tests or nearby code need it through `models.agent`.
   - Prefer keeping callers on `compute_row_runtime()` where possible, but exporting the predicate makes the policy easy
     to test directly and documents the intended row classes.

## Tests

Add focused coverage in `tests/ace/tui/widgets/test_agent_list_runtime.py`:

- `compute_row_runtime()` returns elapsed runtime for a workflow child with `step_type="agent"`.
- `compute_row_runtime()` returns `(None, None)` for workflow children with `step_type="python"` and `step_type="bash"`.
- `format_agent_option()` renders an empty suffix for a non-agent workflow child even when it has start/stop times.
- `runtime_suffix_ticks()` returns `False` for a running non-agent workflow child and `True` for a running agent step.

These tests cover both the raw runtime computation and the visible rendered row suffix without needing filesystem
fixtures.

## Verification

After implementation:

- Run the focused runtime widget test file.
- Run `just install` if the workspace environment needs refreshing.
- Run `just check` before replying, per repo instructions.
