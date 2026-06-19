---
create_time: 2026-06-19 14:39:11
status: done
prompt: sdd/prompts/202606/xprompts_enabled_skips_embedded_validation.md
---
# Plan: `%xprompts_enabled:false` must exempt its block from embedded-workflow expansion & VCS validation

## Problem

An agent launch failed with:

```
sase.xprompt.workflow_executor.WorkflowExecutionError:
Multiple VCS-tagged workflows in one prompt: #gh, #gh, #gh, #gh, #gh.
At most one VCS workflow is allowed per prompt.
```

The offending prompt wrapped an approved implementation plan in a disabled region:

```
%model:claude/opus
#gh:sase  ...

The above plan has been reviewed and approved. Implement it now.

%xprompts_enabled:false
### PR features and branches
... prose that repeatedly mentions #gh/sase (5 times) ...
%xprompts_enabled:true
```

The five `#gh` tokens counted by the validator come from **inside** the `%xprompts_enabled:false` …
`%xprompts_enabled:true` block. That block is supposed to be inert — exempt from **any** xprompt processing or
validation — but the embedded-workflow expander counted (and would have expanded) those references anyway, aborting the
launch.

## Root cause

The prompt preprocessing pipeline in `_execute_prompt_step`
(`src/sase/xprompt/workflow_executor_steps_prompt.py:203-236`) runs in three stages:

1. `preprocess_prompt_early(...)` — Jinja2, xprompt expansion, directive extraction. It deliberately **preserves**
   disabled-region markers (`extract_prompt_directives(..., strip_disabled_markers=False)`) so a later stage can protect
   their contents.
2. `_expand_embedded_workflows_in_prompt(early.prompt)` — detects `#gh`-style workflow references, validates them, runs
   pre-steps, and substitutes `prompt_part` content. **This is where the error is raised.**
3. `preprocess_prompt_late(...)` — _this_ is the only stage that protects disabled regions (`protect_disabled_regions`
   at `src/sase/llm_provider/preprocessing.py:145-147`), then later restores and strips the markers.

So disabled-region protection happens in stage 3, but the embedded-workflow validation runs in stage 2 — **before**
anything shields the disabled block.

Inside `_expand_embedded_workflows_in_prompt` (`src/sase/xprompt/workflow_executor_steps_embedded_expand.py:56-372`):

- It already protects **fenced code blocks** before collecting references (line 121) so that `#gh` inside ` ``` ` blocks
  is ignored.
- It does **not** protect `%xprompts_enabled:false` regions. Therefore Phase 1 "Collection" (`iter_xprompt_references`,
  line 129) picks up the `#gh` refs in the disabled block, and Phase 2 "Validation" (lines 181-190) counts them and
  raises `Multiple VCS-tagged workflows`.

There is a second, related latent bug at the same layer: the function splits multi-agent prompts on `^---$` segment
separators (line 86) **before** any disabled-region protection. A markdown `---` thematic break inside a
`%xprompts_enabled:false` block (common in plan/PR prose) would wrongly split the block across agents. The correct
behavior is for the block to be opaque to **all** of this stage's processing.

## Why this is a Python-only fix (Rust boundary check)

Per `memory/rust_core_backend_boundary.md` I checked the sibling `sase-core` repo:

- The disabled-region **primitive** already exists on both sides and is in parity: Python `_disabled_regions.py` ↔ Rust
  `disabled_region_re` / `disabled_region_ranges` / `strip_disabled_region_markers`
  (`crates/sase_core/src/agent_launch/mod.rs:903-974`).
- Rust's `agent_launch` already **excludes** disabled regions from its directive processing (`%model` / `%repeat` /
  `%name` / `%alt`) via `ignored_ranges` (lines 421, 559, 615).
- The "Multiple VCS-tagged workflows" embedded-workflow expansion/validation is **Python-only** runtime logic in the
  workflow executor; it has no Rust mirror.

So the fix simply applies the **already-shared** disabled-region primitive in the one Python pipeline stage that skipped
it. This brings the Python embedded-expander into parity with how the rest of the pipeline (and Rust `agent_launch`)
already treats disabled regions. **No Rust changes, no wire/API changes, no golden-vector changes.**

## Fix

