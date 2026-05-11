---
create_time: 2026-05-11 16:33:33
bead_id: sase-2w
tier: epic
status: done
prompt: sdd/prompts/202605/axe_lumberjack_chop_sidebar.md
---
# AXE Lumberjack/Chop Sidebar Plan

## Goal

Replace the AXE tab's synthetic `sase axe` sidebar entry with a tree where lumberjacks are the main entries and chops
are child entries. Selecting a chop should show the output from that chop's most recent run by default, and `ctrl+n` /
`ctrl+p` should cycle through up to the last 10 recorded run outputs for that selected chop.

The design must preserve the existing AXE-tab performance guarantees: navigation and display refreshes must paint from
memory caches, not from synchronous disk reads on every keypress.

## Current System Shape

The relevant code is concentrated in:

- `src/sase/axe/lumberjack.py`: runs configured chops and currently logs aggregated lumberjack output.
- `src/sase/axe/state.py`: owns persisted AXE/lumberjack state, logs, metrics, and tail readers.
- `src/sase/ace/tui/actions/axe_display/_data.py`: async collector payload for the AXE tab.
- `src/sase/ace/tui/actions/axe_display/_loaders.py`: applies collector data, builds AXE sidebar items, and preserves
  selection identity.
- `src/sase/ace/tui/actions/axe_display/_render.py`: renders the side panel and detail dashboard from caches.
- `src/sase/ace/tui/widgets/bgcmd_list.py`: AXE sidebar row types and row rendering.
- `src/sase/ace/tui/widgets/axe_dashboard.py`: AXE detail/dashboard rendering and ANSI parse cache.
- `src/sase/ace/tui/actions/agents/_folding.py`: currently treats AXE as one fold rooted at `axe`.
- `src/sase/ace/tui/actions/agents/_panel_detail.py`: owns the `ctrl+n` / `ctrl+p` app actions used on the Agents tab.

Existing tests already pin two important invariants:

- `tests/ace/tui/test_axe_navigation.py`: AXE navigation must not touch disk.
- `tests/ace/tui/test_axe_selection_identity.py`: AXE selection must follow stable item identities across rebuilds.

This feature should extend those contracts rather than replacing them.

## Product Design

The AXE tab should feel like an operational tree:

- Top-level sidebar rows are lumberjacks, sorted as the config currently sorts them.
- Expanded lumberjacks show their configured chops as child rows.
- Background commands remain in the same sidebar, visually separated below the lumberjack tree.
- The synthetic `sase axe` row is removed from the sidebar. Daemon state stays visible through the AXE top/status panel
  and footer, so start/stop controls remain discoverable without a selectable daemon row.
- Selecting a lumberjack shows a compact overview: status, interval, cycles, errors, and a table of chops with last run
  status/time.
- Selecting a chop shows the selected run output. The default run index is `0`, meaning newest run.
- `ctrl+n` moves to the next older run for that chop, stopping or wrapping only within the available bounded history.
  `ctrl+p` moves toward newer output. The UI should show a clear `Run 1/N` indicator.
- Empty states should be explicit: no chops configured, no run recorded yet, no output captured, or output trimmed.

## Data Contract

Add a bounded per-chop run-history contract under each lumberjack's existing state directory:

```text
~/.sase/axe/lumberjacks/<lumberjack>/
  chops/
    <chop>/
      runs/
        <run-id>.json
        <run-id>.log
      index.json
```

Recommended metadata fields:

- `run_id`: stable timestamp-based ID, sortable newest-first.
- `lumberjack_name`
- `chop_name`
- `started_at`
- `finished_at`
- `duration_ms`
- `status`: `success`, `failure`, `timeout`, `missing_script`, or `agent_launched`.
- `exit_code`
- `agent_pid`
- `error`
- `traceback`
- `output_bytes`
- `output_log`

Keep only the newest 10 entries per chop in `index.json`, and prune older run metadata/log files. The TUI collector
should read at most those 10 entries, and should tail output logs with the existing seek-based bounded reader rather
than reading arbitrary-sized files.

Record only actual chop attempts. Do not create run entries for ordinary `run_every` skips; those would pollute the
history and make `ctrl+n` less useful.

## Phase 1: Persist Chop Run History

Owner: backend/state agent.

Scope:

- Add chop run-history dataclasses and helpers to `src/sase/axe/state.py`.
- Update `ensure_lumberjack_dirs` to create the per-chop container lazily through helper functions, not for every
  possible chop up front.
