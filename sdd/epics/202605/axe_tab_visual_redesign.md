---
create_time: 2026-05-11 20:28:03
status: done
prompt: sdd/prompts/202605/axe_tab_visual_redesign.md
bead_id: sase-2y
tier: epic
---
# AXE Tab Visual Redesign Plan

## Goal

Make the AXE tab substantially easier to scan and debug:

- AXE sidebar entries must never wrap.
- The sidebar should grow dynamically to fit realistic lumberjack, chop, and user command labels.
- Lumberjack rows, chop rows, and user/background command rows must be visually distinct at a glance.
- Controlled AXE/lumberjack output should get purpose-built syntax highlighting instead of plain ANSI parsing.
- PNG visual snapshots should prove the layout and styling behavior, including long labels and mixed row types.

This is intentionally split into phases that can be handled by distinct agent instances. Each phase should keep changes
small enough to review independently while leaving the AXE tab usable after every merge.

## Current System Shape

Relevant production code:

- `src/sase/ace/tui/app.py`: composes `#axe-view` as a left `#bgcmd-list-container` plus right `#axe-container`.
- `src/sase/ace/tui/styles.tcss`: currently fixes `#bgcmd-list-container` at `width: 35`, `min-width: 30`,
  `max-width: 50`.
- `src/sase/ace/tui/widgets/bgcmd_list.py`: renders AXE sidebar row types: `LumberjackItem`, `ChopItem`, and
  `BgCmdItem`.
- `src/sase/ace/tui/actions/axe_display/_loaders.py`: builds the flat AXE row list from cached lumberjack/chop/bgcmd
  data and preserves selection identity.
- `src/sase/ace/tui/actions/axe_display/_render.py`: refreshes the sidebar and dashboard from cache.
- `src/sase/ace/tui/widgets/axe_dashboard.py`: renders lumberjack overview, chop run detail, bgcmd output, and the
  current ANSI parse cache.
- `src/sase/axe/lumberjack.py`: emits controlled lumberjack log lines shaped like
  `[YYYY-MM-DD HH:MM:SS] [lumberjack] message`.
- `src/sase/axe/chop_runner.py` and `src/sase/axe/chop_script_runner.py`: record per-chop output; script output may be
  arbitrary external text, while agent-chop launch lines are controlled.

Relevant tests:

- `tests/ace/tui/visual/test_ace_png_snapshots.py`: existing 120x40 PNG snapshot fixtures for AXE tree, chop detail,
  running chop detail, empty state, error state, and bgcmd rows.
- `tests/ace/tui/widgets/test_axe_dashboard_chop_detail.py`: unit coverage for AXE dashboard rendering.
- `tests/ace/tui/widgets/test_axe_dashboard_ansi_cache.py`: ANSI cache behavior.
- `tests/ace/tui/widgets/test_bgcmd_list_disk_free.py`: sidebar render path must not read config from disk.
- `tests/ace/tui/test_axe_navigation.py`: navigation/render should use cached data, not synchronous disk reads.
- `tests/ace/tui/test_axe_selection_identity.py`: selection must survive row list rebuilds.

## Design Direction

The AXE sidebar should read as an operational tree, not a flat list:

- Lumberjacks are top-level sections with a strong left accent, clear fold/status marker, and a distinct color.
- Chops are child rows with tree guides, compact run-status icons, and a different quieter color treatment.
- User/background commands are separated below the lumberjack tree and use a command badge/slot marker so they cannot be
  mistaken for scheduled AXE work.
- Row text must be single-line. The widget should compute natural row width, ask the container to grow, and still render
  with `no_wrap` plus ellipsis for pathological labels or very narrow terminals.
- The right dashboard should preserve the current cache-first navigation behavior.

Controlled output should use a small semantic highlighter before falling back to ANSI/plain rendering:

- Lumberjack aggregate logs: timestamp, lumberjack name, status words, chop names, PIDs, durations, errors, and counts.
- Controlled chop output: agent launch lines and internal error/timeout/missing-script messages.
- External script output and user background command output: preserve ANSI and cap/tail behavior. Do not invent language
  highlighting for arbitrary external logs.

## Phase 1: Sidebar Width and No-Wrap Foundation

Owner: layout/widget agent.

Scope:

