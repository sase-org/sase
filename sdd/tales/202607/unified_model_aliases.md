---
create_time: 2026-07-03 11:46:31
status: wip
prompt: sdd/prompts/202607/unified_model_aliases.md
---
# Plan: Unified `model_aliases` Config Field + Always-Visible Alias Descriptions

## Problem

Commit `72c62642a` ("feat: Add support for custom model aliases") introduced a second top-level config map,
`llm_provider.custom_model_aliases`, alongside the existing flat `llm_provider.model_aliases`. This has two problems:

1. **Awkward schema.** Two sibling top-level fields (`model_aliases` for builtin-role overrides, `custom_model_aliases`
   for described user aliases) should instead be one `model_aliases` field with two subfields: `builtin` and `custom`.
2. **The `d` (Describe) keymap is unnecessary.** The Models panel already renders a description strip below the alias
   list, and every custom alias is _required_ by the schema to carry a description. The description for the currently
   selected alias (builtin or custom) should simply always be shown in the panel; there is no need for a TUI flow that
   writes descriptions (`d` today opens an input modal that writes `custom_model_aliases.<name>.description` or migrates
   a legacy flat user alias). Descriptions become config-file-managed, display-only in the TUI.

## Target Config Shape

```yaml
llm_provider:
  model_aliases:
    builtin: # overrides for implicit role aliases only
      default: opus
      coder: "@default"
      claude_coder: gpt-5.5
    custom: # user-defined aliases; description required
      blogger:
        model: claude/opus
        description: "Agents that draft and edit blog posts."
```

- `builtin`: string map (bare model, `provider/model`, nested provider-local path, or `@<alias>` reference) — exactly
  the value grammar of today's flat `model_aliases`.
- `custom`: map of alias name → object with required `model` (minLength 1) and `description` (minLength 1,
  maxLength 160) — exactly the value shape of today's `custom_model_aliases`.
- Merge/precedence semantics are unchanged: `custom` wins name collisions with `builtin`; custom aliases shadow implicit
  specials of the same name.

## Key Design Decisions

1. **Clean break, no runtime compat shim.** The schema makes `model_aliases` an object with only `builtin`/`custom`
   properties (`additionalProperties: false`) and drops top-level `custom_model_aliases` entirely. The runtime readers
   stay defensive (unrecognized shapes are ignored, never crash a launch), but legacy flat entries and
   `custom_model_aliases` entries stop resolving. Migration is driven by `sase doctor -C config.model_aliases`, which
   gains precise per-key guidance (see below). Rationale: the `custom_model_aliases` field shipped today and has no real
   installs; the flat `model_aliases` map migrates with a one-line indent under `builtin:`. The generic config-inventory
   diagnostics also flag the removed `custom_model_aliases` key as unsupported automatically once it leaves the schema.
2. **Descriptions are display-only in the TUI.** Remove the `d` keymap, its action, callbacks, and the
   `alias_description_edit` helper. The always-visible description strip (already present) remains the single surface. A
   user alias that somehow lacks a description (malformed custom entry, or a user-named key parked in `builtin`) shows
   an inline hint naming the config path to fix (`llm_provider.model_aliases.custom.<name>.description`) instead of
   "press d".
3. **No Rust-core changes.** The Rust config-edit planner, field model, and inventory are all driven by the bundled
   `src/sase/config/sase.schema.json`; dotted edit paths like `llm_provider.model_aliases.custom.<name>.model` work
   through the existing generic machinery. Alias policy/resolution already lives in Python in this repo and does not
   move.
4. **Config-source vocabulary becomes `"builtin" | "custom"`.** The `ModelAliasConfigSource` literal (and every consumer
   comparing against `"model_aliases"`/`"custom_model_aliases"`) switches to the new subfield names, which also reads
   better in AliasView provenance and tests.

## Implementation

### Phase 1 — Config layer (`src/sase/llm_provider/`)

- `config.py`:
  - Read the nested map: `get_builtin_model_aliases()` (renamed from `get_legacy_model_aliases()`) reads
    `llm_provider.model_aliases.builtin`; `get_custom_model_aliases()` and `_custom_model_alias_descriptions()` read
    `llm_provider.model_aliases.custom`. All keep the current defensive parsing (skip non-dict/blank entries).
  - `ModelAliasConfigSource = Literal["builtin", "custom"]`; `model_alias_config_source()` returns the new values.
  - Update the module-level alias-policy comment block and docstrings that name the old fields.
- `__init__.py`: update re-exports (`get_builtin_model_aliases` replaces `get_legacy_model_aliases`).
- `alias_view.py`: docstring updates only (`configured_source` now `"builtin"`/`"custom"`).
- `src/sase/xprompt/model_completion.py`: compare against `"custom"` instead of `"custom_model_aliases"`.

### Phase 2 — Schema + default config

- `src/sase/config/sase.schema.json`: replace the flat `model_aliases` string map and the top-level
  `custom_model_aliases` block with the nested object described above (`additionalProperties: false` on `model_aliases`;
  `builtin` = string map; `custom` = object map with required `model`/`description`). Refresh both `description`
  strings.
