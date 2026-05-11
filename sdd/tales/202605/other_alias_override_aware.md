---
create_time: 2026-05-11 16:05:42
status: done
prompt: sdd/prompts/202605/other_alias_override_aware.md
---
# Plan: Make the `other` Model Alias Override-Aware

## Goal

Treat the literal `"other"` model alias as a special, context-aware key. When a temporary LLM override
(`~/.sase/llm_override.json`) is active, `%model:other` (and `%m:other`) must resolve to the **(provider, model) that
was active immediately before the override was set**, not to the static target in `llm_provider.model_aliases.other`.
When no override is active, behavior is unchanged — the configured alias target wins (or `"other"` falls through as a
literal model name today).

## Why

The configured `model_aliases.other: claude/opus` works only as long as the user's normal default is sonnet — then
"other" naturally means "the alternate, opus". The moment a temporary override moves the user onto opus, every xprompt
that fans out with `%m(other, …)` launches opus _again_, side-by-side with itself, defeating the entire "pair with the
alternate model" idea. "Other" should always mean "the model I would have been using if I hadn't taken this temporary
detour."

## Current Behavior

- Aliases are a plain `dict[str, str]` from `llm_provider.model_aliases` in `~/.config/sase/sase.yml`.
- `resolve_model_alias("other")` (config.py) does a flat-with-cycle-detection lookup; `"other"` has no special status in
  code — it's only a conventional name documented in `resolve_model_provider`'s docstring.
- `resolve_model_provider("other")` calls `resolve_model_alias` first, then explicit `provider/model` syntax, then
  plugin model-to-provider map.
- `TemporaryLLMOverride` (temporary*override.py) stores the _new* override's
  `(provider, model, raw_model, created_at, expires_at, source)` — nothing about what it displaced.
- `set_temporary_override()` does not record any "before" state; once written, the file is the sole source of truth.

## Design

### 1. Capture the displaced model when the override is set

Add three optional fields to `TemporaryLLMOverride` plus the persisted JSON state:

- `pre_override_provider: str | None`
- `pre_override_model: str | None`
- `pre_override_raw_model: str | None` (cosmetic, for display/debug)

In `set_temporary_override()`:

- Call `resolve_effective_default_provider_model()` **before** writing the new state file. Because the _previous_
  override (if any) is still on disk, this returns:
  - The previous override's `(provider, model)` if one was active when this new override is being set.
  - Otherwise the configured-default provider + its `resolve_model_name(model_tier)`.
- Store that tuple as the `pre_override_*` snapshot in the new state file.

Semantics: "other" always refers to whatever was active immediately before the _current_ override. Chained overrides
each remember what they displaced; this matches the user's literal "the one that was active before the override" wording
and avoids tracking history beyond one hop.

### 2. Make `resolve_model_alias` short-circuit for `"other"` when an override is active

In `sase/llm_provider/config.py`:

- Before the existing alias-map lookup, special-case `model.strip() == "other"`:
  - Lazily import `get_active_temporary_override` from `sase.llm_provider.temporary_override` (lazy to avoid a circular
    import — config.py is imported by registry.py which is imported by temporary_override.py via `__init__.py`).
  - If an active override exists and has a non-`None` `pre_override_provider` + `pre_override_model`, return
    `f"{pre_override_provider}/{pre_override_model}"` directly.
  - Otherwise (no override, expired, or legacy state file lacking the snapshot), fall through to the existing
    config-alias resolution path.
- Returning a `"provider/model"` string slots cleanly into `resolve_model_provider`'s existing explicit-syntax branch,
  so the (provider, model) tuple is recovered without further code changes.

### 3. Backward compatibility for legacy state files

- In `_load_state`, leave the existing `required` fields unchanged. Treat `pre_override_provider`, `pre_override_model`,
  `pre_override_raw_model` as optional: read them when present and string-typed; otherwise default to `None`. A legacy
  state file (written before this change) keeps working — the override still applies, and `%model:other` simply falls
  back to the configured alias until the user resets the override.

### 4. Coverage of all `"other"` call sites is automatic

Every site we care about funnels through `resolve_model_alias` and/or `resolve_model_provider`:

- `invoke_agent` (`_invoke.py:140`) via `%model` directive
- Fan-out naming `_model_value_for_naming` (`xprompt/_directive_alt.py:418, 430, 431`) directly calls
  `resolve_model_alias`
- Query handler, axe phase runner, exec plan, prompt panel helpers, approve-options modal, provider styles, and the
  workflow executor all call `resolve_model_provider`

Special-casing `resolve_model_alias` covers all of them with no per-site changes.

## Edge Cases

