---
create_time: 2026-04-25 16:15:41
status: done
prompt: sdd/prompts/202604/short_model_aliases_in_agent_names.md
---
# Plan: Short model aliases in multi-model agent name suffixes

## Problem

The recently-shipped `<base>.<runtime>-<model>` collision suffix (commit `cc237f77`) embeds the raw `%model` value
verbatim. For Gemini models that's painful: a `%m:gemini-2.5-flash,gemini-3-flash-preview` fan-out produces agent names
like `@o.gemini-gemini-3-flash-preview` — almost 30 characters of suffix, with the word "gemini" repeated.

Worst offenders today (from `llm_known_model_names`):

| Provider | Long form                | Resulting suffix                 |
| -------- | ------------------------ | -------------------------------- |
| Gemini   | `gemini-3-flash-preview` | `.gemini-gemini-3-flash-preview` |
| Gemini   | `gemini-3.1-pro-preview` | `.gemini-gemini-3.1-pro-preview` |
| Gemini   | `gemini-2.5-flash`       | `.gemini-gemini-2.5-flash`       |
| Codex    | `codex-mini-latest`      | `.codex-codex-mini-latest`       |
| Codex    | `gpt-5.3-codex`          | `.codex-gpt-5.3-codex`           |

Claude's `opus`/`sonnet`/`haiku` are already short — the issue is real only for Gemini and a few Codex names.

## Goal

When a same-runtime collision triggers the `<runtime>-<model>` suffix, substitute a short alias for the model component
so multi-Gemini fan-outs become readable:

| Prompt                                              | Today                                                           | After                                  |
| --------------------------------------------------- | --------------------------------------------------------------- | -------------------------------------- |
| `%m:gemini-2.5-flash,gemini-3-flash-preview` `%n:o` | `o.gemini-gemini-2.5-flash` / `o.gemini-gemini-3-flash-preview` | `o.gemini-flash25` / `o.gemini-flash3` |
| `%m:opus,sonnet` `%n:o`                             | `o.claude-opus` / `o.claude-sonnet`                             | unchanged (already short)              |
| `%m:opus,gpt-5.5` `%n:o`                            | `o.claude` / `o.codex`                                          | unchanged (no collision)               |
| `%m:opus` `%n:o`                                    | `o`                                                             | unchanged (single-model path)          |

The short alias only kicks in for the same-runtime collision branch, where the model name actually appears in the
suffix. Everywhere else, today's behavior is preserved.

## Where today's code lives

- `src/sase/xprompt/directives.py:514` — `_apply_multi_model_naming()`. Line 546 builds
  `f"{r}-{m}" if runtime_count[r] > 1 else r`. The `m` here is the raw model string. **This is the only line that needs
  to consult an alias map.**
- `src/sase/llm_provider/_hookspec.py:57` — `llm_known_model_names()` already exists. Adding `llm_model_short_aliases()`
  parallels it.
- `src/sase/llm_provider/registry.py:48` — `model_to_provider_map()` is the existing pattern for aggregating per-plugin
  metadata. A new `model_short_alias_map()` follows the same shape.
- `src/sase/llm_provider/{claude,codex,gemini}.py` — each gets a small `llm_model_short_aliases` impl.

## Design

### Where the aliases live

Each provider plugin owns its own short-alias dict via a new hookspec:

```python
@hookspec(firstresult=True)
def llm_model_short_aliases(self) -> dict[str, str]: ...
```

Returning `{"gemini-3-flash-preview": "flash3", "gemini-2.5-flash": "flash25", ...}`. Defaulting to `{}` when a provider
has no aliases worth declaring.

The registry exposes a single aggregator:

```python
def model_short_alias_map() -> dict[str, str]:
    """Build {model_name → short_alias} from plugin metadata. Last writer wins."""
```

Mirrors `model_to_provider_map()` exactly. Any model not in the map keeps its original spelling.

### Proposed alias seed values

These are starting points — easy to tune in code review. The criterion is "short, unambiguous within the provider,
recognizable to someone who knows the long name":

| Provider | Long name                   | Short alias                  |
| -------- | --------------------------- | ---------------------------- |
| Gemini   | `gemini-3-flash-preview`    | `flash3`                     |
| Gemini   | `gemini-3.1-pro-preview`    | `pro31`                      |
| Gemini   | `gemini-3.1-pro`            | `pro31`                      |
| Gemini   | `gemini-2.5-flash`          | `flash25`                    |
| Gemini   | `gemini-2.5-pro`            | `pro25`                      |
| Gemini   | `gemini-2.0-flash`          | `flash20`                    |
| Codex    | `codex-mini-latest`         | `mini`                       |
| Codex    | `gpt-5.3-codex`             | `gpt53`                      |
| Codex    | `gpt-5.5`                   | `gpt55`                      |
| Codex    | `gpt-5.4`                   | `gpt54`                      |
| Codex    | `gpt-4.1`                   | `gpt41`                      |
| Codex    | `gpt-4.1-mini`              | `gpt41m`                     |
| Codex    | `gpt-4o`                    | (unchanged — already short)  |
| Codex    | `gpt-4o-mini`               | `gpt4om`                     |
| Codex    | `o3`                        | (unchanged)                  |
| Codex    | `o4-mini`                   | (unchanged)                  |
| Claude   | `opus` / `sonnet` / `haiku` | (no aliases — already short) |

