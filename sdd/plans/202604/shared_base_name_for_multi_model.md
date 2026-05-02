---
create_time: 2026-04-25 15:45:39
status: done
prompt: sdd/prompts/202604/shared_base_name_for_multi_model.md
---
# Plan: Shared base name + `<base>.<llm>` suffix for multi-model agent spawns

## Problem

A prompt that produces multiple agents via `%model:a,b` (or repeated `%m`) currently leaves both spawned agents fighting
over the same name:

- The user's `%name:foo` directive is preserved verbatim in **every** split sub-prompt, so each child runs
  `extract_prompt_directives()` and ends up with `directives.name = "foo"`. The second child to call
  `claim_agent_name()` evicts the first. Net result: two agents from the same prompt collide on identity, and there is
  no stable way to refer to "the codex one" vs. "the claude one".
- When `%name` is absent, each child independently calls `get_next_auto_name()` (`run_agent_phases.py:95`), so the
  auto-allocated names are unrelated alphabetic letters with no shared base — there is nothing to tell a user that two
  agents originated from the same prompt.

## Goal

When a single prompt is split across N models, every resulting agent should share a base name and carry a
runtime-specific suffix:

| Prompt                               | Agent names                                                   |
| ------------------------------------ | ------------------------------------------------------------- |
| `%m:opus,gpt-5.5` `%n:foo`           | `foo.claude`, `foo.codex`                                     |
| `%m:opus,gpt-5.5` (no `%name`)       | `<auto>.claude`, `<auto>.codex` (single shared `<auto>` base) |
| `%m:opus` `%n:foo` (single model)    | `foo` — **unchanged**                                         |
| `%m:opus` (single model, no `%name`) | `<auto>` — **unchanged**                                      |

The `.<llm>` suffix only kicks in when the prompt actually fans out to multiple agents. Single-model prompts retain
today's naming exactly so we don't churn existing behavior or filenames.

(Open question, see "Decisions to confirm": whether single-model + auto-gen should also adopt `.<llm>` form. The user's
wording is ambiguous; default proposal is "no, only multi-model".)

## Where today's code lives

- `src/sase/xprompt/directives.py:238` — `split_prompt_for_models()` rewrites multiple `%model` occurrences into a
  single `%alt(%model:a,%model:b,...)`, then defers to `_split_prompt_for_alternatives()` which produces N sub-prompts.
  The outer `%name:foo` is **not** touched, so it appears verbatim in every sub-prompt.
- `src/sase/xprompt/directives.py:412` — `extract_prompt_directives()` reads `%name`/`%n` (last-wins for non-multi).
  Bare `%name` triggers a single call to `get_next_auto_name()` (line 528).
- `src/sase/agent/multi_prompt_launcher.py:189` — entry point that calls `split_prompt_for_models()` per segment and
  spawns one subprocess per sub-prompt.
- `src/sase/axe/run_agent_phases.py:89` — name resolution inside each spawned agent: `directives.name` →
  `SASE_REPEAT_NAME` → `get_next_auto_name()`.
- `src/sase/llm_provider/registry.py:122` — `resolve_model_provider()` maps a model string (`"opus"`, `"codex/o3"`,
  etc.) to a provider/runtime label (`"claude"`, `"codex"`, ...). This is the canonical model→runtime map.

## Design

### Where to make the change

The cleanest seam is **`split_prompt_for_models()` itself**, because that's the single place that already knows "this
prompt is being fanned out into N distinct prompts" and has each sub-prompt's bound model in hand. Doing it there means:

- `extract_prompt_directives()` and `run_agent_phases.py` need no special cases — they just see a normal
  `%name:foo.claude` directive in the sub-prompt and act on it as usual.
- The single-model path is untouched; `split_prompt_for_models()` returns `None` and no naming rewrite ever runs.
- All existing layers that consume the returned sub-prompts (TUI launcher, multi-prompt launcher, tests) get the renamed
  directive transparently.

### Algorithm

1. Run today's logic up through producing `unique_models` (the deduped ordered list of model args). If
   `len(unique_models) <= 1`, return unchanged — same as today.
2. Determine the **shared base name** for the fan-out, once:
   - Scan the prompt for a `%name`/`%n` directive (reusing the existing directive regex; respect fenced/disabled regions
     exactly as today).
   - If found with a non-empty value → base = that value.
   - If found bare (`%name` with no arg) → base = `get_next_auto_name()`.
   - If absent → base = `get_next_auto_name()`.
   - Strip the original outer `%name` directive from the prompt so it doesn't shadow the per-split directive added
     below. (No-op if absent.)
3. Run the existing alt-splitting logic to get N sub-prompts.
4. For each sub-prompt:
   - Recover its bound model (already known: same loop that drives the alt-args list, in document order, line up 1:1
     with sub-prompts).
   - Compute the runtime label via `resolve_model_provider(model)`. If it returns `None` for the provider, fall back to
     `get_default_provider_name()` (this matches the same fallback used in `run_agent_phases.py:99-102`).
   - Insert/replace the `%name` directive in the sub-prompt with `%name:<base>.<runtime>`. Insertion location: a new
     line at the top of the sub-prompt (or replacing in place if step 2 left a stripped marker — design choice:
     stripping outright in step 2 and re-inserting here is simpler than tracking a placeholder).
