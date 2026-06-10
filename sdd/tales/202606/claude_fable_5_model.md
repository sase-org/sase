---
create_time: 2026-06-10 08:37:32
status: wip
prompt: sdd/prompts/202606/claude_fable_5_model.md
---
# Plan: Recognize `claude-fable-5` as a Claude Model + Surface It in TUI Model Pickers

## Background

Anthropic released **Claude Fable 5** (model ID `claude-fable-5`), a new top tier above Opus. SASE's Claude provider
plugin currently only advertises the Claude CLI aliases `opus`, `sonnet`, and `haiku` via its `llm_known_model_names()`
hook (`src/sase/llm_provider/claude.py:70`).

That hook is the **single source of truth** for which models belong to the claude provider. The registry
(`src/sase/llm_provider/registry.py`) aggregates every plugin's known model names into `model_to_provider_map()`, which
powers:

1. **Bare-model provider inference** — `resolve_model_provider()` (registry.py:225) resolves `"opus"` →
   `("claude", "opus")` via this map. Today `"claude-fable-5"` falls through to `(None, "claude-fable-5")`, so
   `%model:claude-fable-5` directives, `-m/--model claude-fable-5` flags, and bare-model custom inputs are _not_
   recognized as claude — they silently fall back to the default provider.
2. **All TUI model selection panels** — `ModelPickerModal._build_model_rows()`
   (`src/sase/ace/tui/modals/model_picker_modal.py:63`) builds its provider-grouped rows from
   `model_to_provider_map()` + `model_short_alias_map()`. This one modal is reused by every model selection surface in
   the TUI:
   - the **temporary LLM override modal** (`,o` leader action) — both the _primary_ and _worker_ lane pickers
     (`temporary_llm_override_modal.py`), and
   - the **approve-options coder model picker** (`approve_options_modal.py`).

So one plugin change propagates everywhere. No Rust core (`sase-core`) changes are needed: the core only handles model
strings opaquely (`%model:` directive parsing / bead `land_model` plumbing), with no model→provider knowledge — verified
by inspecting `crates/sase_core/src/agent_launch/mod.rs` and `crates/sase_core/src/bead/work.rs` in the sase-core_10
sibling workspace.

## Goals

- `claude-fable-5` is recognized as a claude model by default (provider inference works for the bare model ID everywhere
  `resolve_model_provider()` is consulted).
- `claude-fable-5` appears under the CLAUDE group in the TUI model picker, and is therefore selectable from the
  temporary override modal (primary + worker lanes) and the approve-options coder picker.
- Long model ID gets a short display alias (`fable`) so multi-model agent-name suffixes and the picker's `(alias)`
  annotation stay compact, consistent with how other providers alias long model names (e.g. codex `gpt-5.5` → `gpt55`,
  opencode `anthropic/claude-sonnet-4-5` → `sonnet45`).
- Agents-tab rows show a sensible short model name (`fable`) instead of the current fallback, which would render
  `claude-fable-5` as `claude` (first `-`-segment).

## Non-Goals

- **No change to model-tier defaults.** `_TIER_TO_MODEL` in `claude.py` keeps `large → opus`, `small → sonnet`. Fable 5
  is opt-in via pickers, overrides, and `%model` directives — making it a default lane model is a separate product
  decision.
- **No opencode catalog change.** The opencode provider has its own model list (`anthropic/claude-sonnet-4-5`, ...).
  Adding `anthropic/claude-fable-5` there is a separate, optional follow-up (and would need verification that opencode
  actually routes that ID).
- **No Rust core changes** (see Background).

## Changes

### 1. `src/sase/llm_provider/claude.py` — the core change

- `llm_known_model_names()`: return `["opus", "sonnet", "haiku", "claude-fable-5"]`.
  - The Claude CLI accepts full model IDs for `--model` in addition to aliases, so the existing `invoke()` path
    (`--model <model_override>`) works unchanged.
- `llm_model_short_aliases()`: return `{"claude-fable-5": "fable"}` (currently `{}`; the existing alias names are
  already short, which is why claude had no aliases until now).

### 2. `src/sase/ace/tui/widgets/_agent_list_helpers.py` — agent list display

- `short_model_name()`: add `"fable"` to the keyword tuple (`("flash", "fable", "opus", "sonnet", "haiku", "pro")`) so
  agent rows display `fable` rather than the `split("-")[0]` fallback `claude`.

### 3. Tests

- `tests/test_llm_provider_core.py`:
  - `resolve_model_provider("claude-fable-5") == ("claude", "claude-fable-5")` (alongside the existing `opus`/`sonnet`
    inference assertions).
  - The aggregated `model_short_alias_map()` contains `"claude-fable-5" → "fable"`; keep the existing "short names carry
    no alias" test intact (opus/sonnet/haiku stay alias-free).
- `tests/test_model_picker_modal.py`: assert `"claude-fable-5"` is among the built option IDs (next to the existing
  `opus`/`sonnet` assertions), and that its row renders the `(fable)` alias annotation.
- Add a small unit test for `short_model_name("claude-fable-5") == "fable"` (no test currently covers this helper;
  co-locate it with the picker/widget tests as `tests/test_agent_list_helpers.py` or fold into an existing widget test
  module).

## Notes / Risks

- The registry memoizes plugin metadata (`_llm_metadata_payload`); tests that mock entry points already clear the
  caches, so no new cache-handling work is expected.
- `sase doctor` provider checks only _count_ `known_model_names` (no fixed expectations), so the new entry is
  automatically reflected there.
- The picker's filter/search matches on model ID and alias, so typing either `fable` or `claude-fable-5` finds the new
  row — no picker code changes needed.

## Verification

- `just install` (fresh ephemeral workspace), then `just check` (lint + mypy + tests).
- Manual spot-check in `sase ace`: `,o` → set primary override → confirm `claude-fable-5 (fable)` is listed under CLAUDE
  and selecting it writes the override with provider `claude`.