(Note: `gemini-3.1-pro` and `gemini-3.1-pro-preview` collapse to the same `pro31`. Acceptable — they're version variants
of the same line, and within a single fan-out users are unlikely to mix preview and non-preview. If they do, the alias
map is a `dict` so last-defined wins; we'd handle the collision by keeping them distinct (`pro31` / `pro31p`). The plan
defaults to keeping them distinct.)

### The substitution

In `_apply_multi_model_naming`, after computing `runtime_for` / `runtime_count`:

```python
from sase.llm_provider.registry import model_short_alias_map
aliases = model_short_alias_map()

for m in distinct_models:
    r = runtime_for[m]
    if runtime_count[r] > 1:
        short = aliases.get(m, m)
        suffix_for[m] = f"{r}-{short}"
    else:
        suffix_for[m] = r
```

That's the entire behavior change. A model not in the alias map gets its raw name, exactly as today.

### Decisions to confirm

1. **Drop the runtime prefix entirely when shortening?** I.e. `o.flash3` instead of `o.gemini-flash3`. Shorter, but
   inconsistent with the no-collision case (`o.gemini`). The base case for "one of these agents is gemini" becomes hard
   to read at a glance. **Default proposal: keep the runtime prefix.** Easy to flip to "drop runtime when alias is in
   the map" later if users prefer it.

2. **Apply aliases to the non-collision case too?** No. The non-collision case produces `<base>.<runtime>` and never
   embeds the model name. Nothing to shorten.

3. **Apply aliases to `_runtime_label_for_model`?** No. Runtime labels (`claude`, `codex`, `gemini`) are already short.

4. **Two models collapsing to the same alias** (e.g. `gemini-3.1-pro` and `gemini-3.1-pro-preview` → `pro31`). Default
   proposal: keep them distinct in the seed map (`pro31` / `pro31p`). If a future model collision sneaks in,
   `_apply_multi_model_naming` would silently collide on agent names — worth a single-line guard that detects collision
   after substitution and falls back to raw model names for that fan-out. Cheap insurance.

### Files touched

- `src/sase/llm_provider/_hookspec.py` — add `llm_model_short_aliases` hookspec.
- `src/sase/llm_provider/registry.py` — add `model_short_alias_map()`.
- `src/sase/llm_provider/{claude,codex,gemini}.py` — add `llm_model_short_aliases` impl on each.
- `src/sase/xprompt/directives.py` — single substitution in `_apply_multi_model_naming` (and a one-line collision
  guard).
- `tests/test_directives_helpers.py` — see below.
- `tests/test_llm_provider_core.py` — small test for `model_short_alias_map`.
- `docs/xprompt.md` — one-line note in the multi-model section that long model names get aliased.

## Test plan

In `tests/test_directives_helpers.py`:

- `%m:gemini-3-flash-preview,gemini-2.5-flash` + `%n:o` → `o.gemini-flash3` and `o.gemini-flash25`.
- `%m:opus,sonnet` + `%n:o` → unchanged (`o.claude-opus` / `o.claude-sonnet`) — regression guard for Claude.
- `%m:opus,gpt-5.5` + `%n:o` → unchanged (`o.claude` / `o.codex`) — non-collision regression guard.
- `%m:gemini-3-flash-preview,unknown_xyz` + `%n:o` (unknown maps to gemini default) → known model uses alias, unknown
  passes through (`o.gemini-flash3` / `o.gemini-unknown_xyz`).
- Collision-after-aliasing fallback (only if we add the guard): two models with hand-rigged aliases that collide → fall
  back to raw names for that fan-out.

In `tests/test_llm_provider_core.py`:

- `model_short_alias_map()` returns the union of plugin-supplied dicts with the expected gemini entries present.

## Out of scope

- Changing how the _base_ name is generated (`get_next_auto_name`) or how single-model names work.
- Configurable per-user alias overrides — can be a follow-up if anyone asks. Today's plugin hook is enough.
- Abbreviating the runtime label itself (`claude` → `cl`). Not requested and would hurt readability.
- Re-running the alias logic on already-spawned agents (no rename UI exists).
