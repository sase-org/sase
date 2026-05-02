---
create_time: 2026-05-01 13:38:17
status: done
prompt: sdd/prompts/202605/agent_bead_description.md
---
# Plan: Enrich Agents Bead Metadata

## Goal

Make the `Bead:` field in the `sase ace` TUI Agents-tab metadata panel more useful by showing the bead's description on
the same line as the inferred bead ID.

Current behavior:

- Agent names written by `sase bead work` are inferred as bead IDs via `derive_agent_bead_id()`.
- `build_header_text()` renders `Bead: <id>` below `Name: @...`.
- The Agents row badge also shows the bead ID, but this request is scoped to the metadata panel line.

Desired behavior:

- When the selected agent maps to a bead and the bead can be found, render:
  - `Bead: <id> - <description>` when the bead has a non-empty description.
  - Keep `Bead: <id>` when the bead is missing or has no description.
- Preserve existing behavior for ordinary named agents and land agents.

## Constraints And Context

- `AgentPromptPanel.update_header_only()` is used during rapid j/k navigation and calls
  `build_header_text(..., cheap=True)`.
- The cheap path is intentionally disk-free and guarded by tests. Bead lookup reads `sdd/beads/issues.jsonl` or bead
  DB state, so it must not run when `cheap=True`.
- The full debounced detail render already performs disk-backed enrichments such as embedded workflow metadata. Bead
  description lookup belongs there.
- Bead data should be read through the existing Python bead APIs rather than shelling out to `sase bead show`.
- Lookup failures must be quiet. A missing bead should not break metadata rendering.

## Technical Approach

1. Extend `src/sase/ace/tui/models/agent_bead.py` with bead display helpers:
   - Keep `derive_agent_bead_id(agent)` as the ID inference primitive used by the row badge and existing tests.
   - Add a small lookup helper that opens `sase.bead.cli_common.get_read_view()` and fetches the issue by ID.
   - Add a formatting helper for metadata display that returns the ID plus a normalized one-line description when
     available.
   - Collapse whitespace/newlines in descriptions so the value remains on the `Bead:` line.

2. Update `build_header_text()` in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`:
   - Continue to infer the bead ID only when `agent.agent_name` is present.
   - In `cheap=True`, render only the bead ID to preserve the no-disk immediate path.
   - In full render, append the description to the same line if lookup returns one.

3. Tests:
   - Update existing bead metadata tests in `tests/ace/tui/widgets/test_agent_display.py`.
   - Add a full-render test that patches the bead lookup to return a multiline description and asserts
     `Bead: <id> - <collapsed description>`.
   - Add a fallback test that empty/missing descriptions still render `Bead: <id>`.
   - Keep/strengthen the cheap-path behavior by asserting `build_header_text(..., cheap=True)` does not call the bead
     lookup helper.
   - Existing `test_update_header_only_does_not_touch_disk` should continue to pass; no disk-backed bead reads should
     happen on that path.

4. Verification:
   - Run focused tests for agent display/header-only behavior.
   - Because this repo memory requires it after edits, run `just install` if needed and then `just check`.

## Risks

- Opening a merged bead view can be moderately expensive if repeated frequently. This is acceptable for the debounced
  full detail render, but not for immediate j/k navigation.
- Some beads may have empty descriptions because the title carries most of the useful context. This plan intentionally
  follows the request and adds description only when present; it does not change the field to title fallback unless
  tests or usage reveal that is better.
