---
create_time: 2026-04-28 16:15:58
status: wip
---
# Shorter LLM Provider Suffixes in Agent Names

## Goal

When an agent prompt fans out across multiple LLM providers (via `%m(...)` or multiple `%m` directives), each spawned
agent's name gets a `.<runtime>` suffix so they can be told apart. Today the suffix is the full provider name:

```
%n:foo %m(opus, gpt-5.5)
→ foo.claude, foo.codex
```

We want shorter, fixed-width-ish suffixes:

| Provider | Today    | New   |
| -------- | -------- | ----- |
| claude   | `claude` | `cld` |
| gemini   | `gemini` | `gem` |
| codex    | `codex`  | `cdx` |
| jetski   | `jetski` | `jet` |

So the example above becomes `foo.cld` / `foo.cdx`. Same-runtime collision disambiguation still appends the model alias:
`foo.cld-opus` / `foo.cld-sonnet`, `foo.gem-flash3` / `foo.gem-flash25`.

The jetski provider lives in the external `../sase-google` plugin repo, so this change spans two repos.

## Context — How the Suffix Is Built Today

Single load-bearing site: `src/sase/xprompt/_directive_alt.py`.

1. `_apply_multi_model_naming()` (lines 380–436) is called once a prompt has fanned out into multiple sub-prompts that
   span ≥ 2 distinct `%model` values.
2. For each model it asks `_runtime_label_for_model(model)` (line 360) for the "runtime label", which today is just the
   provider entry-point name from `resolve_model_provider()` / `get_default_provider_name()` in
   `src/sase/llm_provider/registry.py`.
3. Same-runtime collisions (e.g. two claude models) get a model-alias suffix appended: `f"{r}-{short}"` where `short`
   comes from `model_short_alias_map()`.

So the **runtime label** is the only thing that needs to change. Provider entry point names (`claude`, `gemini`,
`codex`, `jetski`) and the public `llm_provider_name()` hook value should stay as-is — they're used for config lookups,
model resolution (`claude/opus`), CLI arguments, log labels (`format_provider_model_label` upper-cases them as
`CLAUDE(opus)`), etc. Conflating "provider identity" with "agent-name suffix" would force ripple edits we don't want.

## Approach

Introduce a new, optional plugin hook that returns the short suffix label, defaulting to the full provider name when a
plugin doesn't implement it. Use the new label only in the agent-naming code path.

### 1. New hook

Add to `src/sase/llm_provider/_hookspec.py` next to `llm_provider_name`:

```python
@hookspec(firstresult=True)
def llm_provider_short_name(self) -> str: ...
```

Document that this is the short label used in spawned-agent name suffixes (e.g. `foo.cld`) and that it should be unique
across providers. When omitted, the registry falls back to the provider entry-point name, preserving today's behavior
for plugins that haven't been updated.

### 2. Provider implementations

In the main repo:

- `src/sase/llm_provider/claude.py` — return `"cld"`
- `src/sase/llm_provider/gemini.py` — return `"gem"`
- `src/sase/llm_provider/codex.py` — return `"cdx"`

In `../sase-google`:

- `src/sase_google/llm_jetski/provider.py` — return `"jet"`

Each implementation is one `@hookimpl` method placed beside the existing `llm_provider_name` impl.

### 3. Registry helper

Add to `src/sase/llm_provider/registry.py`, parallel to `model_short_alias_map()`:

```python
def provider_short_name_map() -> dict[str, str]:
    """Return {provider_name → short_label} for agent-name suffixes."""
    mapping: dict[str, str] = {}
    for name, plugin in iter_plugins():
        method = getattr(plugin, "llm_provider_short_name", None)
        short = method() if method is not None else None
        mapping[name] = short or name
    return mapping
```

The fallback to `name` keeps third-party plugins (and any provider we forget to update) working with no behavior change.

### 4. Wire into the suffix builder

Update `_runtime_label_for_model()` in `src/sase/xprompt/_directive_alt.py` to return the short label:

```python
def _runtime_label_for_model(model: str) -> str:
    from sase.llm_provider.registry import (
        get_default_provider_name,
        provider_short_name_map,
        resolve_model_provider,
    )
    provider, _ = resolve_model_provider(model)
    name = provider or get_default_provider_name()
    return provider_short_name_map().get(name, name)
```

The collision-counting loop in `_apply_multi_model_naming()` already operates on the return value of this function, so
same-runtime collision detection and the `f"{r}-{short_model_alias}"` formatting keep working unchanged — they just read
the new short label.

