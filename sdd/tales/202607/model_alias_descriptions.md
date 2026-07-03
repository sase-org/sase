---
create_time: 2026-07-03 06:37:21
status: wip
prompt: sdd/prompts/202607/model_alias_descriptions.md
---
# Model Alias Descriptions on the Models Panel

## Summary

Show a description for the currently highlighted model alias on the ace **Models** panel (leader `,m`), explaining what
that alias is used for. Builtin aliases (`default`, `coder`, `<provider>_coder`, `epic_creator`, `epic_lander`,
`phase_worker`) get fixed, code-owned descriptions. Custom (user-defined) aliases get their description from a new
config field — and the config schema is restructured so a description is _required_ for custom aliases but never needed
for builtin ones.

## Design Decisions

### 1. Config schema: split builtin overrides from custom aliases

Today `llm_provider.model_aliases` is one flat `name -> target` string map that mixes two very different things:
overrides for SASE's builtin role aliases, and user-invented custom aliases. A `description` requirement that applies to
only one of those two cannot be expressed in one homogeneous map, so we split the config surface:

```yaml
llm_provider:
  # UNCHANGED shape: overrides for SASE's builtin aliases only.
  model_aliases:
    coder: "@default"
    claude_coder: gpt-5.5
    codex_coder: claude/opus

  # NEW: user-defined custom aliases. `description` is REQUIRED.
  custom_model_aliases:
    blogger:
      model: claude/opus
      description: "Agents that draft and edit blog posts (used by my #blog xprompts)."
```

