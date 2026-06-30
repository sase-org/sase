---
create_time: 2026-06-30 13:59:25
bead_id: sase-5e
tier: epic
status: done
prompt: sdd/prompts/202606/models_panel.md
---
# Plan: "Models" Panel — unified model-alias viewing, editing & temporary overrides

## Summary

Migrate the single-purpose **Model Override** panel (leader-mode `,m`, today `TemporaryLLMOverrideModal`) into a
general-purpose **Models** panel that lets the user view and manage _all_ configured model aliases from one beautiful,
keyboard-driven surface.

The new panel does three things for **every** alias (the implicit role aliases `default` / `coder` / `<provider>_coder`
/ `epic_creator` / `epic_lander` / `phase_worker`, plus any user-defined `llm_provider.model_aliases` entry):

1. **View** its effective target, provenance (configured vs. implicit), and any active temporary override.
2. **Edit** its persistent value in `sase.yml` — written through the existing Rust-backed, source-preserving,
   chezmoi-aware config-edit path, then **committed and pushed** after a `y/n` confirmation (honoring
   `use_chezmoi: true`).
3. **Temporarily override** it for a user-specified duration — the same set/change/clear + duration-picker flow used
   today for the default, now generalized to any alias.

The `default` override keeps its current behavior and its current TUI illustration (the gold top-bar pill). Overrides on
any _other_ alias are surfaced through a new, concise, **uniform** top-bar indicator so the user can always see at a
glance that non-default overrides are in effect, with full detail available in the Models panel.

## Goals

- One panel (`,m`) to view/manage all model aliases — persistent config and temporary overrides — for both implicit role
  aliases and user-defined ones.
- Persistent alias edits are written safely (Rust-planned, source-preserving) and **committed + pushed after a `y/n`
  confirm**, with first-class `use_chezmoi: true` support (write to the chezmoi source, commit/push the chezmoi repo,
  then `chezmoi apply`).
- Temporary, time-bound overrides work for **any** alias, reusing the existing model-picker + duration-picker +
  override-state interfaces.
- The `default` override is unchanged in behavior and in how it is shown today.
- Non-default overrides get a distinct, concise, uniform TUI representation.
- The result is intuitive, reliable, and visually polished — consistent with the existing provider-themed badge / pill
  design language.

## Non-goals