- `src/sase/default_config.yml`: rewrite the commented `model_aliases` example to the nested `builtin:`/`custom:` form
  (fold the current `custom_model_aliases` example under `custom:`).

### Phase 3 — Models panel (`src/sase/ace/tui/modals/`)

- `models_panel.py`:
  - Remove the `("d", "describe", ...)` binding, `d=Describe` footer entry, `action_describe`, `_pending_describe_view`,
    `_on_description_picked`, and `_configured_or_effective_target` (describe-only helper).
  - `_description_text_for_view`: keep always-on rendering; replace the "press d to describe" missing-description hint
    with config-path guidance (`no description — set llm_provider.model_aliases.custom.<name>.description`).
  - Update `configured_source` comparisons (`"custom_model_aliases"` → `"custom"`) in the Edit / Reset actions and the
    module docstring.
- `models_panel_edit_helpers.py`:
  - Field prefixes become `llm_provider.model_aliases.builtin` and `llm_provider.model_aliases.custom`;
    `alias_model_edit_path` / `alias_reset_path` route user aliases with `configured_source == "custom"` to
    `...custom.<name>.model` / `...custom.<name>` (reset still deletes the whole custom entry) and everything else to
    `...builtin.<name>`.
  - Delete `alias_description_edit` and its export.
- `custom_model_input_modal.py`: drop the `initial_value`/`empty_message` parameters if the describe flow was their only
  caller (verify before removing).
- Verify no help-modal/keybinding-footer content references the Models panel `d` key (none found in exploration; the
  panel documents keys in its own footer).

### Phase 4 — Doctor (`src/sase/doctor/checks_config.py`)

Rework `_check_config_model_aliases` for the nested shape while keeping the check id (`config.model_aliases`) and the
existing `worker_models`/`default_model` checks:

- **New:** flag any non-`builtin`/`custom` key directly under `llm_provider.model_aliases` (legacy flat entry) —
  guidance depends on the alias kind: builtin-kind names move under `builtin:`, user-kind names move under `custom:`
  with a description.
- **New:** flag a still-present top-level `llm_provider.custom_model_aliases` key — entries move to
  `llm_provider.model_aliases.custom`.
- **Re-key existing checks** to the new paths: user-kind names inside `builtin`, builtin-kind names inside `custom`,
  names present in both maps, custom entries missing/blank `model` or `description`, non-map `custom` value, and
  `@`-reference checks (retired `@worker`/`@other`, unknown aliases) with `model_aliases.builtin.<name>` /
  `model_aliases.custom.<name>.model` keys.

### Phase 5 — Tests

- Update unit tests for the new field names/paths/source literals: `tests/llm_provider/test_config_aliases.py`,
  `tests/llm_provider/test_alias_view.py`, `tests/test_models_panel.py`, `tests/test_models_panel_edit.py`,
  `tests/test_models_panel_edit_helpers.py`, `tests/doctor/test_checks_config.py`,
  `tests/test_xprompt_model_completion.py`.
- `tests/test_config_schema.py`: nested-shape acceptance tests (builtin string map with `@` references; described custom
  entries), rejection tests (flat string entry under `model_aliases`, top-level `custom_model_aliases`, custom entry
  missing `model`/`description`).
- Remove describe-flow tests; add coverage that the description strip renders builtin and custom descriptions and the
  new missing-description hint.
- Visual snapshots: update fixture `configured_source` values in
  `tests/ace/tui/visual/test_ace_png_snapshots_models_panel.py` and regenerate the two Models-panel PNG goldens
  (`just test-visual` with `--sase-update-visual-snapshots`) since the footer loses `d=Describe` and hint text changes.

### Phase 6 — Docs

- `docs/llms.md`: nested config examples and field tables (`llm_provider.model_aliases.builtin` / `.custom`),
  doctor-guidance paragraph, remove both "press `d`" references.
- `docs/configuration.md`: same example/table updates.
- `docs/ace.md` (Models panel section): drop the `d` keymap row and describe example; update the description-strip
  paragraph and the persistent-edit path descriptions to the new dotted paths.

## Verification

- `just install && just check` (lint + mypy + tests, includes the visual suite).
- Manual TUI pass: open `,m`; confirm the description strip tracks the highlighted alias for builtin and custom rows,
  `d` does nothing, and `e`/`r` on a custom alias preview writes against `llm_provider.model_aliases.custom.<name>`
  while builtin overrides target `llm_provider.model_aliases.builtin.<name>`.
- `sase doctor -C config.model_aliases` against a config using the old flat/`custom_model_aliases` shapes reports the
  new migration guidance.

## Rollout Note (post-merge, outside this repo)

The live user config (`~/.config/sase/sase.yml`, chezmoi-managed) still uses the flat `model_aliases:` map; after this
lands its entries must be indented under `model_aliases.builtin:` (one-line migration). Until then those overrides stop
applying and doctor will flag them.