- `model_aliases` keeps its exact current shape (`additionalProperties: {type: string}`) — zero migration for builtin
  overrides, which is all most configs (including Bryan's) contain. Its schema `description` text is updated to say it
  is for builtin alias overrides only and to point custom aliases at the new field.
- `custom_model_aliases` values are objects with `additionalProperties: false`, `required: ["model", "description"]`,
  `model: {type: string, minLength: 1}` and `description: {type: string, minLength: 1, maxLength: 160}`. The 160-char
  cap guarantees a description always fits the panel's 2-line description strip (2 × 78 content columns).

Why not enforce "`model_aliases` keys must be builtin names" in JSON Schema: the builtin set includes one
`<provider>_coder` alias per _dynamically registered_ provider, so it is not statically enumerable — and the Rust config
validator (draft-07 subset in `sase-core`'s `config/validate.rs`) deliberately has no `patternProperties`. That rule is
enforced at runtime by the existing `config.model_aliases` doctor check instead (see below).

**No Rust core changes are required.** Verified against the sase-core config module: the schema JSON is bundled in this
repo (`src/sase/config/sase.schema.json`) and passed verbatim to the schema-generic Rust planner/validator, which
already supports `required`, object-valued `additionalProperties`, and `minLength`/`maxLength`. The write planner
(`plan_edit` → `set_at_path`/`unset_at_path`) and the Python surgical YAML writer (`sase/config/_edit_yaml.py`) are both
depth-generic, so `llm_provider.custom_model_aliases.<name>.model` edits work today. Alias _policy_ (resolution, kinds,
and now descriptions) already lives in Python in this repo (`src/sase/llm_provider/config.py`), so the new policy stays
there — consistent with the current boundary.

### 2. Collision + precedence semantics (keep resolution reliable)

- `get_model_aliases()` (the merged map every consumer uses — resolution, `%model` completion, alias-view provenance,
  default-model checks in `registry.py`/`_invoke.py`) becomes: legacy `model_aliases` entries overlaid by
  `custom_model_aliases` entries (`name -> model`). **Custom wins on collision.** This makes the new field authoritative
  for user aliases and enables a clean one-write migration path (see the `d` keymap below).
- Runtime parsing of `custom_model_aliases` is defensive: malformed entries (missing/blank `model`) are skipped and a
  missing `description` degrades to "no description" — a bad config must never crash alias resolution or a launch.
  Schema validation (editor LSP + config-edit preview) and doctor are where strictness lives.
- The `config.model_aliases` doctor check gains new actionable warnings:
  - a non-builtin key in `model_aliases` → "migrate to `custom_model_aliases` (with a description)";
  - a builtin name in `custom_model_aliases` → "move to `model_aliases`";
  - a name present in both fields → "remove the legacy `model_aliases` entry (custom wins)";
  - a `custom_model_aliases` entry with a missing/blank `description` or `model`;
  - the existing dangling-`@ref` validation naturally covers custom targets via the merged map.

### 3. Where descriptions come from

New policy helper in `src/sase/llm_provider/config.py` — `model_alias_description(name) -> str | None`:

- **Builtin aliases** return fixed, code-owned strings (no config needed), mirroring the semantics already documented in
  `default_config.yml`:
  - `default`: "Model used when a prompt has no %model directive; every other alias ultimately falls back to it."
  - `coder`: "Coder follow-up agents launched from plans (fallback for every <provider>_coder alias)."
  - `<provider>_coder`: "Coder follow-up agents for plans authored by <provider>." (provider name derived from the alias
    name)
  - `epic_creator`: "Agents that create epics from #bd/new_epic follow-ups."
  - `epic_lander`: "Epic land agents that finalize and submit an epic."
  - `phase_worker`: "Bead phase agents that implement individual plan phases."
- **User aliases** return the configured `custom_model_aliases.<name>.description`, or `None` when absent (legacy entry
  still living in `model_aliases`).

`AliasView` (`src/sase/llm_provider/alias_view.py`) gains a `description: str | None = None` field populated by
`build_alias_views()`. The default value keeps every existing constructor call site (including the visual snapshot
tests' `_view()` helper) working unchanged.

### 4. Models panel UI: a description strip (the beautiful part)

Add a fixed-height, two-line **description strip** between the alias list and the keymap footer:

```
┌───────────────────────────── Models ─────────────────────────────┐
│ default       default          CLAUDE(opus)          implicit    │
│ role          coder            CLAUDE(opus)   implicit → @default│
│ user          blogger          CLAUDE(opus)          configured  │
│ ──────────────────────────────────────────────────────────────── │
│ Agents that draft and edit blog posts (used by my #blog          │
│ xprompts).                                                       │
│ ──────────────────────────────────────────────────────────────── │
│ o=Override  x=Clear  e=Edit  d=Describe  r=Reset  j/k  esc       │
└───────────────────────────────────────────────────────────────────┘
```

- A `Static` (`#models-panel-description`) with **fixed `height: 2`**, muted italic styling, and a subtle
  `border-top: solid $secondary` separating it from the list. Fixed height means zero layout shift while navigating —
  the list never jumps as descriptions change length.
- Content updates from the `OptionList.OptionHighlighted` handler, plus once on mount and after `_refresh_rows()`. The
  lookup is pure in-memory (`AliasView.description` on the already-built views dict) — this respects the TUI perf rules:
  highlight paints immediately, no disk IO in the handler, and the update is cheap + idempotent so the
  `OptionHighlighted` echo emitted by programmatic `highlighted =` assignments is harmless.
- A user alias with **no** configured description (legacy `model_aliases` entry) renders a dim warning-toned hint
  instead: `no description — press d to describe (writes llm_provider.custom_model_aliases.<name>)`. This makes the
  migration path discoverable exactly where the gap is felt.
- Builtin descriptions render in the normal muted italic; no visual noise distinguishing builtin vs custom is needed —
  the existing kind badge already covers that.
- CSS budget: `#models-panel-container` is `width: 84; max-height: 30` with the list capped at 22. The strip adds 3 rows
  (border + 2 lines), so bump the container `max-height` to 33 and keep the list cap at 22 (rows only shrink when the
  terminal itself is short, in which case the list scrolls — never the strip).

### 5. Persistent-edit flows follow the field split

`plan_alias_edit()` (`src/sase/ace/tui/modals/models_panel_edit_helpers.py`) becomes field-aware based on the alias's
kind and where it is currently configured:

- **Builtin alias** (default/role/provider_coder kinds) — unchanged: Edit sets / Reset unsets
  `llm_provider.model_aliases.<name>`.
- **User alias configured under `custom_model_aliases`** — Edit sets `llm_provider.custom_model_aliases.<name>.model`;
  Reset unsets the whole `llm_provider.custom_model_aliases.<name>` entry (for a user alias, reset means "delete the
  alias").
- **User alias still in legacy `model_aliases`** — Edit/Reset keep targeting the legacy key (predictable: an Edit never
  silently restructures config), while doctor + the panel's "no description" hint drive migration.

New **`d` (Describe)** binding on the panel:

- On a **user alias**: opens a one-line description input (prefilled with the current description when one exists) and
  routes the write through the existing `AliasEditPreviewModal` plan → diff preview → confirm → write → chezmoi-apply →
  commit+push-offer pipeline. For an alias already under `custom_model_aliases` it sets
  `...custom_model_aliases.<name>.description`; for a legacy alias it sets the whole `...custom_model_aliases.<name>`
  entry to `{model: <current target>, description: <input>}` in one write — a self-serve migration (the now-shadowed
  legacy key is flagged by doctor for cleanup). `ConfigEditOp.value` is `Any` end-to-end (serde `Value` on the Rust
  side), so the object write already round-trips.
- On a **builtin alias**: a gentle notify — "builtin alias descriptions are fixed" — no modal.
- Whole-config validation at plan time is a free guardrail here: the Rust validator checks the _candidate merged
  config_, so any write that would produce a custom entry without a description is rejected in the preview modal before
  a byte hits disk.

The panel footer (`_footer_markup`) and the help-modal documentation of Models-panel bindings are updated for `d` (per
the ace help-popup maintenance rule).

### 6. `%model` completion polish (small, free win)

`src/sase/xprompt/model_completion.py` already gives user-alias completion entries a description channel
(`"alias for {target}"`). When a configured description exists, surface it: `"<description> (alias for <target>)"`,
falling back to the current text. This makes `#m`-style completion self-documenting with zero new UI.

## Phases

### Phase 1 — Config schema + alias policy layer

- `src/sase/config/sase.schema.json`: add `llm_provider.custom_model_aliases` (object values,
  `required: [model, description]`, `additionalProperties: false`, `minLength`/`maxLength` as above); reword the
  `model_aliases` description to "builtin alias overrides".
- `src/sase/default_config.yml`: update the commented `model_aliases` doc block and add a commented
  `custom_model_aliases` example (schema and default-config comments must stay in sync — this repo's most common
  gotcha).
- `src/sase/llm_provider/config.py`: `get_custom_model_aliases()` (defensive parse), merge custom entries into
  `_get_model_aliases()` (custom wins on collision), `model_alias_description(name)` with the builtin description table.
- `src/sase/doctor/checks_config.py`: extend `_check_config_model_aliases()` with the four new problem classes.
- Tests: `tests/llm_provider/test_config_aliases.py` (merge/precedence/description/defensive parsing),
  `tests/test_config_schema.py` (schema shape + validation of good/bad custom entries),
  `tests/doctor/test_checks_config.py` (new warnings).

### Phase 2 — AliasView + Models panel description strip

- `src/sase/llm_provider/alias_view.py`: `AliasView.description` (default `None`), populated in `build_alias_views()`;
  export anything new from `sase/llm_provider/__init__.py`.
- `src/sase/ace/tui/modals/models_panel.py`: description strip `Static`, highlight handler, missing-description hint
  text, mount/refresh wiring.
- `src/sase/ace/tui/styles.tcss`: `#models-panel-description` (fixed height 2, muted italic, `border-top`), container
  `max-height` 30 → 33.
- Tests: `tests/test_models_panel.py` (strip content for builtin / described-custom / undescribed-custom rows,
  highlight-change updates); extend `tests/ace/tui/visual/test_ace_png_snapshots_models_panel.py` with a custom-alias
  view (with and without description) and regenerate goldens via `--sase-update-visual-snapshots`.

### Phase 3 — Field-aware edits + `d` Describe keymap

- `src/sase/ace/tui/modals/models_panel_edit_helpers.py`: route Edit/Reset paths per design decision 5 (needs the
  alias's kind + configured location — pass the `AliasView` or a small routing enum in from the panel).
- `src/sase/ace/tui/modals/models_panel.py`: `d` binding + description input modal (reuse/generalize
  `CustomModelInputModal` or add a sibling single-line input modal), builtin-alias notify, footer text.
- Help modal: document the new binding wherever the Models panel keys are documented.
- Tests: `tests/test_models_panel_edit_helpers.py` (path routing for all three cases, whole-object legacy-migration
  write), `tests/test_models_panel.py` / `tests/test_models_panel_keymaps.py` (keymap + flow), and a
  `tests/test_models_panel_edit.py` case asserting the plan-time validation rejects a description-less custom entry.

### Phase 4 — Completion polish, docs, chezmoi

- `src/sase/xprompt/model_completion.py`: prefer configured descriptions for user-alias completion entries (+
  `tests/test_xprompt_model_completion.py`).
- `docs/llms.md`: document the `model_aliases` / `custom_model_aliases` split, the required description, the doctor
  migration guidance, and the panel's description strip + `d` keymap.
- Chezmoi repo (`~/.local/share/chezmoi`, a linked repo with direct-path access): update `home/dot_config/sase/sase.yml`
  — reword the `llm_provider.model_aliases` comment block to reflect "builtin overrides only" and add a short commented
  `custom_model_aliases` example so the new field is discoverable the next time an alias is added. Bryan's config
  defines only builtin overrides today (verified across `sase.yml` and `sase_athena.yml`), so no entries need to move —
  this is a comment/documentation update, committed in the chezmoi repo.

## Verification

- `just check` in this repo after each phase; full `just test` before finishing.
- `just test-visual` for the Models-panel PNG goldens (inspect `.pytest_cache/sase-visual/` diffs; use
  `--sase-update-visual-snapshots` only for the intentional strip addition).
- Manual: `sase ace` → `,m` → j/k across builtin, described-custom, and undescribed-custom rows; `d` on a custom alias
  end-to-end (preview diff → write → chezmoi apply → commit offer); `sase doctor -C config.model_aliases` against a
  config exercising each new warning.

## Out of Scope

- Creating brand-new aliases from the Models panel (today it only edits existing rows; unchanged).
- Overriding builtin alias descriptions from config.
- Any Rust core (`sase-core`) changes — verified unnecessary (schema-generic planner/validator).
