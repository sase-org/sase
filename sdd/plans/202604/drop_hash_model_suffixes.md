---
create_time: 2026-04-28 18:04:35
status: done
prompt: sdd/prompts/202604/drop_hash_model_suffixes.md
---
# Drop `#` From Model Shorthand Agent Suffixes

## Goal

Multi-model agent names should not expose xprompt shorthand syntax in the model-disambiguation suffix.

Current bad case from `sase ace`:

```text
%n:ag
%m(#flash,#pro)
```

can produce names like:

```text
ag.gem-#flash
ag.gem-#pro
```

even though the launched agents correctly run resolved models such as `gemini-3-flash-preview`. The desired names are
based on the resolved model labels:

```text
ag.gem-flash3
ag.gem-pro31p   # or the configured alias for the resolved pro model
```

This is not a provider-short-name problem. Provider labels are already `cld`, `gem`, `cdx`, and `jet`. The `#` leaks
because same-runtime disambiguation currently uses the raw `%model` argument before directive-argument xprompt
expansion.

## Current Behavior

The relevant code path is `src/sase/xprompt/_directive_alt.py`.

1. `split_prompt_for_models()` rewrites `%m(a,b)` into `%alt(%model:a,%model:b)` and splits it into sub-prompts.
2. `_apply_multi_model_naming()` extracts the first `%model` value from each sub-prompt.
3. `_runtime_label_for_model()` resolves the provider/runtime label.
4. If two variants share the same runtime, `_apply_multi_model_naming()` appends the model value or
   `model_short_alias_map()` result:

   ```python
   suffix_for[m] = f"{runtime}-{aliases.get(m, m)}"
   ```

For `%m(#flash,#pro)`, the extracted model values are raw `#flash` and `#pro`. The downstream runner later calls
`extract_prompt_directives()`, which expands xprompt references in directive arguments, so execution metadata is
correct. The naming pass just runs too early to see that resolved value.

## Design

Add a naming-only normalization step for model directive values. It should resolve xprompt shorthand references for the
purpose of provider resolution and suffix alias lookup, while preserving the original `%model:<raw>` directive in the
spawned prompt so the existing directive extraction pipeline remains the source of truth for execution.

Conceptually:

```python
raw_model = "#flash"
label_model = "gemini-3-flash-preview"
emitted_directive = "%model:#flash"
agent_name_suffix = "gem-flash3"
```

### Helper

Add a small private helper in `_directive_alt.py`, for example:

```python
def _model_value_for_naming(
    model: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> str:
    ...
```

Behavior:

- If the model string contains no `#`, return it unchanged.
- If it contains `#`, call `process_xprompt_references(model, extra_xprompts=extra_xprompts or None).strip()`.
- If expansion does not change the string because the shorthand is unknown, return the raw string unchanged for provider
  resolution, but use a display fallback that strips one leading `#` only when building the final disambiguator. This
  gives a graceful `gem-flash` instead of `gem-#flash` for unknown shorthand while still preserving the raw
  `%model:#...` directive.
- Do not expand the whole prompt from inside the naming helper; only expand the model argument token. Full prompt
  expansion can trigger unrelated workflow behavior and belongs to the normal preprocessing pipeline.

### Pass Local XPrompts

`split_prompt_for_models()` currently has no way to see frontmatter-local xprompts when it is called on raw segments.
Extend its public signature with an optional keyword-only argument:

```python
def split_prompt_for_models(
    prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> list[str] | None:
```

Use the argument only for naming/model-argument normalization. Existing callers remain compatible because the default is
`None`.

Update the two launcher paths that already know about local xprompts:

