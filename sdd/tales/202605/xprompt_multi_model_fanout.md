---
create_time: 2026-05-09 19:08:47
status: done
prompt: sdd/prompts/202605/xprompt_multi_model_fanout.md
---
# Multi-model fan-out broken for xprompt-wrapped `%model` directives

## Problem

When a prompt is launched via the mobile/telegram bridge or `sase run -d` and the multi-model directive is hidden behind
an xprompt reference (e.g. `#m_opus_codex`, which resolves to `%model(opus, #codex)`), the launcher spawns **one** agent
instead of fanning out to **two** (one per model).

Concrete repro: the in-flight `df` agent at `/home/bryan/.sase/projects/sase/artifacts/ace-run/20260509185301`. Its
`raw_xprompt.md` contains `#gh:sase ... #plan #m_opus_codex` and `agent_meta.json` shows a single-model launch
(`model: opus, llm_provider: claude`). The peer codex agent (`gpt-5.5`) was never spawned.

The same prompt previously fanned out (e.g. `n.r1.r1.r1.cld` + `n.r1.r1.r1.cdx` at 2026-05-09 00:11), so the regression
is a path-dependent gap rather than a catalog change.

## Root cause

`launch_agents_from_cwd()` in `src/sase/agent/launch_cwd.py:253` calls `plan_prompt_fanout_variants(query)` on the
**raw** prompt. The fan-out planner walks the prompt for literal `%model:` / `%alt(...)` directives — it does not expand
xprompt references. Because the user's prompt only contains `#m_opus_codex` (an xprompt reference, not a `%model`
directive), the planner returns `None` and the launcher falls through to the single-agent path.

The other two launch sites that consume `plan_prompt_fanout_variants` already guard against this by retrying after one
round of xprompt expansion:

- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py:357-382` (TUI `@` keymap) — calls
  `process_xprompt_references` when the first plan is `None`.
- `src/sase/agent/multi_prompt_launcher.py:200-216` (per-segment dispatch in multi-prompt `---` flows) — same fallback.

`launch_agents_from_cwd()` is the entry point used by:

- The mobile/telegram bridge (`src/sase/integrations/_mobile_agent_launch.py:82`).
- `sase run -d` / `--daemon` (`src/sase/main/query_handler/_daemon.py`).
- Any external caller of `sase.agent.launcher.launch_agent_from_cwd`.

…all of which silently lose multi-model fan-out for xprompt-wrapped directives. The `dd.plan` planner today still sees a
multi-model prompt when it emits a `---`-separated multi-prompt to `launch_multi_prompt_agents`, which is why historical
fan-out spawns succeeded — they took the multi-prompt path that already has the fallback.

## Goal

Restore fan-out for xprompt-wrapped multi-model directives on every launch entry point that takes a single segment of
free-form prompt text. The fix should be small, mirror the existing fallback in the TUI and multi-prompt launchers, and
be guarded to avoid spurious xprompt expansion.

## Proposed fix

Add a single expansion fallback at the top of the alt-split detection block in `launch_agents_from_cwd()`
(~`launch_cwd.py:251`):

```python
from sase.xprompt.directives import plan_prompt_fanout_variants

alt_plan = plan_prompt_fanout_variants(query)
if alt_plan is None and "#" in query:
    from sase.xprompt.processor import (
        process_xprompt_references,
        prompt_may_reference_xprompt,
    )
    if prompt_may_reference_xprompt(query):
        expanded = process_xprompt_references(query)
        alt_plan = plan_prompt_fanout_variants(expanded)
```

Notes / decisions for this site:

- No `extra_xprompts` are available here (single-segment top-level launch), matching the `_launch_body.py` shape.
  User-frontmatter local xprompts only apply on the multi-prompt path which already has its own fallback.
- The downstream `launch_multi_prompt_agents(segments=[slot.prompt for slot in alt_plan.slots], ...)` consumes the
  planner-rewritten prompts (with `%name:<base>.<runtime>` and `%model:<resolved>` injected), so the agent runner still
  re-expands xprompts inside the subprocess — no behavioral change for already-working prompts.
- Use `prompt_may_reference_xprompt` to skip the expansion when no `#` could plausibly be a reference (matches the TUI
  guard).

## Tests

Two layers, mirroring conventions already in the repo:

1. **Unit (planner)** — extend `tests/test_directives_split_models.py` (or add a sibling
   `test_directives_split_models_xprompt.py`) with a case that wraps a `%model(opus, sonnet)` body inside a custom
   xprompt and asserts that `split_prompt_for_models` returns two prompts only when the caller passes `extra_xprompts`.
   (This documents the planner contract; the fix lives at the call site.)

2. **Launcher (regression)** — extend `tests/test_cd_launch_resolution.py` with a test that:
   - Registers a temporary xprompt resolving to `%model(opus, sonnet)` (or uses a stubbed `process_xprompt_references`
     patch if simpler).
   - Stubs `launch_multi_prompt_agents` and asserts it is called with two segments when
     `launch_agents_from_cwd("#stub_m Hello")` is invoked.
   - Confirms the same prompt without expansion stub returns a single agent to lock the failure mode down.

Both new tests should fail on master before the fix and pass after.

## Out of scope

- The empty-response case in `~/.sase/chats/202605/sase-ace_run-260509_184344.md` (a single-model `%model:gpt-5.5`
  prompt that never produced output) — that's a separate, unrelated symptom and not part of this regression.
- Refactoring the three duplicated expansion-fallback call sites into a shared helper. Worth doing as a follow-up but
  not required to ship the fix; keeping the change minimal makes the regression reviewable.
- Any change to the `extra_xprompts` plumbing in `plan_prompt_fanout_variants` — the existing API already supports it;
  the bug is just that the launch_cwd call site never expanded.

## Risks

- Adding xprompt expansion in the launch-side hot path costs one extra catalog walk for prompts that contain `#`.
  Bounded by `prompt_may_reference_xprompt`, and the TUI/multi-prompt paths already pay this cost without complaints.
- If a prompt contains a `#` that _looks_ like an xprompt but isn't, the expansion is a no-op and
  `plan_prompt_fanout_variants` returns `None` again — same behavior as today.
