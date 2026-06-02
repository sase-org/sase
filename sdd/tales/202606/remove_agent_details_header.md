---
create_time: 2026-06-02 18:42:17
status: done
prompt: sdd/prompts/202606/remove_agent_details_header.md
---
# Remove Agents Metadata Panel Header

## Problem

On the `sase ace` TUI Agents tab, the selected agent's metadata panel begins with an `AGENT DETAILS` title and a blank
line before the first real metadata row. The title is redundant because the panel context is already clear, and it costs
vertical space in a detail-heavy surface. The requested behavior is for the panel's first rendered line to be the agent
`Name:` field.

## Scope

This is a presentation-only TUI change in the Python ACE prompt-panel renderer. It does not affect agent loading, agent
metadata models, Rust core behavior, keymaps, or the agent run-log modal.

The relevant renderer is `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`, specifically
`build_header_text()`. There is a separate `AGENT DETAILS` section in `src/sase/ace/tui/modals/agent_run_log_modal.py`;
that modal is not the Agents-tab metadata panel and should keep its current title unless separately requested.

## Proposed Approach

1. Update `build_header_text()` so it no longer prepends the `AGENT DETAILS` label or the following blank line.
2. Preserve the existing metadata order, with `Name:` still first for named and unnamed agents.
3. Preserve all downstream sections and dividers:
   - `Bead:` remains immediately after `Name:` when present.
   - `Retry chain:`, `ChangeSpec:`, `Project:`, `Workspace:`, `Model:`, timestamps, deltas, artifacts, step metadata,
     memory reads, and errors keep their existing relative order.
   - The trailing separator before prompt/chat content remains unchanged.
4. Update test expectations that currently treat `AGENT DETAILS` plus a blank line as the metadata prefix.
5. Update narrow wording in tests/docstrings that refers to an `AGENT DETAILS header` where it now means the agent
   metadata header/panel.

## Test Plan

Run the focused tests that exercise the metadata panel renderer and immediate header-only path:

```bash
pytest tests/ace/tui/widgets/test_agent_display_name_model_metadata.py \
  tests/ace/tui/widgets/test_agent_display_bead_metadata.py \
  tests/ace/tui/widgets/test_agent_display_header_only.py \
  tests/test_agent_display_meta_priority.py
```

Because this repo's short-term build notes require full verification after source changes, run:

```bash
just install
just check
```

If visual snapshot tests fail because the detail panel lost the expected two lines of vertical content, inspect the
snapshot diff and update snapshots only if the diff is exactly the intentional removal of the `AGENT DETAILS` line and
the blank spacer.