- No change to alias _resolution semantics_ for the `default` lane (explicit `@default` still means "the configured
  default," and the no-`%model` launch default still applies the default override exactly as today).
- No new alias _kinds_ or changes to the role-alias model shipped by epic `sase-5d`.
- Not moving the temporary-override runtime state into the Rust core (see "Rust core boundary" below) — out of scope;
  called out as a future option.

## Background — current state

- **`,m` → `TemporaryLLMOverrideModal`** (`src/sase/ace/tui/modals/temporary_llm_override_modal.py`) sets/changes/clears
  a _single, global_ override of the **default** model. It reuses `ModelPickerModal`, `CustomModelInputModal`, and a
  duration picker (`DurationChoiceModal`). Leader key declared in `src/sase/default_config.yml`
  (`temporary_llm_override: "m"`) and `src/sase/ace/tui/keymaps/types.py`.
- **Temporary override state** lives in `~/.sase/llm_override.json` and is owned by
  `src/sase/llm_provider/temporary_override.py`. It stores one `TemporaryLLMOverride` (provider, model, raw_model,
  created_at, expires_at, source), parses durations (`15m`, `1h30m`, `until cleared`), self-cleans on expiry, and feeds
  `resolve_effective_default_provider_model()`.
- **Model aliases** are configured under `llm_provider.model_aliases` and resolved by `resolve_model_alias()` in
  `src/sase/llm_provider/config.py`. Implicit specials (`default`, `coder`, `<provider>_coder`, `epic_creator`,
  `epic_lander`, `phase_worker`) always resolve via `_ROLE_ALIAS_FALLBACKS`. `model_alias_names()` returns the union of
  configured + implicit names.
- **Config editing** is already solved: `src/sase/config/edit.py` (`plan_config_edit` / `apply_config_edit`) plans a
  Rust-backed, source-preserving YAML edit with chezmoi remapping (`src/sase/config/targets.py`), and `apply_chezmoi()`
  propagates it. The Config Center modal (`src/sase/ace/tui/modals/config_edit_modal.py`) is a working reference for the
  edit→preview→write flow.
- **Commit + push** already exists for xprompt saves: `run_git_commit_push_sync()` in
  `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt_git.py` does add→commit→pull→push and, when
  `use_chezmoi`, `chezmoi apply`. `deploy_to_chezmoi()` (`src/sase/main/_init_chezmoi_deploy.py`) is the richer variant.
  `get_git_root()` / `has_git_changes()` live in `src/sase/ace/tui/modals/xprompt_browser_helpers.py`.
- **Confirmation UI**: `ConfirmActionModal` (`src/sase/ace/tui/modals/confirm_action_modal.py`, on `ConfirmDialog`) is
  the canonical `y/n` panel (`y`/`n`/`esc`, custom labels, subject text).
- **TUI illustration of the default override**: `LLMOverrideIndicator`
  (`src/sase/ace/tui/widgets/llm_override_indicator.py`) renders a gold pill `Override PROVIDER(model) 1h2m` when
  active, dim-cyan default otherwise, in the top bar (`src/sase/ace/tui/app.py`).
- **Reusable rendering**: `provider_model_badge_markup()` (`src/sase/ace/tui/provider_styles.py`) and
  `append_model_field()` (`src/sase/llm_provider/model_label.py`) give consistent provider theming.

## Design overview

### The Models panel

A new modal `ModelsPanel` (built on `OptionListNavigationMixin, ModalScreen[...]`, matching `ModelPickerModal`'s
patterns) replaces the `,m` action. It shows a scrollable, vim-navigable list of **alias rows**. Each row renders,
uniformly:

- the **alias name** with a small **kind badge** (`default` / `role` / `<provider> coder` / `user`);
- the **effective target** as a provider-themed badge (`provider_model_badge_markup`), e.g. `CLAUDE(opus)`;
- a compact **provenance / state tag** — `configured`, `implicit → @default`, or, when a temporary override is active,
  an `override · 15m left` chip in the same uniform style used by the new non-default indicator.

Per selected alias, single-key actions (final letters chosen in the UI phase, shown in the footer + help):

- **Override** → set/change a temporary override (model picker → duration picker), via the generalized override API.
- **Clear** → clear that alias's temporary override.
- **Edit** → change the persistent configured value (model picker / custom input → planned config edit → preview/confirm
  → write → offer commit+push).
- **Reset** → unset the configured value (back to the implicit fallback), same write + commit/push offer.
- **Close** (`esc`/`q`).

Rows sort deterministically: `default` first, then the other role aliases, then `<provider>_coder` aliases, then
user-defined aliases alphabetically.

### Backend: per-alias temporary overrides

Generalize `src/sase/llm_provider/temporary_override.py` from one global override to a **per-alias map**, keyed by alias
name, while keeping `default`'s behavior identical:

- **State schema v2** in `~/.sase/llm_override.json`:
  `{"version": 2, "overrides": {"<alias>": { ...TemporaryLLMOverride... }}}`.
- **Legacy migration (read path)**: a v1 flat object (today's shape, with top-level `provider`/`model`/...) is read as
  `overrides.default`, so an override set by the current build keeps working after upgrade.
- **New API** (alias-keyed): `get_active_alias_override(alias)`,
  `set_alias_override(alias, raw_model, duration_seconds, *, source)`, `clear_alias_override(alias)`, and
  `get_active_alias_overrides()` returning all currently-active overrides (expired entries pruned, file removed when the
  map becomes empty — same self-cleaning guarantees as today).
- **Back-compat wrappers**: `get_active_temporary_override()`, `set_temporary_override()`, `clear_temporary_override()`
  continue to exist and operate on the `default` key, so the default lane and the existing indicator need no behavior
  change.

### Resolution semantics (precise, to avoid surprises)

- **`default` (unchanged):** the no-`%model` launch default still applies the default override first, then `@default`,
  via `resolve_effective_default_provider_model()`. Explicit `@default` still resolves to the configured default and
  ignores overrides.
- **Any other alias (new):** `resolve_model_alias()` consults `get_active_alias_override(<bare alias>)` **before** the
  configured/implicit lookup for each non-`default` alias name it encounters in a chain. If an override is active, the
  alias resolves to the override target. This is what makes overrides on explicitly-referenced aliases (`coder`,
  `phase_worker`, etc.) actually take effect, since those are never the implicit "no-directive" default. The `default`
  name is deliberately _not_ short-circuited here so its current two-path semantics are preserved exactly.

Net effect: each alias's override is independent and affects only that alias's resolution; a default override changes
only the default launch lane (as today).

### TUI illustration

- **Default override (unchanged):** keep `LLMOverrideIndicator` showing the gold `Override PROVIDER(model) <remaining>`
  pill, sourced via the `default` back-compat wrapper (no behavior change).
- **Non-default overrides (new, concise, uniform):** a new top-bar widget (e.g. `AliasOverridesIndicator`) that,
  whenever ≥1 non-`default` alias has an active override, shows a single compact pill in a _distinct_ uniform accent
  (e.g. violet, visually parallel to but clearly different from the gold default pill). It reads
  `get_active_alias_overrides()` minus `default`. The pill is intentionally terse — a count (and the single alias's
  name + remaining when exactly one) — with the Models panel as the authoritative detail view. Exact glyph/wording
  finalized with snapshot tests in its phase.

### Commit + push (honoring `use_chezmoi`)

After a persistent alias **Edit** or **Reset** is written:

- Resolve the written file (chezmoi source when `use_chezmoi`, else the user `sase.yml`) and its git root via
  `get_git_root()`.
- Offer a `ConfirmActionModal` (`y/n`) — "Commit and push your model-alias change?" — with the relative path as subject.
- On confirm, run `run_git_commit_push_sync()` (add→commit→pull→push, plus `chezmoi apply` when `use_chezmoi`) inside a
  tracked background task, with a `chore(config): …` auto-tagged commit message.
- When the target file is not in a git repo (e.g. non-chezmoi config outside any repo), skip the offer gracefully and
  just confirm the save.

### Rust core boundary (explicit decision)

- **Persistent alias edits go through the Rust core**: planning/validation/ preview already live behind
  `plan_config_edit` (`config_plan_edit` binding). Phase 3 must confirm the Rust planner accepts a path into the
  `llm_provider.model_aliases` `additionalProperties` map (`llm_provider.model_aliases.<alias>`); if it does not yet,
  **extend the Rust core** (wire/API + bindings + tests in `../sase-core`) rather than bypassing it — this is the
  boundary-correct fix.
- **Temporary override state stays in Python.** It already lives in `temporary_override.py` and is consumed by Python
  launch paths shared by CLI and TUI; the user asked to _extend the existing interfaces_. Moving this runtime state into
  the Rust core is intentionally out of scope and noted as a future consideration.

## Phases

Each phase is independently implementable and reviewable by a distinct agent and builds on the prior ones. Run
`just install` then `just check` (plus the visual suite where snapshots change) before completing any phase with code
changes.

### Phase 1 — Backend: per-alias temporary overrides + resolution

**Objective:** generalize the override state model and wire non-default overrides into alias resolution, with `default`
behavior byte-for-byte intact.

**Scope:**

- Extend `src/sase/llm_provider/temporary_override.py`: v2 keyed schema, v1→v2 read migration into `overrides.default`,
  the new alias-keyed API, the back-compat `default` wrappers, and per-entry expiry pruning + empty-file cleanup.
- Update `resolve_model_alias()` in `src/sase/llm_provider/config.py` to apply an active override for each non-`default`
  bare alias name encountered (before configured/implicit lookup), without touching the `default` path.
- Surface any new public functions through `src/sase/llm_provider/__init__.py`.

**Deliverables / tests:** unit tests for state IO, v1→v2 migration, multi-alias set/clear, expiry pruning + empty-file
deletion, and resolution precedence (override beats configured/implicit for non-default aliases; `default` lane and
explicit `@default` unchanged). No UI changes — `,m`, the modal, and the indicator behave exactly as before.

**Acceptance:** existing override behavior unchanged for `default`; setting an override on `coder`/`phase_worker`
changes what `@coder`/`@phase_worker` resolve to; `just check` green.

### Phase 2 — Models panel: view all aliases + temporary overrides for any alias

**Objective:** ship the new panel as the `,m` target, with full view + temporary-override management; persistent editing
arrives in Phase 3.

**Scope:**

- Add a pure, testable **alias-view aggregation** helper (near the `llm_provider` layer) producing an `AliasRow`-style
  list: name, kind/ provenance, raw configured value (if any), resolved provider/model, and the active override (via
  Phase 1). Build from `model_alias_names()`, `get_model_aliases()`, `resolve_model_alias` / `resolve_model_provider`,
  and `get_active_alias_overrides()`.
- New `ModelsPanel` modal rendering the rows with provider-themed badges, kind badges, and override chips; vim
  navigation; footer hints.
- Temporary-override actions (set/change/clear) for the selected alias, reusing `ModelPickerModal` +
  `CustomModelInputModal` + the duration picker, now alias-aware via the Phase 1 API.
- Repoint leader `,m` to open `ModelsPanel`: rename the action (e.g. `temporary_llm_override` → `models_panel`) in
  `src/sase/default_config.yml`, `src/sase/ace/tui/keymaps/types.py`, and the leader-mode dispatch; keep a back-compat
  alias for the old action name. Retire `TemporaryLLMOverrideModal` (fold its default-override path into the new panel).

**Deliverables / tests:** unit tests for the aggregation helper (provenance, sorting, override merge); panel interaction
tests for set/change/clear; PNG snapshot(s) of the panel (default state and an override-active state) under
`tests/ace/tui/visual/`. Update `?` help and footer per the ace AGENTS.md help rules.

**Acceptance:** `,m` opens the Models panel; the user can view every alias and set/clear a timed override on any of
them; default override still works and still renders in the existing gold pill; `just check` + visual suite green.

### Phase 3 — Persistent alias editing + commit/push (use_chezmoi-aware)

**Objective:** edit and reset alias _config_ from the panel, written safely and committed+pushed after a `y/n` confirm.

**Scope:**

- Add **Edit** and **Reset** actions to `ModelsPanel` for the selected alias, targeting
  `llm_provider.model_aliases.<alias>` via `plan_config_edit` / `apply_config_edit` (`set` for Edit, `unset` for Reset),
  with a concise preview/confirm before writing (reuse the Config Center edit flow patterns; pick the write layer via
  `default_target_layer`).
- **Confirm Rust planner support** for `additionalProperties` map-key paths; if missing, extend `../sase-core`
  (wire/API + bindings + tests) so the edit is still Rust-planned/validated.
- After a successful write, offer commit+push via `ConfirmActionModal` → `run_git_commit_push_sync()` in a tracked task,
  honoring `use_chezmoi` (chezmoi-source write target, chezmoi-repo commit/push, `chezmoi apply`); skip gracefully when
  the target is not in a git repo.

**Deliverables / tests:** unit tests for planning an alias `set`/`unset` edit (incl. chezmoi remap of the target) and
for the commit/push offer logic (git root detection; `use_chezmoi` on/off branches); PNG snapshot of the edit-preview /
commit-confirm flow. Any Rust changes carry their own `../sase-core` tests.

**Acceptance:** editing an alias updates `sase.yml` (or its chezmoi source) with comments/order preserved; a confirmed
commit lands and pushes (and applies via chezmoi when enabled); declining leaves the file written but uncommitted;
`just check` (here and in `../sase-core` if touched) green.

### Phase 4 — TUI indicators for non-default overrides

**Objective:** show non-default overrides concisely and uniformly, leaving the default illustration unchanged.

**Scope:**

- New `AliasOverridesIndicator` top-bar widget (next to `LLMOverrideIndicator` in `src/sase/ace/tui/app.py`) reading
  `get_active_alias_overrides()` minus `default`; concise uniform pill in a distinct accent with its own countdown
  formatting; placeholder/empty states handled like the existing indicator.
- Keep `LLMOverrideIndicator` (default) unchanged, now sourced via the `default` wrapper. Ensure Models-panel override
  actions refresh both indicators.

**Deliverables / tests:** unit tests for the indicator's content across states (no non-default overrides; exactly one;
several; default + non-default together); PNG snapshot(s) of the top bar in those states.

**Acceptance:** setting an override on a non-default alias shows the new pill; clearing it hides it; default pill and
behavior unchanged; visual suite green.

### Phase 5 — Docs, help, glossary & full verification

**Objective:** finish the seams and lock in correctness.

**Scope:**

- Update the `?` help modal, footer conditional keymaps, and any "Model Override" references to describe the **Models**
  panel and its actions (per ace AGENTS.md help-maintenance rules).
- Update `src/sase/default_config.yml` keymap comments, and `docs/llms.md` / any user docs covering aliases and
  overrides; refresh the glossary if it names the old panel.
- Full `just check` and the visual snapshot suite across the repo; accept any intentional new/changed snapshots with the
  documented update flag; reconcile drift.

**Acceptance:** docs/help/glossary match shipped behavior; `just check` and the visual suite are green end-to-end; no
references to the retired modal remain.

## Risks & open questions

- **Rust map-key edits (Phase 3):** if `config_plan_edit` cannot target an `additionalProperties` map key, Phase 3 must
  extend the Rust core (preferred over a Python-only bypass) — scoped within that phase.
- **`,m` action rename:** keep a back-compat alias for the old leader-action name so user keymap overrides referencing
  it don't break.
- **Override × persistent-edit interaction:** an active temporary override on an alias visually "wins" the
  effective-target column even after a persistent edit; the panel must clearly distinguish _configured value_ from
  _currently effective (overridden)_ so this isn't confusing.
- **Non-default indicator verbosity:** the pill must stay terse with many overrides (use a count, not a long list); the
  panel is the detail view.

## Out of scope / future

- Moving temporary-override runtime state into the Rust core.
- A non-TUI (CLI/web) surface for the Models panel.
- Bulk/multi-alias edits or override presets.
