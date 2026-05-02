---
create_time: 2026-04-23 12:43:43
status: done
prompt: sdd/prompts/202604/multi_model_directive.md
---

# Allow Multiple `%model` Directives in a Single Prompt

## Problem

Today, `extract_prompt_directives()` in `src/sase/xprompt/directives.py:364-365` raises
`DirectiveError("Duplicate directive '%model' in prompt")` whenever a user writes more than one `%model` / `%m`
directive in the same prompt. For example:

```
%model:opus
%model:sonnet
Review this code.
```

…is rejected outright. The only way today to target multiple models from one prompt is the parenthesized multi-model
form `%model(opus,sonnet)` (handled by `split_prompt_for_models()` at `directives.py:245-269`), which rewrites the
directive to `%alt(%model:opus,%model:sonnet)` and produces one variant prompt per model.

We want to lift the "at most one `%model` directive" restriction. Multiple `%model` directives should be treated as if
the user had written a single directive whose argument list is the union of all the individual model args — i.e.
semantically identical to `%model(a,b,…)` and therefore split via the existing alternatives machinery into one prompt
per model.

## Goal & User-Visible Behavior

After this change, all of the following are accepted and produce the same end result (one launched agent per distinct
model):

| Input (same prompt body elided)                    | Effective models        |
| -------------------------------------------------- | ----------------------- |
| `%model(opus,sonnet)` (status quo — already works) | `[opus, sonnet]`        |
| `%model:opus` + `%model:sonnet`                    | `[opus, sonnet]`        |
| `%m:opus` + `%model:sonnet` (alias mix)            | `[opus, sonnet]`        |
| `%model:opus` + `%model(sonnet,haiku)`             | `[opus, sonnet, haiku]` |
| `%model:opus` + `%model:opus` (identical dupes)    | `[opus]` → no split     |
| `%model:opus` alone (status quo)                   | `[opus]` → no split     |

Ordering: document order (first occurrence wins for dedupe). Other directives (`%plan`, `%edit`, `%wait`, `%name`,
`%repeat`, etc.) continue to reject duplicates — the relaxation is `%model`-specific.

## Non-Goals

- No new directive syntax. We are relaxing validation, not inventing a form.
- No change to how a single `%model:X` is consumed downstream. The `PromptDirectives.model` field remains `str | None`;
  multi-model still splits into N prompts with one model each.
- No change to `%alt(…)` / `%(…)` semantics.
- No change to the set of directives that are allowed to repeat generally (`_MULTI_VALUE_DIRECTIVES`) — model is a
  special case handled at the splitter layer, not a generic multi-value directive.

## Design Overview

The existing pipeline already has the right layering:

1. **Splitter layer** (`split_prompt_for_models()`): runs early in routing paths (`agent/launcher.py:286`,
   `agent/multi_prompt_launcher.py:189`, `main/query_handler/special_cases.py:51`,
   `ace/tui/actions/agent_workflow/_agent_launch.py:247`). Converts multi-model prompts into a list of single-model
   variants.
2. **Extraction layer** (`extract_prompt_directives()`): runs per variant; sees only one `%model:X` and populates
   `PromptDirectives.model`.

The fix keeps that layering and touches both ends:

- **Primary change — splitter**: detect _all_ `%model` / `%m` occurrences (colon, paren, bare) and collapse them into a
  single `%alt(%model:a,%model:b,…)` rewrite. Today the splitter only picks up the first `%model(…)` parenthesized match
  and ignores scalar forms entirely.
- **Secondary change — extractor**: drop the hard duplicate-model error. If the splitter has already run (the common
  path), each variant has at most one `%model` and the check is unreachable. If a caller invokes
  `extract_prompt_directives()` directly on a prompt with multiple `%model:` directives, we fall back to
  collapse-then-use-last-unique so nothing explodes.

### Why not add `model` to `_MULTI_VALUE_DIRECTIVES`?

