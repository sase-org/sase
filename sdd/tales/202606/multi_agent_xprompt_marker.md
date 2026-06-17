---
create_time: 2026-06-17 09:24:21
status: done
prompt: sdd/prompts/202606/multi_agent_xprompt_marker.md
---
# Plan: Make `#` the canonical marker for multi-agent xprompts + allow multiple fan-outs per prompt

## Problem & motivation

A multi-agent xprompt is a simple (markdown) xprompt whose body contains `---` segment separators; referencing it fans
the call out into one agent per body segment.

The user observed that the current "`#!` is required for multi-agent xprompts" framing is wrong, and the codebase
confirms it:

- **Multi-agent xprompts already expand inline today.** When one is embedded in surrounding prompt text,
  `_expand_embedded_multi_agent_reference` (`src/sase/agent/multi_agent_xprompt.py:408-446`) splices the xprompt's
  **first** body segment in at the reference location
  (`first = segment[:ref.start] + sub_segments[0] + segment[ref.end:]`) and appends the remaining body segments as
  follow-up agent prompts. Surrounding user text therefore attaches to the **first** agent prompt — exactly as the user
  described.
- **The marker is functionally a no-op for them.** Neither the sole-reference fan-out path
  (`_extract_top_level_xprompt_reference` → `multi_agent_names` check) nor the embedded path (`_multi_agent_references`)
  filters on `#` vs `#!`. Both `#name` and `#!name` resolve and expand identically for a multi-agent xprompt.

So the user's statement is **accurate for the single-reference case** and already implemented. Two things are _not_
aligned with it:

1. **The canonical displayed/inserted marker is `#!`, not `#`.** Both the Rust core
   (`crates/sase_core/src/xprompt_catalog.rs:439-451`, `workflow_reference_prefix`) and its Python mirror
   (`src/sase/xprompt/reference_display.py:9-17`, `_workflow_uses_standalone_reference_marker`) emit `#!` for any simple
   xprompt whose body has `---`. Docs and error messages repeat "standalone workflows **and multi-agent xprompts** use
   `#!`".