- Extend `Lumberjack._run_single_chop` and `_launch_agent_chop` to capture enough run output and metadata to write a
  bounded history entry for every actual attempt.
- Preserve the existing aggregated lumberjack log; this feature adds per-chop history rather than replacing current
  logs.
- Use atomic JSON writes for indexes and metadata.
- Prune history to the newest 10 runs per chop.

Tests:

- Add unit tests near `tests/test_axe_lumberjack_state.py` for write/read/prune behavior, invalid/missing JSON, tailing
  bounded output, and path creation.
- Add lumberjack tests that script success, script failure, timeout, missing script, and agent launch attempts produce
  the expected run-history entries.

Acceptance:

- A chop with 12 attempts leaves exactly 10 readable newest entries.
- Existing lumberjack status, metrics, and logs continue to pass current tests.
- The read APIs do not scan or parse unbounded logs.

## Phase 2: Extend AXE Collector and Cache Model

Owner: TUI data/cache agent.

Scope:

- Add TUI-facing dataclasses in `actions/axe_display/_data.py`, for example `ChopRunSnapshot`, `ChopSnapshot`, and
  `LumberjackSnapshot`.
- Change the collector to load configured lumberjacks and their configured chops, not just lumberjack names.
- Collect each chop's newest run history, capped at 10, in the background collector.
- Add the matching cache fields to `StateInitMixin`.
- Update `_apply_axe_status_data` to apply chop metadata/run caches alongside existing lumberjack and bgcmd caches.
- Update targeted refresh so `y` on a selected chop refreshes only that chop's cached history.
- Add stable item identity support for chop rows: `("chop", lumberjack_name, chop_name)`.

Tests:

- Extend `tests/ace/tui/test_axe_collector.py` to assert chop metadata and run history are populated once per configured
  chop.
- Extend `tests/ace/tui/test_axe_force_refresh.py` for selected-chop targeted refresh.
- Extend `tests/ace/tui/test_axe_navigation.py` so navigation over lumberjack and chop rows still raises if any disk
  reader is called from the render/navigation path.

Acceptance:

- Full refresh disk I/O happens in the async collector.
- `j` / `k`, sidebar highlight updates, and dashboard rendering use only cached data.
- Missing run history is represented as an empty cache entry, not a failing display path.

## Phase 3: Replace Sidebar Structure

Owner: AXE sidebar/navigation agent.

Scope:

- Replace `AxeParentItem` with top-level `LumberjackItem` rows.
- Add `ChopItem(lumberjack_name, chop_name)` child rows.
- Keep `BgCmdItem` rows, visually separated after the lumberjack tree.
- Update `BgCmdList.update_list` and row formatters:
  - lumberjack rows should be top-level and foldable;
  - chop rows should be indented children with compact status markers;
  - bgcmd rows should keep their existing identity and affordance.
- Update `_build_axe_items` to build `LumberjackItem -> ChopItem* -> BgCmdItem*`.
- Replace the single `"axe"` fold key with per-lumberjack fold keys, probably `lumberjack:<name>`.
- Update fold actions in `actions/agents/_folding.py`:
  - `l` expands the focused lumberjack, or the parent of a focused chop;
  - `h` collapses the focused lumberjack, or moves from a chop to its parent and collapses;
  - `L` expands all lumberjacks;
  - `H` collapses all lumberjacks.
- Preserve AXE saved selection by identity across config changes, bgcmd changes, and fold changes.

Tests:

- Rewrite/extend `tests/ace/tui/test_axe_selection_identity.py` for lumberjack and chop identities.
- Add sidebar row rendering tests in `tests/ace/tui/widgets/test_bgcmd_list_disk_free.py` or a new focused test file.
- Add fold behavior tests for focused lumberjack, focused chop, expand-all, and collapse-all.

Acceptance:

- No `sase axe` option appears in the sidebar.
- Lumberjacks are the main entries.
- Chops are selectable child entries.
- Selection remains stable when new lumberjacks, chops, or bgcmds appear.

## Phase 4: Render Lumberjack and Chop Detail Views

Owner: AXE dashboard/detail agent.

Scope:

- Update `_derive_axe_view_from_selection` so it distinguishes:
  - selected lumberjack overview;
  - selected chop run output;
  - selected bgcmd output.
- Replace `_axe_current_view` with a richer internal view type or companion fields. Avoid overloading `"axe"` for
  lumberjack and chop views.
- Add dashboard rendering methods:
  - `update_lumberjack_overview(...)`;
  - `update_chop_run_display(...)`.
