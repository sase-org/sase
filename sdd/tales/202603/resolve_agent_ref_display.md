---
create_time: 2026-03-29 14:19:19
status: done
prompt: sdd/prompts/202603/resolve_agent_ref_display.md
---

# Plan: Fix ChangeSpec display for `#gh:@d` agent references

## Problem

When a prompt like `#gh:@d #resume:d ...` is submitted in the TUI, the agent's ChangeSpec shows `resume(d)` instead of
`sase`. The `#gh:@d` should resolve to `#gh:sase` (since agent `@d` has ChangeSpec `sase`), but it doesn't — the agent
inherits whatever `display_name` the prompt context started with.

## Root Cause

The `@name` agent reference resolution happens only in the **runner subprocess** (line 220 of `run_agent_runner.py`),
but the `cl_name` / `display_name` is determined in the **TUI** (in `_finish_agent_launch`) before the subprocess
starts:

1. The TUI's VCS ref pattern `[a-zA-Z0-9_./-]+` does **not** allow `@`, so `#gh:@d` isn't recognized as a VCS ref. The
   `ctx.display_name` is never updated from it.

2. The runner's VCS tag pattern `[_:][^\s]*` is more permissive and matches `#gh:@d`. It resolves `@d` → `sase`, but
   only in the prompt — the `cl_name` (from `sys.argv[1]`) is already set.

## Solution

Resolve `@name` agent references in `_finish_agent_launch` **before** VCS resolution, so the ref pattern matching sees
`#gh:sase` instead of `#gh:@d`. Use the resolved prompt only for VCS resolution; pass the original prompt to the runner
(preserving `#gh:@d` in `raw_xprompt.md`).

## Changes

### `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`

In `_finish_agent_launch`, before the home-mode VCS resolution loop (before line 107), resolve `@name` refs into a
separate variable used only for VCS pattern matching:

```python
# Resolve @name agent references in VCS tags (e.g. #gh:@d → #gh:sase)
# so the VCS ref pattern can match the resolved name for display_name.
_vcs_prompt = prompt
try:
    from sase.axe.run_agent_phases import resolve_agent_refs_in_prompt
    _vcs_prompt, _ = resolve_agent_refs_in_prompt(prompt)
except Exception:
    pass  # Agent not done yet — runner will resolve later
```

Then pass `_vcs_prompt` (instead of `prompt`) to the two VCS resolution sites:

1. **Home mode** (line ~112): `_resolve_vcs_from_prompt(_vcs_prompt, wf_name, ...)`
2. **Non-home fallback** (line ~162): `pattern.search(_vcs_prompt)`
3. **Multi-prompt VCS** (line ~96): `pattern.search(_vcs_prompt)` (same pattern matching)

The original `prompt` continues through to `raw_prompt` and the runner subprocess unchanged.
