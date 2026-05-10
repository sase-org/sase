---
create_time: 2026-05-10 01:04:55
status: wip
prompt: sdd/prompts/202605/remove_ace_tab_counts.md
---
# Remove ACE TUI Tab Title Counts

## Goal

Remove numeric count suffixes from the `sase ace` TUI tab titles (`CLs`, `Agents`, `AXE`) and prune the refresh work
that exists only to keep those title counts current. The visible tab titles should stay stable and compact, while
existing count displays in info panels, footers, cleanup modals, and list panels remain unchanged.

## Current Findings

- Tab titles are rendered by `src/sase/ace/tui/widgets/tab_bar.py`.
- `TabBar` currently stores per-tab count state, keymap-derived suffix hints, and an Agents loading flag.
- Count updates enter the tab bar through:
  - `ChangeSpecDisplayMixin._update_cls_tab_count()`
  - `finalize_agent_list()` in `actions/agents/_loading_finalize.py`
  - `AgentsDisplayMixin._refresh_tab_bar_agent_counts()`
  - `AxeDisplayLoadersMixin._update_axe_tab_count()`
  - startup loading state in `actions/startup.py`
- The count work has different performance implications:
  - CL query/hidden counts are already mostly produced while filtering, and hidden counts still feed
    `ChangeSpecInfoPanel`.
  - Agents tab counts require scans over `_agents` and `_hideable_agents` that are otherwise only needed for the tab
    title in some paths.
  - AXE tab counts loop through cached lumberjack status and background-command slots for the title, while footer counts
    are handled separately.
- Tests currently assert tab-count rendering in:
  - `tests/test_ace_tui_widgets.py`
  - `tests/ace/tui/test_startup_loading_indicators.py`
  - `tests/ace/tui/test_axe_navigation.py`

## Proposed Design

1. Make `TabBar` render fixed labels only:
   - `CLs`
   - `Agents`
   - `AXE`

2. Preserve non-count behavior:
   - Active/inactive styling stays the same.
   - Click ranges still cover each visible tab label.
   - `update_tab()` remains the active-tab API.
   - Keep the Agents first-load ellipsis only if we still want startup feedback in the tab bar; otherwise move that
     expectation fully to `AgentInfoPanel` and the list loading indicator. My recommendation is to keep a lightweight
     `set_agents_loading(bool)` for now because it is not a count and avoids changing startup affordance at the same
     time.

3. Remove tab-count APIs and state from `TabBar`:
   - Delete `_cls_*_count`, `_agents_*_count`, `_axe_*_count`, and show-hidden count state used only for suffix
     rendering.
   - Replace `update_agents_count(..., loading=...)` with a narrow loading-only method if keeping the ellipsis.
   - Remove `_append_tab_with_suffix()` and replace it with a simpler `_append_tab()` helper.

4. Stop count-only calls from refresh paths:
   - Remove `_update_cls_tab_count()` calls from ChangeSpec loading/refilter paths, or reduce the method to a no-op
     temporarily if tests/mixins still depend on the method shape.
   - Remove the count math in `finalize_agent_list()` that only feeds `TabBar`.
   - Remove or no-op `_refresh_tab_bar_agent_counts()` and drop its calls from fast-path kill/dismiss code once tests
     are updated.
   - Remove `_update_axe_tab_count()` and its calls where its only effect is `TabBar.update_axe_count()`.

5. Keep counts that are still product-visible elsewhere:
   - Keep `_hidden_reverted_count` and `_hidden_submitted_count` because `ChangeSpecInfoPanel.update_hidden_counts()`
     uses them.
   - Keep `_get_bgcmd_counts()` and footer updates because conditional keybindings and footer state still use
     running/done background-command counts.
   - Keep agent cleanup/counting code used by cleanup modals, info panels, and command availability.

## Implementation Steps

1. Update `TabBar`.
   - Simplify internal state to current tab, optional agents loading flag, click ranges, and keymap registry if still
     needed elsewhere.
   - Render fixed labels with the existing active colors.
   - Ensure the plain text has stable separators so click detection remains deterministic.

2. Update tab-count callers.
   - Replace startup `update_agents_count(..., loading=True)` with the new loading-only call, if keeping the ellipsis.
   - Remove or no-op CL/Agents/AXE title-count update methods and their expensive local count calculations.
   - Remove imports that only existed for `TabBar` count updates.

3. Update tests.
   - Replace suffix assertions with fixed-label assertions.
   - Keep or revise startup loading tests based on whether the Agents ellipsis remains.
   - Replace the AXE tab count disk-read test with a refresh-path assertion that navigation/display still uses cached
     AXE data; the old test becomes irrelevant if the method is removed.

4. Run targeted checks first:
   - `just install` if this workspace has not been prepared recently.
   - `pytest tests/test_ace_tui_widgets.py tests/ace/tui/test_startup_loading_indicators.py tests/ace/tui/test_axe_navigation.py tests/test_agent_kill_dismiss_fast_path.py`

5. Run the repo check before finishing because this will be a code change:
   - `just check`

## Risks and Mitigations

- Risk: removing tab counts also removes quick visibility into hidden/done counts.
  - Mitigation: verify those counts still appear where action decisions are made: info panels, footers, list panels,
    cleanup modals, and command palette availability.

- Risk: test harnesses may stub `_update_cls_tab_count()` or `_refresh_tab_bar_agent_counts()`.
  - Mitigation: update stubs only where they were asserting the old title-count behavior; keep temporary no-op methods
    if removing them causes unnecessary mixin churn.

- Risk: the performance gain may be modest if the dominant refresh cost is list/detail rendering rather than count
  suffix updates.
  - Mitigation: remove count-only list scans where obvious, but avoid broad refactors. After the change, use existing
    TUI perf tracing (`SASE_TUI_PERF=1`) to compare refresh paths if more tuning is needed.

## Acceptance Criteria

- ACE tab titles no longer show numeric count suffixes.
- Tab switching and mouse clicks still work.
- Agents startup loading still has appropriate feedback, either via the retained tab ellipsis or existing loading
  indicators.
- Footer/info-panel counts that drive actions remain intact.
- Targeted tests and `just check` pass.
