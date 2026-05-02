---
create_time: 2026-04-30 22:59:29
status: done
prompt: sdd/prompts/202604/agent_bead_metadata.md
---
# Agent Bead Metadata Panel Plan

## Goal

Show a `Bead:` metadata row in the Agents tab detail panel whenever the selected agent appears to have been launched by
`sase bead work <epic_id>`.

The row should make the bead linkage obvious without making the agent header busy. For phase agents the value should be
the phase bead id. For the final land agent, whose agent name is `<epic_id>.land`, the value should point back to the
epic bead id.

## Product Design

- Render the new row in the existing `AGENT DETAILS` header, near the user-facing identity fields.
- Use the same label styling as other metadata labels so the panel remains visually consistent.
- Use a warm accent on the bead id so it stands apart from ChangeSpec, workspace, model, and VCS fields.
- Keep the row terse: `Bead: <id>`. The presence of the row is the signal; avoid extra explanatory text in the TUI.
- For land agents, render the epic id (`sase-x`) instead of the internal agent name (`sase-x.land`) so the row describes
  the bead, not the orchestration role.

## Detection Strategy

Use the selected agent's assigned agent name as the primary source of truth, matching the current epic launcher
behavior:

- Phase segments are rendered as `%name:<phase_bead_id>`.
- The land segment is rendered as `%name:<epic_id>.land`.

Add a small pure helper for the display layer:

- If `agent.agent_name` is empty, return no bead.
- If the name has a dismissed-agent date prefix like `260428.<name>`, ignore the prefix for detection and display the
  underlying bead id.
- If the normalized name ends with `.land`, return the prefix before `.land`.
- Otherwise, if the name looks like a phase bead id (`<epic>.<number>`), return the normalized name.

This deliberately avoids synchronous bead database lookups in the hot j/k navigation path. It is cheap, deterministic,
and uses exactly the metadata the epic integration already writes into `agent_meta.json`.

## Implementation

- Add a helper, likely alongside the agent display helpers, to derive an optional bead id from an `Agent`.
- Add the `Bead:` row to `build_header_text()` after the `Name:` row, so agent name and inferred bead are visually
  adjacent.
- Keep the helper independent of Textual/Rich so it is easy to unit test.
- Add focused tests covering:
  - phase agent name `sase-x.3` renders `Bead: sase-x.3`;
  - land agent name `sase-x.land` renders `Bead: sase-x`;
  - dismissed historical name `260428.sase-x.3` still renders `sase-x.3`;
  - ordinary names do not render a bead row.

## Verification

- Run the focused agent display tests.
- Run `just check` before finishing, per repo instructions.
