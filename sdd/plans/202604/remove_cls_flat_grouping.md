---
create_time: 2026-04-27 22:57:52
status: done
prompt: sdd/prompts/202604/remove_cls_flat_grouping.md
---
# Remove FLAT Grouping from the CLs Tab

## Goal

Eliminate the "flat" (no-grouping) option from the `sase ace` TUI's **CLs** tab so that one of the three real grouping
strategies — `BY_PROJECT`, `BY_DATE`, `BY_STATUS` — is always active. After this change a fresh user always sees grouped
banners on the CLs tab, and the `o` cycle key walks a 3-mode loop instead of a 4-mode loop.

The Agents tab is **out of scope** — its `STANDARD`/`BY_DATE`/`BY_STATUS` cycle and its separate
`~/.sase/grouping_mode.txt` are untouched.

## Background

The CLs tab currently supports four grouping modes (see `src/sase/ace/tui/models/changespec_groups/_buckets.py:15`):

| Mode         | L0 grouping                                                                            | Notes                                                                              |
| ------------ | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `FLAT`       | none — direct one-row-per-CL render                                                    | The first-paint default; the legacy code path the grouped feature was bolted onto. |
| `BY_PROJECT` | project name (with L1 sibling-root sub-banners)                                        |                                                                                    |
| `BY_DATE`    | bucket (`Today`, `Yesterday`, `This Week`, `Earlier`) from the latest TIMESTAMPS entry |                                                                                    |
| `BY_STATUS`  | literal `status` field                                                                 |                                                                                    |

`FLAT` is the persisted default in `src/sase/ace/changespec_grouping_mode_state.py:12`, the first entry in the cycle
tuple in `src/sase/ace/tui/actions/agents/_grouping.py:39`, and is also the load-fallback when the on-disk state file
(`~/.sase/changespec_grouping_mode.txt`) is missing or unparsable. The render dispatch in
`src/sase/ace/tui/widgets/changespec_list.py:174` branches between a dedicated `render_flat` path and the grouped path.

## Decisions

1. **Drop the `FLAT` enum value entirely.** Per the project convention against backwards-compat shims, leaving a dead
   enum entry would just attract bugs. The state loader's existing `ValueError → _DEFAULT` branch makes this safe for
   users who have `flat` already persisted on disk — they silently re-default into a real grouping mode the next time
   `sase ace` starts.
2. **New default mode: `BY_PROJECT`.** Reasoning:
   - It mirrors the Agents-tab analog (`STANDARD` is the first cycle entry there).
   - It gives the densest information layout for the typical CL list (project + sibling roots) without depending on
     TIMESTAMPS data.
   - The cycle order naturally becomes `BY_PROJECT → BY_DATE → BY_STATUS → BY_PROJECT`, keeping the existing relative
     ordering of the three real modes.
3. **Delete `render_flat` and the dispatch branch.** Always go through `render_grouped`. The grouped path already
   handles every shape we need (single CL, single group, etc.) and the patch-row guard already disables in-place
   patching whenever banner rows are present, so behavior in that path is well-tested.
4. **Simplify `_changespec_grouping_active()`.** Once `FLAT` is gone, "grouping is active" is always true on the CLs
   tab. Inline the check at call sites instead of keeping a constant-true helper, so the navigation/fold mixin reads as
   the actual model rather than a guarded one.
5. **Always show the grouping badge on the CL info panel.** Today the badge is hidden when the label is `""` or
   `"flat"`; with FLAT removed there is always a real label and the badge is unconditionally meaningful.
6. **No migration of the persisted file.** Existing `~/.sase/changespec_grouping_mode.txt` files containing `flat` will
   simply fall through the `ValueError` path on load and land on the new default — that's already how unknown values are
   handled.

## Scope of Change

### Source code (production)

