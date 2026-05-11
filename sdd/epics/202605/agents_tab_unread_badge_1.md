---
create_time: 2026-05-11 11:06:25
status: done
prompt: sdd/prompts/202605/agents_tab_unread_badge_1.md
bead_id: sase-2u
tier: epic
---
# Agents Tab Unread Completion Badge Plan

## Context

Agent completion notifications are no longer sent to the TUI. The TUI already has session-local unread state for
completed agent rows via `_unread_completed_agent_ids`, row-level unread rendering, unread counts in `AgentInfoPanel`,
and jump-to-next-unread navigation. Today that state is only visible once the user is on the Agents tab, and first-seen
terminal rows are intentionally not marked unread. This work moves the off-tab signal to the tab title: when completed
agent rows are unread and the Agents tab is not focused, the tab title should render as `Agents(N)` in yellow, where `N`
is the number of unread completed top-level agent rows since the last time the Agents tab was focused.

The behavior must also work on `sase ace` startup. If the initial tab is not Agents and the initial agent load finds two
unread completed agent rows, the first visible tab bar should show `Agents(2)` highlighted yellow.

## Product Rules

- The Agents tab title is `Agents` when there are no unread completed agent rows, or while the Agents tab is focused.
- The Agents tab title is `Agents(N)` when the Agents tab is not focused and `N > 0`.
- The off-tab unread badge uses the same row identities as the existing completed-agent unread system.
- Focusing the Agents tab acknowledges the tab-level badge by clearing automatically generated unread completed-agent
  state for visible selected/focused rows according to existing row unread rules, and by removing the off-tab tab title
  badge.
- Manual unread markers must continue to behave as they do today for row rendering and navigation.
- Counts should be based on visible top-level agent rows, not workflow child rows or stale hidden identities.

## Phase 1 - Tab Bar Badge Rendering

Owner scope: `src/sase/ace/tui/widgets/tab_bar.py` and widget-level tests.

Implement a small API on `TabBar` for per-tab badges/alerts, with Agents as the only current caller. Keep the existing
labels and click ranges stable by deriving ranges from the rendered label text. Add focused-tab precedence so the active
tab still uses its normal active color, while an inactive Agents tab with an unread count uses a yellow alert style.

Expected implementation shape:

- Add state such as `_tab_badges: dict[TabName, int]` and `_tab_alerts: set[TabName]`, or a narrowly named Agents-only
  equivalent if that better fits the widget.
- Render `Agents(<count>)` with no extra space before the parenthesis.
- Use a yellow style for inactive alerted Agents tab, matching the existing unread orange/yellow palette where
  practical.
- Add focused unit tests in `tests/test_ace_tui_widgets.py` for:
  - inactive Agents with count 2 renders `Agents(2)` and has yellow style;
  - active Agents suppresses the alert color and count;
  - zero count restores plain `Agents`;
  - click ranges still identify the Agents tab when the label includes the count.

Exit criteria:

- `pytest tests/test_ace_tui_widgets.py -k tab_bar` passes.
- The widget API is generic enough that app code does not need to mutate private `TabBar` fields.

## Phase 2 - Unread State Semantics And App Wiring

Owner scope: agent loading/finalization and tab switching, primarily
`src/sase/ace/tui/actions/agents/_loading_finalize.py`, `src/sase/ace/tui/actions/agents/_core.py`,
`src/sase/ace/tui/actions/_state_init.py`, and `src/sase/ace/tui/app.py`.

Wire the tab badge to the existing unread-agent state. The key design decision is to make startup/off-tab completed rows
count as unread even when their previous status is unknown, while preserving the existing rule that the selected
Agents-tab row is not marked unread just because it is visible.

Expected implementation shape:

- Add a helper that computes the visible top-level unread completed count from `app._agents` and
  `_unread_completed_agent_ids`.
- Update `TabBar` from one central app helper, e.g. `_refresh_agents_tab_unread_badge()`, called after every
  `_sync_unread_completed_agents`, after tab switches, and after explicit unread clears/toggles.
- Extend `_sync_unread_completed_agents` so first-seen terminal rows are marked unread when `on_agents_tab` is false.
  Keep first-seen selected-row behavior on the Agents tab read/acknowledged.
- When `watch_current_tab` switches to `agents`, clear/suppress the tab badge immediately and then let the existing
  Agents-tab finalization and selection acknowledgment reconcile row unread state.
- Ensure manual unread toggles, jump-to-next-unread, row selection, dismissal, and filtering all refresh the tab badge
  when they mutate unread state.
- Do not reintroduce TUI completion notifications or notification-store writes for agent completion.

Tests to add/update:

- Update `tests/ace/tui/test_agent_unread_finalizer.py` for first-seen terminal off-tab rows becoming unread.
- Add app-level/unit tests that fake a `TabBar` and assert:
  - off-tab completion transition updates `Agents(N)`;
  - switching to Agents clears the tab badge;
  - row acknowledgment/toggle updates the badge count;
  - child workflow rows and hidden/stale unread identities are not counted.

Exit criteria:

- Agent unread unit tests pass.
- No existing row unread behavior regresses except the intentional startup/off-tab first-seen terminal behavior.

## Phase 3 - Startup Integration And PNG Visual Snapshots

Owner scope: startup visual fixtures and committed PNG goldens, primarily
`tests/ace/tui/visual/test_ace_png_snapshots.py` and `tests/ace/tui/visual/snapshots/png/`.

Add deterministic PNG coverage for the new top-bar behavior. The current visual harness already patches startup agent
loading and renders 120x40 PNGs, so this phase should extend that harness instead of creating a new one.

Expected tests:

- A startup/off-tab snapshot where the current tab remains CLs, the patched startup loader returns two completed
  top-level unread agent rows, and the tab bar shows yellow `Agents(2)`.
- A follow-up snapshot or visual assertion after switching to Agents showing that the title returns to normal `Agents`
  and the Agents view itself still renders cleanly.
- Keep fixture data deterministic: fixed timestamps, stable query, no real notification store or filesystem agent scan.

Snapshot workflow:

- Run the visual tests with `--sase-update-visual-snapshots` only after inspecting the rendered artifacts.
- Commit the new PNG goldens alongside the test code.

Exit criteria:

- `pytest tests/ace/tui/visual/test_ace_png_snapshots.py -m visual` passes in an environment with the visual extra.
- The new goldens clearly show both the yellow off-tab alert and the cleared focused-tab state.

## Phase 4 - Integration Sweep And Regression Guardrails

Owner scope: cross-cutting cleanup, verification, and any small follow-up changes discovered by phases 1-3.

Run the targeted test groups first, then the repo check. Look specifically for stale tab badge state after non-visual
mutations such as dismissing agents, applying search filters, grouping changes, and manual unread toggles.

Verification commands:

- `just install` if the workspace has not been prepared recently.
- `pytest tests/test_ace_tui_widgets.py -k tab_bar`
- `pytest tests/ace/tui/test_agent_unread_finalizer.py tests/ace/tui/test_agent_unread_selection.py tests/ace/tui/test_agent_unread_navigation.py`
- `pytest tests/ace/tui/visual/test_ace_png_snapshots.py -m visual`
- `just check`

Exit criteria:

- All targeted tests and `just check` pass, or any environment-only visual dependency gap is documented with the exact
  command that could not run.
- The final diff contains no unrelated refactors and no completion-notification reintroduction.
