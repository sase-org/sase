---
create_time: 2026-05-08 17:15:02
status: done
prompt: sdd/prompts/202605/artifacts_glyph.md
---
# Plan: ARTIFACTS Entry Prefix Glyph

## Goal

Replace the current `~` prefix used before entries in the Agents tab `ARTIFACTS:` metadata section with a clearer, nicer
glyph.

## Context

The `sase ace` Agents tab renders agent metadata through `AgentPromptPanel`. The header is assembled in
`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`. For full, non-cheap headers, it appends `DELTAS:` and
then `ARTIFACTS:`.

The artifact entry rendering itself lives in:

- `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py`

The current prefix is hardcoded there:

```python
text.append("  ~ ", style=_GLYPH_STYLE)
```

Tests covering this behavior live in:

- `tests/ace/tui/widgets/test_agent_display_metadata.py`

## Design Choice

Use `•` as the new artifact entry prefix.

Rationale:

- It reads naturally as a bullet for a list of artifact paths.
- It is terminal-friendly and single-column in typical monospace environments.
- It avoids emoji width/color ambiguity that can make Textual/Rich alignment inconsistent.
- It avoids overloading `~`, which already has path and delta/status meanings elsewhere in the UI.

Keep the existing glyph style (`bold #FFD787`) so the visual treatment changes only the symbol, not the section's color
hierarchy.

## Implementation Steps

1. Update `_agent_artifacts.py` to define a small named constant for the glyph, e.g. `_ARTIFACT_ENTRY_PREFIX = "•"`.
2. Replace the hardcoded `~` emission with the new constant while preserving spacing: `  • path`.
3. Update the existing artifact metadata assertion in `test_agent_display_metadata.py` from `ARTIFACTS:\n  ~ [1] ...` to
   `ARTIFACTS:\n  • [1] ...`.
4. Add or adjust one direct assertion so the non-hint path also verifies the new bullet prefix appears in rendered
   artifact lines.
5. Run the focused metadata test file.
6. Per repo instructions, run `just install` if needed and `just check` before reporting completion because this repo
   requires it after file changes.

## Risk

Low. This is presentation-only TUI rendering and should not cross the Rust core/backend boundary. The main risk is
terminal glyph support, which is why the plan uses the conservative bullet symbol instead of an emoji.