| File                                                    | Change                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/models/changespec_groups/_buckets.py` | Remove `FLAT` from the `ChangeSpecGroupingMode` enum and from the docstring.                                                                                                                                                                                                                                                |
| `src/sase/ace/tui/models/changespec_groups/_tree.py`    | Remove the `mode is FLAT` branches from `enumerate_changespec_group_keys` and `build_changespec_tree`; drop `FLAT` defaults on the `mode` parameter (require explicit mode, or default to `BY_PROJECT`).                                                                                                                    |
| `src/sase/ace/tui/models/changespec_groups/_keys.py`    | Remove the `FLAT` early-return in `walk_order` and the `FLAT` arm of `_l0_sort_key`.                                                                                                                                                                                                                                        |
| `src/sase/ace/changespec_grouping_mode_state.py`        | Change `_DEFAULT` to `ChangeSpecGroupingMode.BY_PROJECT`; update docstrings.                                                                                                                                                                                                                                                |
| `src/sase/ace/tui/actions/agents/_grouping.py`          | Remove `"FLAT"` from `_CHANGESPEC_GROUPING_CYCLE` (now 3 entries) and from `_CHANGESPEC_MODE_LABELS`. Update the module docstring comment about FLAT being the first-paint default.                                                                                                                                         |
| `src/sase/ace/tui/actions/changespec/_grouping_nav.py`  | Drop `_changespec_grouping_active()` (it always returns True now); inline `True` at the call sites and prune the dead `if not active: return …` branches.                                                                                                                                                                   |
| `src/sase/ace/tui/actions/changespec/_display.py`       | Drop `ChangeSpecGroupingMode.FLAT` from `_CHANGESPEC_GROUPING_BADGE_LABELS`; remove the `mode is not FLAT` guards around `fold_registry` / `current_group_key` / `banner_jump_hints` since they're now unconditional. Update the `getattr(..., FLAT)` defaults to use `BY_PROJECT`.                                         |
| `src/sase/ace/tui/widgets/changespec_list.py`           | Delete the `if grouping_mode is FLAT: render_flat` branch in `_update_list_impl`; always call `render_grouped`. Drop the `grouping_mode=FLAT` defaults on `update_list` / `_update_list_impl` and on `self._grouping_mode` initialization.                                                                                  |
| `src/sase/ace/tui/widgets/_changespec_list_render.py`   | Delete the `render_flat` function. Update the module docstring to reflect that there is only one render path now.                                                                                                                                                                                                           |
| `src/sase/ace/tui/widgets/changespec_info_panel.py`     | Simplify `update_grouping_mode`: always show the badge for any non-empty label; drop the `"flat"` special case and the "empty hides the badge" comment block. Update the `_grouping_label` default initialization to a sane non-empty string (or compute it on first `update_grouping_mode`).                               |
| `src/sase/ace/tui/modals/help_modal/bindings.py`        | Update the CLs-tab "Grouping" section: change `"Cycle: flat→proj→date→status"` to `"Cycle: proj→date→status"`; drop the `(non-flat)` qualifier from the expand/collapse rows since grouping is always on. Maintain the 32-char description-length cap from the help-modal box-formatting rules in `src/sase/ace/AGENTS.md`. |
| `src/sase/ace/tui/actions/_state_init.py`               | No code change required (the loader already returns the new default). Audit only — confirm no hard-coded `FLAT` reference remains.                                                                                                                                                                                          |

### Tests

| File                                                                                                                   | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/ace/test_changespec_grouping_mode_state.py`                                                                     | Replace the three `…returns_flat…` tests with `…returns_by_project…` equivalents. Add a new test asserting that a file containing the literal `"flat"` falls through to the `BY_PROJECT` default (covers the on-disk migration story).                                                                                                                                                                                                                                                                                                              |
| `tests/ace/tui/test_changespec_grouping_cycle.py`                                                                      | Update the harness `_StubApp` to seed `_changespec_grouping_mode = BY_PROJECT`. Replace the cycle-order tests so the loop is `BY_PROJECT → BY_DATE → BY_STATUS → BY_PROJECT`. Delete `test_cycle_advances_flat_to_by_project`, replace `test_cycle_wraps_back_to_flat` with `test_cycle_wraps_back_to_by_project`, and update `test_four_cycles_returns_to_flat` to a 3-cycle round trip. Update toast assertion in `test_cycle_emits_cl_grouping_toast` (first cycle now goes BY_PROJECT → BY_DATE so the toast becomes `"CL grouping: by date"`). |
| `tests/ace/tui/test_changespec_grouping_integration.py`                                                                | Remove `FLAT` initial state from the harness; switch every "no banners drawn" assertion to "banners present"; update guards `if … is not FLAT` to unconditional.                                                                                                                                                                                                                                                                                                                                                                                    |
| `tests/ace/tui/test_changespec_grouped_navigation.py`                                                                  | Update fixtures using `mode=ChangeSpecGroupingMode.FLAT` to use `BY_PROJECT` (or whichever real mode the test was implicitly exercising).                                                                                                                                                                                                                                                                                                                                                                                                           |
| `tests/ace/tui/widgets/test_changespec_list_grouped.py`                                                                | Update the two assertions that `widget._grouping_mode is ChangeSpecGroupingMode.FLAT`.                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `tests/ace/tui/widgets/test_changespec_info_panel_grouping.py`                                                         | Drop the `panel.update_grouping_mode("flat")` test (or repurpose to assert that an empty label hides the badge while any real mode label shows it).                                                                                                                                                                                                                                                                                                                                                                                                 |
| `tests/ace/tui/models/test_changespec_groups_layout.py`                                                                | Replace the two `mode=ChangeSpecGroupingMode.FLAT` assertions: the `enumerate_changespec_group_keys` empty-result case becomes the empty-CL-list case, and `build_changespec_tree([], FLAT, …)` becomes `build_changespec_tree([], BY_PROJECT, …)`.                                                                                                                                                                                                                                                                                                 |
| `tests/ace/tui/test_agent_grouping_cycle.py`                                                                           | Update the harness `_changespec_grouping_mode` seed to `BY_PROJECT`; the assertion at line 264 (Agents-cycle leaves CL state alone) needs to compare against the new default.                                                                                                                                                                                                                                                                                                                                                                       |
| `tests/ace/tui/test_changespec_grouping_cycle.py::test_cycle_on_axe_tab_is_silent_noop` and `…does_not_touch_cl_state` | Update the "untouched CL state" assertions to compare against `BY_PROJECT`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

