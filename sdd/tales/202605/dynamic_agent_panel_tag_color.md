---
create_time: 2026-05-06 13:33:17
status: done
prompt: sdd/prompts/202605/dynamic_agent_panel_tag_color.md
---
# Dynamic Agent Panel Tag Header Color Plan

## Goal

Make tag names in the Agents tab's dynamic panel headers more visible without changing panel ordering, grouping, counts,
focus behavior, or the rendered agent rows inside each panel.

## Current Understanding

- Dynamic tag panels are refreshed in `src/sase/ace/tui/actions/agents/_display_panels.py`.
- Each `AgentList` panel currently receives a plain string border title:
  - `(untagged) · N` for untagged agents.
  - `@<tag> · N` for tagged panels.
- Textual's `border_title` descriptor accepts `rich.text.Text`, converts it into styled console markup internally, and
  returns markup on read. This lets us style just the tag-name segment rather than changing the whole panel border.
- Existing tests in `tests/ace/tui/test_agent_panel_titles.py` verify title labels and slot ordering. They use a fake
  widget with a simple `border_title` attribute, so tests should be adjusted to check plain title text while also
  covering the new styled tag span.

## Proposed Design

1. Add a small helper near the panel title assignment that builds the panel title as `Text`.
   - Tagged panels: render `@<tag>` in a high-contrast accent, then render ` · N` in a quieter style.
   - Untagged panel: keep `(untagged)` more neutral/dim so user-defined tags stand out.
2. Use an existing palette direction that does not blur into the current blue panel border and banner colors.
   - Proposed tag color: bold warm gold/amber (`#FFD75F`), which contrasts with the existing blue/cyan agent panel
     palette and remains readable on dark terminal backgrounds.
   - Count separator/count: dim gray (`#AFAFAF` or similar) so the count remains available without competing with the
     tag name.
3. Keep the public behavior stable:
   - Preserve title plain text exactly as `@tag · N` and `(untagged) · N`.
   - Do not change panel keys, sorting, focus class handling, or sizing.
   - Do not style agent row tags or group banners in this change.

## Test Plan

1. Update `tests/ace/tui/test_agent_panel_titles.py` so it validates:
   - Plain title text is unchanged for untagged and tagged panels.
   - Tagged panel titles contain the new high-contrast style on the `@tag` span.
   - Alphabetical slot-order behavior remains unchanged.
2. Run the focused title test:
   - `pytest tests/ace/tui/test_agent_panel_titles.py`
3. Because this repo's memory requires it after file changes, run:
   - `just install`
   - `just check`

## Risks And Mitigations

- Textual converts styled `Text` border titles into markup when read from real widgets. Tests should inspect either the
  fake `Text` object directly or normalize via `.plain`/markup-aware helpers rather than assuming the runtime getter
  always returns a plain string.
- A too-bright title could compete with focused panel borders. Styling only the tag segment, while dimming counts, keeps
  the visual hierarchy restrained.
- Terminal theme variance can affect perceived contrast. Warm gold is intentionally distinct from the existing blue/cyan
  palette and tends to remain legible across common dark terminal themes.
