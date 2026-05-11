---
create_time: 2026-05-11 11:56:43
status: wip
prompt: sdd/prompts/202605/agent_fanout_failure.md
---
# Plan: Fix TUI Agent Fanout Launch Failures

## Problem

Launching agents from the TUI with prompt fanout directives such as `%alt(...)`, `%(...)`, or `%model(...)` can fail
before any child agents are visible. The user sees a transient "Prompt fan-out launch failed" toast, but no persistent
SASE notification is written, so there is no durable diagnostic in the notification inbox.

The fanout parser itself is not the primary failure: local reproduction shows the Rust-backed planner returns valid
slots for representative prompts including `%model(opus,sonnet)`, `%alt(x,y)`, `%(#plan,#epic)`, and
`%alt(#plan,#epic)`.

The risky split is in launch execution:

- The TUI single-prompt path plans fanout in `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`.
- It then dispatches the planned prompts to `src/sase/ace/tui/actions/agent_workflow/_launch_multi_model.py`.
- `_launch_multi_model.py` reconstructs a fake fanout plan from already-planned prompt strings and launches it through a
  TUI-only worker path.
- The canonical fanout path, used by CLI/mobile and by multi-prompt segments, is
  `src/sase/agent/multi_prompt_launcher.py::launch_multi_prompt_agents()`.

That TUI-only path has two concrete problems:

1. It reimplements fanout execution instead of using the canonical launcher, so it can diverge on per-slot VCS/context
   resolution, local xprompt serialization, workspace handling, and planned-name behavior.
2. It catches all fanout launch errors and only logs + shows a toast. Since no agent artifacts exist yet when the
   failure occurs, the user has no durable notification or inspectable failed agent.

## Approach

Unify TUI prompt fanout execution with the canonical fanout launcher and add durable failure reporting.

1. Preserve the full fanout context at TUI dispatch time.
   - Pass the planned slot prompts plus the parsed local xprompt definitions from `_launch_body.py` into the TUI fanout
     worker.
   - Keep the existing display name, VCS ref, wait/deferred state, and prompt-context snapshot behavior.

2. Replace the TUI-only fake-plan execution for `%alt` / `%model` fanout.
   - Have `_launch_multi_model.py` call `launch_multi_prompt_agents()` with each planned fanout slot as an independent
     segment.
   - Provide the same `local_xprompts` mapping that was available during planning so fanout branches that reference
     local xprompts can launch correctly.
   - Preserve immediate and per-slot refresh callbacks through `request_agents_refresh("launch")`.

3. Keep single-launch and repeat-launch behavior unchanged.
   - The single-agent path already has its own context handling and should remain scoped to one prompt.
   - Repeat fanout has repeat-specific env and naming behavior, so do not fold it into this change.

4. Improve error observability.
   - On fanout worker failure, keep the existing error toast.
   - Add a small persistent notification for pre-agent fanout failures with the exception summary and launch context, so
     failures that occur before artifacts exist are visible in the notifications inbox.
   - Avoid noisy stack traces in the notification body; the stack remains in logs.

5. Add regression coverage.
   - TUI fanout launches through `launch_multi_prompt_agents()` instead of fake-plan execution.
   - Local xprompts parsed from prompt frontmatter are forwarded into the fanout launcher.
   - `%(#plan,#epic)` / `%alt(#plan,#epic)` style prompts are passed as two planned slot prompts.
   - Worker failure records an error toast and persistent notification.
   - Existing parser tests remain as contracts that the Rust planner handles `%alt`, `%()`, and `%model(...)` slots.

## Validation

Run focused tests first:

```bash
.venv/bin/python -m pytest \
  tests/ace/tui/test_launch_fan_out_unified.py \
  tests/test_directives_split_alternatives.py \
  tests/test_directives_split_models.py \
  tests/test_multi_prompt_launcher_xprompts_models.py
```

Then run the repository-required check:

```bash
just check
```
