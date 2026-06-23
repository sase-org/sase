---
create_time: 2026-06-23 08:37:05
status: done
prompt: sdd/prompts/202606/xprompts_enabled_skips_early_jinja_render.md
---
# Plan: `%xprompts_enabled:false` must exempt its block from early-phase Jinja2 rendering

## Problem

An agent launch (continuation after a `sase questions` round) failed with:

```
WorkflowExecutionError: Step 'main' failed: Encountered unknown tag 'm'.
```

The agent was working on a task about migrating sase's multi-model directive to a new syntax. During the run it asked
the user a question via `sase questions`. The user's answer (and/or the surrounding Q&A transcript) demonstrated the
**new** multi-model syntax:

```
%{%m:claude/opus | %m:codex/gpt-5.5}
```

Per the existing Q&A feature, that transcript is wrapped in a `%xprompts_enabled:false` … `%xprompts_enabled:true`
disabled region before being appended to the prompt and re-fed to the next agent invocation. A disabled region is
supposed to be **inert** — exempt from _any_ xprompt expansion, directive parsing, **or template rendering**. Instead,
the launch aborted.

The crash is a `jinja2.exceptions.TemplateSyntaxError`. The literal string `%{%m:claude/opus | %m:codex/gpt-5.5}`
contains the substring `{%m`, and Jinja2 reads `{%` as the start of a block tag whose name is `m` — an unknown tag —
producing "Encountered unknown tag 'm'." The content is just opaque prose inside a disabled region; it should never have
reached the Jinja parser at all.

## Root cause

The prompt-step preprocessing entry point is `preprocess_prompt_early` (`src/sase/llm_provider/preprocessing.py`),
called from `_execute_prompt_step` (`src/sase/xprompt/workflow_executor_steps_prompt.py`) with a workflow `context`. It
runs three stages:

1. **Jinja2 context rendering** — `render_template(prompt, context)` (`preprocessing.py:88`), run only when a workflow
   `context` is supplied. It protects fenced code blocks before rendering — **but not `%xprompts_enabled:false` disabled
   regions.** This is the stage that raises.
2. **xprompt expansion** — `process_xprompt_references` already protects disabled regions, so `#name` tokens inside the
   block are not expanded.
3. **directive extraction** — `extract_prompt_directives` already protects disabled regions, so `%name` directives
   inside the block are not parsed/validated.

So stages 2 and 3 correctly treat the disabled region as inert, and the **late** phase (`preprocess_prompt_late`) also
protects disabled regions _around_ its own top-level Jinja render. The early-phase Jinja render (stage 1) is the lone
stage that skips disabled-region protection. Any Jinja-significant text (`{%`, `{{`, `{#`) inside a disabled region —
here, the new multi-model `%{…}` syntax — is parsed and can abort the launch.

This is the direct analog of the previously fixed bug `xprompts_enabled_skips_embedded_validation`
(`sdd/tales/202606/`), where the embedded-workflow expander was the one pipeline stage that skipped disabled-region
protection. Same shape, adjacent stage.

## Why this is a Python-only fix (Rust boundary check)

Per `memory/rust_core_backend_boundary.md`, checked against the sibling `sase-core` repo:

- The disabled-region **primitive** is already shared and in parity: Python `_disabled_regions.py` ↔ Rust
  `disabled_region_re` / `disabled_region_ranges` / `strip_disabled_region_markers`
  (`crates/sase_core/src/agent_launch/mod.rs`). Rust's `agent_launch` already **excludes** disabled regions from its
  directive processing via `ignored_ranges`.
- sase-core has **no Jinja/Tera/minijinja template engine** and **no `render_template` / `preprocess_prompt`
  equivalent**. The early-phase Jinja workflow-variable rendering is Python-only runtime logic in the workflow executor;
  it has no Rust mirror.

So the fix applies the already-shared disabled-region primitive in the one Python pipeline stage that skipped it,
bringing early-phase rendering into parity with the rest of the pipeline. **No Rust changes, no wire/API changes, no
golden-vector changes.**

## Fix