2. **Multiple multi-agent references in one prompt are a hard error**, not a sequential fan-out. The guard at
   `src/sase/agent/multi_agent_xprompt.py:588-593` raises `_multiple_multi_agent_reference_message` ("A prompt segment
   can contain only one multi-agent xprompt reference…") whenever a segment contains 2+ multi-agent refs.

This plan fixes both, plus the surrounding guidance/error/doc accuracy.

## Decisions (from clarifying Q&A)

- **Q1 — canonical marker:** `#` (inline). Multi-agent xprompts are treated as inline-capable like other xprompts; `#!`
  stays **accepted** for back-compat (it already resolves). This matches their real inline behavior and the original
  epic intent.
- **Q2 — ordering for multiple refs:** `[Review #a then #b]` with `#a → [a1,a2]`, `#b → [b1,b2]` yields
  **`[a1, a2, b1, b2]`** — each ref fans out fully and independently in document order; sub-segments concatenated.
  Leading prose (before the first ref) attaches to the **very first** generated segment (`a1`). Inter-reference text
  ("then") and trailing prose are **dropped** for later agents. (This is deliberately lossy — see Risks.)
- **Q3 — scope:** Both workstreams in one plan: the canonical-marker/guidance/doc fixes **and** the
  multiple-multi-agent-refs sequential fan-out.

## Workstream A — make `#` the canonical marker

The marker decision is core backend logic (per `memory/short/rust_core_backend_boundary.md`: a web/CLI/editor frontend
must agree with the TUI), so Rust is the source of truth and the Python helper is its mirror. Both change together; a
parity fixture pins their agreement.

1. **Rust core — `crates/sase_core/src/xprompt_catalog.rs`** (open via `sase workspace open -p sase-core 11`):
   - In `workflow_reference_prefix` (439-451), drop the `SimpleXprompt if content_has_segment_separators(...) => "#!"`
     arm. Result: only `StandaloneWorkflow => "#!"`; everything else (including multi-agent simple xprompts) → `"#"`.
   - `content_has_segment_separators` (461-486) becomes unused after this — remove it (and its now-dead
     `workflow_prompt_part` call site) so the build stays warning-clean. Confirm no other caller first (grep currently
     shows only the 443 use site).
   - Update assertions that pin the old behavior:
     - `loads_markdown_and_workflow_with_canonical_insertions` (~2142-2143): `swarm` (markdown `---` fixture) → expect
       `#swarm` / `#`. Leave `ship` (standalone workflow, ~2150) on `#!`.
     - `parity_fixture_covers_supported_catalog_sources` (~2519-2526): `app/swarm` → `#app/swarm`. Verify whether
       `app/flow` is a standalone workflow (keep `#!`) or multi-agent (→ `#`) and adjust accordingly.
   - Rebuild the `sase_core_rs` binding so Python tests see the new marker; run sase-core's own test suite.

2. **Python mirror — `src/sase/xprompt/reference_display.py`:**
   - `_workflow_uses_standalone_reference_marker` returns `True` only for `WorkflowKind.STANDALONE_WORKFLOW`; delete the
     segment-separator clause and the now-unused `xprompt_content_has_segment_separators` import.
   - All Python display/insertion consumers route through this single helper (`xprompt_browser_modal`,
     `xprompt_select_modal`, `xprompt_arg_assist`, `main/xprompt_handler`, `xprompt/_catalog_structured`), so flipping
     it updates the picker, completion, arg-assist, LSP/catalog insertion, and `sase xprompt` output uniformly. No
     per-consumer edits needed beyond the docstring fix in `xprompt_arg_assist.py:162` (which still claims the `#!`
     marker for segment-separated helpers).
   - Update the Python marker/parity tests under `tests/` that assert `#!` for `---`-bodied xprompts to expect `#`.

## Workstream B — allow multiple multi-agent references (sequential fan-out)

All edits in `src/sase/agent/multi_agent_xprompt.py`, in the `else` branch of
`_expand_multi_agent_xprompts_with_metadata` (579-607).

- **Remove the `len(multi_agent_refs) > 1` error** (588-593) and delete `_multiple_multi_agent_reference_message`
  (377-383).
- **Add a sequential expander** for the `len(multi_agent_refs) >= 1` case that implements the Q2 semantics:
  - `leading_prose = segment[:refs[0].start]` (text before the first multi-agent ref; includes the existing
    leading-directive prefix and any leading VCS ref handling).
  - For each ref in document order, render its full fan-out via `_render_multi_agent_xprompt` (using that ref's own
    parsed args). Concatenate all sub-segments.
  - Attach `leading_prose` (and leading directives) to the **first** sub-segment of the **first** ref only; a leading
    VCS ref is inherited by the generated follow-up segments that don't already declare one (reuse
    `_prepend_inherited_vcs_ref` / `_leading_vcs_ref_text`, matching the existing sole/embedded paths).
  - **Drop** inter-reference and trailing prose (the user's Q2 choice).
  - Give **each ref** its own template-allocation group (`_next_template_group` per ref), since each is a distinct
    invocation, then recurse each ref's sub-segments through `_expand_multi_agent_xprompts_with_metadata` with
    `max_depth - 1` so nested multi-agent xprompts and the depth cap still work.
- **Preserve the single-reference embedded path unchanged** (`len == 1` → `_expand_embedded_multi_agent_reference`). Per
  Q2, only the multi-ref case is redefined; the single embedded ref keeps prose on both sides of the reference. (Known
  wrinkle — see Risks.)
- Keep `_first_invalid_standalone_xprompt_reference` and the sole-`#!`-on-embeddable error: a `#!` pointing at an
  ordinary (non-multi-agent, non-standalone) xprompt is still a real mistake and must still raise.

## Workstream C — guidance / error-message / doc accuracy

**Error messages** (make them state the _new_ rule: only standalone workflows canonically use `#!`; multi-agent xprompts
use `#` and merely _accept_ `#!`):

- `src/sase/agent/multi_agent_xprompt.py:386-391` `_invalid_explicit_xprompt_message`: drop "and multi-agent xprompts" →
  "Only standalone workflows use `#!`; `{raw}` resolves to an embeddable xprompt. Use `#{name}` for inline expansion."
- Re-read and confirm the workflow-side messages already say the right thing and stay accurate:
  `src/sase/xprompt/workflow_executor_steps_embedded_types.py:28-48` (`format_inline_workflow_reference_error`) and
  `src/sase/xprompt/workflow_runner.py:42-54`. These reference standalone _workflows_ only and should need no change
  beyond a consistency pass.

**Docs** — apply one rule: _standalone YAML workflows keep `#!`; markdown multi-agent xprompts (`---` body) become `#`
(with `#!` noted as still-accepted, deprecated)_. The canonical multi-agent examples that flip are `three_phase` and the
`swarm` fixtures; the `sase/fix_just`, `sase/pylimit_split`, `sase/refresh_docs`, `sase/reads`, `research_swarm`, `gh`,
`sync` examples are standalone workflows and **stay `#!`** (verify each `#!sase/...` and `#!*_swarm` entry is genuinely
a no-`prompt_part` workflow before leaving it).

Primary doc edits:

- `docs/xprompt.md`: line 99 (insertion summary), 252-253 (the "use `#!` for … plus markdown-defined multi-agent
  xprompts" sentence), the `#!name` reference table 266-269, the "Multi-Agent XPrompts" section 1556-1563 (picker shows
  `#name`; `#!name` recognized for back-compat), the **Rules and Limitations** 1608-1614 (replace the "at most one
  multi-agent reference" rule with the new sequential fan-out + leading-prose/drop semantics), 1541, and the
  "Relationship to Workflows" 1626-1631 lines.
- `docs/blog/posts/xprompts-in-depth.md:122-125` directly states the now-wrong "picker shows `#!` … prefer `#!`" rule —
  correct it. Other blog `#!sase/...` mentions are standalone workflows and stay.
- Sweep `docs/configuration.md`, `docs/development.md`, `docs/ace.md`, `docs/editor.md`, `docs/cli.md`,
  `docs/architecture.md`, `docs/images/*infographic*` for prose tying multi-agent xprompts to `#!`; flip multi-agent
  examples to `#`, leave standalone-workflow guidance intact.

## Files touched (summary)

- **Rust (sase-core):** `crates/sase_core/src/xprompt_catalog.rs` (logic + 2 tests; remove dead
  `content_has_segment_separators`). Rebuild binding; run sase-core tests.
- **Python logic:** `src/sase/xprompt/reference_display.py`, `src/sase/agent/multi_agent_xprompt.py`.
- **Python guidance:** docstring in `src/sase/ace/tui/widgets/xprompt_arg_assist.py:162`; error string in
  `multi_agent_xprompt.py`.
- **Tests:** `tests/test_multi_agent_xprompt_expansion.py`, `tests/test_multi_agent_xprompt_edge_cases.py`,
  `tests/_multi_agent_xprompt_helpers.py`, reference-display/marker tests, and the cross-language parity fixture.
- **Docs:** `docs/xprompt.md` (primary) + the sweep list above.

## Testing

- New Python expansion tests: `[a1,a2,b1,b2]` ordering for two refs; leading prose lands on `a1` only; inter/trailing
  prose dropped; three refs; each ref keeps its own args and template group; leading VCS ref inherited by follow-ups;
  depth cap still fires; single embedded ref unchanged; `#` and `#!` produce identical results for a multi-agent ref.
- Update/remove the test asserting the old multiple-ref error.
- Rust: updated catalog/parity assertions (`#swarm`, `#app/swarm`).
- `just install` then `just check` (lint + mypy + tests, including PNG snapshot suite — picker insertion text appears in
  snapshots, so regenerate intentionally if those change). Run sase-core's Rust tests for the core change.

## Risks & open questions

- **Lossy multi-ref prose (Q2 option 3):** inter-reference and trailing text — including any ordinary `#inline` xprompts
  or VCS refs sitting in that text — are silently dropped for the 2+-ref case. This is the user's explicit choice;
  flagging so it can be reconsidered at review. Will be documented in `docs/xprompt.md` so the behavior isn't
  surprising.
- **Single- vs multi-ref discontinuity:** one embedded ref keeps trailing prose on its first segment; two refs drop it.
  Intentional per Q2 (option 1, the generalized-embed alternative, was declined), but worth confirming.
- **Boundary note:** the marker decision lives in Rust core and is updated there (+ Python mirror). The multi-agent
  **expansion algorithm** currently lives only in Python (`multi_agent_xprompt.py`); this plan extends it in place
  rather than porting it to `sase-core`. A port is a much larger, separate effort — calling it out in case the user
  wants the algorithm relocated instead.
- **Rust/Python lockstep:** a parity fixture asserts the two marker implementations agree; they must land together or
  that test fails.
