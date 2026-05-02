---
create_time: 2026-04-28 14:18:48
status: done
prompt: sdd/prompts/202604/wrap_qa_xprompts_disabled.md
---
# Wrap Q&A Section with `%xprompts_enabled` Directive

## Problem

When an agent calls `sase questions` and the user answers, the rendered Q&A markdown is appended to
`state.current_prompt` and fed back to the next agent invocation. The Q&A markdown contains **user-supplied free text**
— question headers, question bodies, custom-feedback strings ("Other:" answers), and the global note — any of which can
contain `#word` tokens that will be misinterpreted as xprompt references (e.g. a user typing "see #123 for context",
"use the `#flag` arg", or referencing a markdown header).

That accidental expansion is at best confusing and at worst destructive (an unintended xprompt could rewrite the prompt
or fail loudly). The Q&A section is a faithful transcript of what the user wrote — it should pass through xprompt
processing untouched.

## Goal

Wrap the Q&A markdown that gets appended to the prompt with the existing `%xprompts_enabled:false` …
`%xprompts_enabled:true` region markers so the entire Q&A block is exempt from xprompt expansion. The markers are
stripped by `strip_disabled_region_markers()` before the agent ever sees the prompt, so the agent's view is unchanged —
only the expansion stage skips this region.

## Scope

In scope:

- Wrap the Q&A text _only at the point where it is appended to the agent prompt_ (the xprompt-expansion path).
- Cover the path in `src/sase/axe/run_agent_exec_plan.py` (`handle_questions_marker`, line ~485-487).

Out of scope (intentionally):

- The TUI modal preview (`src/sase/ace/tui/modals/user_question_modal.py`) — that's user-facing and never goes through
  xprompt expansion; markers would just be visual noise.
- The chat-history copy passed to `save_chat_history()` (line ~460) — that's the recorded response artifact, not a
  prompt fed back into expansion.
- Changing `build_qa_markdown()` in `src/sase/main/qa_markdown.py` — keep the canonical formatter expansion-agnostic;
  wrapping is a concern of the prompt-append site, not the markdown builder.
- Worrying about a user typing the literal string `%xprompts_enabled:true` inside their answer (a pathological
  early-close). If we hit it in practice we'll add escaping; not worth designing for now.

## Design

### Where to wrap

Two reasonable sites:

1. **Inside `format_qa_for_prompt()`** (`src/sase/axe/run_agent_helpers.py:470`). It's already the "for-prompt" variant
   of the formatter, which makes the name accurate.
2. **At the call site** in `run_agent_exec_plan.py` where `current_prompt` is augmented.

Recommendation: **Option 1**. `format_qa_for_prompt` is the prompt-bound formatter and its only caller that matters here
is the prompt-append site. The chat-history call at line 460 also uses it, but wrapping the chat-history copy with
markers is harmless: chat history is not re-expanded, and the markers will simply appear as literal text in the saved
transcript. If that's undesirable we'll move the wrap to the call site instead — flag this during review.

Open question to resolve in implementation: **does the chat-history transcript get re-fed into a future xprompt
expansion** (e.g. via `#resume:<name>`)? If yes, wrapping inside `format_qa_for_prompt` is doubly correct (history needs
the markers too). If no, either site works. A 2-minute grep around `save_chat_history` and `#resume` callers will settle
it; default to Option 1 unless that grep surprises us.

### What the wrapping looks like

```python
WRAP_OPEN = "%xprompts_enabled:false"
WRAP_CLOSE = "%xprompts_enabled:true"

def format_qa_for_prompt(questions, response) -> str:
    body = build_qa_markdown(questions, response)        # existing call
    return f"{WRAP_OPEN}\n{body}\n{WRAP_CLOSE}"
```

Each Q&A section gets its own pair of markers. Multiple Q&A rounds in the same agent run produce multiple independent
regions — that's fine; the protect/unprotect machinery in `_disabled_regions.py` handles N regions.

### State list

`state.qa_sections.append(qa_text)` (line ~486 in `run_agent_exec_plan.py`) — should the stored copies be wrapped or
unwrapped? Audit what consumes `qa_sections`:

- If it's only used to _reconstruct_ the prompt for retries / handoff, wrapped is correct (consistent with what's in
  `current_prompt`).
- If it's surfaced to humans (logs, artifacts), unwrapped reads better.

Resolve during implementation by tracing references; default to "store what we appended to the prompt" (wrapped) so the
two stay in sync.

## Test plan

Add tests under `tests/` (likely a new `test_qa_xprompts_wrap.py` or extend `test_qa_format.py`):

1. **Unit**: `format_qa_for_prompt(...)` output starts with `%xprompts_enabled:false\n` and ends with
   `\n%xprompts_enabled:true`.
2. **Integration with xprompt processor**: Build a Q&A section whose body contains `#some_xprompt_name`, feed it through
   `protect_disabled_regions` → expansion → `unprotect_disabled_regions` → `strip_disabled_region_markers`. Assert: the
   `#some_xprompt_name` text survives literally, and the markers are gone from the final string.
3. **Regression**: a Q&A custom-feedback string containing the literal text `#fix-me` is preserved verbatim in the
   final, post-expansion prompt.

Existing `tests/test_qa_format.py` and `tests/test_disabled_regions.py` cover the building blocks; the new tests are
about their composition.

## Risks & mitigations

- **Chat history shows ugly markers** — acceptable, but if it bothers reviewers, move the wrap to the
  `current_prompt += ...` call site instead of into `format_qa_for_prompt`. One-line change.
- **User text contains `%xprompts_enabled:true`** — unlikely; would prematurely close the region. Out of scope; add a
  note in code if we want a future hardening pass.
- **Snapshot/golden tests** that assert exact `current_prompt` contents will break. Find and update them (grep for
  `format_qa_for_prompt` and `Questions and Answers` in tests).

## Files touched (estimate)

- `src/sase/axe/run_agent_helpers.py` — `format_qa_for_prompt` (≤ 5 lines).
- `tests/test_qa_format.py` (or new file) — 2-3 new test cases.
- Possibly `src/sase/axe/run_agent_exec_plan.py` if we decide to wrap at the call site instead.

## Out-of-scope follow-ups (don't do now, just note)

- Escaping a literal `%xprompts_enabled:true` token inside user-typed answers.
- Applying the same wrapping to other places where untrusted user text gets concatenated into a prompt (if any exist —
  quick audit could be a separate task).