### 5. Test updates

`tests/test_directives_split_models.py` has ~28 string-equality assertions on the old long suffixes. They mechanically
become:

- `foo.claude` → `foo.cld`
- `foo.claude-opus` / `foo.claude-sonnet` / `foo.claude-haiku` → `foo.cld-opus` / `foo.cld-sonnet` / `foo.cld-haiku`
- `foo.codex` → `foo.cdx`
- `foo.gemini-flash3` / `foo.gemini-flash25` → `foo.gem-flash3` / `foo.gem-flash25`
- `z.claude` / `z.codex` → `z.cld` / `z.cdx`
- `o.claude*` / `o.gemini*` / `o.codex` likewise

Plan: skim the file once, do a structured global replace of those substrings, re-run `just test`. The behavior under
test (collision detection, base-name sharing, alias-collision fallback) doesn't change — we're only renaming the
expected runtime labels.

If the sase-google plugin repo has any tests that assert on `.jetski` agent names, they get the same treatment (`.jet`).

### 6. Docs

Update the multi-model naming section in `docs/xprompt.md` (lines ~921–928). Replace each occurrence of `foo.claude` /
`foo.codex` / `foo.gemini-*` with the new `cld` / `cdx` / `gem` forms in the prose example, and add a one-line note that
the suffix is a short alias declared by the provider plugin (so readers know why it's not literally `claude`). Link the
new hook for plugin authors who want to declare their own.

The `memory/short/gotchas.md` jetski note is about the skill deploy path, not the agent-name suffix — leave it alone.

### 7. Validation

In **both** `sase_100` and `../sase-google`:

```bash
just install   # workspace may be stale
just check     # ruff + mypy + tests
```

Manual smoke (in `sase_100`):

```bash
echo '%n:foo %m(opus, gpt-5.5)\nhello' | sase prompt parse  # or equivalent
# → expect %name:foo.cld and %name:foo.cdx in the two emitted sub-prompts
```

(If there's no thin parse-only entry point, a one-off pytest of `_apply_multi_model_naming` is fine.)

## Out of Scope

- Changing the entry-point names (`claude`, `gemini`, `codex`, `jetski`) — that would break model resolution syntax
  (`claude/opus`), config keys, status-bar labels, and external user expectations.
- Changing model short aliases (e.g. `flash3`, `flash25`) — those are model- level disambiguators and already short.
- Changing `format_provider_model_label()` (which upper-cases the provider name into `CLAUDE(opus)` for status output).
  The short label is for agent names only; status-bar labels stay long-form.
- Adding a CLI flag to opt out of short suffixes. If we ever want it, fine, but YAGNI — agent names are display-only,
  and the old form had no opt-out either.

## Risks & Open Questions

- **Collision risk across plugins.** If a third-party plugin happens to also return `"cld"` (or any of the four), we'd
  get duplicate suffixes. Mitigation: the existing alias-collision fallback in `_apply_multi_model_naming()` (lines
  423–427) already detects duplicate `suffix_for` values and falls back to raw model names — this works at the _model_
  level today but not the _provider_ level. If two providers share a short name and the user picks one model from each,
  every short label is unique within that fan-out (no collision triggers). If the same provider short label appears for
  two different providers _and_ both runtimes have multiple models, the existing fallback handles it. The realistic risk
  is effectively zero with four built-in providers; we'll address it if/when a conflicting plugin lands.
- **Plugin-version skew.** A user with an outdated `sase-google` (no `jet` hook impl) still gets `foo.jetski` until they
  upgrade. That's the desired fallback behavior, not a bug.
- **Discoverability for plugin authors.** Worth a sentence in the xprompt doc and/or `_hookspec.py` docstring; covered
  by step 6.

## Files Touched

Main repo (`sase_100`):

- `src/sase/llm_provider/_hookspec.py` — hook spec
- `src/sase/llm_provider/registry.py` — new helper
- `src/sase/llm_provider/claude.py` — `"cld"`
- `src/sase/llm_provider/gemini.py` — `"gem"`
- `src/sase/llm_provider/codex.py` — `"cdx"`
- `src/sase/xprompt/_directive_alt.py` — wire into `_runtime_label_for_model`
- `tests/test_directives_split_models.py` — updated assertions
- `docs/xprompt.md` — updated example prose

Plugin repo (`../sase-google`):

- `src/sase_google/llm_jetski/provider.py` — `"jet"`
- any test asserting on `.jetski` agent suffix (TBD — grep at edit time)