- `src/sase/agent/multi_prompt_launcher.py`
  - Pass `segment_local_xprompts` to the first raw `split_prompt_for_models(segment, ...)` call.
  - The fallback call on a fully expanded segment can omit `extra_xprompts` because expansion has already happened, but
    passing it is harmless and consistent.
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`
  - Pass `local_xprompts` to the raw `split_prompt_for_models(dispatch_prompt, ...)` call.
  - The fallback call on `expanded_prompt` can also pass it for consistency.

The lower-level `src/sase/agent/launcher.py` path has no local frontmatter context at the point it checks a single raw
query, so it can continue to call the default signature. Global/config xprompts still resolve through
`process_xprompt_references()`.

### Dedupe With Resolved Model Values

When collecting `%model` arguments in `split_prompt_for_models()`, dedupe using the normalized naming value rather than
the raw argument. Preserve the first raw argument for emitted directives.

This avoids launching duplicates for cases like:

```text
%m(#flash,gemini-3-flash-preview)
```

where both entries resolve to the same concrete model. This mirrors the current "single unique model returns `None`"
contract, but makes "unique" mean unique after model-ref expansion.

### Naming With Resolved Model Values

In `_apply_multi_model_naming()`:

- Keep `models_per_sub` as the raw values extracted from each sub-prompt.
- Build `label_models_per_sub` using `_model_value_for_naming()`.
- Compute `distinct_models`, runtime labels, collision counts, and `model_short_alias_map()` lookups from the label
  models.
- Inject the name suffix chosen from the label model, while leaving the stripped prompt body unchanged.

Result examples:

```text
%n:ag
%m(#flash,#pro)
```

becomes:

```text
%name:ag.gem-flash3
%model:#flash
...

%name:ag.gem-pro31p
%model:#pro
...
```

The agent subprocess then expands `%model:#flash` through the existing directive parser and runs the same concrete model
as before.

## Tests

Add focused coverage to `tests/test_directives_split_models.py`.

1. Global/config shorthand naming:
   - Patch or provide xprompt expansion so `#flash` resolves to `gemini-3-flash-preview`.
   - Assert `%model:#flash` remains in the prompt.
   - Assert `%name:<base>.gem-flash3`, not `%name:<base>.gem-#flash`.

2. Same-runtime pair:
   - `#flash` plus `#pro` should produce two `gem-*` suffixes using resolved aliases.

3. Mixed raw and shorthand duplicate:
   - `%m(#flash,gemini-3-flash-preview)` should be treated as a single unique model and return `None`, or otherwise not
     fan out into duplicate agents.

4. Local xprompt support:
   - Add or extend a launcher-level test in `tests/test_multi_prompt_launcher.py` using frontmatter/local xprompts.
   - Verify the prompt passed to `spawn_agent_subprocess()` keeps `%model:#flash` but the name prefix is resolved.

5. Unknown shorthand fallback:
   - If `#unknown_model_alias` does not resolve, assert the generated name does not contain `#`.
   - Preserve the raw `%model:#unknown_model_alias` directive so downstream behavior is unchanged.

Run the targeted tests first:

```bash
just test tests/test_directives_split_models.py tests/test_multi_prompt_launcher.py
```

Then run the repo check:

```bash
just install
just check
```

`just install` matters in this workspace because `.sase` workspaces can have stale editable installs.

## Docs

Update `docs/xprompt.md` in the multi-model naming section:

- Mention that model arguments used for naming are resolved through xprompt shorthand expansion.
- Add a short example:

  ```text
  %n:ag %m(#flash,#pro) -> ag.gem-flash3 / ag.gem-pro31p
  ```

No provider hook docs need to change for this fix because `llm_provider_short_name` is already doing the right thing.

## Out Of Scope

- Renaming persisted historical agents already written to `agent_meta.json` or `done.json`. Existing rows like
  `@ag.gem-#flash` will remain historical artifacts; newly launched agents should get the cleaned names.
- Changing provider short names (`gem`, `cld`, `cdx`, `jet`).
- Changing model alias definitions unless a missing built-in alias is discovered while testing.
- Changing execution-time model expansion. The existing directive extraction path should remain authoritative.

## Risks

- `process_xprompt_references()` can load user/config xprompts. Keep calls limited to strings containing `#`, and only
  for model argument tokens, to avoid unnecessary work.
- Local xprompts require explicit plumbing. If a caller has no local-xprompt context, the behavior is still no worse
  than today.
- Direct `%alt(%model:#flash,%model:gemini-3-flash-preview)` will still be treated as an explicit alt split. That is
  acceptable because `%alt` is a generic user-requested fan-out mechanism; the duplicate-dedupe behavior should be
  limited to `%m(...)`/multi-model collection.