### Snapshot / golden files

- Search `tests/ace/**/snapshots/` and `tests/ace/**/*.txt` for any byte-stable CL-list snapshot files captured while
  FLAT was the default. Re-generate any that show one-row-per-CL output without banners.

### Documentation / spec hygiene

- Add a one-paragraph SDD spec under `specs/202604/remove_cls_flat_grouping.md` and a matching plan stub under
  `plans/202604/` so the change has a paper trail consistent with prior CL-grouping work (see
  `changespec_group_headings.md`, `rename_default_grouping_to_by_project.md`).
- No CLAUDE.md / AGENTS.md update required — neither file mentions the FLAT mode.

## Behavior After the Change

- **First-paint on a fresh `~/.sase`:** CLs tab opens in `BY_PROJECT`, banners visible, grouping badge
  `[group: by project (o)]` shown in the info panel.
- **Existing user with `~/.sase/changespec_grouping_mode.txt = "flat"`:** Loader falls through to default →
  `BY_PROJECT`. The next cycle press persists the new mode.
- **`o` keypress cycles:** `BY_PROJECT → BY_DATE → BY_STATUS → BY_PROJECT → …`.
- **Help modal CLs tab:** "Grouping" section reads "Cycle: proj→date→status"; the expand/collapse rows lose the
  `(non-flat)` qualifier.
- **Info-panel badge:** always shown (no longer hidden in any mode).
- **Render path:** `render_flat` is gone; every CLs render goes through the grouped builder. The patch-row fast path
  remains disabled in grouped mode (unchanged behavior — already disabled today for any user who had cycled out of
  FLAT).

## Risks & Tradeoffs

- **One-row-per-CL render is no longer reachable.** Users who relied on the bare legacy view to see every CL without
  banner overhead lose that option. Mitigation: the `BY_DATE` "Today" bucket on a typical workday is effectively a flat
  list with one banner above it, so the loss is small; if it turns into a real complaint we can revisit by adding a
  banner-suppression mode rather than restoring FLAT.
- **Single-row patch optimization is permanently off on the CLs tab.** The patch path in `_patch_changespec_row_impl`
  already refuses to run when banner rows offset indices, so all CLs-tab refreshes will be full rebuilds. This matches
  the behavior any non-FLAT user already gets, so there's no per-user perf regression — just a removal of the FLAT-only
  fast path. If a future profile flags this as hot, we can teach the patch path about banner offsets without
  re-introducing FLAT.
- **Snapshot churn.** Any captured CL-list output that assumed FLAT will need regeneration. Cost is mechanical, not
  architectural.
- **External callers / future maintainers.** Removing the enum member is a hard break for anyone (in plugins or scripts)
  who imported `ChangeSpecGroupingMode.FLAT` by name. The Explore audit found no such importers in this repo, and there
  is no public-API contract for the TUI internals; flagging in case the user has out-of-tree consumers.

## Implementation Order

1. **Models layer** — drop `FLAT` from the enum, the tree builder, and the key/walk helpers. Run
   `just test tests/ace/tui/models/` to validate the bottom layer.
2. **Persistence + cycle action + render dispatch** — change the default, the cycle tuple, and the widget dispatch. Run
   grouping/cycle test files.
3. **Help modal + info-panel badge** — surface text changes. Visual; run the modal tests and snapshot any layout
   assertions.
4. **Test sweep** — update every test fixture that initialized `FLAT` and rename the FLAT-specific test cases.
   Regenerate any stale snapshots.
5. **Full check** — `just check` (lint + mypy + test) from the workspace `sase_<N>` directory after running
   `just install` per the project workspace gotcha.

## Out of Scope

- Agents-tab grouping (separate enum, separate persistence file, separate cycle).
- Any change to fold-registry semantics, banner styling, sort order within a group, or hint-mode / jump-mode behavior.
- Migration of legacy persisted state files beyond the existing ValueError-fallback (no proactive rewrite).
