---
create_time: 2026-04-24 11:57:09
status: done
prompt: sdd/prompts/202604/tui_simple_xprompt_colon_args.md
---
# Plan: Fix TUI Agent Launch Failure for Simple Xprompts With Multi-Arg Colon Syntax

## Problem

Launching an agent from the `sase ace` TUI with a prompt like

```
#hg:ilar #launch/free:445408805,SS_ILAR_TOGGLE
```

fails with `Agent launch failed (see log)`. The same prompt succeeds when passed to `sase run`.

The `#launch/free` xprompt is a **simple xprompt** defined by the `retired Mercurial plugin` plugin (via the `sase_xprompts` /
`sase_config` entry points) in `src/retired_mercurial_plugin/default_config.yml`:

```yaml
launch/free:
  input: { bug_id: int, feature: word }
  content: |
    ... {{ feature }} ... {{ bug_id }} ...
```

## Root Cause

The TUI launch body calls `_try_execute_workflow()` (after stripping VCS refs) for any remaining prompt that starts with
`#` — see `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:279-289` and
`src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py:24-96`.

For simple xprompts, `_try_execute_workflow()`:

1. Parses the `#name:args` reference using `parse_workflow_reference()` (`src/sase/xprompt/_parsing.py:580-592`). For
   colon syntax, that function returns **exactly one** positional arg containing the full rest of the string — it does
   **not** split on comma.
2. Immediately Jinja-renders the xprompt `content` via `render_template()`
   (`src/sase/xprompt/workflow_executor_utils.py:40-55`), which uses `StrictUndefined`.

For `#launch/free:445408805,SS_ILAR_TOGGLE` this produces `positional_args = ["445408805,SS_ILAR_TOGGLE"]`, which the
executor maps to the first input (`bug_id`). The second input (`feature`) is never bound, and `{{ feature }}` triggers
`jinja2.exceptions.UndefinedError`. The exception bubbles up to `_run_agent_launch_body_async()`'s catch-all at
`src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:95-101`, which logs it and notifies
`"Agent launch failed (see log)"`.

Notably, the caller's simple-xprompt branch only _uses_ the rendered string when `vcs_ref is None`
(`_agent_launch.py:286-289`):

```python
elif vcs_ref is None and isinstance(workflow_result, str):
    # Simple xprompt expanded inline — use as regular prompt
    # (with VCS refs, expansion happens in agent runner instead)
    prompt = workflow_result
```

So with `#hg:ilar` present (`vcs_ref = ("hg", "ilar")`), the rendered value would be **discarded** even if rendering had
succeeded. The TUI still expands `#launch/free` correctly later via `process_xprompt_references()` at
`_agent_launch.py:302-308` — that path uses the processor's colon-arg logic in `src/sase/xprompt/processor.py:299-310`
which _does_ split on comma (`colon_arg.split(",")`). That is why `sase run` works: `sase run` funnels the whole prompt
through `_run_query`, which relies on `process_xprompt_references` rather than `_try_execute_workflow`.

### Why this reads as the "not a project xprompt" clue

`_try_execute_workflow` derives `project = "launch"` from the `/` in `launch/free` (`_workflow_exec.py:46-48`). That
derivation is a heuristic designed for **project xprompts** loaded from `~/.config/sase/xprompts/<project>/`. For
plugin-provided xprompts whose _name_ happens to contain `/`, that code path still works for loading (plugin xprompts
load unconditionally inside `get_all_xprompts`), but the downstream simple- xprompt branch that `_try_execute_workflow`
takes on a hit is the thing that crashes here. The user's hint is a signal that we shouldn't "fix" loading/project
detection — the bug is in arg parsing / unnecessary eager render.

## Fix

**Minimal fix:** stop eagerly rendering simple xprompts inside `_try_execute_workflow()` when a VCS ref is present — the
rendered value is going to be discarded anyway, and `process_xprompt_references()` will correctly expand the xprompt a
few lines later using the comma-splitting logic.

Concretely, in `src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py`:

- Give `_try_execute_workflow` a way to know that the caller has a VCS ref (new parameter `has_vcs_ref: bool = False`).
- When `has_vcs_ref` is `True` **and** the matched workflow is a simple xprompt, return `False` (same signal as
  multi-step `prompt_part` workflows) so the caller falls through to the `process_xprompt_references` path.
- Wire the new parameter at the single call site in `_agent_launch.py:280` by passing `vcs_ref is not None`.

No other call sites exist (confirmed via grep of `_try_execute_workflow`). CLI behavior is unchanged because CLI never
enters `_try_execute_workflow`.

### Secondary consideration (out of scope for this plan)

`parse_workflow_reference` and `process_xprompt_references` disagree on how `name:a,b` parses. Unifying them is a larger
refactor with repo-wide implications (VCS tag extraction, workflow_reference UIs, history replay), so we do **not**
tackle it here. The chosen fix narrows the blast radius to the specific bug path while keeping the two parsers' existing
contracts intact.

## Tests

Add a focused regression test under `tests/ace/tui/actions/agent_workflow/`:

- **Case:** simple xprompt with two inputs using colon-comma syntax plus a VCS ref (mirroring the failing prompt). The
  test should verify that `_try_execute_workflow` returns `False` (not a string, not raising) when `has_vcs_ref=True`,
  so the caller falls through to `process_xprompt_references`. Stub `get_all_prompts` to return a fake simple xprompt
  whose template would raise under `StrictUndefined` if rendered with only one positional arg — this proves we didn't
  render it.
- **Case (guard against regression of existing behavior):** same xprompt reference with `has_vcs_ref=False` → returns
  the rendered string (confirms we didn't break the inline-expansion path when there is no VCS ref and all args are
  supplied by the caller, e.g. via full `parse_args`-style parenthesis syntax).

Also verify at the integration level that the `_run_agent_launch_body` path, given
`#hg:ilar #launch/free:445408805,SS_ILAR_TOGGLE`, now proceeds without raising (mock out subprocess spawning).

## Acceptance

1. Launching `#hg:ilar #launch/free:445408805,SS_ILAR_TOGGLE` from `sase ace` no longer fails; an agent starts, and the
   expanded prompt passed to the agent contains the template with both `bug_id=445408805` and `feature=SS_ILAR_TOGGLE`
   correctly substituted.
2. `sase run "#hg:ilar #launch/free:445408805,SS_ILAR_TOGGLE"` behavior is unchanged.
3. `just check` passes.