Make `_expand_embedded_workflows_in_prompt` treat `%xprompts_enabled:false` regions exactly like it already treats
fenced code blocks: protect them into placeholders up-front, process the rest, and restore them verbatim (markers
intact) before returning. Protection happens at the **very top of the function, before segment splitting**, so the block
is opaque to segment separators, reference collection, VCS validation, and expansion alike.

### Change — `src/sase/xprompt/workflow_executor_steps_embedded_expand.py`

1. Import the existing helpers at module top:
   `from sase.xprompt._disabled_regions import protect_disabled_regions, unprotect_disabled_regions`.

2. At the start of `_expand_embedded_workflows_in_prompt` (before the segment-separator handling at line 82), protect
   disabled regions:

   ```python
   disabled_regions: list[str] = []
   prompt = protect_disabled_regions(prompt, disabled_regions)
   ```

3. Restore at **every** return path, so the returned prompt keeps the original markers for `preprocess_prompt_late` to
   strip:
   - before the segment-handling `return rebuilt, ...` (line ~107),
   - before the `if not pending:` early `return` (line ~178),
   - after the final `unprotect_fenced_blocks` (line ~318), before the final `return` (line ~372).

### Why this placement is correct

- **Mirrors existing fenced-block handling** — same protect/process/restore shape, same module, minimal surface area.
- **Recursion-safe.** The function recurses per `---` segment. The outermost call replaces the real markers with
  placeholders; inner recursive calls see no markers (already placeholders) so their `protect`/`unprotect` are no-ops,
  and the outermost call restores. Placeholders (`\x00XPD_n\x00`) contain no `#`, no `---`, and no `_`, so they survive
  segment splitting, fenced-block protection, `normalize_vcs_underscore_refs`, and reference scanning untouched.
- **Position-safe.** Reference offsets (`match_start`/`match_end`) and Phase 4 text replacement all operate on the same
  protected string; restoration is the last step, so offsets stay consistent.
- **Composes with the existing canonical order.** `preprocess_prompt_late` protects disabled regions _then_ fenced
  blocks (and restores in reverse); this change uses the same nesting, so a disabled region containing a fenced block
  (or vice-versa) round-trips correctly.
- **Does not disturb expansion-introduced disabled regions.** Only regions present in the _input_ are protected here;
  regions emitted by an expanded `prompt_part` still flow through to `preprocess_prompt_late` and the existing
  `_DISABLED_REGION_START_RE` line-start handling (lines 304-314) is untouched.

## Tests

Add to `tests/test_wraps_all.py` (reuses the existing `_FakeExecutor` / `_make_workflow` harness that drives
`_expand_embedded_workflows_in_prompt` directly):

1. **`test_vcs_refs_inside_disabled_region_not_counted`** — multiple `#git`-style VCS refs inside a
   `%xprompts_enabled:false` block do **not** raise, are **not** expanded, and survive verbatim in the output;
   `embedded == []`, `pre_steps == 0`. (Direct regression for the screenshot.)
2. **`test_single_vcs_outside_with_vcs_mentions_inside_disabled_region`** — one real `#git` outside the block plus
   several `#git` mentions inside it → no error; the outside ref expands (one embedded workflow / one pre-step) and the
   inside mentions are preserved.
3. **`test_segment_separator_inside_disabled_region_not_split`** — a `---` inside a disabled region must not split it;
   encode the block so that _if_ it were split each half would expose >1 VCS ref (and thus raise), proving the block
   stayed intact when no error occurs and refs are preserved.

Existing tests must still pass, notably `test_multiple_wraps_all_raises_error` (refs outside any block still raise) and
`test_multiple_wraps_all_allowed_across_multi_prompt_segments` (real top-level `---` still splits).

## Validation

- `just install` (ephemeral workspace), then `just check` (ruff + mypy + tests).
- Targeted: `just test` on `tests/test_wraps_all.py` and `tests/test_disabled_regions.py`.

## Risks & edge cases

- **Low blast radius:** one self-contained function, using utilities already proven in `preprocess_prompt_late`.
- **Behavioral change:** workflow references inside `%xprompts_enabled:false` blocks are now never expanded or counted.
  This is the intended/desired semantics ("the block undergoes no processing") and matches Rust `agent_launch` and the
  late-phase pipeline.
- A prompt that legitimately has >1 VCS workflow **outside** any disabled block still (correctly) raises — this fix does
  not weaken that guard.
