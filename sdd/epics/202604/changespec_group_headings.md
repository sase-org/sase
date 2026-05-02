---
status: done
create_time: 2026-04-27 20:09:18
bead_id: sase-z
prompt: sdd/prompts/202604/changespec_group_headings.md
---

# CLs Tab — ChangeSpec Group Headings

## Goal

Add configurable grouping/sorting modes to the CLs tab, controlled by the existing configurable app-level `o`
(`cycle_grouping_mode`) keymap. The CLs tab should gain foldable group heading rows whose behavior and visual language
closely match the Agents tab group headings, while preserving the current flat CL list as the default starting point.

The user-facing grouping strategies are:

1. **By project**: level 1 headings are project names; level 2 headings are sibling roots such as `foobar` when
   `foobar_1` and `foobar_2` are both present in the current ChangeSpec query result.
2. **By date**: level 1 headings only; bucket from the latest `TIMESTAMPS` entry on each ChangeSpec.
3. **By status**: level 1 headings only; bucket from the ChangeSpec `STATUS` field value.

## Existing Shape

- `o` is already present in `src/sase/default_config.yml` as `cycle_grouping_mode: "o"`, but
  `AgentGroupingMixin.action_cycle_grouping_mode()` returns unless `current_tab == "agents"`.
- Agents already have the useful primitives:
  - `GroupingMode` plus date/status buckets in `src/sase/ace/tui/models/agent_groups/`.
  - Tuple-keyed fold state in `src/sase/ace/tui/models/agent_group_fold.py`.
  - Banner rows, selectable collapsed headings, jump hints, and j/k navigation over collapsed banners.
- The CLs tab is still flat:
  - `ChangeSpecLoadingMixin._filter_changespecs()` produces the filtered `self.changespecs` list.
  - `ChangeSpecList.update_list()` maps one rendered `Option` per ChangeSpec, and row index == `current_idx`.
  - `BasicNavigationMixin.action_next_changespec()` / `action_prev_changespec()` increment `current_idx` directly on the
    CLs tab.
  - `h/H/l/L` currently mean CL-specific hooks/log behavior, while Agents overload those actions for fold controls.

## Design Decisions

- **Keep legacy flat mode as the default.** The requested strategies are the grouped modes, but first paint should not
  surprise users by changing CL navigation and `h` semantics before they press `o`. The CLs cycle should be
  `FLAT -> BY_PROJECT -> BY_DATE -> BY_STATUS -> FLAT`.
- **Separate CL grouping state from Agents grouping state.** Do not reuse `~/.sase/grouping_mode.txt`; add a CL-specific
  state file/helper so cycling Agents does not alter CLs and vice versa. If persistence is judged too much for phase 1,
  keep the same API with in-memory state first and wire persistence in the interactivity phase.
- **Use a ChangeSpec-specific grouping model.** Do not stretch `Agent` grouping helpers to accept `ChangeSpec`.
  Introduce a small `changespec_groups` model package with its own tree builder and bucket helpers, while sharing only
  generic concepts such as tuple group keys and fold registry behavior.
- **Fold registry should become generic.** Add `src/sase/ace/tui/models/group_fold.py` with `GroupFoldRegistry` /
  `GroupKey`, then keep `agent_group_fold.py` as a compatibility re-export or subclass alias. This lets CL code avoid
  importing an agent-named type without forcing a large migration in one step.
- **Date grouping uses the latest parsed TIMESTAMPS value.** Support both current `YYMMDD_HHMMSS` and old
  `YYYY-MM-DD HH:MM:SS` formats. Missing or unparsable timestamps fall into `Earlier` and sort after timestamped CLs.
- **Status grouping uses the literal `ChangeSpec.status` value for group identity and heading text.** Sorting should use
  known lifecycle order by base status first (`WIP`, `Draft`, `Ready`, `Mailed`, `Submitted`, `Reverted`, `Archived`),
  then exact status text for unknown/suffixed values. This keeps labels faithful to the file while avoiding random
  order.
- **Sibling headings are suppressed for singletons.** In `BY_PROJECT`, emit level 2 sibling-root headings only when the
  root has at least two visible ChangeSpecs under the same project. Singletons render directly under their project
  heading, matching the Agents tab name-root behavior.
- **Fold controls mirror Agents only when grouping is active.** In `FLAT`, CLs keep today’s `h/H/l/L` behavior. In
  grouped modes, `h/l` operate on the focused or enclosing CL group and `H/L` collapse/expand all visible CL groups.
  This is the main UX tradeoff: grouped mode makes headings first-class navigation objects, while flat mode preserves
  existing hook shortcuts.

## Phase 1 — Data Model, Buckets, And Tree Builder

