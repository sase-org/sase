---
create_time: 2026-07-01 07:05:33
status: done
prompt: sdd/prompts/202607/onboarding_install_plugins_step.md
---
# Plan: "Install plugins" onboarding step (shown only when no plugins are installed)

## Goal & product context

The Agents-tab empty-state onboarding (`AgentOnboarding`, shown when a user has zero agents) currently walks a brand-new
user through three numbered steps: **1 Launch your first agent**, **2 The three tabs**, **3 Get more help**.

Add a new onboarding step that teaches the user to install plugins and keep sase current from the **Updates** tab of the
**SASE Admin Center**, explicitly recommending **`sase-github`** as the first plugin to install. The step must appear
**if and only if the user currently has no sase plugins installed at all** — it is a nudge for bare installs and must
vanish the moment any plugin exists (including right after the user installs `sase-github` from that very panel).

### Design principles for this feature

- **Intuitive:** the step reads as a natural continuation of the existing numbered flow, uses the same terse
  keycap-driven copy style, names the real UI ("SASE Admin Center", "Updates" tab), and is visually tied to the Updates
  tab by reusing that tab's violet accent (`#AF87FF`).
- **Reliable:** visibility is driven by a _local, offline, network-free_ plugin check that cannot misfire on a fresh
  install (the exact scenario we most want to catch), and that provably excludes the host `sase` package and the Rust
  core so the step doesn't silently never-show.
- **Beautiful:** the step is a distinct, accented "recommendation" card; numbering reflows cleanly so there is never a
  gap or a duplicated number whether the card is present or not; a dedicated visual snapshot locks the rendered result.

## Current behavior (verified)

- Widget: `src/sase/ace/tui/widgets/agent_onboarding.py`. `compose()` yields `Static` cards (`agent-onboarding-card`)
  with hard-coded `border_title = "1 …"/"2 …"/"3 …"`. `render_content()` returns a `{selector: Text}` dict that tests
  call directly (no mount needed). A per-card conditional pattern already exists: `set_launch_targets_available()`
  toggles one extra hint line inside the launch card.
- Empty-state plumbing: `src/sase/ace/tui/actions/agents/_display_detail.py` shows/hides the panel
  (`_sync_agents_onboarding`) and drives the launch-target hint via a coalesced off-thread refresh
  (`_schedule_/_run_/_apply_agents_onboarding_launch_targets_*`, backed by four flags on the app). The discovery itself
  lives in `src/sase/ace/tui/actions/agents/_onboarding_launch_targets.py` and is the monkeypatch seam used by tests.
- Plugin detection: `src/sase/plugins/installed.py` +
  `src/sase/version/_plugins.py::plugin_candidates_from_distributions`. Crucially, `is_runtime_distribution()` excludes
  both `HOST_DISTRIBUTION_NAME = "sase"` and `CORE_DISTRIBUTION_NAME = "sase-core-rs"`, and the _candidates_ path
  returns only real third-party plugins (by `sase-` dist name, `sase_*` entry-point group, or sase console script). This
  runs purely against `importlib.metadata.distributions()` — **no network, offline-safe**. (Note:
  `build_installed_index()`'s inventory path _does_ include host `sase`, so we deliberately use the candidates path, not
  the index, for the boolean.)
- Admin Center: modal `src/sase/ace/tui/modals/config_center_modal.py`, opened by the configurable `open_config_center`
  keymap action (default `#`, confirmed present in `src/sase/ace/tui/keymaps/types.py`). The **Updates** tab
  (`plugins_browser_pane.py`) installs plugins with `i`, updates sase-core + all plugins with `u`, updates one plugin
  with `U`, removes with `x`. Its identity accent is violet `#AF87FF`.

## Why the strict "no plugins" signal is safe