`_MULTI_VALUE_DIRECTIVES` is for directives whose canonical representation is a _list_ on `PromptDirectives` (e.g.
`wait: list[str]`). Model is different: the canonical representation of "multi-model" is "one variant prompt per model,"
expressed via splitting. Making `model` multi-value would leak a `list[str]` through `PromptDirectives.model` that
downstream consumers (`llm_provider/_invoke.py:136`, `run_agent_phases.py:97`, `workflow_executor_steps_prompt.py:247`,
`query_handler/_query.py`) would all have to re-handle. Keeping the split semantics avoids that ripple.

## Implementation Plan

### 1. Extend `split_prompt_for_models()` in `src/sase/xprompt/directives.py`

Current behavior (lines 245-269): `_MULTI_MODEL_RE.search()` finds the _first_ `%model(…)` / `%m(…)` paren form and
rewrites it. Scalar `%model:X` forms are ignored.

New behavior:

1. Walk the prompt with a broadened regex that matches every `%model` / `%m` directive in any of its forms: `%model:X`,
   `%model(X,Y,…)`, `%m:X`, `%m(X,Y,…)`, bare `%model` / `%m` (no arg), `%model+` (plus suffix — still treated as "no
   real arg," skipped for collection).
2. Respect the same position guards the existing `_DIRECTIVE_PATTERN` uses (start-of-input, after whitespace, or after
   `([{"'`) and skip occurrences inside fenced code blocks (reuse `protect_fenced_blocks` / `unprotect_fenced_blocks`)
   and inside `%xprompts_enabled:false` disabled regions (reuse `protect_disabled_regions`).
3. Collect the argument list for each match (using `parse_args` for the paren form, raw value for colon/backtick form).
   Preserve document order.
4. Dedupe while preserving first-occurrence order. Empty/bare model directives are dropped from the collected list (they
   contribute nothing) but their spans are still scheduled for removal so the rewrite is clean.
5. Decide the rewrite:
   - **Zero non-empty models collected** → return `None` (unchanged; nothing to split).
   - **One unique model collected from one directive** → return `None` (status quo — extractor handles the single-model
     case).
   - **One unique model collected from multiple directives** (e.g. `%model:opus` twice) → strip the redundant directive
     spans and return `None` (no split, single model). The prompt handed to `extract_prompt_directives` must contain
     exactly one `%model:X` so the extractor is happy.
   - **Two or more unique models** → splice out _all_ the collected directive spans and insert a single
     `%alt(%model:a,%model:b,…)` at the position of the first collected directive, then delegate to
     `_split_prompt_for_alternatives` as today.

   Splice order: right-to-left by span to keep indices stable (same pattern used by `_split_prompt_for_alternatives` at
   line 236-241).

6. Continue to honor existing `%alt(…)` / `%(…)` in the prompt — after collapsing `%model` directives, pass the
   rewritten prompt to `_split_prompt_for_alternatives`, which already computes the Cartesian product with any other
   `%alt(…)` directives present.

Edge cases to handle explicitly:

- Identical dupes: `%model:opus` + `%model:opus` → collapse to single `%model:opus`, no split.
- `%model:opus` + `%model(opus,sonnet)` → unique set `{opus, sonnet}`, splits into 2.
- Spread across disabled regions: `%model:X` inside a `%xprompts_enabled:false` region is ignored (consistent with
  extractor behavior).
- Inside fenced code blocks: ignored (consistent with extractor behavior).
- Empty paren: `%model()` — already produces no args; contributes nothing.

### 2. Relax duplicate validation in `extract_prompt_directives()`

At `directives.py:361-365`, the duplicate check reads:

```python
if name in _MULTI_VALUE_DIRECTIVES:
    pass
elif name in seen:
    raise DirectiveError(f"Duplicate directive '%{name}' in prompt")
```

Change: carve out `model` specifically. When a second `%model` is seen:

- If the new `raw_arg` equals the already-seen value (after strip) → silently accept; add the span to
  `regions_to_remove` but do not overwrite `seen["model"]`.
- If the new `raw_arg` differs → this is the "splitter was bypassed" case. Options:
  - **Option A (recommended):** use last-wins (overwrite `seen["model"]`) and strip the prior span too. Matches the
    user's stated framing of "treat as if a single model directive was used that included all model arguments" — from
    the extractor's point of view there is only one scalar slot, so the last value wins. This is a soft fallback; routed
    paths will never hit it because the splitter collapsed duplicates first.
  - **Option B:** keep raising. Safer/stricter, but then any direct `extract_prompt_directives` caller that forgets to
    split first will still crash on the prompts the user is now writing.

  Recommendation: Option A, with a brief docstring note that multi-model splitting is handled upstream.

Other directives retain the existing duplicate error.

### 3. Tests

**`tests/test_directives_helpers.py`** — splitter behavior (primary coverage):

- Two `%model:X` directives → two variants, correct models, directive lines stripped.
- `%m:opus` + `%model:sonnet` (alias mix) → two variants.
- `%model:opus` + `%model(sonnet,haiku)` → three variants, unique set preserved in order.
- `%model:opus` + `%model:opus` → returns `None`, prompt cleaned to a single `%model:opus`.
- Duplicates spread across non-adjacent lines (interleaved with other text) split correctly.
- `%model:X` inside a fenced code block is left untouched (not collected, not stripped).
- `%model:X` combined with a user `%alt(a,b)` yields a full Cartesian product (regression guard for the
  `_split_prompt_for_alternatives` interaction).

**`tests/test_directives_extract.py`** — extractor behavior:

- **Flip** `test_alias_m_and_model_duplicate_raises` (lines 89-93): rename to
  `test_alias_m_and_model_duplicate_last_wins` and assert `directives.model == "sonnet"` when the prompt is
  `"%m:opus\n%model:sonnet\nPrompt"`, plus the directive lines are stripped.
- Add: identical duplicates (`"%model:opus\n%model:opus\n…"`) yield `directives.model == "opus"`.
- Confirm other duplicate-directive tests (`%plan` etc., if any exist) still raise.

**Integration-level regression**: existing multi-model launcher tests (`test_multi_prompt_launcher.py`,
`test_directives_helpers.py::test_split_prompt_for_models_*`) should continue to pass unchanged — the `%model(a,b)` form
must still produce the same list of variants.

### 4. Documentation

- Update the `split_prompt_for_models` docstring (`directives.py:245-256`) to describe the new "repeated scalar" case
  alongside the existing `%model(a,b)` and `%alt(…)` cases.
- Update the `extract_prompt_directives` docstring's `Raises` section: `DirectiveError` still raised for duplicate
  non-model directives; note that multi-`%model` is accepted (last-wins in the extractor; multi-model splitting happens
  upstream).
- Spot-check any user-facing docs / xprompt references (e.g. generated SKILL.md help, docs referring to "only one %model
  per prompt") — update if such text exists.

### 5. Check-in sequence

1. Splitter change + splitter tests.
2. Extractor relaxation + flipped extractor test.
3. Docstring / doc sweep.
4. `just check` before commit.

## Risk & Open Questions

- **Dedupe semantics**: recommending first-occurrence-wins dedupe by exact string match. We are _not_ attempting to
  normalize `claude/opus` vs `opus` — resolution happens later in `resolve_model_provider()`. Two syntactic variants
  that resolve to the same provider would produce two variants. Acceptable; matches current `%model(opus,opus)` behavior
  (which also does not dedupe — worth confirming and possibly aligning in a follow-up).
- **Order of models in split output**: document order of first occurrence. Matches existing `%model(a,b)` left-to-right
  behavior.
- **Extractor fallback policy** (Option A vs B above): flagged as recommendation; worth a quick confirm before
  implementation.
- **No silent swallow**: if a prompt reaches the extractor with conflicting `%model` directives, the last-wins path will
  proceed but may warrant a log/warning for debugging. Proposal: no warning in v1; revisit if confusion reports come in.
