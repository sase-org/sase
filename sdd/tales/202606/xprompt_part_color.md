---
create_time: 2026-06-17 10:23:32
status: done
prompt: sdd/prompts/202606/xprompt_part_color.md
---
# Plan: Distinct Xprompt Part Color In Agent Metadata

## Context

The Agents tab metadata panel renders its xprompt usage summary from
`src/sase/ace/tui/widgets/prompt_panel/_agent_xprompts.py`. The field label `Xprompts:` uses `bold #87D7FF`, matching
the shared metadata-label blue used throughout the panel. Workflow xprompt entries already use a distinct orange
(`bold #FFAF5F`), but part entries currently use the same `bold #87D7FF` as field labels.

This makes part values such as `#review_checklist` visually read like metadata field names rather than values. The
change is presentation-only and should stay inside the Python TUI rendering layer.

## Proposed Approach

1. Update the xprompt part entry style only.
   - Change `_COLOR_PART` in `_agent_xprompts.py` from `bold #87D7FF` to a distinct non-blue value.
   - Use a bright mint/green tone such as `bold #87FFAF`, which is clearly separate from the metadata-label blue, the
     workflow orange, and dim argument text while still reading as a value on the existing dark TUI background.
   - Keep the `Xprompts:` label, summary, workflow entries, glyphs, spacing, and argument rendering unchanged.

2. Add a focused regression test for Rich span styling.
   - Extend the existing xprompt metadata test coverage in `tests/test_ace_tui_widgets.py`.
   - Assert that:
     - `Xprompts:` still renders with the metadata-label style.
     - workflow values still render with the workflow style.
     - part values render with the new part style.
     - the part value style is not the same as the field-label style.
   - Keep existing plain-text assertions so behavior and copy remain pinned.

3. Validate the user-visible rendering.
   - Run the focused widget test(s) that cover xprompt metadata rendering.
   - Because the repo requires it after file changes, run `just install` if needed and then `just check`.
   - If the PNG visual snapshot suite flags the Agents metadata zoom snapshot due to the intentional color change,
     inspect the diff artifacts and update only the affected snapshot with `--sase-update-visual-snapshots`.

## Risks And Mitigations

- Risk: choosing a hue that collides with nearby semantic colors. Mitigation: use a mint/green value rather than blue or
  orange, preserving the existing workflow orange distinction and metadata-label blue hierarchy.

- Risk: a text-only test would miss the styling regression. Mitigation: add span-level Rich style assertions for the
  exact label and part value segments.

- Risk: visual snapshots may fail because this is an intentional pixel change. Mitigation: update only the affected
  Agents metadata snapshot after inspecting the generated actual/expected/diff artifacts.