- Add a `BgCmdList.WidthChanged` message similar to `AgentList.WidthChanged` and `ChangeSpecList.WidthChanged`.
- Compute natural sidebar row width during `BgCmdList.update_list` from the formatted Rich `Text.cell_len`, including
  padding, border, scrollbar gutter, jump hints, tree prefixes, and badges.
- Add `_requested_width` / `_target_width` state to `BgCmdList`.
- Handle the width event in `actions/event_handlers.py` and resize `#bgcmd-list-container`.
- Replace fixed-width-only CSS with dynamic bounds:
  - keep a practical minimum;
  - allow wider than 50 cells;
  - preserve enough width for `#axe-container`;
  - clamp to terminal size so tiny terminals do not break layout.
- Ensure every sidebar option renderable is no-wrap. If Textual/Rich still wraps at impossible widths, add explicit
  ellipsizing at the final clamped width rather than allowing multi-line rows.

Tests:

- Add focused widget tests for long lumberjack, chop, and bgcmd labels asserting the requested width is large enough.
- Add a regression test that rendered option `Text` is no-wrap or otherwise cannot wrap.
- Add an event-handler test for `BgCmdList.WidthChanged` clamping and applying container width.
- Keep `test_bgcmd_list_disk_free.py` green: width calculation must not read disk.

Acceptance:

- Long row labels do not wrap in the AXE sidebar.
- The AXE sidebar grows when labels require it.
- Navigation remains cache-only and existing selection identity tests still pass.

## Phase 2: Sidebar Visual Hierarchy

Owner: sidebar rendering agent.

Scope:

- Redesign row formatters in `bgcmd_list.py`:
  - lumberjack rows: strong top-level marker, fold/state affordance, name, optional compact status/cycle/error chip;
  - chop rows: child connector, last-run icon, shorter metadata, visually subordinate style;
  - bgcmd rows: command/slot badge, running/done indicator, command label style distinct from AXE-managed rows.
- Add an explicit visual divider or spacer before bgcmd rows when both lumberjacks/chops and bgcmds are present.
- Keep row labels concise. Do not add explanatory prose inside the app.
- Keep jump hints readable and aligned after the style changes.
- Update `jump_all_modal.py` labels if needed so the same item taxonomy is clear in jump-all mode.

Tests:

- Unit-test formatter output by row type, checking plain text, IDs, and distinct style spans.
- Extend selection/fold tests if a divider row is introduced; divider rows should not become selectable unless product
  direction explicitly wants that.
- Add/refresh PNG snapshots showing mixed lumberjack/chop/bgcmd rows and selected rows.

Acceptance:

- A screenshot with mixed row types makes lumberjack, chop, and user command entries immediately distinguishable.
- Existing `j`/`k`, folds, jump hints, and selection restoration still work.

## Phase 3: Semantic AXE Output Highlighting

Owner: dashboard/output rendering agent.

Scope:

- Introduce a small renderer module for AXE-controlled logs, likely under `src/sase/ace/tui/widgets/` or
  `src/sase/ace/tui/util/`.
- Add a classifier for known source types:
  - lumberjack aggregate log;
  - controlled chop/agent launch output;
  - generic ANSI output fallback.
- Implement a Rich `Text` highlighter for controlled lines:
  - timestamp dim;
  - lumberjack/chop names colored consistently with sidebar taxonomy;
  - status words (`success`, `failure`, `timeout`, `missing`, `running`) styled by severity;
  - `PID`, `Exit`, durations, counts, quoted chop names, and error lines styled intentionally.
- Preserve `cap_ansi_output`, per-source caching, and tail-biased rendering.
- Make cache keys include source type and identity, not just source ID, so semantic and ANSI paths cannot collide.
- Do not syntax-highlight arbitrary external script output beyond ANSI preservation.

Tests:

- Add parser/highlighter unit tests with representative lumberjack lines from `Lumberjack._log` and controlled
  `chop_runner` output.
- Extend cache tests to prove semantic renders cache independently from ANSI renders.
- Add dashboard unit tests showing lumberjack log output uses semantic highlighting when rendered as a log.

Acceptance:

- Controlled lumberjack/AXE output is readable without depending on external ANSI colors.
- Unknown or external output remains fast, capped, and safe.

