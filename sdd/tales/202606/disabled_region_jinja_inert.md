---
create_time: 2026-06-24 11:06:11
status: done
prompt: sdd/prompts/202606/disabled_region_jinja_inert.md
---
# Plan: Make disabled (`%xprompts_enabled:false`) regions inert for all Jinja2 expansion and validation

## Problem

SASE prompts can wrap a region in `%xprompts_enabled:false` … `%xprompts_enabled:true` markers to tell the xprompt
pipeline "do not process anything in here." This is used heavily — for example, the agent question/answer blocks that
`sase axe` writes into a chat response are wrapped in these markers so the literal example text (which often contains
`#xprompt`, `%directive`, and `{{ jinja }}`-looking content) is never re-interpreted.

The xprompt **expansion processor** (`xprompt/processor.py`) and the shared **preprocessing pipeline**
(`llm_provider/preprocessing.py`) already honor these markers: they call `protect_disabled_regions(...)` before any
Jinja2 / xprompt work and restore afterward. However, several _other_ Jinja2 entry points do **not** protect disabled
regions, so content the user explicitly marked "disabled" still gets Jinja-parsed, Jinja-rendered, or Jinja-validated.
That is the bug class this plan eliminates.

### Concrete failure: the `05h` agent

Agent `05h` failed with:

```
TypeError: expected string or bytes-like object, got 'NoneType'
  File ".../xprompt/workflow_runner.py", line 469, in execute_workflow
    validate_workflow(workflow)
  File ".../xprompt/workflow_validator.py", line 59, in validate_workflow
    used_vars = collect_used_variables(workflow)
  File ".../xprompt/workflow_validator_extract.py", line 239, in collect_used_variables
    for ref in extract_template_refs(content):
  File ".../xprompt/workflow_validator_extract.py", line 64, in extract_template_refs
    for ident_match in _IDENT_PATTERN.finditer(block_text):
TypeError: expected string or bytes-like object, got 'NoneType'
```

Root cause: the agent's Q&A response contained a disabled region whose example text included empty Jinja braces `{{}}`
(it was literally explaining the `{{  }} -> {{}}` padding feature). On the question-answered resume, that response text
flowed back into a workflow step. `validate_workflow` → `collect_used_variables` → `extract_template_refs` scans **all**
`{{ }}` / `{% %}` blocks for variable references, with no awareness of disabled regions. On the empty-braces block it
hits this line:

```python
block_text = block_match.group(1) or block_match.group(2)
```

For `{{}}` the first alternative matches with an **empty** capture group, so `group(1)` is `""` (falsy) and `group(2)`
is `None`; `"" or None` evaluates to `None`, and `_IDENT_PATTERN.finditer(None)` raises the `TypeError`. The whole agent
run is aborted before it even starts.

Two independent defects combine here:

