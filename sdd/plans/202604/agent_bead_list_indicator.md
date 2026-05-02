---
create_time: 2026-04-30 23:08:24
status: done
prompt: sdd/prompts/202604/agent_bead_list_indicator.md
---
# Agent Bead List Indicator Plan

## Goal

Add a compact, polished visual indicator in the Agents tab list for agents launched by `sase bead work`, matching the
bead id inferred for the details panel. The list should make bead-driven work easy to scan without adding row height,
crowding the status text, or duplicating metadata more than necessary.

## Product Design

Use a small bead badge in the agent row:

```text
<name> (RUNNING) ◆ sase-x.3 @sase-x.3
<name> (DONE)    ◆ sase-x   @sase-x.land
```

The badge should appear immediately after the status/fold annotation area and before user tags and the raw agent name
annotation. This location works because:

- Status remains the primary live signal.
- The bead badge becomes stable work-context metadata, colocated with tags and names.
- It avoids stealing the row prefix area, which already carries jump hints, marks, approval, hidden, retry, workflow
  depth, and type glyphs.
- It keeps the existing `@agent_name` visible for exact launched-agent identity while presenting the normalized bead id
  as the meaningful project-management anchor.

Visual treatment:

- Glyph: `◆` for bead context. It is distinct from existing row glyphs (`×`, `↻`, `≡`, `❑`, `⚡`, `◌`, `↳`) and reads as
  a small jewel/marker rather than another status.
- Style: glyph in bold mint/teal, bead id in dim mint/teal. This should harmonize with existing SASE colors (`#00D7AF`,
  `#5FD7AF`, `#87D7AF`) while staying calmer than status colors.
- Text: render the normalized bead id, not the literal agent name. Phase agents show `sase-x.3`; land agents show the
  epic bead `sase-x`; dismissed names like `260428.sase-x.3` show `sase-x.3`.

## Technical Design

1. Move bead-id derivation into a shared TUI helper

   The current implementation keeps `_derive_agent_bead_id()` in
   `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`, but the agent list renderer should not import from
   the prompt panel. Create a small shared module, likely `src/sase/ace/tui/models/agent_bead.py` or
   `src/sase/ace/tui/widgets/_agent_bead.py`, with a pure helper such as:

   ```python
   def derive_agent_bead_id(agent: Agent) -> str | None:
       ...
   ```

   Keep the same parsing behavior already tested for:
   - `sase-x.3` -> `sase-x.3`
   - `sase-x.land` -> `sase-x`
   - `260428.sase-x.3` -> `sase-x.3`
   - ordinary names -> `None`

   Update the details panel to consume this shared helper so both surfaces remain consistent.

2. Add list-row bead badge rendering

   In `src/sase/ace/tui/widgets/_agent_list_render_agent.py`, after status and fold annotation rendering, derive the
   bead id and append:

   ```text
    ◆ <bead_id>
   ```

   Use local style constants from `src/sase/ace/tui/widgets/_agent_list_styling.py`, for example:
   - `_BEAD_GLYPH = "◆"`
   - `_BEAD_GLYPH_STYLE = "bold #5FD7AF"`
   - `_BEAD_TEXT_STYLE = "dim #87D7AF"`

   Keep this as a plain `Text` append so it participates in the existing one-line clipping behavior and right-side
   runtime suffix alignment.

3. Update the render cache key

   `agent_render_key()` is intentionally explicit. Add the derived bead id or a stable source field that fully captures
   it. Prefer adding the derived bead id itself to the key, since it directly represents the visible output and guards
   against future parsing changes.

4. Update the help legend

   Add `◆` to the "Agent Row Glyphs" section in `src/sase/ace/tui/modals/help_modal/bindings.py`, with a concise label
   such as `Bead-linked agent`.

5. Tests

   Add focused tests in the existing widget test area:
   - A phase agent row renders `◆ sase-x.3`.
   - A land agent row renders `◆ sase-x`.
   - A dismissed phase agent row renders `◆ sase-x.3`.
   - An ordinary named agent does not render `◆`.
   - The render cache key changes when the bead-bearing agent name changes, preventing stale badge output.

   Keep the details-panel tests, but point them at the shared helper instead of importing a prompt-panel-private
   function.

6. Validation

   Run the focused tests first:

   ```bash
   .venv/bin/pytest tests/ace/tui/widgets/test_agent_display.py tests/ace/tui/widgets/test_agent_render_cache.py -q
   ```

   If this workspace has stale dependencies, run `just install` first per repo memory. After implementation changes,
   run:

   ```bash
   just check
   ```

## Non-Goals

- Do not add a second row, hover UI, modal, or wide metadata column.
- Do not query bead state from disk or shell out to `bd`; the current feature is purely inferred from agent names.
- Do not hide the existing `@agent_name` annotation, because it remains useful as the exact launched agent identity.