**Scope:** Pure model layer and tests. No widget rendering, app key handling, or display changes.

- Add a neutral fold registry module:
  - `src/sase/ace/tui/models/group_fold.py`
  - Update `agent_group_fold.py` to re-export the neutral types so existing imports continue to pass.
- Add `src/sase/ace/tui/models/changespec_groups/` with:
  - `ChangeSpecGroupingMode`: `FLAT`, `BY_PROJECT`, `BY_DATE`, `BY_STATUS`.
  - `ChangeSpecGroupRow` and `ChangeSpecTreeEntry`, analogous to Agents `GroupRow` / `TreeEntry`.
  - `latest_changespec_timestamp(cs) -> datetime | None`.
  - `date_bucket_for_changespec(cs, now) -> Today / Yesterday / This Week / Earlier`.
  - `status_bucket_for_changespec(cs) -> cs.status`.
  - `sibling_root_for_changespec(cs)`, using the existing suffix logic from
    `sase.core.changespec.strip_reverted_suffix`.
  - `build_changespec_tree(changespecs, mode, fold_registry, now)` and `enumerate_changespec_group_keys(...)`.
- Sorting rules:
  - `FLAT`: no group rows, preserve existing filtered list order.
  - `BY_PROJECT`: project name ascending, then singleton roots before grouped roots, then visible ChangeSpecs in the
    same stable relative order they had in `changespecs`.
  - `BY_DATE`: fixed bucket order `Today`, `Yesterday`, `This Week`, `Earlier`; within bucket latest timestamp desc.
  - `BY_STATUS`: lifecycle/status bucket order; within bucket stable by current filtered order.
- Tests:
  - TIMESTAMPS parser helper covers new, old, hybrid, missing, malformed, and multiple-entry latest selection.
  - Project tree emits project L1 and sibling-root L2 only for 2+ visible siblings.
  - Date and status modes emit only L1 headings.
  - Folded group suppresses descendants and leaves sibling groups visible.
  - `FLAT` exactly preserves old visible ChangeSpec order.

**Deliverable:** A tested model package that can produce a flat list of group/ChangeSpec entries independent of Textual.

## Phase 2 — ChangeSpecList Rendering And Row Mapping

**Scope:** Widget-level rendering. The app still stays in `FLAT` unless tests pass explicit modes.

- Extend `ChangeSpecList` so `update_list()` accepts:
  - `grouping_mode: ChangeSpecGroupingMode = FLAT`
  - `fold_registry: GroupFoldRegistry | None`
  - `current_group_key: tuple[str, ...] | None`
  - `banner_jump_hints: dict[tuple[str, ...], str] | None`
  - `now: datetime | None`
- Add row bookkeeping analogous to `AgentList`:
  - `_row_entries` mapping option rows to ChangeSpec indices or banner sentinels.
  - `_banner_at_row` and `_banner_row_by_key` for selectable collapsed headings.
  - `SelectionChanged(index, group_key=None)` where banner rows resolve to the first ChangeSpec in the group while
    preserving group focus.
  - `update_highlight(current_idx, group_key=None)` that can highlight collapsed headings.
- Add CL banner rendering, preferably in a new helper near `changespec_list.py`, reusing Agents tab colors/gutter style:
  - Level 1 project/date/status headings use the strong Agents L0 visual treatment.
  - Level 2 sibling headings use the dim branch/name-root treatment.
  - Chips summarize `N CLs` plus useful status counts without crowding the left pane.
- Keep full refresh and patch behavior conservative:
  - In `FLAT`, preserve current fast single-row patch behavior.
  - In grouped modes, allow full-list rebuilds first; only re-enable row patching when the row maps and widths are
    proven stable.
- Tests:
  - Rendered option order and disabled/selectable state for expanded vs collapsed headings.
  - Selection messages from ChangeSpec rows and banner rows.
  - Width calculation includes banners and does not shrink below existing ChangeSpec row needs.
  - Flat-mode rendering remains byte-for-byte compatible enough for existing tests.

**Deliverable:** `ChangeSpecList` can render grouped trees in isolation, but normal app usage still behaves flat.

## Phase 3 — CL Grouping State, `o` Cycle, And Info/Help Surfacing

**Scope:** User-facing mode selection on the CLs tab.

- Add CL-specific state in `_init_app_state`:
  - `_changespec_grouping_mode`
  - `_changespec_group_fold_registries`
  - `_changespec_group_fold_registry`
  - `_current_changespec_group_key`
- Add `src/sase/ace/changespec_grouping_mode_state.py` or a generalized mode-state helper with a separate file from
  Agents grouping mode.
