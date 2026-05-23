---
create_time: 2026-05-23 19:39:29
status: done
prompt: sdd/prompts/202605/fork_wait_suffix_priority.md
---
# Fork/Wait Suffix Priority Plan

## Problem

The failed agent was a research-swarm follow-up whose prompt combined `%wait`/`%w` with `#fork`. The agent was named
with a wait-derived `.w<N>` suffix even though the prompt also asked to fork a previous conversation. That allows the
fork workflow to resolve the wrong chat target in chained multi-prompt launches and can fail when the most recent named
agent is still waiting or has no chat history.

## Root-Cause Hypothesis

SASE now derives names from explicit `%wait` dependencies by allocating `<target>.w<N>`. Fork/resume prompts already
have a stronger semantic relationship to the source agent and should allocate `<target>.f<N>`. The launch pipeline has
multiple naming layers:

- repeat fan-out in `sase.agent.repeat_launcher`
- multi-prompt parent-side planned names in `sase.agent.multi_prompt_references`
- child runner metadata naming in `sase.axe.run_agent_directives`
- model/alt fan-out naming in `sase.xprompt._directive_alt`

Some of these layers either already prioritize fork/resume or do not plan names when a `#` reference exists. The
diagnosis should verify which layer let a prompt containing both `%wait:<agent>` and `#fork:<agent>` choose `.w<N>`,
then make the precedence explicit and shared enough that future changes do not regress it.

## Implementation Plan

1. Add focused regression tests for prompts containing both wait and fork/resume references:
   - single runner directive extraction should name `%wait:foo #fork:foo` as `foo.f1`, even when
     `SASE_AGENT_PLANNED_NAME=foo.w1` is present.
   - repeat fan-out should keep the existing `.f<N>` behavior when both `%wait:foo` and `#fork:foo` are present.
   - multi-prompt launch should rewrite both bare `%w` and bare `#fork` to the same previous agent and should carry a
     fork-derived planned name where possible.
   - model/alt fan-out should use a fork-derived base when both references are present.

2. Fix the naming precedence in the smallest layer that explains the failing behavior:
   - In the child runner, do not let a parent-provided wait-derived planned name override a detected fork/resume target.
   - If parent-side planning becomes necessary for `#fork:<agent>` prompts, teach `PlannedNameAllocator` to allocate
     `.f<N>` before `.w<N>` for explicit fork/resume references while still avoiding unsafe bare or arbitrary xprompt
     cases.

3. Preserve existing safety rules:
   - explicit `%name` still wins over derived names.
   - auto-dismissed agents still do not get derived names.
   - ambiguous or bare waits still do not create `.w<N>` names.
   - bare first-segment `#fork` keeps default global resume behavior unless multi-prompt chaining supplies a
     predecessor.

4. Validate with targeted tests first, then run the required repo check:
   - `pytest tests/test_agent_names_extract.py tests/test_repeat_launcher.py tests/test_multi_prompt_launcher_fork.py tests/test_directives_split_models.py`
   - `just install`
   - `just check`
