---
create_time: 2026-07-07 20:40:05
status: done
prompt: sdd/prompts/202607/updates_all_current_banner.md
---
# Plan: "All up to date" banner + gate the `u` key on the Updates tab

## Goal

Make the **Updates** tab of the **SASE Admin Center** panel feel finished and trustworthy for the (common, happy) case
where nothing needs updating:

1. **Beautiful confirmation.** When `sase`, `sase-core`, and every installed SASE plugin are already current, show a
   distinct, celebratory banner at the top of the tab that reads at a glance as "you're all good."
2. **No misfires.** When there is nothing to update, the in-tab `u` ("update sase, core & plugins") key should be
   _unavailable_ rather than producing an error toast ("Nothing to update…" / "No editable checkout updates are
   available."). The affordance for `u` should disappear in lock-step so the UI never advertises a key that does
   nothing.

The result should be intuitive (the banner and the missing `u` hint tell a consistent story), reliable (we only claim
"up to date" when we actually verified it), and beautiful (a hero element that fits the tab's visual language).

## Product context / current behavior

The Updates tab is implemented by `PluginsBrowserPane` (`src/sase/ace/tui/modals/plugins_browser_pane.py`), a `Vertical`
composed from several mixins. Its `compose()` lays out, top to bottom:

- `#sase-core-versions` — a purple ("SASE Core", border `#AF87FF`) Rich `Panel` showing installed/latest versions for
  `sase` and `sase-core`, plus the `u run 'sase update'` call-to-action.
- `#plugins-summary` — a one-line counts summary (`N plugins · M installed · K updates available · cached <age>`).
- a `/` filter input, the master/detail plugin browser, and a `#plugins-hints` footer line.

Today the tab has **no** whole-tab "everything is current" state — only per-row "up to date" notes in the SASE Core
panel and a `0 updates available` count in the summary. And the `u` key is **always live**: pressing it when nothing is
outdated opens a confirm modal and, for managed (`uv tool`) installs, surfaces an **error** toast after the `uv` run
(`_SASE_UPDATE_NOOP_MESSAGE`, `severity="error"` in `plugins_browser_sase_update.py`); for editable installs it errors
immediately via `dev_update_blocking_reason`.

### Signals available (no new backend work required)

"Is everything up to date?" is fully determinable from state the pane already holds after a catalog load, and it lines
up with the top-bar `UpdatesAvailableIndicator` badge (which hides at `compute_update_status().count == 0`):

- Plugins: `self._catalog.updates_available` (count of installed plugins behind their latest) — see
  `PluginCatalog.updates_available` in `src/sase/plugins/catalog.py`.
- Core: `self._core_versions.packages[*].update_available` for `sase` and `sase-core` — see `CorePackageVersion` /
  `CoreVersions` in `src/sase/uv_tool/versions.py` (each package also carries `installed_version`, `latest_checked`, and
  `latest_error`, which we use to avoid false positives).

This is presentation-layer TUI work: it composes existing pane state into a banner and a key-availability check. It does
**not** cross the Rust core backend boundary — no `sase-core` changes.

## Design

### A. The "all up to date" predicate (single source of truth)

Add one predicate that both the banner and the `u`-key gating consume, so they can never disagree. Define
`_all_up_to_date()` on `PluginsBrowserStatusMixin` (`plugins_browser_status.py`), which already owns the affordance
logic. Return `True` only when we can _confidently_ claim everything is current:

- not currently loading, and no load `_error`;
- a catalog is present (`self._catalog is not None`);
- this is a manageable install (`not isinstance(self._uv_tool, NotUvToolInstall)`) — a non-`uv tool` install can't be
  updated from here, so a celebratory banner would be misleading (that state already shows its own warning);
- **not offline** (`not self._offline`) — offline means "couldn't check," which the tab already flags with `⚠ OFFLINE`;
  we must not celebrate an unverified state;
- no installed plugin is behind: `self._catalog.updates_available == 0`;
- every core package is _confidently current_: it is installed (`installed_version is not None`), was checked
  (`latest_checked`), had no lookup error (`latest_error is None`), and reports `update_available is False`.

The `latest_checked` / `latest_error` guard is what makes this reliable: an online-but-failed PyPI lookup (core note
cell shows "latest unknown") will _not_ be treated as "up to date," even though `update_available` is `False`.

Rationale for the offline gate specifically: today `u` works offline (it just runs the update), and offline we genuinely
don't know if we're current — so we neither show the banner nor disable `u` while offline. Behavior offline is therefore
unchanged.

### B. The banner (Feature 1)

Add a dedicated, initially-hidden `Static(id="updates-current-banner")` as the **first** child in
`PluginsBrowserPane.compose()` (above `#sase-core-versions`), so when shown it reads as the tab's hero. It stays
additive: the SASE Core panel and plugin browser remain below so the user can still browse/install community plugins.

Content — a Rich `Panel` built by a new `_all_current_banner()` helper (in the status mixin), using an icon-beside-text
grid for a clean hero layout:

- A green success check `✓` beside a bold headline, e.g. **"You're all up to date"**.
- A dim detail line summarizing what was verified, built from live state:
  `sase v<installed> · sase-core v<installed> · <N> plugins current` (uses `CoreVersions.packages` +
  `PluginCatalog.installed_count`; pluralize "plugin").
- A dim freshness/affordance line: `Last checked <age> · press r to re-check` (reuse
  `humanize_age(self._catalog.age_seconds(self._now))`; phrasing avoids the "just now ago" trap).

Visual language / "beautiful": use a **green** success accent for the border and the `✓`/headline (reusing the palette
already in this pane — installed rows are `green`, marks are `#00D700`). Green makes the banner pop above the purple
(`#AF87FF`) SASE Core panel and creates a clear hierarchy: green "all good" hero → purple detail panel. Exact green
shade is a polish detail; default to the existing `#00D700` / `green` tokens for palette + snapshot determinism.

Visibility is driven only by the predicate. Add a `_sync_current_banner()` helper that sets
`banner.display = self._all_up_to_date()` and, when shown, refreshes its content. Call it from:

- `on_mount` (starts hidden until the first load lands),
- `_start_load` (hidden during reloads — the predicate is already `False` while loading), and
- `_render_all` (the post-load repaint that also refreshes `#sase-core-versions`, `#plugins-summary`, `#plugins-hints`).

CSS: add `PluginsBrowserPane #updates-current-banner { width: 100%; height: auto; }` in `src/sase/ace/tui/styles.tcss`
next to the other `PluginsBrowserPane` rules. Toggling Textual's `display` removes it from layout when hidden, so it
costs zero rows in the (common) has-updates case.

The `#plugins-summary` counts line is left unchanged (other states rely on it); the banner is purely additive. Trimming
the redundant `0 updates available` wording when the banner is up is a possible later polish, explicitly out of scope
here.

### C. Gate the `u` key + keep the affordance in sync (Feature 2)

Three coordinated changes so the key, the hint, and the state always agree:

1. **Key availability.** Add `check_action` to `PluginsBrowserPane`: return `self._can_update_sase()` for the
   `update_sase` action, else delegate to `super().check_action(...)`. Returning `False` makes `u` unavailable — the key
   press does nothing (no toast) and the binding drops out of any binding-driven surface. Only `update_sase` is
   special-cased; all other pane bindings (`j`, `k`, `i`, `U`, `x`, `m`, `r`, …) delegate to `super()` and are
   unaffected. `check_action` is evaluated live on each key press, so no explicit `refresh_bindings()` is needed.

2. **Affordance parity.** Extend `_can_update_sase()` (status mixin) — currently only `not NotUvToolInstall` — to also
   return `False` when `self._all_up_to_date()`. This drives the `u update` chip in `#plugins-hints`, so the hint
   disappears exactly when the key becomes unavailable. (Because the hint already hid `u` for non-`uv tool` installs,
   this also finally makes the _key_ inert for that case instead of firing a warning toast — a consistency win. The
   direct-call warning path in `action_update_sase` is untouched, so the existing "disabled when not uv tool" test still
   passes.)

3. **App-level bubble guard (correctness).** The app binds `Binding("u", "clear_marks")`
   (`src/sase/ace/tui/bindings.py`). When the pane's `u` is disabled, the key bubbles; `ConfigCenterModal` does not bind
   `u`, so it would reach `action_clear_marks` and clear marks on the tab _behind_ the modal. The app already gates
   `next_tab`/`prev_tab` under a `ModalScreen` in `App.check_action` (`src/sase/ace/tui/app.py`); extend that same modal
   guard to return `False` for `clear_marks` whenever `isinstance(self.screen, ModalScreen)`. This is correct in its own
   right (clearing main-tab marks while any modal is open is never desired) and is required for the gating to be
   side-effect-free.

### D. The auto-update entry point (leader `,U` shortcut)

The leader-mode `,U` shortcut (`action_update_sase_shortcut`) opens the Updates panel with `auto_update_on_load=True`;
after load, `on_worker_state_changed` calls `action_update_sase`. To keep that path consistent (no error toast, honest
feedback) when the user asks to update but is already current: in the `_auto_update_on_load` branch, if
`_all_up_to_date()`, show a friendly `severity="information"` toast (e.g. "Everything is already up to date.") and skip
the run; otherwise behave exactly as today. The banner is also visible, so the explicit request gets clear positive
confirmation.

`action_update_sase` itself is intentionally **not** hard-gated on the predicate: it stays callable for the auto path
and for direct/programmatic callers, and the genuinely-rare anomaly toasts it can still emit (managed no-op discovered
only after `uv` runs; real dev blockers like "checkout has local changes") remain meaningful. In normal interactive use
those are now unreachable via `u` because the key is gated when we're confidently current.

## Files to change (high level)

- `src/sase/ace/tui/modals/plugins_browser_pane.py` — add `Static(id="updates-current-banner")` to `compose()`; add
  `_sync_current_banner` calls in `on_mount` / `_start_load` / `_render_all`; add `check_action`; in the
  `_auto_update_on_load` branch, short-circuit to an info toast when up to date.
- `src/sase/ace/tui/modals/plugins_browser_status.py` — add `_all_up_to_date()`, `_all_current_banner()`,
  `_sync_current_banner()`; extend `_can_update_sase()`; add the `_core_versions` type hint to the mixin's
  `TYPE_CHECKING` block; import the Rich helpers needed for the banner.
- `src/sase/ace/tui/app.py` — extend `App.check_action` to disable `clear_marks` while a `ModalScreen` is active.
- `src/sase/ace/tui/styles.tcss` — add the `#updates-current-banner` rule.

## Testing

Unit / interaction tests (extend `tests/ace/tui/test_plugins_browser_pane_sase_update.py` and/or a sibling module,
reusing helpers in `tests/ace/tui/_plugins_browser_pane_helpers.py`). Note the shared `_catalog()` fixture already
contains one plugin update, so an "all current" catalog must be built explicitly (e.g. clone `_catalog()` with the
`github` entry's latest set equal to its installed version, default `_core_versions()` which has no updates):

- Banner **shown** when up to date: `#updates-current-banner` has `display is True` and its rendered text contains the
  headline, the `sase v… · sase-core v… · N plugins current` summary, and the freshness line.
- Banner **hidden** in has-updates (default `_catalog()`), loading, error, offline, and non-`uv tool` states
  (reliability cases).
- `pane.check_action("update_sase", ())` is `False` when up to date and truthy when updates exist.
- `#plugins-hints` omits `u update` when up to date and includes it when updates exist.
- Leader auto-update path: opening with `auto_update_on_load=True` against an all-current catalog emits the information
  toast and pushes **no** confirm modal.
- App guard: with a `ModalScreen` active, `app.check_action("clear_marks", ())` is `False` (co-locate with the existing
  app `check_action` tests).

Visual snapshot (deterministic PNG suite): add `test_config_center_updates_all_current_png_snapshot` in
`tests/ace/tui/visual/test_ace_png_snapshots_config_center_plugins.py`, mirroring
`test_config_center_updates_core_update_available_png_snapshot` but patching an all-current catalog + default core
versions so the banner renders above the SASE Core panel. Generate the golden with
`just test-visual --sase-update-visual-snapshots` and commit the new `snapshots/png/` artifact.

Regression watch: no existing test should need editing. `action_update_sase` and its not-`uv tool` warning are
unchanged; the managed no-op error test (`test_updates_pane_sase_update_noop_closes_without_restart`) still drives
`action_update_sase()` directly against a catalog that reports an update, so it is unaffected.

## Docs / conventions

- The in-tab `u` affordance lives in the dynamic `#plugins-hints` line (now correctly conditional); the global `?` help
  modal and the footer document the leader `,U` shortcut, which is unchanged. Grep the help modal for any Updates-tab
  `u` copy and only touch it if something is now stale (per the ace help-popup maintenance rule).
- No memory/`CLAUDE.md`/provider-shim edits.

## Out of scope

- Backend/`sase-core` changes (the predicate is pure presentation state).
- Reworking the `#plugins-summary` counts line, the badge, or the confirm-modal flows.
- Changing severity/wording of the genuine anomaly toasts (managed post-`uv` no-op; real dev blockers).
- Any change to offline behavior beyond not celebrating an unverified state.

## Risks & mitigations

- **False "up to date" claim.** Mitigated by the strict predicate: offline, unchecked, and failed-lookup core states are
  excluded.
- **Key bubbling side effect (`clear_marks`).** Mitigated by the app-level modal guard, with a dedicated test.
- **Visual drift in snapshots.** Mitigated by reusing existing palette tokens and the deterministic visual harness; the
  golden is regenerated intentionally.