- Keep ANSI parsing cached by source ID. Use a source ID that includes `lumberjack`, `chop`, and `run_id` so different
  runs do not collide.
- Show run metadata in the status section: chop name, parent lumberjack, run status, time, duration, and `Run N/M`.
- Update `AxeInfoPanel` copy so the top bar remains useful without the `sase axe` row.
- Update clear-output behavior:
  - selected chop clears/prunes that chop's run history only if the existing clear-output affordance is intentionally
    kept for chops;
  - otherwise leave chop history intact and show a warning that run history is immutable from the TUI. The safer default
    is to leave history intact unless product direction says otherwise.

Tests:

- Add unit tests for dashboard output rendering, empty run states, and ANSI cache source separation.
- Update existing AXE dashboard tests so they cover lumberjack overview and chop detail.
- Add integration tests that selecting a chop displays newest output by default.

Acceptance:

- Selecting a lumberjack never shows the old daemon log as the primary content.
- Selecting a chop shows that chop's newest run output.
- Large outputs are capped/tail-rendered and do not cause unbounded parse work.

## Phase 5: `ctrl+n` / `ctrl+p` Run-History Navigation

Owner: keymap/interaction agent.

Scope:

- Reuse the existing configured app actions `next_agent_file` and `prev_agent_file`; do not add new default keymap
  fields unless this proves necessary.
- Update `AgentPanelDetailMixin.action_next_agent_file` and `action_prev_agent_file` to branch on `current_tab == "axe"`
  and dispatch to AXE run-history navigation.
- Add AXE state for selected run offset by chop identity, for example
  `_axe_chop_run_offsets: dict[tuple[str, str], int]`.
- Clamp offsets to available history length, max 10.
- Reset to newest run when switching to a different chop or when the selected chop receives a newer run, unless the user
  has explicitly moved to an older run and that run still exists.
- Update footer/help text from "Next / prev lumberjack output" to "Next / previous chop run" on the AXE tab.

Tests:

- Add unit tests for offset clamping, newest default, per-chop offset persistence, and behavior with zero/one/many runs.
- Add an AXE-tab integration test that presses `ctrl+n` / `ctrl+p` on a selected chop and verifies the displayed run
  changes without disk reads.
- Update `tests/test_keybinding_footer_status.py`, `tests/test_keymaps.py`, and help-modal tests as needed for the
  revised label.

Acceptance:

- `ctrl+n` / `ctrl+p` do nothing disruptive on lumberjack rows and bgcmd rows.
- On chop rows, they cycle or clamp predictably through only that chop's available cached history.
- Navigation remains instant under the existing no-disk-on-navigation invariant.

## Phase 6: Visual Polish, Regression, and Performance Validation

Owner: integration/QA agent.

Scope:

- Update visual fixtures and PNG snapshots for the AXE tab.
- Tune colors and symbols so the tree is readable:
  - lumberjack rows: strong top-level labels, clear running/error/stopped markers;
  - chop rows: quieter child labels with status/result marker and concise last-run hint;
  - selected rows: bold but not noisy;
  - bgcmd rows: remain distinct from the lumberjack/chop tree.
- Verify text fits in the existing left panel width and truncates gracefully.
- Ensure jump hints still align with row indices.
- Ensure copy/snapshot actions include the selected chop run output when appropriate.
- Run the expected validation commands.

Tests/commands:

- `just install` first if the workspace has not been prepared recently.
- Targeted pytest for the new backend/TUI tests while iterating.
- `just check` before handing off, because this repo requires it after non-bead file changes.
- Visual snapshot update/review for AXE after the behavior is stable.

Acceptance:

- AXE tab first paint is visually coherent at 120x40 and narrower terminal sizes.
- Current AXE, bgcmd, keymap, and visual tests pass.
- No synchronous disk read is introduced into selection movement or run-history cycling.

## Cross-Phase Notes

- Do not move shared AXE persistence behavior into Rust core in this feature unless the existing architecture already
  forces it. Current AXE/lumberjack persistence lives in Python under `src/sase/axe/state.py`; keep the feature
  consistent with that local boundary.
- Keep file edits scoped. This feature has enough moving parts without unrelated refactors.
- Preserve existing background command behavior. Bgcmd rows are adjacent operational entries, not chop children.
- Treat all agent runtimes uniformly for agent chops; do not special-case Claude/Gemini/Codex/Qwen/OpenCode.
- The plan intentionally separates persistence, collector cache, sidebar tree, rendering, keymaps, and QA so distinct
  agent instances can work sequentially with clear handoff points.
