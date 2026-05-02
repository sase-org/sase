---
create_time: 2026-05-01 17:04:53
status: done
prompt: sdd/prompts/202605/land_bead_description.md
---
# Plan: Land Agent Bead Description

## Goal

Make the Agents-tab metadata panel show useful `Bead:` text for final land agents named `<epic_id>.land`, matching the
quality of the phase-agent bead descriptions.

Current behavior:

- Phase agents are named after real phase bead IDs, such as `sase-1u.4`.
- The metadata panel infers the bead ID from the agent name and, on the full render path, looks up the bead description.
- Land agents are named `<epic_id>.land`, but there is no real `.land` bead. The land xprompt targets the plan bead via
  `#bd/land_epic:<epic_id>`.
- The current helper intentionally maps `<epic_id>.land` back to `<epic_id>`, so the panel displays the real plan bead.
- Plan beads often have a title and design file but no `description`, so the land metadata line falls back to just
  `Bead: <epic_id>`.

Desired behavior:

- Preserve the existing `Bead: <epic_id>` identity for land agents. The panel should point at the real plan bead, not at
  a nonexistent `<epic_id>.land` issue.
- When the plan bead has a non-empty description, keep using that description.
- When the selected agent is a land agent and the plan bead has no description, render a concise synthetic description
  from the plan bead title, for example: `Bead: sase-1u - Land epic: Make \`sase bead\` Fast With \`sase-core\``.
- Preserve the cheap/header-only render path: no bead storage reads while rapidly moving through agents.

## Technical Approach

1. Extend `src/sase/ace/tui/models/agent_bead.py` without changing the public meaning of `derive_agent_bead_id()`:
   - Keep phase names mapping to their phase bead ID.
   - Keep `<epic_id>.land` mapping to `<epic_id>`.
   - Add a tiny helper to recognize normalized land agent names.
   - Replace or wrap the description-only lookup with an issue lookup so display formatting can access both
     `description` and `title`.

2. Update `format_agent_bead_display()`:
   - If `include_description=False`, return only the inferred bead ID exactly as today.
   - If the looked-up bead has a normalized description, render `<id> - <description>`.
   - If the agent is a land agent, the looked-up bead exists, and its description is empty, render
     `<id> - Land epic: <normalized title>`.
   - If lookup fails or the title is empty, fall back to `<id>`.

3. Tests:
   - Keep the current cheap-path tests proving bead storage is not touched.
   - Keep current phase-agent description tests.
   - Add a full-render land-agent test for a plan bead with an empty description and non-empty title.
   - Add a land-agent test proving an explicit plan description wins over the synthetic title fallback.
   - Keep existing row-badge expectations unchanged: the list badge for `sase-x.land` still shows the plan bead ID
     `sase-x`.

4. Verification:
   - Run focused agent display tests first.
   - Because this repo requires it after edits, run `just install` if necessary, then `just check`.

## Risks And Notes

- This is intentionally a display-layer fix. Creating real `.land` beads would change the bead model and launcher
  semantics, and is not needed for the metadata panel issue.
- The land fallback uses the plan bead title only when the plan description is empty, so it does not degrade projects
  that already provide a real plan-bead description.
- The full detail render already performs disk-backed enrichment, so the extra title access belongs there, not in the
  immediate header-only path.
