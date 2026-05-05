---
create_time: 2026-05-04 20:44:05
status: done
prompt: sdd/prompts/202605/telegram_at_vcs_xprompt_normalization.md
---
# Plan: Normalize Telegram `#workflow@ref` VCS Prompts

## Problem

Telegram-originated launch prompts currently need workarounds like `#gh_sase` because `#gh:sase` is inconvenient in the
Telegram input surface. We want inbound Telegram messages such as:

```text
#gh@sase Fix the bug
```

to reach SASE as:

```text
#gh:sase Fix the bug
```

This should let us remove `gh_sase`-style alias hacks for VCS xprompt workflows, while keeping the behavior scoped to
Telegram ingress instead of changing CLI/TUI prompt parsing globally.

## Findings

- The Telegram integration lives in the sibling repo `../sase-telegram`.
- Text launch ingress is `src/sase_telegram/scripts/sase_tg_inbound.py::_handle_text_message()`.
- Photo/document launch prompts are built from captions in `_handle_photo_message()` and `_handle_document_image()`.
- Feedback flows and slash commands are intentionally handled before agent launch and must preserve the user's raw text.
- The plugin already extracts project context using VCS-ish tags in `_extract_project_from_prompt()`, and this needs to
  see the same normalized prompt that will be sent to SASE.
- Core SASE already supports `#gh_sase` normalization in `src/sase/xprompt/_parsing.py`, but there is no Telegram-only
  `@` shorthand. Broadening core parsing would change every prompt surface, which is not necessary for this request.

## Design

Implement Telegram-only launch prompt normalization in `../sase-telegram`, with a pure helper that converts `@` to `:`
only when it is acting as the separator in a VCS/workspace xprompt invocation:

```text
#gh@sase       -> #gh:sase
%n:a #gh@sase -> %n:a #gh:sase
#git@repo      -> #git:repo
#hg@change     -> #hg:change
```

The first implementation should be intentionally narrow:

- Match only known workspace workflow names already recognized by the Telegram plugin: `gh`, `git`, `hg`, `jj`, `p4`,
  and likely `cd` if we want parity with current SASE workspace workflows.
- Match only references that begin in xprompt-safe leading context: start of text, after whitespace, or after opening
  punctuation/quotes.
- Preserve the ref body and only replace the separator character.
- Do not rewrite ordinary mentions, email addresses, slash command bot suffixes, or arbitrary prose.
- Do not rewrite inside Telegram-reconstructed inline code or fenced code blocks, because those are literal text rather
  than active xprompt invocations.

I would not generalize this to every `#name@arg` xprompt yet. The motivating problem is VCS workspace selection, and a
generic rewrite could surprise users who mention Telegram usernames next to hashtags.

## Implementation Steps

1. Add a pure helper in `../sase-telegram/src/sase_telegram/inbound.py`, for example
   `normalize_launch_xprompt_at_refs(text: str) -> str`.
   - Use a small regex over known workflow names.
   - Protect inline/fenced code spans before replacement, or otherwise skip matches inside those spans.
   - Keep the helper independent of Telegram API objects so it is straightforward to unit test.

2. Apply that helper only on agent-launch paths in `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`.
   - In `_handle_text_message()`, run it after feedback and slash-command handling and after the launch-disabled check,
     then pass the normalized text to `_record_project_context()` and `_launch_agent()`.
   - In `_handle_photo_message()` and `_handle_document_image()`, normalize the reconstructed caption before calling
     `build_photo_prompt()`, so the wrapped image prompt contains the SASE-native `#gh:sase` form.
   - Consider also normalizing at the start of `_launch_agent()` as a defensive backstop if there are direct launch
     callers, but avoid double-normalization side effects by making the helper idempotent.

3. Make project-context extraction consistent.
   - Prefer feeding `_record_project_context()` the normalized launch prompt.
   - Optionally make `_extract_project_from_prompt()` call the same helper internally so pending prompts or historical
     retry prompts containing `#gh@sase` still resolve a bead project context.

4. Add focused tests in `../sase-telegram/tests/test_inbound.py`.
   - Pure helper cases: `#gh@sase`, `%n:a #gh@sase`, quoted/parenthesized forms, multiple refs, idempotent `#gh:sase`,
     and existing `#gh_sase`.
   - Non-rewrite cases: `@someone`, `name@example.com`, `/command@bot`, prose hashtags, and code-formatted
     `` `#gh@sase` `` / fenced `#gh@sase`.
   - Launch integration: `_handle_text_message()` calls `_record_project_context()` and `_launch_agent()` with
     `#gh:sase`, not `#gh@sase`.
   - Photo/document caption integration: captions with `#gh@sase` become wrapped prompts containing `#gh:sase`.
   - Feedback-flow test: a reply completing a HITL/question flow keeps feedback text unchanged.

5. Update docs in `../sase-telegram/docs/inbound.md`.
   - Add one line under Agent Launching describing Telegram's VCS shorthand, for example: `#gh@sase` is normalized to
     `#gh:sase` before launch.

6. Verification.
   - Run `just test tests/test_inbound.py` in `../sase-telegram`.
   - Run `just check` in `../sase-telegram` because that repo will be modified.
   - No core SASE files should need changes unless implementation discovers shared parsing behavior is required.

## Risks and Edge Cases

- `@` already has meaning inside VCS refs for agent references, e.g. `#gh:@planner`. This plan does not introduce a
  compact `#gh@planner` agent-ref shorthand; it treats `#gh@planner` as `#gh:planner`. If we want an agent-ref
  shorthand, we should define a distinct syntax such as `#gh@@planner` and test it explicitly.
- If a user formats the entire launch tag as Telegram code, the helper should leave it alone, matching SASE's existing
  behavior of protecting code from xprompt expansion.
- If future workspace plugins add new workflow names, the Telegram plugin's local known-workflow list may need to be
  refreshed. A later improvement could read registered SASE workspace workflow names dynamically with a safe fallback.

## Expected Outcome

After this change, Telegram users can launch VCS-scoped agents with `#gh@sase`, while SASE receives and records the
canonical `#gh:sase` prompt. Existing colon and underscore forms continue to work, and non-launch Telegram interactions
are unaffected.
