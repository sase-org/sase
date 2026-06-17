---
create_time: 2026-06-17 14:22:44
status: done
prompt: sdd/prompts/202606/bad_fanout_xprompt.md
---
# Fix xprompt-injected model fanout shape

## Problem

The prompt in `~/tmp/bad_fanout_prompt.md` is:

```text
#gh:sase Describe this repo %(briefly, in detail). %(Don't trust the documentation!) #m_opus_codex
```

The live chezmoi config defines:

```yaml
xprompts:
  codex: "gpt-5.5"
  m_opus_codex: "%model(opus, #codex)"
```

The intended fanout shape is:

- `%(briefly, in detail)` -> 2 alternatives
- `%(Don't trust the documentation!)` -> 2 alternatives because one-argument alt directives include the implicit empty
  branch
- `#m_opus_codex` -> `%model(opus, #codex)` -> 2 models

That gives `2 * 2 * 2 = 8` launch slots: 4 Opus and 4 GPT-5.5.

The observed launch was 4 slots, all Opus.

## Root Cause

The TUI launch body currently calls `plan_prompt_fanout_variants()` on the raw dispatch prompt first. Because the raw
prompt already contains `%(` alternative directives, the Rust-backed fanout planner returns a valid 4-slot alternatives
plan immediately.

Only when that first plan is `None` does the launch body run `process_xprompt_references()` to discover xprompt-injected
fanout directives. For this prompt, that fallback is skipped, so `#m_opus_codex` remains unexpanded while the launch
shape is decided.

Each of the 4 generated child prompts still contains `#m_opus_codex`; the child agent runner later expands it to
`%model(opus, #codex)` too late for parent-side fanout planning, so the `%model(...)` directive is interpreted as one
model selection rather than a 2-way launch dimension. That explains “4 agents, all Opus.”

The Rust fanout planner itself is not the root cause. It already composes model and alternative axes correctly when the
prompt it receives contains `%model` plus `%alt`/`%(` directives.

## Fix Strategy

Change the TUI prompt-fanout dispatch path so xprompt expansion happens before final fanout-shape planning whenever the
submitted prompt may contain launch-shaping xprompts, even if the raw prompt already contains `%alt`/`%(` directives.

The important behavior is:

1. Preserve the submitted prompt for history and failure recording.
2. Preserve local frontmatter xprompts and pass them into both expansion and fanout naming.
3. Use the xprompt-expanded prompt only to compute the preplanned fanout slots.
4. Keep the original dispatch prompt as the fanout worker's submitted/raw prompt context unless existing history
   semantics require otherwise.
5. Avoid doing xprompt work for plain prompts that cannot reference xprompts.

Concretely, refactor the fanout-planning section in `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` from “plan
raw, expand only if no raw plan” to “prepare a fanout-planning prompt first”:

- Build `dispatch_prompt` from parsed segments as today.
- If `prompt_may_reference_xprompt(dispatch_prompt, extra_xprompts=...)` is true, compute
  `planning_prompt = process_xprompt_references(dispatch_prompt, extra_xprompts=...)`.
- Call `plan_prompt_fanout_variants(planning_prompt, extra_xprompts=...)`.
- If the prompt cannot reference xprompts, keep the current fast path and plan directly from `dispatch_prompt`.

This keeps the existing no-xprompt performance behavior while ensuring xprompt-injected model directives participate in
the same Cartesian fanout plan as raw `%alt` directives.

## Tests

Add focused tests in the Python repo:

1. A dispatch-level regression test in `tests/ace/tui/test_agent_launch_dispatch.py` using an xprompt catalog equivalent
   to:

   ```python
   {
       "codex": XPrompt(name="codex", content="gpt-5.5"),
       "m_opus_codex": XPrompt(name="m_opus_codex", content="%model(opus, #codex)"),
   }
   ```

   Prompt:

   ```text
   #gh:sase Describe this repo %(briefly, in detail). %(Don't trust the documentation!) #m_opus_codex
   ```

   Assert that `_launch_multi_model_agents` is scheduled once with a preplanned fanout of 8 slots and slot models
   containing four `opus` entries and four `gpt-5.5` entries after xprompt alias resolution.

2. A lower-level directive/fanout test, likely in `tests/test_directives_split_models.py`, proving that once
   `#m_opus_codex` is expanded before planning, `%model(opus, #codex)` composes with two `%(` alternative axes into 8
   slots.

3. Preserve the existing test `test_run_agent_launch_body_skips_xprompt_processing_for_plain_prompt` so plain prompts
   still avoid xprompt expansion.

## Validation

Before running tests in this ephemeral workspace, run:

```bash
just install
```

Then run targeted tests:

```bash
just test tests/ace/tui/test_agent_launch_dispatch.py tests/test_directives_split_models.py
```

Because this repo requires it after source changes, finish with:

```bash
just check
```

No changes are expected in the chezmoi config or in `sase-core`; this should be a Python launch-dispatch ordering fix
plus tests.
