---
create_time: 2026-05-08 22:09:20
status: done
---
# Remove Agents Header Position Fraction

## Goal

Remove the loaded-state `Agents: <N>/<M>` position fraction from the Agents-tab info panel while keeping the new count
strip (`unread · running · total`) and the existing filter/view/group/auto-refresh context.

The user-visible target is that examples like `Agents: 1/9` no longer appear in the header after agents have loaded. The
header should instead start with the Agents label followed directly by the metric strip, for example:

`Agents: 3 unread · 5 running · 12 total   [group: by status (g)]   (auto-refresh in 8s)`

## Product Behavior

- Keep the `Agents:` label. It anchors the header and keeps the loading state consistent.
- Remove only the selected-position fraction (`<position>/<total>`) from the normal loaded header.
- Keep `unread`, `running`, and `total` counts, since `total` already provides the useful list-size context without
  repeating a navigation position that is noisy in the header.
- Keep startup loading unchanged: while the agent list is loading, continue to render exactly `Agents: …`.
- Keep filter, view mode, grouping, and auto-refresh segments after the count strip.
- Do not change ChangeSpec or AXE info panels. Their position counters are separate UI surfaces and are not part of this
  request.

## Technical Design

1. Update `AgentInfoPanel._update_display()` so the non-loading path appends the count strip immediately after
   `Agents: ` instead of appending `self._position/self._total` first.
2. Decide whether to retain or remove `AgentInfoPanel.update_position()`:
   - Preferred implementation: retain it as a compatibility no-op or low-impact state setter during this narrow change,
     then stop depending on `_position`/`_total` for rendering.
   - This avoids coupling the UI cleanup to a broader call-site cleanup and keeps
     `DetailMixin._update_agents_info_panel()` low risk.
   - If static checks show the now-unused fields are better removed, remove `_position`/`_total` and stop calling
     `update_position()` from `DetailMixin`, but only after confirming tests do not rely on that interface.
3. Leave `DetailMixin._update_agents_info_panel()` count computation unchanged unless the chosen cleanup path removes
   the position call. The count semantics from the approved agent-counts change remain correct:
   - visible top-level agents only
   - workflow children excluded via `AgentPanelIndex.non_child_indices`
   - unread matched by agent identity
   - running computed with `DISMISSABLE_STATUSES`
4. Update focused widget tests:
   - Replace the existing “renders after position” assertion with one asserting no `Agents: <N>/<M>` prefix and that the
     header starts with `Agents: <unread> unread · <running> running · <total> total`.
   - Keep loading suppression coverage asserting `Agents: …`.
   - Adjust tests that seed `_position`/`_total` only to support the old rendering.
5. Update integration tests only if the implementation removes or changes the `update_position()` call. If retained, the
   count-semantics integration test can remain focused on count computation.

## Verification

Run the focused tests first:

```bash
.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_info_panel.py tests/ace/tui/test_agent_panel_index_integration.py
```

Then, because this repo requires full validation after source edits, run:

```bash
just install
just check
```

If the known parallel `~/.sase/agent_name_registry.json.tmp` xdist race appears again, rerun the specific failing test
serially and report the full-check caveat explicitly.

## Risks And Decisions

- The main UI risk is making the header read awkwardly if the count strip is also hidden. That should not happen because
  the count strip remains visible in loaded state, including `0 unread · 0 running · 0 total`.
- Keeping `update_position()` may leave a method that no longer affects rendering, but it minimizes blast radius. A
  broader cleanup can happen later if desired.
- Removing the selection fraction means the header no longer communicates the selected row’s ordinal position. This is
  intentional for the Agents tab because the total count is still present and the fraction was visually redundant after
  the metric strip was added.
