---
create_time: 2026-05-27 10:31:40
status: done
prompt: sdd/prompts/202605/move_pencil_provider_badge.md
---
# Move Agent Row Pencil Next To Provider Badge

## Context

Agent rows currently render the persisted-diff pencil marker from `agent.diff_path` after the status/fold annotation and
before bead / `@agent_name` metadata:

```text
test_cl (RUNNING)×3 ✏️ ◆ @sase-x.3
```

Provider emoji badges render earlier in the row, immediately before `agent.display_name` for rows where provider badges
are allowed:

```text
🐙 root-agent (RUNNING)
```

The requested change is to move the pencil marker into that leading badge area so it appears to the right of the LLM
provider emoji, instead of in the metadata area near the agent name annotation.

## Proposed Behavior

For rows with both a provider emoji and a diff path, render provider then pencil then display name:

```text
🐙 ✏️ root-agent (RUNNING)
```

For rows with a diff path but no rendered provider emoji, keep the pencil visible in the same leading badge area
immediately before the display name:

```text
✏️ plain-agent (RUNNING)
```

For workflow child rows that intentionally omit provider emojis because they are not agent entries, keep the same
fallback behavior: the pencil still appears before the child display name rather than disappearing.

The diff-path signal remains cheap and presence-based: only `bool(agent.diff_path)` controls the marker, and no diff
file should be read while rendering rows.

## Implementation Plan

1. Update `format_agent_option` in `src/sase/ace/tui/widgets/_agent_list_render_agent.py`.
   - Keep `_has_file_change_hint(agent)` as the single rendering predicate.
   - Resolve the provider emoji once in the existing provider-badge section.
   - Append the provider emoji first when it exists.
   - Append the pencil glyph immediately after the provider emoji, or as the first leading badge when no provider emoji
     is rendered.
   - Remove the later pencil append block that currently sits after the fold annotation and before bead metadata.

2. Preserve spacing deliberately.
   - Badge cluster output should read as separate visual tokens, e.g. `🐙 ✏️ root-agent`.
   - Rows without a provider badge should read `✏️ test_cl`, with no doubled or leading-only spaces.
   - Bead and `@agent_name` metadata should continue to flow after status/fold annotation, e.g.
     `(RUNNING)×3 ◆ @sase-x.3`.

3. Keep cache-key semantics unchanged.
   - `agent_render_key` already includes `bool(agent.diff_path)` and `agent.llm_provider`, which still cover every
     visible output affected by this placement.
   - No cache-key edit is expected unless the implementation introduces a new visible input, which it should not.

4. Update focused rendering tests in `tests/ace/tui/widgets/test_agent_display_list_rendering.py`.
   - Change the existing pencil-flow assertion to prove the pencil no longer appears before bead / `@agent_name`
     metadata.
   - Add or adjust a provider test to assert `provider emoji -> pencil -> display name`, for example
     `🐙 ✏️ root-agent (RUNNING)`.
   - Add a fallback assertion for a row with `diff_path` and `llm_provider=None` so the marker remains visible even
     without a provider emoji.
   - Keep the non-agent workflow child provider-omission test meaningful by asserting provider emoji absence separately
     from pencil placement if needed.

5. Run validation after source edits.
   - Run `just install` first because this is an ephemeral SASE workspace.
   - Run the focused tests:
     `./.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_display_list_rendering.py tests/ace/tui/widgets/test_agent_render_cache.py`
   - Run `just check` because source/test files will change.

## Risks And Notes

- Emoji display width can vary by terminal, but this change follows the existing row rendering style of appending emoji
  tokens separated by spaces.
- The provider badge helper only returns emojis for known providers. Unknown or missing providers should not suppress
  the pencil marker.
- The change is presentation-only TUI logic and does not cross the Rust core backend boundary.
