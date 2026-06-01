---
create_time: 2026-06-01 10:53:09
status: done
prompt: sdd/prompts/202606/agent_bead_cross_project_metadata.md
---
# Fix Cross-Project Bead Metadata in Agents Tab

## Problem

The Agents tab already infers bead-shaped agent names such as `bob-cli-1.4` and renders a `Bead:` metadata row in the
agent details panel. The full details path is supposed to enrich that row with the bead description/title, but that
enrichment can depend on where `sase ace` was launched from.

The live symptom is `bob-cli-1.4`: the agent metadata lives under the `bob-cli` project and the bead exists in
`/home/bryan/projects/github/bbugyi200/bob-cli/sdd/beads`, while `sase ace` may be running from the `sase` workspace. A
plain `sase bead show bob-cli-1.4` from the `sase` workspace fails, which confirms that a CWD-bound bead lookup is not
enough for TUI agent metadata.

## Relevant Current Flow

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` builds the agent details header.
- `build_detail_header_summary()` performs the expensive bead lookup for the debounced full detail render.
- `src/sase/ace/tui/models/agent_bead.py` passes only `agent.agent_name` and a project name inferred from
  `agent.project_file` into `sase.agent.bead_display`.
- `src/sase/agent/bead_display.py` derives the bead id from the name, then looks up the issue through project/CWD/global
  bead-store resolution.
- Active and completed agents often have stronger context available: `agent.workspace_dir`, `agent.artifacts_dir`,
  `agent.project_file`, and sometimes agent metadata fields such as `bead_id`, `phase_bead_id`, or `epic_bead_id`.

## Implementation Plan

1. Make bead display lookup accept explicit agent context.
   - Extend `format_agent_bead_display_for_name()` and `_lookup_bead_issue()` to accept an optional `workspace_dir`.
   - Keep the existing `project_name` parameter for registered project lookup.
   - Preserve the existing public behavior when no context is supplied.

2. Resolve bead stores from the selected agent before falling back to CWD.
   - Add a small read-only helper that derives candidate bead directories from `workspace_dir`:
     - nearest `sdd/beads` ancestor for version-controlled bead stores;
     - `.sase/sdd/beads` for non-VC stores;
     - managed-checkout marker primary workspace when the agent workspace is an ephemeral checkout and local lookup does
       not find the bead.
   - Prefer these agent-specific candidates before the current CWD-based `get_read_view()` fallback.
   - Keep the all-known-project fallback as a final compatibility path, but do not rely on it for the common
     active-agent case.

3. Thread the context from TUI agents into the formatter.
   - Update `src/sase/ace/tui/models/agent_bead.py` so `format_agent_bead_display(agent, include_description=True)`
     passes `agent.workspace_dir` along with the inferred project name.
   - Keep the cheap header path description-free so j/k navigation still avoids disk I/O.

4. Cover the regression with focused tests.
   - Add a unit test where CWD is a different project, the agent name is `bob-cli-1.4`, and the bead exists only under
     the agent `workspace_dir`; the formatted display should include the bead title/description.
   - Add a managed-checkout variant where `workspace_dir` has a `.sase/checkout.json` pointing to a primary workspace
     with `sdd/beads`.
   - Add a TUI-level test showing an agent with `project_file` from one project or `home` plus `workspace_dir` in
     another project still renders the enriched `Bead:` row in the full header.
   - Keep existing tests that non-bead dotted names do not touch bead storage.

5. Verify with targeted and repo-level checks.
   - Run the bead display and TUI metadata tests first:
     - `.venv/bin/pytest tests/test_agent_bead_display.py tests/ace/tui/widgets/test_agent_display_bead_metadata.py`
   - Run `just check` after implementation, because this repo requires it after source changes.

## Design Notes

- The fix should not scan arbitrary numbered sibling workspaces. It should read the specific workspace attached to the
  agent record, then fall back to the registered project/canonical store and finally the existing global compatibility
  path.
- This keeps behavior aligned with `sase bead`: version-controlled bead state comes from one checkout at a time, not
  from merging sibling workspaces.
- The lookup remains presentation-only for the TUI metadata line; missing or unreadable bead stores should continue to
  degrade to just the bead id instead of breaking the Agents tab.
