---
create_time: 2026-03-28 18:22:03
status: done
prompt: sdd/prompts/202603/recursive_resume_expansion.md
---

# Plan: Recursive `#resume` Expansion in Chat History

## Problem

When resuming a conversation that itself used `#resume`, the `#resume:name` reference appears as raw text in the
"Previous Conversation" section. For example, after `#resume:t`, the agent sees:

```
# Previous Conversation

**User:**

#gh:sase #resume:t Let's go with 7s instead.

**Assistant:**

Python checks pass...
```

Instead of seeing the actual conversation history that `#resume:t` loaded. This happens because:

1. The resume workflow wraps loaded history in `%xprompts_enabled:false` markers, preventing xprompt expansion
2. `_parse_chat_turns()` only extracts `## Prompt`/`## Response` heading pairs, missing **User:**/**Assistant:**
   formatted turns stored under `## Previous Conversation`
3. Multi-level chains (A -> B -> C) lose history from earlier conversations

## Solution

Modify `load_chat_for_resume()` in `src/sase/history/chat.py` to recursively expand `#resume:name` and
`#resume_by_chat:path` references found in loaded prompt text. When a `#resume` ref is detected, resolve it to a chat
file, recursively load that history, and inline the turns before the current prompt (stripping the raw `#resume` tag).

## Changes

### `src/sase/history/chat.py`

**New helpers:**

- `_RESUME_REF_RE` - Regex matching `#resume:name`, `#resume(name)`, `#resume_by_chat:path`, `#resume_by_chat(path)`.
  Covers colon syntax (including backtick-quoted args) and parenthesis syntax.

- `_find_resume_refs(text)` - Returns list of `(full_match, xprompt_name, argument)` tuples found in text.

- `_resolve_resume_to_chat_path(xprompt_name, argument)` - For `resume`: calls `find_named_agent(arg, only_done=True)`
  from `sase.agent.names`, reads `done.json` from `agent.artifacts_dir`, returns `response_path`. For `resume_by_chat`:
  returns the argument directly. Returns `None` on any failure (agent not found, file missing, etc.). Uses lazy import
  for `find_named_agent` to keep the module's import footprint light.

- `_parse_flat_turns(text)` - Parses **User:**/**Assistant:** formatted text (the output of `load_chat_for_resume()`)
  back into `(prompt, response)` tuples. Splits on `**User:**` markers, then splits each chunk on `**Assistant:**`.

- `_extract_previous_conversation_turns(content)` - Finds `## Previous Conversation` (or deeper heading variants like
  `### Previous Conversation`) sections in raw chat file content, extracts their body text, and parses it with
  `_parse_flat_turns()`. Used as fallback when agent resolution fails.

**Modified `load_chat_for_resume()`:**

Add a `_visited: set[str] | None = None` parameter for cycle detection. After parsing turns with `_parse_chat_turns()`,
iterate through each turn's prompt text:

1. Call `_find_resume_refs(prompt)` to detect `#resume` patterns
2. For each ref, try `_resolve_resume_to_chat_path()` to get a file path
3. If resolved and not in `_visited`: recursively call `load_chat_for_resume(path, _visited)`, parse result with
   `_parse_flat_turns()`, prepend those turns before the current turn
4. If resolution fails: fall back to `_extract_previous_conversation_turns()` on the current file's raw content
5. Strip the `#resume` ref text from the prompt
6. Add current file to `_visited` before recursing

### `tests/history/test_chat.py`

Add tests for:

- `_parse_flat_turns()` - basic parsing, empty input, malformed input
- `_find_resume_refs()` - colon syntax, paren syntax, backtick-quoted, no match, multiple refs
- Single-level recursive expansion (prompt with `#resume:name` gets expanded)
- Multi-level chain (A -> B -> C all properly expanded)
- Cycle detection (doesn't infinite loop)
- Fallback to `## Previous Conversation` when agent not found
- `#resume_by_chat:path` expansion
- Prompt text cleanup (ref stripped, surrounding text preserved)
