---
create_time: 2026-05-06 20:05:26
status: done
prompt: sdd/prompts/202605/agent_tag_hash_prefix.md
---
# Plan: Use `#` For Agents-Tab Dynamic Agent Tag Prefixes

## Context

The Agents tab currently stores agent tags as prefixless strings. That storage model is correct and should remain
unchanged: `src/sase/ace/agent_tags.py` validates and persists `alpha`, not `@alpha` or `#alpha`.

The current display surface is mixed:

- Dynamic split-panel titles still render tag panels as `@<tag>` in
  `src/sase/ace/tui/actions/agents/_display_panels.py`.
- Merged-panel row badges already render effective tag labels as `#<tag>` in
  `src/sase/ace/tui/widgets/_agent_list_render_agent.py`.
- Agent names still render as `@<agent_name>`, and that should stay unchanged because it is a separate concept from
  agent tags.

The requested behavior is to start using `#` instead of `@` for the agent-tag prefix shown in dynamic agent panels on
the `sase ace` Agents tab. This is presentation-only TUI work and does not cross the Rust core boundary.

## Goal

Make the Agents tab present user-managed agent tags with a `#` prefix in dynamic agent panel UI, while preserving:

- Prefixless tag storage and validation.
- Existing panel grouping semantics.
- Existing `@<agent_name>` annotations.
- Existing xprompt and file-reference `#` / `@` behavior outside this display surface.

## Implementation Strategy

1. Centralize the display decision where the dynamic panel title is produced.
   - Update `_agent_panel_border_title()` in `src/sase/ace/tui/actions/agents/_display_panels.py`.
   - Tagged panel titles should render `#<tag> · N`.
   - Untagged and merged titles should remain `(untagged) · N` and `All agents · N`.

2. Keep storage and panel identity prefixless.
   - Do not change `PanelKey`, `Agent.tag`, `agent_tags.json`, `validate_tag_name()`, or CLI persistence.
   - Do not allow `#`-prefixed input as stored tag names unless a separate product decision asks for input syntax
     changes.

3. Preserve agent-name display.
   - Leave row suffixes like `@<agent_name>` alone.
   - Avoid broad replacements of `@` in Agents-tab rendering because `@agent_name`, xprompt references, and file
     references are distinct semantics.

4. Align nearby TUI tag affordances only where they describe the agent tag display contract.
   - Update comments/docstrings that explicitly describe dynamic panel tags as `@<tag>`.
   - Consider updating the tag modal/current-tag label and success toast only if we decide the TUI should present
     user-managed tags consistently everywhere, not only in dynamic panel titles. If included, keep validation messaging
     clear that users type the bare tag name.
   - If modal/help text changes, update the help popup content as required by `src/sase/ace/AGENTS.md`.

5. Keep merged-panel behavior unchanged except for assertions if needed.
   - The merged row badge already uses `#<tag>`, so it should be treated as the desired reference behavior.
   - The effective-tag plumbing should not change.

## Test Plan

1. Update focused panel-title tests:
   - `tests/ace/tui/test_agent_panel_titles.py` should expect `#apple · 2`, `#banana · 1`, and alphabetical slot titles
     like `#alpha · 1`.
   - Keep span assertions covering the tag label plus count style.

2. Add or adjust regression coverage for boundaries:
   - Tagged panel titles use `#`.
   - Untagged panel title remains `(untagged)`.
   - Merged panel title remains `All agents`.
   - Row agent-name annotation remains `@<agent_name>`.
   - Merged row tag badge remains `#<tag>`.

3. Run focused tests first:
   - `just install` if this workspace has not been installed recently.
   - `pytest tests/ace/tui/test_agent_panel_titles.py`
   - Relevant row-render/tag tests, likely:
     `pytest tests/ace/tui/widgets/test_agent_render_cache.py tests/ace/tui/test_agent_panels_display.py`

4. Run repository check after implementation:
   - `just check`

## Risks And Mitigations

- Risk: accidentally changing `@<agent_name>` displays.
  - Mitigation: keep edits targeted to tag-specific helpers and add/retain row-render assertions.

- Risk: confusing stored tag syntax with displayed tag syntax.
  - Mitigation: leave validation/storage unchanged and keep modal input guidance focused on bare tag names.

- Risk: tests or docs still encode the old `@<tag>` visual convention.
  - Mitigation: search targeted Agents-tab panel/tag files for `@<tag>`, `@alpha`, `@apple`, and `@{tag}` after the code
    change, then update only references that describe user-managed agent tags.

## Definition Of Done

- Dynamic Agents-tab tag panel titles display `#<tag>`.
- Untagged and merged panel titles are unchanged.
- Prefixless tag storage remains unchanged.
- Agent-name annotations still display with `@`.
- Focused tests and `just check` pass.
