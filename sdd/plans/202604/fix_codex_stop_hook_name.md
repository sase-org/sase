---
status: done
create_time: 2026-04-04 18:24:48
prompt: sdd/prompts/202604/fix_codex_stop_hook_name.md
---

# Fix: Codex stop hook not surfacing name instruction to agent

## Problem

When Codex ran `sase commit` for the `agent_tags` PR workflow, the ChangeSpec name was `sase_agent_tags_ui_research_1`
instead of the expected `sase_agent_tags_1`. The agent invented its own name based on the research file it created
rather than using the name specified by the `pr(name=agent_tags)` workflow.

## Root Cause

In `_emit_block()` (`src/sase/scripts/sase_commit_stop_hook.py:64-76`), the three runtimes receive the stop hook output
differently:

| Runtime | Where `details` goes          | Agent sees it? |
| ------- | ----------------------------- | -------------- |
| Gemini  | JSON `reason` field on stdout | Yes            |
| Claude  | stderr (non-zero exit)        | Yes            |
| Codex   | **stderr only** (exit 0)      | **No**         |

For Codex, the JSON printed to stdout contains only the generic reason
(`"Stop hook blocked: uncommitted changes remain."`). The detailed instructions — including the critical
`You MUST include "name": "sase_agent_tags"` — are printed to stderr, which Codex agents do not surface to the LLM.

Without the name instruction, the Codex agent falls back to choosing a descriptive name from context
(`sase_agent_tags_ui_research`), and the suffix logic adds `_1`.

## Fix

### Phase 1: Include details in Codex JSON reason

**File**: `src/sase/scripts/sase_commit_stop_hook.py`

Change `_emit_block()` so that, for Codex, the `reason` field in the JSON contains `details` (when available), matching
the Gemini pattern. Keep the stderr output for debugging/logging.

Before:

```python
if _is_codex_runtime():
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=True))
    if details:
        print(details, file=sys.stderr)
    return 0
```

After:

```python
if _is_codex_runtime():
    print(json.dumps({"decision": "block", "reason": details or reason}, ensure_ascii=True))
    if details:
        print(details, file=sys.stderr)
    return 0
```

### Phase 2: Add unit tests for `_emit_block`

**File**: `tests/test_commit_stop_hook.py` (new)

Add tests verifying that `_emit_block` includes `details` in the JSON output for both Codex and Gemini runtimes, and
that Claude gets details on stderr with non-zero exit.
