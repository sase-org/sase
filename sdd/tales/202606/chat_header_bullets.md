---
create_time: 2026-06-02 16:49:18
status: done
prompt: sdd/prompts/202606/chat_header_bullets.md
---
# Plan: Bullet-Style SASE Chat Transcript Metadata

## Goal

Change the metadata preamble at the start of newly saved SASE agent chat transcripts from separated bold blocks:

```markdown
**Timestamp** 2026-06-02 16:31:40 EDT

**MODEL** codex/gpt-5.5

**AGENT** sase_fix_just-10
```

to a compact Markdown bullet list with uppercase `TIMESTAMP`, bold labels that include colons, and no blank lines
between metadata rows:

```markdown
- **TIMESTAMP:** 2026-06-02 16:31:40 EDT
- **MODEL:** codex/gpt-5.5
- **AGENT:** sase_fix_just-10
```

The change should affect newly generated transcripts while preserving compatibility with existing chat files that use
either the current `**Timestamp** ...` block format or older `**Timestamp:** ...` format.

## Current Findings

- The write path is centralized in `src/sase/history/chat.py` via `_format_transcript_metadata_blocks()` and
  `save_chat_history()`.
- Existing tests in `tests/history/test_chat_save.py` assert the old metadata block layout and ordering.
- `src/sase/history/chat_links.py` inserts linked-chat sections after transcript metadata using regexes that recognize
  current and legacy timestamp metadata. This must be updated so linked chats still insert after the new bullet-list
  metadata preamble.
- `tests/history/test_chat_links.py` covers linked-chat insertion for the current block format and legacy timestamp
  format; it should gain or update coverage for the new bullet-list format while keeping legacy coverage.
- `sase.history.chat_catalog` parses workflow/agent from the H1 and snippets from `## Prompt` / `## Response`, so it
  does not appear to require a metadata parser change. Its test fixtures can be updated to the new format for
  generated-style examples.
- Resume parsing in `sase.history.chat` is heading-based and should not be affected by metadata formatting.

## Implementation Plan

1. Update `_format_transcript_metadata_blocks()` in `src/sase/history/chat.py` to return bullet-list rows:
   - Always include `- **TIMESTAMP:** <display timestamp>`.
   - Include `- **MODEL:** <provider/model>` only when model metadata is present after existing normalization.
   - Include `- **AGENT:** <agent>` only when agent metadata is present after existing normalization.
   - Join rows with single newlines, with no blank line between metadata rows.

2. Keep the surrounding `save_chat_history()` document structure stable:
   - H1 remains unchanged.
   - There should still be one blank line between the H1 and metadata list.
   - There should still be one blank line between the metadata list and the next section (`## Prompt`, linked chats,
     extra sections, previous history, etc.).

3. Update `src/sase/history/chat_links.py` metadata detection:
   - Add recognition for the new bullet-list metadata preamble.
   - Keep current block-format and legacy timestamp-format recognition so historical transcripts remain editable.
   - Ensure insertion happens after the entire bullet metadata list, not after only the timestamp row.

4. Update focused tests:
   - Change `tests/history/test_chat_save.py` expectations to assert the new bullet-list strings, ordering, uppercase
     `TIMESTAMP`, label colons, and absence of blank metadata-row separators.
   - Update the metadata-agent test to expect `- **AGENT:** ...`.
   - Keep the "no model/agent when absent" behavior, using the new labels in negative assertions.
   - Update extra-section ordering assertions to use `**TIMESTAMP:**`.
   - Update `tests/history/test_chat_links.py` to cover linked-chat insertion after the new bullet metadata list and
     preserve legacy/current-old format compatibility where appropriate.
   - Update `tests/history/test_chat_catalog.py` generated-style fixtures to use the new bullet metadata list while
     verifying catalog behavior remains unchanged.

5. Validate with the relevant test slice:
   - `pytest tests/history/test_chat_save.py tests/history/test_chat_links.py tests/history/test_chat_catalog.py tests/history/test_chat_resume.py tests/history/test_chat_resume_refs.py`
   - If failures point to additional direct assumptions about old metadata labels, update only those focused
     expectations.

## Risks And Compatibility

- Existing transcripts should remain readable and linkable because link insertion will keep legacy/current-old regex
  support.
- Any downstream code that searches raw transcript text for `**MODEL**` or `**AGENT**` without the colon could break. A
  repository search currently shows the direct assumptions are concentrated in history tests and `chat_links.py`.
- The change is intentionally limited to transcript rendering and insertion-point detection; it should not alter
  filenames, agent metadata JSON, prompt/response parsing, or chat catalog identity fields.
