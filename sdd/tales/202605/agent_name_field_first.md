---
create_time: 2026-05-27 10:55:09
status: done
---
# Plan: Agent Prompt Header Name Field First

## Problem

The agent prompt panel header currently renders `Name:` only when `agent.agent_name` is present, and it places that row
after several other metadata rows such as `Workspace:`, `Workflow:`, `Model:`, `PID:`, and `BUG:`. The requested
behavior is for the `Name:` field to always appear and to be the first field in the header metadata list.

The relevant shared path is `build_header_text()` in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`.
That one builder is used by the normal full render, the cheap header-only j/k render path, and the file-hint render
path, so changing it once should keep those views aligned.

## Scope

- Update the `AGENT DETAILS` prompt-panel header built by `build_header_text()`.
- Keep the behavior presentation-only; do not touch agent-name allocation, loaders, artifact metadata, or Rust core.
- Keep ChangeSpec detail rendering and shared delta rendering unchanged.
- Do not change agent list rows, `sase agents show`, or the agent run-log modal unless review determines those should be
  separate follow-up surfaces.
- Do not change top-level `WORKFLOW DETAILS` rendering in this plan. That header has a separate first field,
  `Workflow:`, and no existing `Name:` row. If the intended requirement includes workflow parent rows too, extend the
  same convention there as a small follow-up.

## Design

1. Move the agent-name rendering to the top of `build_header_text()`, immediately after:

   ```text
   AGENT DETAILS

   ```

   This makes `Name:` the first metadata row, before retry-chain, ChangeSpec, Project, Step, Workspace, Model, and other
   fields.

2. Always render exactly one `Name:` row:
   - When `agent.agent_name` is present, preserve the current user-facing format: `Name: @<agent_name>`.
   - When `agent.agent_name` is missing, render `Name: unassigned` in a dim style and do not add an `@` prefix. This
     keeps the field always visible without inventing a resolvable agent reference.

3. Keep `Bead:` adjacent to the `Name:` row when the name maps to a bead:
   - Named bead agents should render `Name:` first and `Bead:` second.
   - Unassigned agents should not render `Bead:`.
   - The cheap path must continue to avoid disk-backed bead lookups; it should use the current cheap fallback behavior.
   - The full path should continue to use `summary.bead_display` when available, preserving bead descriptions.

4. Remove the old lower `Name:`/`Bead:` block so the header never renders duplicate name rows.

5. Keep all existing field labels and styles otherwise unchanged.

## Tests

Add focused tests around `build_header_text()` in `tests/ace/tui/widgets/test_agent_display_metadata.py`:

- An unnamed agent renders `Name: unassigned` and that row appears before `ChangeSpec:`.
- A named agent renders `Name: @reviewer` immediately after `AGENT DETAILS` and before retry/context rows.
- A bead-backed name still renders `Name:` followed directly by `Bead:` at the top, for both cheap and full summary
  paths where existing tests already cover bead lookup differences.
- Retry-chain agents keep the retry information, but `Name:` appears before `Retry chain:`.

Update existing prompt-panel header assertions only where their expected ordering changes.

Focused verification:

```bash
pytest tests/ace/tui/widgets/test_agent_display_metadata.py \
  tests/ace/tui/widgets/test_agent_display_header_only.py \
  tests/ace/tui/widgets/test_prompt_panel_header.py \
  tests/ace/tui/widgets/test_agent_deltas.py \
  tests/test_ace_tui_widgets.py \
  tests/test_qwen_opencode_integration_polish.py
```

Repository verification after source changes, per local instructions:

```bash
just install
just check
```

## Acceptance Criteria

- Every agent rendered through `build_header_text()` includes exactly one `Name:` row.
- `Name:` is the first metadata row after the `AGENT DETAILS` heading.
- Named agents keep the existing `@name` display.
- Unnamed agents show a clear non-reference placeholder, `unassigned`.
- Bead metadata remains tied to real agent names and stays adjacent to `Name:`.
- Cheap header-only rendering remains disk-light.
- Existing ChangeSpec and delta-builder behavior is unchanged.

## Risks

- The placeholder text is a product choice. If `unassigned`, `none`, or `-` is preferred, the implementation should keep
  that choice centralized in the header helper and update only the narrow tests.
- Adding a row shifts prompt-panel content down. If a visual snapshot covers this exact header, update it only after
  confirming the rendered change is intentional.
- Top-level workflow parent rows use a separate `WORKFLOW DETAILS` renderer. This plan intentionally avoids broadening
  into that surface unless the requirement is clarified to include it.
