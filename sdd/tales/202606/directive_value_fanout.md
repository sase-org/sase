---
create_time: 2026-06-23 14:43:55
status: done
prompt: sdd/prompts/202606/directive_value_fanout.md
---
# Plan: Directive-Value Fan-Out (`%directive:%{a | b | c}`)

## Problem

This prompt was expected to launch **3 Opus agents at different reasoning-effort levels** (medium / high / xhigh), but
instead failed at launch time:

```
#gh:sase Describe this repo. #m_opus %effort:%{medium | high | xhigh}

DirectiveError: '%effort' directive requires a level argument
```

The user's intent is that the `%{medium | high | xhigh}` group fans the prompt out into three agents, each receiving a
distinct `%effort:<level>` value. Today that syntax does not fan out at all — it errors.

## Root Cause (verified by reproduction)

There are **two** interacting facts, and together they produce the error:

1. **The fan-out planner never sees the `%{`.** The `%{ ... | ... }` fan-out group is only recognized at a
   "directive-valid position": start-of-line, or immediately after whitespace / `(` / `[` / `{` / `"` / `'`. In
   `%effort:%{medium | high | xhigh}` the `%{` is preceded by `:` (the directive's argument colon), which is **not** in
   that set. So the launch fan-out planner finds **zero** alternative groups and treats the whole thing as a single
   agent.

2. **The single, un-split prompt then fails directive parsing.** The directive colon-argument character class excludes
   `%` and `{`, so `%effort:` captures no argument. `%effort` is parsed as a **bare** directive, and
   `_resolve_reasoning_effort` raises `'%effort' directive requires a level argument`.

Reproduction (against the current build) confirms both:

- `plan_agent_launch_fanout("Describe this repo. %m:opus %effort:%{medium | high | xhigh}", launch_kind="model")` → **0
  slots** (no fan-out).
- `extract_prompt_directives("Describe this repo. %m:opus %effort:%{medium | high | xhigh}")` → raises
  `DirectiveError: '%effort' directive requires a level argument`.
- Proxy with the group at an already-recognized position (`"Describe. %m:opus (%{medium | high | xhigh})"`) → **3
  slots**: `(medium)`, `(high)`, `(xhigh)` — proving the span-replacement keeps surrounding text intact once the `%{` is
  recognized.

The launch order is **fan-out first, then per-agent directive extraction** (`_launch_body.py` expands xprompts →
`plan_prompt_fanout_variants` → launches each slot; per-agent extraction in `llm_provider/preprocessing.py` /
`axe/run_agent_directives.py` only ever sees a single already-split slot). No raw-prompt directive extraction precedes
fan-out in the launch path. Therefore, **making the fan-out planner recognize the `%{` is sufficient** to fix the bug:
each slot becomes `%effort:medium` / `%effort:high` / `%effort:xhigh`, which the per-agent extractor parses cleanly
(verified: `model='opus'`, `effort='medium'`, etc.).

## Design Decision

**Recognize `%{` / `%(` / `%alt(` when preceded by a directive-argument colon `:`, enabling "value fan-out".**

`%directive:%{a | b | c}` becomes a fan-out that expands to `%directive:a`, `%directive:b`, `%directive:c`. This is a
small, uniform extension of the existing alt-group grammar — it is **directive-agnostic** and works the same for every
directive:

- `%effort:%{medium | high | xhigh}` → three agents at those efforts.
- `%m:%{opus | sonnet}` → equivalent to the documented `%{%m:opus | %m:sonnet}`.
- Combines/Cartesians naturally: `%m:%{opus | sonnet} %effort:%{medium | high}` → 4 agents.

Concretely: add `:` to the preceding-character set in the three mirrored alt-directive recognizers. This is purely
**additive** — it only causes `%{`/`%(` to be recognized in a position where it is currently ignored; it changes no
existing recognized case.

### Why this interpretation

The user explicitly wanted this exact prompt to _work_ (fan out), not to be told to rewrite it. Value fan-out is the
most ergonomic and intuitive spelling, and it composes cleanly with the existing model/effort fan-out machinery. The
currently-documented alternative (`%{%effort:medium | %effort:high | %effort:xhigh}`, the per-branch full-directive
form) keeps working unchanged.

### Alternative considered (not chosen)

Instead of supporting the syntax, only improve the error message to point users at the per-branch form
(`%{%effort:... | ...}`). Rejected: it contradicts the user's stated intent and leaves a sharp, surprising edge in the
grammar (`%{` works everywhere except right after a directive colon).

## Scope of Change

The fan-out grammar is owned by the **Rust core** (per the Rust-core backend boundary), with two Python mirrors that
must stay in parity. All three carry the same preceding-character set today (`^ | whitespace | ( [ { " '`) and all three
need `:` added:

1. **Rust (authoritative splitter):** `alt_directive_re()` in `../sase-core/crates/sase_core/src/agent_launch/mod.rs`
   (currently `(?m)(^|[\s\(\[\{"'])(%(?:alt)?\(|%\{)`). This is what actually splits the prompt at launch.
   - Edit the numbered linked-repo workspace via `sase workspace open -p sase-core ...`, then rebuild with
     `just install` so the Python binding (`sase_core_rs`) picks up the change.

2. **Python mirror — `_ALT_DIRECTIVE_RE`** in `src/sase/xprompt/_directive_alt.py`. Used by `has_alt_directive`
   (CLI/query routing in `main/query_handler/special_cases.py`) and by `extract_prompt_directives` to compute alt-inner
   regions. Must match Rust so CLI routing and inner-region detection agree.

3. **Python mirror — `_ALT_OPEN_RE`** in `src/sase/xprompt/alt_inspect.py`. Drives `%{...}` syntax highlighting in the
   prompt editors; its module docstring states it deliberately mirrors the Rust grammar, so the highlight must follow.

Out of scope (note, don't change as part of the core fix): editor diagnostics/completion regexes
(`editor/diagnostics.rs`, `editor/completion.rs`) recognize directive _names_, not the alt group, and are a separate
presentation concern.

## Edge Cases & Risks

- **Single-branch value fan-out** `%effort:%{medium}` follows existing single-branch "with/without" semantics: it
  produces `%effort:medium` **and** an empty variant `%effort:` (which would then error as a bare directive). This is an
  odd thing to write and is consistent with current alt behavior; document it as a known wrinkle rather than special
  casing it. The reported 3-branch case is unaffected.
- **Slightly broader matching:** any `:` immediately before `%{`/`%(` now opens a group (e.g. prose like
  `ratio 3:%{a | b}`). This is rare, and `%{` is already a reserved fan-out marker, so the risk is low. Confirm no
  existing tests assert the negative (none found in a search for `:%{`).
- **Parity:** the Python regexes and the Rust regex must be changed together; a mismatch would make CLI pre-routing or
  highlighting disagree with actual launch behavior.

## Testing

- **Rust** (`agent_launch/mod.rs` test module): `%effort:%{medium | high | xhigh}` splits into three slots rendering
  `%effort:medium` / `%effort:high` / `%effort:xhigh`; value fan-out for `%m:%{opus | sonnet}`; Cartesian combination of
  two value fan-outs; surrounding text preserved. Run the core crate tests.
- **Python**:
  - `tests/test_directives_split_alternatives.py` / `tests/test_directives_split_models_alts.py`: value fan-out splits
    and renders correctly; combines with a model directive.
  - `tests/test_directives_effort.py`: the end-to-end offending prompt now fans out (no `DirectiveError`), and each
    resulting slot extracts the expected `reasoning_effort`.
  - `tests/test_directives_has_helpers.py`: `has_alt_directive("%effort:%{...}")` is `True`.
  - `tests/test_xprompt_alt_inspect.py`: `tokenize` returns delimiter/separator spans for a `:%{...}` group.
- Run `just check` (lint + mypy + tests) in this repo and the core crate's test suite in the linked repo. Confirm the
  full original prompt fans out into 3 Opus agents end-to-end.

## Documentation

Update `docs/xprompt.md`:

- In the alt/fan-out section, document the value-fan-out shorthand `%directive:%{a | b | c}` alongside the existing
  per-branch examples.
- In the Effort Directive section, add `%effort:%{medium | high | xhigh}` as a fan-out example next to the existing
  `%{%m:opus@xhigh | %m:sonnet@low}` example.

## Out of Scope

- Editor diagnostics/completion behavior for `%directive:%{...}` (separate presentation surface).
- Changing the directive colon-argument character class itself (the value-fan-out path never relies on the un-split
  prompt parsing, because fan-out always precedes extraction).
- Any change to effort vocabulary, provider support matrix, or `default_effort` (delivered by the sase-55 epic).