5. Return the rewritten sub-prompts as today.

### Helpers to add (in `src/sase/xprompt/directives.py`)

- `_extract_and_strip_name_directive(prompt: str) -> tuple[str, str | None, bool]` — returns
  `(prompt_without_name, raw_value, was_bare)`. `raw_value` is `None` if no `%name` directive existed.
- `_runtime_label_for_model(model: str) -> str` — wraps `resolve_model_provider()` + `get_default_provider_name()`
  fallback. Lives here (not registry) because it's a naming concern, not a provider-resolution concern.
- `_inject_name_directive(prompt: str, name: str) -> str` — prepends a `%name:<name>` line.

These are file-local helpers; nothing public.

### Edge cases & decisions

| Case                                                                       | Proposed behavior                                                                                                                                        |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Two models that map to the same runtime (`%m:opus,sonnet` both → `claude`) | Disambiguate with model name: `foo.claude-opus` and `foo.claude-sonnet`. Detect by checking if the runtime label is non-unique across the split.         |
| Explicit provider syntax `%m:codex/o3,claude/opus`                         | Works as-is — `resolve_model_provider` handles `provider/model` form.                                                                                    |
| Unknown model (`resolve_model_provider` returns `(None, model)`)           | Use `get_default_provider_name()` as the runtime label. Same fallback as `run_agent_phases.py`.                                                          |
| Bare `%name` with multi-model                                              | Generate one auto-name as the base, then suffix per-runtime. (Solves a current latent bug where each child auto-generates independently.)                |
| User wrote `%name:foo.claude` explicitly with `%m:opus,gpt-5.5`            | Base becomes `foo.claude`, suffixed names become `foo.claude.claude` and `foo.claude.codex`. Acceptable for v1; flagging as a known wart, not a blocker. |
| `%alt(...)` with non-`%model` branches (existing alt feature)              | Untouched — naming rewrite only triggers on the multi-model path, not generic alt-splitting.                                                             |
| `SASE_REPEAT_NAME` env var                                                 | Untouched. Only consulted when `directives.name is None` inside an already-spawned agent; multi-model parents never read it.                             |

### Decisions to confirm with the user

1. **Single-model + auto-gen**: should `%m:opus` (no `%name`) produce `a.claude` instead of `a`? The user wrote _"this
   same form should be used when the name is auto-generated"_ which is ambiguous. **Default proposal: no — only
   multi-model fan-outs get the suffix**, to avoid breaking existing artifacts and habits. Easy to flip later if
   desired.
2. **Same-runtime collision suffix**: confirm `foo.claude-opus` / `foo.claude-sonnet` is the desired form when multiple
   models share a runtime. Alternative: `foo.opus` / `foo.sonnet` (drop the runtime entirely when it's redundant).
   Either is one line of code.

## Test plan

Add tests in `tests/test_directives_helpers.py` (the existing home for `split_prompt_for_models` tests):

- `%m:opus,gpt-5.5` + `%n:foo` → sub-prompts contain `%name:foo.claude` and `%name:foo.codex` respectively; outer
  `%name:foo` no longer appears.
- `%m:opus,gpt-5.5` + no `%name` → sub-prompts contain `%name:<X>.claude` and `%name:<X>.codex` for the same `<X>`.
  (Mock `get_next_auto_name` so the test isn't order-dependent.)
- `%m:opus,gpt-5.5` + bare `%name` → same as above; base is auto-generated exactly once.
- `%m:opus` + `%n:foo` → single-model path, name unchanged (regression guard).
- `%m:codex/o3,claude/opus` + `%n:foo` → uses provider-prefix syntax cleanly.
- `%m:opus,sonnet` (both → claude) + `%n:foo` → `foo.claude-opus` / `foo.claude-sonnet` (depending on decision above).
- `%m:unknown_model,opus` + `%n:foo` → unknown maps to default provider's label.

End-to-end coverage in `tests/test_multi_prompt_launcher.py` (or a new test): launch a multi-model segment, confirm the
spawned agents' `agent_meta.json` files end up with the suffixed names. Existing tests in `test_directives_helpers.py`
for the no-rename multi-model path will need their expected sub-prompt strings updated.

## Documentation

- `docs/xprompt.md` — add a short paragraph under the `%model` / `%name` sections explaining the `<base>.<runtime>` form
  for multi-model spawns, with a worked example.
- `memory/short/glossary.md` — no change needed (ChangeSpec/xprompt entries are unaffected).

## Out of scope

- Renaming agents _after_ spawn (no UI flow today, and not requested).
- Changing the `agent_meta.json` schema — the `name` field already stores the final string; adding `base_name` /
  `runtime_suffix` columns is unnecessary churn.
- Touching `SASE_REPEAT_NAME`, retry-spawn naming, or `#resume:<name>` semantics. The new names are still valid agent
  identifiers, so all downstream consumers keep working unmodified.