- Generalize `action_cycle_grouping_mode()` so:
  - On Agents, existing behavior remains unchanged.
  - On CLs, it advances `FLAT -> BY_PROJECT -> BY_DATE -> BY_STATUS -> FLAT`, swaps the per-mode fold registry, clears
    invalid banner focus, persists the CL mode, toasts `CL grouping: by date`, and refreshes the CL display.
  - On AXE, it remains a no-op.
- Thread the active CL mode/registry/current group key through `_refresh_display()` into `ChangeSpecList.update_list()`.
- Update CL info panel or search panel with a compact grouping badge when not flat, including the configured key display
  for `o`. Do not clutter the already dense CL top bar in flat mode.
- Update help modal / keybinding footer descriptions so `o` is discoverable for CLs as well as Agents.
- Tests:
  - CL cycle order and no-op behavior on AXE.
  - CL and Agents grouping modes persist independently.
  - Cycling mode clears stale `_current_changespec_group_key`.
  - App-level refresh passes the active mode to the list widget.

**Deliverable:** Pressing `o` on the CLs tab changes grouping mode and redraws the left list with headings.

## Phase 4 — Fold-Aware CL Navigation And Jump Hints

**Scope:** Make grouped CL headings feel like Agents headings.

- Add CL navigation helpers mirroring Agents:
  - `_changespec_navigation_stops()` returns visible ChangeSpec rows plus collapsed banner rows in render order.
  - `action_next_changespec()` / `action_prev_changespec()` use those stops on the CLs tab when grouping is not `FLAT`.
  - Preserve current direct index stepping in `FLAT`.
- Add CL group fold actions:
  - `l`: expand focused collapsed group.
  - `h`: collapse focused group or the selected ChangeSpec’s deepest enclosing group.
  - `L`: expand all visible CL groups one level.
  - `H`: collapse all visible CL groups one level.
  - In `FLAT`, leave existing CL `h/H/l/L` meanings unchanged.
- Re-anchor focus after fold changes:
  - If a selected ChangeSpec becomes hidden, focus the deepest collapsed ancestor heading.
  - If a heading is expanded and becomes disabled, move to its first visible child heading or ChangeSpec.
- Extend one-key jump mode:
  - CL jump targets should include collapsed headings as banner targets in grouped modes.
  - Existing flat CL jump hints remain unchanged.
- Update reload/reposition:
  - Preserve selected ChangeSpec by name where possible.
  - Preserve banner focus only when the group key still exists; otherwise fall back to nearest visible ChangeSpec.
  - Call `clear_unknown()` on the active CL fold registry after list/filter refreshes.
- Tests:
  - j/k walks visible grouped rows including collapsed headings.
  - h/l/H/L fold behavior and focus re-anchoring.
  - Jump hints include collapsed headings and dispatch to the correct group.
  - Query changes and reloads prune stale fold keys without leaking between modes.

**Deliverable:** Grouped CL headings are navigable and foldable with the same mental model as Agents headings.

## Phase 5 — Integration Coverage, Polish, And Performance Pass

**Scope:** Hardening after the feature is functionally complete.

- Add end-to-end-ish Textual pilot tests for:
  - Start flat, press `o` through each mode, verify visible headings.
  - Collapse a project group, change query, ensure no stale selection crash.
  - Switch between CLs and Agents and verify each tab keeps its own grouping state.
- Expand widget tests around long names and narrow widths so heading labels, chips, and ChangeSpec rows do not overlap.
- Add targeted performance checks:
  - Large ChangeSpec list tree build does not dominate j/k navigation.
  - Latest TIMESTAMPS parsing is cached or computed once per refresh, not per render row repeatedly.
- Update any docs or help text snapshots affected by the new CL `o` behavior.
- Run:
  - Focused tests for changespec groups, widgets, keymaps, and navigation.
  - `just install` if the workspace has not been initialized recently.
  - `just check` before handing back the implementation.

**Deliverable:** Feature is stable under the normal TUI refresh/query/navigation paths and ready to use.

## Risks And Watchpoints

- **`h` shortcut conflict:** Grouped modes intentionally give `h/H/l/L` to group folding; flat mode keeps today’s CL
  hooks/log behavior. This needs to be obvious in the footer/help text.
- **TIMESTAMPS cost:** A naive implementation can parse timestamps repeatedly during renders. Keep parsed latest
  timestamps in the tree/build context for the current refresh.
- **Status label cardinality:** Using exact `STATUS` field values may create more groups if suffixes are present. That
  matches the request but should be covered by tests.
- **Sibling-root semantics:** Reuse existing `_N` / `__N` stripping; do not invent broader fuzzy grouping.
- **Agent regressions:** The `cycle_grouping_mode` action and generic fold registry touch Agents code. Phase agents
  should run focused Agents grouping/fold tests after each shared change.