## Phase 4: Dashboard Polish and Integration

Owner: AXE detail-panel agent.

Scope:

- Revisit `AxeDashboard` layout after the sidebar grows:
  - status/header text should survive narrower right panels;
  - long headers should crop cleanly rather than overflow into adjacent content;
  - tables should keep stable columns or degrade to a compact vertical format when width is tight.
- Apply the semantic output renderer to the right output panel for source types that are known.
- Consider showing the selected lumberjack log tail below or after the overview only if it improves debugging without
  crowding the chop table. If added, keep it cache-backed from `LumberjackSnapshot.log_tail`.
- Keep bgcmd and arbitrary chop-script output on the ANSI/plain fallback.
- Make visual styling coherent with sidebar colors without turning the whole AXE tab into one dominant hue.

Tests:

- Unit-test right-panel render modes at normal and narrow widths where feasible.
- Add targeted assertions for no traceback/exception on empty output, huge output, and narrow terminal state.
- Re-run existing AXE widget tests and update expectations only when the product output intentionally changes.

Acceptance:

- The right panel remains readable when the sidebar widens.
- Controlled output highlighting is visible in the dashboard.
- The UI still performs well with large logs.

## Phase 5: PNG Snapshot Suite

Owner: visual regression agent.

Scope:

- Expand `tests/ace/tui/visual/test_ace_png_snapshots.py` with deterministic fixtures that demonstrate the new behavior:
  - long lumberjack and chop labels causing dynamic sidebar widening without wrapping;
  - mixed row taxonomy: lumberjack, chop, and user/background command rows in one screen;
  - selected lumberjack row;
  - selected chop row with controlled highlighted output;
  - selected bgcmd row showing distinct user-command styling;
  - narrow terminal or constrained-width case proving ellipsis/no-wrap behavior.
- Keep existing AXE snapshots where they still add value; rename only if necessary.
- Use deterministic timestamps, fixed pids, fixed run IDs, and fixed output strings.
- Inspect generated PNGs manually before accepting goldens.

Commands:

```bash
just install
just test-visual -- --sase-update-visual-snapshots -k "axe_"
just test-visual -- -k "axe_"
```

Acceptance:

- PNGs visibly prove no wrapping, dynamic sidebar width, and row-type distinction.
- Snapshot tests are deterministic on repeat runs without update mode.
- Failure artifacts remain useful for reviewing visual regressions.

## Phase 6: Docs, Final Verification, and Cleanup

Owner: integration/finalization agent.

Scope:

- Update `docs/ace.md` AXE tab section with concise behavior notes:
  - sidebar row taxonomy;
  - dynamic no-wrap sidebar behavior;
  - controlled-output highlighting and fallback behavior.
- Run focused tests while iterating, then the repo check required after code changes.
- Review color usage in `styles.tcss` and `bgcmd_list.py` so the final palette is balanced and accessible in the
  existing ACE theme.
- Remove obsolete comments that refer to the AXE panel as only a "background command list".

Commands:

```bash
just install
just test-visual -- -k "axe_"
just test -- -k "axe or bgcmd"
just check
```

Acceptance:

- Documentation matches the shipped behavior.
- AXE visual snapshots pass.
- Focused AXE/bgcmd tests pass.
- `just check` passes before final handoff.

## Cross-Phase Constraints

- Do not move backend/domain behavior into Python TUI code if it belongs in `../sase-core`; this plan appears
  presentation-only, so it should stay in this repo.
- Do not perform synchronous disk reads from AXE navigation or render paths.
- Do not modify memory files.
- Do not revert unrelated user changes if the worktree becomes dirty.
- Keep each phase independently reviewable; avoid broad refactors of unrelated ACE tabs.

## Risks

- Textual `OptionList` may wrap renderables despite Rich `Text.no_wrap`; Phase 1 should prove actual rendered behavior
  with a visual test, not only unit assertions.
- A wider sidebar can starve the dashboard on 120-column snapshots. Clamp dynamically and use ellipsis before the right
  panel becomes unusable.
- Semantic highlighting can become expensive if it reparses large logs every tick. Keep caps and cache behavior from the
  existing ANSI path.
- External chop scripts produce arbitrary output. Highlight only controlled formats and preserve fallback rendering.