The Updates tab's own "N installed" count comes from `PluginCatalog.installed_count`, which requires the GitHub catalog
(network/`gh` or cache) and **raises on a fresh, offline install with no cache** — exactly our trigger scenario. So we
must _not_ depend on the catalog. Instead the step uses the local candidates path. Deliberate, documented divergence
from `installed_count`: a plugin installed locally but absent from the GitHub catalog counts as "installed" for us (we
won't nag someone who already has a plugin). This mirrors the "asymmetric source, unified intent" pattern used elsewhere
in the plugins domain.

## Design

### 1. New local plugin-presence helper (Python, `src/sase/plugins/installed.py`)

Add two thin, pure, dependency-injected functions next to the existing detection code:

- `installed_plugin_distributions(*, candidates_fn=_installed_plugin_candidates) -> tuple[str, ...]` — normalized
  distribution names of installed **third-party** plugins (candidates path already excludes host `sase` +
  `sase-core-rs`), de-duplicated.
- `any_plugins_installed(*, candidates_fn=_installed_plugin_candidates) -> bool` — the boolean the UI needs. Add both to
  `__all__`.

Rationale for candidates path over `build_installed_index()`: the index includes the host `sase` distribution (it
contributes `sase_*` entry points), which would make "any plugins" always true.

### 2. Discovery seam (`src/sase/ace/tui/actions/agents/_onboarding_plugins.py`, new)

`discover_agents_onboarding_plugins_installed() -> bool` → returns `any_plugins_installed()`. New module (sibling of
`_onboarding_launch_targets.py`) so it is an independent monkeypatch seam and the existing launch-target discovery/tests
are untouched.

### 3. Widget changes (`agent_onboarding.py`)

- New card `#agent-onboarding-plugins`, classes `agent-onboarding-card -recommend`, built by
  `_build_plugins_card(registry)`. Yield it in `compose()` **between** the tabs card and the help card so DOM order
  matches display order; start it with the `hidden` class.
- New instance state `self._plugins_installed = True` (default assume-installed ⇒ hidden, so users who have plugins
  never see a flash), plus `set_plugins_installed(installed: bool)` which stores the value and, when mounted, applies
  visibility + renumbering (idempotent).
- **Dynamic numbering** replaces the hard-coded border-title numbers. A pure helper
  `_ordered_step_selectors() -> list[tuple[str, str]]` returns `(selector, base_title)` for the _visible_ steps in order
  — always launch, tabs; then the plugins card only when `not self._plugins_installed`; then help.
  `_apply_step_numbers()` walks it and sets `border_title = f"{n} {base_title}"`. Expose `numbered_step_titles()` for
  mount-free unit testing. `on_mount()` calls `refresh_content()` then applies visibility+numbering.
- `render_content()` gains `"#agent-onboarding-plugins": self._build_plugins_card(registry)` so refreshes and tests
  cover it.

**Card copy** (terse, keycap style; violet for the Updates-tab tie-in). Title (base):
`Install plugins & keep sase current`. Body:

- heading `Extend sase from the Admin Center`
- `[<open_config_center>]` open the **SASE Admin Center**, then its **Updates** tab. ← key rendered from the registry
  via `key_display_name(app.open_config_center)`; "Updates" in violet.
- `[i]` install a plugin · `[u]` update sase & all plugins. ← in-modal keys as literal keycaps (they are modal-fixed,
  not in the main keymap registry); avoid hard-coding the fragile tab _number_.
- Recommended first plugin: **`sase-github`** — adds GitHub PR & repo workflows. ← `sase-github` in violet.

### 4. CSS (`src/sase/ace/tui/styles.tcss`)

Add `.agent-onboarding-card.-recommend { border: round #AF87FF; border-title-color: #AF87FF; }` after the existing
`.agent-onboarding-card` block. Everything else inherits, so layout stays consistent.

### 5. Empty-state plumbing (`_display_detail.py`, `_state_init.py`, `startup.py`)

Mirror the launch-target machinery with an independent, coalesced off-thread refresh (the same triple-flag idiom already
used twice in this file):

- App state (init in `_state_init.py`, annotate in `_display_detail.py` + `startup.py`):
  `_agents_onboarding_plugins_installed = True`, plus `_scheduled/_running/_pending = False`.
- `_schedule_agents_onboarding_plugins_refresh()` / `_run_agents_onboarding_plugins_refresh()` (async,
  `asyncio.to_thread(discover_agents_onboarding_plugins_installed)`) /
  `_apply_agents_onboarding_plugins_installed(installed)` — copies of the launch-target methods.
- In `_sync_agents_onboarding`, when onboarding is shown: push the current value
  (`onboarding.set_plugins_installed(self._agents_onboarding_plugins_installed)`) and call
  `_schedule_agents_onboarding_plugins_refresh()`. Re-running on every show is what makes the card disappear after the
  user installs `sase-github` and returns to the empty Agents tab.

Visibility condition stays exactly "no plugins installed"; the "keep sase up to date" idea is card _content_ (the `[u]`
hint), not a second trigger — matching the spec precisely.

## Testing

- **Helper unit tests** (extend `tests/test_plugin_catalog_installed.py`, reusing `_FakeDistribution` /
  `_FakeEntryPoint` from `tests/_version_inventory_helpers.py`): `any_plugins_installed` is False for empty candidates
  and True for one fake plugin candidate; and — driving the real `_installed_plugin_candidates` via fake distributions —
  host `sase` and `sase-core-rs` are excluded while a genuine `sase-foo` plugin is counted.
- **Widget unit tests** (`tests/ace/tui/widgets/test_agent_onboarding.py`): `render_content` includes the plugins card
  heading, "Updates", "sase-github", and the `[i]`/`[u]` labels; the Admin Center key honors a custom
  `open_config_center` keymap (mirror the existing active-registry test); `numbered_step_titles()` yields
  Launch/Tabs/Help as 1-2-3 when installed and Launch/Tabs/Plugins/Help as 1-2-3-4 when `_plugins_installed = False`.
- **Functional tests** (`tests/ace/tui/test_agents_onboarding.py`): add a `_wait_for_onboarding_plugins_refresh` helper
  mirroring the launch-target one; monkeypatch `_onboarding_plugins.discover_agents_onboarding_plugins_installed` →
  False ⇒ card visible (not hidden) with "sase-github"/"Updates" copy; → True ⇒ card hidden and Help numbered "3".
- **Visual snapshots** (`tests/ace/tui/visual/test_ace_png_snapshots_agents_onboarding.py`):
  - Update the existing test to _also_ monkeypatch the plugins discovery → `lambda: True` so the base golden
    `agents_onboarding_120x40` stays byte-identical (**required** — CI installs no plugins, so without this the base
    golden would regress).
  - Add a new test that monkeypatches → `lambda: False`, asserts the screen contains "sase-github", and captures a new
    golden `agents_onboarding_no_plugins_120x40`. Generate goldens with
    `just test-visual --sase-update-visual-snapshots`.

## Out of scope / non-goals

- No changes to the Updates tab / plugin install flow itself, no new keybindings, no `default_config.yml` changes (the
  card only references existing actions), and thus no `?` help-modal changes.
- Visibility is strictly "zero plugins installed"; we do not gate on whether sase itself has an available update.

## Risks & callouts

- **Rust boundary (needs your veto):** per `rust_core_backend_boundary`, plugin-presence is arguably backend logic. It
  is kept in Python because the _entire_ plugins/updates domain is already pure Python and the Rust core exposes no
  plugin-enumeration surface; the new helper is a thin, reusable API (a CLI/other frontend could call it too). Flagging
  for approval, consistent with the prior Updates-tab decision.
- **One-frame reflow:** for a zero-plugin user, the empty state first paints 1-2-3 (card hidden by the assume-installed
  default) and reflows to 1-2-3-4 after the sub-100 ms local check. This mirrors the existing launch-target hint's async
  appearance and is the price of never flashing the card at users who _do_ have plugins.
- **Tab-number fragility avoided:** the card says "open the Updates tab" and uses `[#]` (from the registry) rather than
  hard-coding the Updates tab's position number, so it won't drift if tabs are reordered.

## Verification

Run `just install` then `just check` (lint + mypy + tests). Regenerate and eyeball both onboarding PNG goldens.
