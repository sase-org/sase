---
create_time: 2026-05-23 17:44:41
status: done
prompt: sdd/prompts/202605/metadata_panel_dynamic_fields_header.md
---
# Plan: Add Header Above Dynamic Fields in Agent Metadata Panel

## Goal

Add a visible section header above the conditional `meta_*` fields (e.g. `Commit Message:`, `New Commit:`) that
currently appear at the bottom of the AGENT DETAILS panel on the "Agents" tab of the `sase ace` TUI. Today these fields
just float beneath the always-present fields (Project, Workspace, Model, VCS, PID, Name, Timestamps, …) separated only
by a blank line, which makes it visually unclear that they are a distinct group sourced from step output.

## Background

The metadata panel is built in two places:

1. **Agent path** — `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py::build_header_text()` (lines
   220–502). The always-present fields are emitted from lines 250–452. The dynamic `meta_*` fields are emitted at lines
   469–476:

   ```python
   # Meta fields from step output
   if agent.step_output and isinstance(agent.step_output, dict):
       meta_fields = extract_meta_fields(agent.step_output)
       if meta_fields:
           header_text.append("\n")
           for name, value in meta_fields:
               header_text.append(f"{name}: ", style="bold #87D7FF")
               header_text.append(f"{value}\n", style="#5FD75F")
   ```

2. **Workflow path** — `src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py` lines 111–117 renders the same kind
   of fields aggregated across workflow steps with identical formatting.

Both spots use `extract_meta_fields()` / `aggregate_meta_fields()` from `_helpers.py`, which strip the `meta_` prefix
and title-case the rest (e.g. `meta_commit_message` → `Commit Message`). The special keys `meta_project`,
`meta_changespec`, and `meta_workspace` are excluded because they are rendered inline in the upper section.

The existing section headers in the panel ("AGENT DETAILS", "AGENT XPROMPT", "AGENT PROMPT", "AGENT REPLY", "AGENT
CHAT", "ERROR") all use the same style: `bold #D7AF5F underline`. That gives us a consistent precedent.

## Design

### Header label

Use **`STEP METADATA`** as the header. Rationale:

- These fields originate from a workflow step's `step_output` (specifically any `meta_*` key) — "STEP" is the most
  accurate noun.
- The existing `_helpers.py` docstrings already refer to them as "meta fields"/"meta_\* fields"; "STEP METADATA" reads
  naturally for users and keeps the AGENT-prefixed top-level sections distinct (this is a subsection of AGENT DETAILS,
  not a peer of AGENT XPROMPT etc.).
- Alternatives considered and rejected:
  - `AGENT METADATA` — overloads "metadata" since the entire upper block is also agent metadata.
  - `META FIELDS` — too internal/jargon-y.
  - `STEP OUTPUT` — misleading: only the `meta_*` subset is shown, not the full output.

### Visual style

Match the existing section-header style exactly: `bold #D7AF5F underline`. This keeps the panel visually coherent and
lets users scan for sections by the same gold underlined affordance.

Although STEP METADATA lives **inside** AGENT DETAILS (above the closing separator, see lines 497–499 of
`_agent_display_parts.py`), we accept the slight hierarchy ambiguity in exchange for visual consistency. A distinct
sub-header style would diverge from every other header in the panel.

### Layout

Before (current):

```
Timestamps: START | …
            DONE  | …
                                ← blank line
Commit Message: fix: align …
New Commit: 96a895335
                                ← blank line
──────────────────────────────────────────────────
```

After:

```
Timestamps: START | …
            DONE  | …
                                ← blank line
STEP METADATA                   ← new header (bold gold underlined)
                                ← blank line (matches other section headers)
Commit Message: fix: align …
New Commit: 96a895335
                                ← blank line
──────────────────────────────────────────────────
```

The header is emitted only when there is at least one dynamic field to show; the panel keeps its current appearance when
`meta_fields` is empty.

## Implementation Steps

1. **`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`** — inside the `if meta_fields:` branch (lines
   472–476), append the header before iterating:

   ```python
   if meta_fields:
       header_text.append("\n")
       header_text.append("STEP METADATA\n", style="bold #D7AF5F underline")
       header_text.append("\n")
       for name, value in meta_fields:
           header_text.append(f"{name}: ", style="bold #87D7FF")
           header_text.append(f"{value}\n", style="#5FD75F")
   ```

2. **`src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py`** — apply the same change to the workflow path so both
   renderers stay symmetric (lines 113–117).

3. **Tests**:
   - Extend `tests/ace/tui/widgets/test_agent_display_metadata.py` (or add a focused test there if no existing fixture
     renders an agent with `meta_*` step_output) to assert that:
     - `"STEP METADATA"` appears in the rendered header text when at least one `meta_*` field is present.
     - The header is absent when no dynamic fields exist (so the rendering is unchanged for the common case).
   - Mirror the same assertion in a workflow-rendering test if one exists for `_workflow_render.py`; otherwise add a
     small one.

4. **PNG snapshot suite**: a header-text change will alter `tests/ace/tui/visual/snapshots/png/` fixtures that include
   the metadata panel with `meta_*` fields. Run `just test-visual`; for any failures that are intentional (header is the
   new expected output), re-record with `--sase-update-visual-snapshots`. Inspect the diff artifacts in
   `.pytest_cache/sase-visual/` before accepting.

5. **`just check`** at the end per repo policy.

## Out of Scope

- Restyling or reorganizing the always-present fields above the new header.
- Changing the special-meta-key handling (`meta_project` / `meta_changespec` / `meta_workspace` stay where they are).
- Promoting STEP METADATA to a peer top-level section outside AGENT DETAILS (would require restructuring the trailing
  separator logic; not worth it for this UX improvement).
- Renaming or grouping individual dynamic fields (e.g. sorting Commit Message before New Commit).

## Risks / Open Questions

- **Header label naming**: "STEP METADATA" is my recommendation, but the user may prefer something shorter like
  "METADATA" or domain-specific like "WORKFLOW OUTPUT". Confirm before implementing.
- **Visual snapshots will churn**: Several existing PNG goldens that include this panel section will need re-recording.
  This is expected, not a regression.
- **No new logic for empty case**: We deliberately do not show "STEP METADATA" with no fields underneath (would look
  broken). The branch guard already handles this.