1. The validator does not skip disabled regions (the user's general request).
2. `extract_template_refs` mishandles a legitimately-empty Jinja block even outside disabled regions.

Both are fixed below.

## Goal

Guarantee that **no Jinja2 expansion, rendering, or validation is performed on text inside a disabled region**, across
every entry point — matching the behavior the xprompt processor and preprocessing pipeline already provide. The `05h`
crash (and the broader class of "disabled example text breaks Jinja handling") must be prevented going forward.

## Scope of the gaps (all reproduced)

The following Jinja entry points currently ignore disabled-region markers. Each was confirmed with a live reproduction:

| #   | Entry point                                                                                | Kind                           | Observed failure on disabled-region Jinja                                             |
| --- | ------------------------------------------------------------------------------------------ | ------------------------------ | ------------------------------------------------------------------------------------- |
| 1   | `xprompt/workflow_validator_extract.py` — `extract_template_refs`, `extract_xprompt_calls` | Validation                     | `extract_template_refs('{{}}')` → `TypeError ... NoneType` (the `05h` crash)          |
| 2   | `xprompt/workflow_executor_utils.py` — `render_template`                                   | Expansion (workflow execution) | Renders disabled-region Jinja; `{{ undefined_var }}` → `jinja2.UndefinedError`        |
| 3   | `xprompt/jinja_inspect.py` — `diagnose` / `unknown_variables` (→ `inspect_template`)       | Validation (TUI editor)        | Reports `ok=False "Encountered unknown tag 'bad'"` for Jinja inside a disabled region |
| 4   | `agent/prompt_inputs.py` — `render_prompt_with_inputs` (→ `substitute_placeholders`)       | Expansion (frontmatter inputs) | `PromptInputError: ... template error` rendering disabled-region Jinja in the body    |

Already correct (no change needed, used as the reference pattern):

- `xprompt/processor.py` (xprompt expansion) — protects disabled regions.
- `llm_provider/preprocessing.py` (early + late phases) — protects disabled regions.
- `xprompt/used_xprompts.py` — ignores `fenced_block_ranges(...) + disabled_region_ranges(...)` when scanning.

Out of scope / not a gap:

- The Rust core (`sase-core`). Jinja2 is a Python concern; the core has no Jinja engine and no disabled-region mirror,
  so this is presentation/Python-glue logic per the core-boundary litmus test. No `sase-core` changes.
- `init_skills_handler.py` Jinja env (renders skill templates, not user prompts with disabled regions).

## Design

Reuse the existing `xprompt/_disabled_regions.py` primitives rather than inventing new mechanisms. The module already
provides `protect_disabled_regions` / `unprotect_disabled_regions` (placeholder swap, for renderers that must keep the
content) and `disabled_region_ranges` (for offset-preserving masking). Add one small, well-named primitive for the
validator case where the content can simply be removed before scanning:

- **`strip_disabled_regions(text) -> str`** in `_disabled_regions.py`: deletes whole
  `%xprompts_enabled:false … %xprompts_enabled:true` regions (markers + body) via the existing `_DISABLED_REGION_RE`.
  This mirrors how `extract_xprompt_calls` already deletes fenced blocks before scanning.

Apply protection at the **shared choke points** so every caller is covered uniformly:

### Fix 1 — Workflow validation extraction (fixes the `05h` crash)

`xprompt/workflow_validator_extract.py`:

- `extract_template_refs`: call `strip_disabled_regions(content)` at the top before scanning, **and** harden the
  empty-block bug: replace `block_text = group(1) or group(2)` with an explicit
  `group(1) if group(1) is not None else group(2)` so an empty `{{}}` yields `""` (no refs) instead of `None`. Both are
  needed: stripping handles the user's general request; the `is not None` fix is a defensive backstop for any
  empty/oddly-formed Jinja block (e.g. an unclosed disabled region that the strip regex can't match).
- `extract_xprompt_calls`: add `strip_disabled_regions(content)` alongside the existing fenced-block stripping so
  xprompt-call validation also ignores disabled examples.

This single choke point covers every validator caller: `workflow_validator.py`, `workflow_validator_checks.py`
(unused-input / cross-step-ref / for-loop checks), `multi_prompt_xprompts.py`, and `ace/.../_wait_resume.py`.

### Fix 2 — Shared workflow Jinja renderer (execution-time expansion)

`xprompt/workflow_executor_utils.py` — `render_template`: wrap the render with `protect_disabled_regions` → render →
`unprotect_disabled_regions` (keep the markers in the output; the downstream pipeline still strips them at the end of
`preprocess_prompt_late`). This makes the one renderer that every workflow step (agent / bash / python / condition /
prompt_part) flows through inherently disabled-region-aware, eliminating the latent `UndefinedError`. The existing outer
protect/unprotect in `preprocess_prompt_early` becomes a harmless no-op (its placeholders contain no markers for the
inner pass to match), so no other call site needs editing.

### Fix 3 — TUI editor Jinja diagnostics (validation)

`xprompt/jinja_inspect.py`: the validation functions `diagnose` and `unknown_variables` already begin with
`masked = _mask_fenced_blocks(text)`. Extend the masking to also blank out `disabled_region_ranges(text)` (a new
combined helper, e.g. `_mask_inert_regions`, that masks fenced blocks + disabled regions while preserving character
offsets). Because both validators feed `inspect_template`, this removes the spurious error chip, error span, and
unknown-variable lint for Jinja that lives only inside a disabled region.

- Recommendation: scope the disabled-region mask to the **validation** functions (`diagnose`, `unknown_variables`) only,
  leaving `tokenize`/highlighting and completion untouched, so the change strictly matches "no validation" and avoids
  perturbing TUI visual snapshots. (Noted alternative: route every fenced-masking function through the combined helper
  to make disabled regions fully inert for highlight + completion too — broader, but risks visual-snapshot churn.
  Default to the conservative scope unless we decide full inertness is wanted.)

### Fix 4 — Frontmatter `input:` substitution (expansion)

`agent/prompt_inputs.py` — `render_prompt_with_inputs`: wrap the `substitute_placeholders(body, …)` call with
`protect_disabled_regions` → substitute → `unprotect_disabled_regions` so declared inputs are rendered into the real
body while disabled-region example Jinja is left verbatim (markers preserved for the downstream pipeline).

- Equivalent-but-broader option: add the same protect/unprotect inside `substitute_placeholders` in `xprompt/_jinja.py`,
  symmetric with the fenced-block protection it already performs, which would also cover xprompt-body substitution.
  Default to the targeted `render_prompt_with_inputs` change to keep blast radius small; mention the centralizing option
  in review.

## Testing

Add focused regression tests (extend existing suites; all must pass under `just check`):

- `tests/test_disabled_regions.py`: `strip_disabled_regions` removes whole regions, leaves surrounding text, is a no-op
  when there are no markers, and handles an unclosed `false` marker gracefully.
- Workflow validator suite (e.g. `tests/test_workflow_validator_inputs.py` or a new
  `tests/test_workflow_validator_disabled_regions.py`): a prompt/workflow whose disabled region contains `{{}}`,
  `{{ undefined }}`, `#fake_xprompt`, and `%directive` validates without raising and without collecting those as used
  variables / xprompt calls. Include a direct `extract_template_refs('{{}}') == []` case to pin the empty-block
  backstop.
- `tests/test_preprocessing_jinja_context.py` (or a new render_template test): `render_template` leaves Jinja inside a
  disabled region untouched (no `UndefinedError`) while still rendering real `{{ var }}` outside it.
- `tests/test_xprompt_jinja_inspect.py`: `inspect_template` returns `ok=True`, no unknown variables, and
  `has_jinja=False` when the only Jinja-looking content is inside a disabled region.
- `tests/test_prompt_inputs.py`: `render_prompt_with_inputs` renders declared inputs in the live body but leaves
  disabled-region example Jinja literal instead of raising `PromptInputError`.
- Regression for `05h`: a test reconstructing the failing shape (a workflow step whose content is a disabled Q&A block
  containing `{{}}`) passes `validate_workflow` cleanly.

## Risks & mitigations

- **Hot-path change to `render_template`.** It runs on every workflow step. Mitigation: protect/unprotect is a pure
  placeholder swap (no semantic change for normal templates), double-protection is a verified no-op, and the full
  workflow test suite plus `just check` will run.
- **Editor diagnostics scope creep.** Mitigated by defaulting to masking only the two validation functions and leaving
  highlight/completion alone, avoiding visual-snapshot churn.
- **Unclosed disabled regions.** `strip_disabled_regions` (like the existing protect/range helpers) only matches a
  closed `false…true` pair. The `extract_template_refs` `is not None` backstop ensures that even an unmatched, malformed
  block cannot crash validation.

## Out of scope

- Changing the disabled-region marker syntax or the strip-on-final-output behavior.
- Any `sase-core` (Rust) work — there is no Jinja or disabled-region logic there to mirror.
- Reworking the xprompt processor / preprocessing pipeline, which already handle disabled regions correctly.