In `preprocess_prompt_early` (`src/sase/llm_provider/preprocessing.py`), make stage 1 protect disabled regions exactly
as it already protects fenced blocks: protect → render → restore. Protection nests _inside_ fenced-block protection
(fenced outer, disabled inner) and is restored _before_ fenced blocks — matching the established ordering in
`extract_prompt_directives` and `process_xprompt_references`.

Concretely, around the existing `render_template` call:

```python
if context is not None:
    from sase.xprompt.workflow_executor_utils import render_template

    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)
    prompt = render_template(prompt, context)
    prompt = unprotect_disabled_regions(prompt, disabled_regions)
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)
```

`protect_disabled_regions` / `unprotect_disabled_regions` are **already imported** at the top of `preprocessing.py`, so
no new imports are needed.

### Why this placement is correct

- **Markers are preserved, not stripped.** The placeholder substitution keeps the `%xprompts_enabled:false/true` markers
  in the returned text (early phase is explicitly called with `strip_disabled_markers=False` at stage 3). The late phase
  still strips them via `strip_disabled_region_markers`, so the agent's final prompt is unchanged.
- **Jinja outside the region still renders.** Only the disabled block is masked; `{{ var }}` / `{% … %}` elsewhere in
  the prompt render normally (verified by reproduction).
- **Placeholders are inert to Jinja.** The disabled-region placeholder token contains no `{`, `}`, or `%`, so it passes
  through `render_template` untouched and round-trips exactly.
- **Composes with fenced blocks.** Same nesting order already used elsewhere, so a disabled region containing a fenced
  block (or vice-versa) round-trips correctly.

## Tests

Add to `tests/test_preprocessing_jinja_context.py` (existing harness patches `process_xprompt_references` to a
pass-through so the test isolates stage 1):

1. **Regression for the exact failure** — a `%xprompts_enabled:false` block containing
   `%{%m:claude/opus | %m:codex/gpt-5.5}`, with a workflow `context` provided, must **not** raise, and the `%{%m…}` text
   must survive verbatim in the output.
2. **General Jinja-significant content is opaque** — a `{% … %}` / `{{ … }}` construct inside a disabled region passes
   through unrendered (no `UndefinedError`, no `TemplateSyntaxError`).
3. **Jinja still renders outside the region** — a prompt with `{{ N }}` _outside_ the block and Jinja-shaped text
   _inside_ the block renders the outside variable while preserving the inside text verbatim.
4. **Markers preserved through early phase** — the returned early-phase prompt still contains the
   `%xprompts_enabled:false/true` markers (so the late phase can strip them); pairs with the existing
   `strip_disabled_markers=False` contract.

Existing tests in `test_preprocessing_jinja_context.py` (e.g. `test_n_not_in_context_raises`) must still pass — Jinja
outside disabled regions still renders strictly.

## Validation

- `just install` (ephemeral workspace), then `just check` (ruff + mypy + full test run).
- Targeted: `just test` on `tests/test_preprocessing_jinja_context.py` and `tests/test_disabled_regions.py`.
- Manual reproduction (pre-fix raises, post-fix succeeds): run `preprocess_prompt_early` with a workflow `context` on a
  prompt whose `%xprompts_enabled:false` block contains `%{%m:claude/opus | %m:codex/gpt-5.5}`.

## Risks & edge cases

- **Low blast radius:** one self-contained stage in one function, reusing utilities already proven in
  `preprocess_prompt_late`, `extract_prompt_directives`, and `process_xprompt_references`.
- **Behavioral change:** Jinja syntax inside `%xprompts_enabled:false` blocks is now never rendered during the early
  phase. This is the intended/desired "the block undergoes no processing" semantics and matches every other stage.
- **No change when no workflow context** is supplied (stage 1 is skipped entirely), and no change to prompts without
  disabled regions.
- **Out of scope:** the broader task agent 041 was attempting (migrating `%m`/`%model` multi-arg usage to the new `%alt`
  / `%{…}` syntax) is unrelated to this defect; the new syntax here is merely opaque transcript text inside a disabled
  region. This plan only fixes the disabled-region exemption gap.