- **No `model_aliases.other` configured + no override** → `%model:other` still falls through to literal `"other"`, same
  as today (resolves against plugin model-to-provider map → default provider). No regression.
- **No `model_aliases.other` configured + override active** → the new dynamic behavior still triggers, because the
  short-circuit happens before the config-map lookup. This is the desired improvement.
- **Override expires mid-session** → `get_active_temporary_override()` returns `None`, short-circuit skipped, configured
  alias (if any) wins. Correct.
- **Override is set to the same model as the displaced default** → snapshot = current model; "other" resolves to the
  same model as the override. Degenerate but coherent (and rare).
- **Override changed twice (sonnet → opus → gemini)** → snapshot for the gemini override is opus. "Other" while on
  gemini = opus. Matches the literal "before the override" reading. If the user wants sonnet back, they clear and
  re-set.
- **Legacy state file on disk** → `pre_override_*` missing; `_load_state` treats them as `None`; short-circuit declines
  to fire; configured alias fallback. The override itself continues to work.
- **`resolve_effective_default_provider_model` raises** during snapshot capture (e.g., no provider configured) → surface
  naturally; the override write is aborted, mirroring how `set_temporary_override` already raises today on invalid
  input.

## Implementation Sketch

Files touched, ordered by dependency:

1. `src/sase/llm_provider/temporary_override.py`
   - Add `pre_override_provider`, `pre_override_model`, `pre_override_raw_model` to `TemporaryLLMOverride`.
   - Loosen `_load_state` to accept missing/`None` pre-override fields (optional + type-checked when present).
   - In `set_temporary_override`, capture the snapshot via `resolve_effective_default_provider_model()` _before_
     building the new override.
2. `src/sase/llm_provider/config.py`
   - At the top of `resolve_model_alias`, special-case `model.strip() == "other"`: lazy-import
     `get_active_temporary_override`; if it returns an override with both `pre_override_provider` and
     `pre_override_model`, return `f"{pre_override_provider}/{pre_override_model}"`.
3. `src/sase/llm_provider/__init__.py` — only if any new symbol needs re-exporting (likely none; existing exports
   already cover the override dataclass).
4. Docs:
   - `docs/llms.md` and `docs/configuration.md` — document `"other"` as a reserved alias whose value is dynamically the
     model displaced by an active temporary override. Clarify that the configured `model_aliases.other` is the fallback
     target when no override is active.
   - `config/sase.schema.json` — no schema change needed (we're only adding semantics around an existing key).
5. Tests:
   - `tests/test_llm_provider_temporary_override.py` (or wherever override tests live):
     - `set_temporary_override` captures the configured default as the snapshot when no prior override exists.
     - Setting an override on top of an existing override captures the prior override's resolved (provider, model).
     - Legacy state file (manually written without pre-override fields) loads cleanly and yields a
       `TemporaryLLMOverride` with `pre_override_*` = `None`.
   - `tests/test_llm_provider_providers.py` (or alias-resolution tests):
     - `resolve_model_provider("other")` while override active returns the snapshot, even when no `model_aliases.other`
       is configured.
     - `resolve_model_provider("other")` while override active **ignores** `model_aliases.other = claude/opus` when the
       snapshot says `claude/sonnet`.
     - `resolve_model_provider("other")` after the override is cleared falls back to the configured alias.
     - Legacy override state (snapshot fields absent) falls back to the configured alias.
   - `tests/test_directives_split_models.py`:
     - Multi-agent fan-out naming for `%m(other, gpt-5.5)` while an override is active produces the suffix derived from
       the snapshot, not from the configured alias.

## Validation

- `just install` (workspace is ephemeral).
- `just check` — covers ruff, mypy, and the full pytest suite including the new cases.
- Manual sanity check: set an override via the leader-mode `,P` flow; in a fresh agent prompt include `%model:other` and
  confirm the agent name suffix + actual model match the previously-active default.

## Risks & Compatibility

- **Surface area is small.** All changes funnel through `resolve_model_alias` and the override dataclass; existing alias
  semantics for every other key are untouched.
- **Backward compatibility.** Legacy state files keep working; the only loss is the new "other" dynamism until the user
  resets the override once.
- **Special-casing a literal string.** We deliberately reserve `"other"` as a magic key. Documented in
  `resolve_model_alias`'s docstring and in `docs/llms.md` so future readers don't think it's accidental. If users
  configure `model_aliases.other`, that target remains the fallback when no override is active — the special-case is
  strictly additive, not destructive.
- **Cycle risk in `resolve_model_alias`.** The short-circuit returns a concrete `"provider/model"` string and doesn't
  recurse through the alias map, so it can't create new cycles.
- **No schema/config migration required.** Users get the new behavior the next time they set a temporary override.
