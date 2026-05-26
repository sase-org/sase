---
create_time: 2026-05-26 18:43:20
status: done
prompt: sdd/prompts/202605/telegram_retry_copy_names.md
---
# Plan: Telegram Retry Copy Names

## Goal

Telegram Retry buttons should copy or send a relaunch prompt that already names the retry as
`%n:<retried_agent_name>.r<N>`, where `<N>` is allocated with the same retry-name rules used by the TUI and mobile retry
paths. A retry copied from an agent named `foo` should therefore launch as `foo.r1`, then skip to `foo.r2` if `foo.r1`
or one of its descendants is already active.

## Current Behavior

The SASE core repo already has the right retry-name allocator:

- `sase.agent.names.allocate_retry_name(base)` returns the first available `<base>.r<N>`.
- `sase.agent.retry_prompt.rewrite_retry_prompt_name(raw_prompt, retry_name)` replaces the first top-level `%name` /
  `%n` directive, or prepends a name directive when the prompt has none.

The Telegram plugin does not use that path yet:

- `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py::_send_launch_notification()` puts `original_prompt`
  directly into the short-prompt `CopyTextButton`, or stores `original_prompt` in `pending_actions` for long-prompt
  callback retries.
- `_send_kill_result()` similarly uses the stored launch prompt or a fallback prompt from `_get_agent_retry_prompt()`.
- `_get_agent_retry_prompt()` reads `raw_xprompt.md` but strips a leading `%n:<name>` directive, which now makes retry
  prompts unnamed instead of assigning a `.r<N>` retry name.

## Design

1. Add a small core extension rather than duplicating directive parsing in `sase-telegram`.
   - Extend `sase.agent.retry_prompt.rewrite_retry_prompt_name()` with an optional keyword such as
     `directive_alias: Literal["name", "n"] = "name"`.
   - Keep the default output as `%name:<retry_name>` so existing TUI/mobile behavior and tests remain stable.
   - Let Telegram call it with `directive_alias="n"` so the copied text exactly uses `%n:<retry_name>`.
   - Reuse the existing fenced-block and disabled-region protection, so prompts containing literal `%n:` examples are
     not corrupted.

2. Add a Telegram-local helper that builds retry prompt text from a source prompt and source agent name.
   - Suggested shape: `def _build_retry_prompt_for_agent(agent_name: str, source_prompt: str | None) -> str | None`.
   - Strip only surrounding whitespace and return `None` for empty prompts.
   - Call `allocate_retry_name(agent_name)`.
   - Call `rewrite_retry_prompt_name(source_prompt, retry_name, directive_alias="n")`.
   - On unexpected allocation/rewrite errors, log a warning and fall back conservatively to the source prompt so the
     button remains usable, but tests should cover the successful named path.

3. Apply that helper to every Telegram Retry-button payload.
   - In `_send_launch_notification()`, compute `retry_prompt` once inside the `if agent_name:` block and use it for:
     - short-prompt `CopyTextButton(text=retry_prompt)`;
     - long-prompt `pending_actions.add(f"retry-{agent_name}", {"action": "retry", "prompt": retry_prompt})`.
   - Keep the existing CopyTextButton length rule, but measure the rewritten prompt, not the original prompt. Adding
     `%n:<name>.r<N>\n` can push a formerly short prompt over Telegram's 256-character copy limit.
   - Keep the existing launch source semantics for this scoped change: launch Retry is still based on `original_prompt`
     so multi-model or repeat launch messages retain their current "retry the original launch request" behavior, now
     under a retry-derived name.
   - Keep the `kill-{agent_name}` pending action's stored `prompt` as the source prompt, not a precomputed retry prompt,
     so a later kill confirmation can allocate a fresher `.r<N>` if another retry has already appeared.

4. Fix kill-result retry prompts.
   - Change `_send_kill_result()` to build `retry_prompt` through `_build_retry_prompt_for_agent()` from the stored
     source prompt or artifact fallback before creating either the copy button or callback button.
   - Adjust `_get_agent_retry_prompt()` so it returns the raw artifact prompt without stripping `%n:`. Its caller should
     own retry-name rewriting now.
   - Update its docstring/name if helpful, for example to clarify that it returns the source prompt for retry, not a
     fully prepared retry prompt.

5. Preserve callback behavior.
   - `_handle_retry_from_callback()` should continue to send the stored prompt and remove `retry-{agent_name}`.
   - After this change, the stored prompt will already contain `%n:<agent>.r<N>` for long launch/kill retry buttons.

## Edge Cases

- Existing `%n:` / `%name:` directive: replace the first top-level name directive with `%n:<agent>.r<N>` instead of
  prepending a second name.
- No name directive: prepend `%n:<agent>.r<N>` on its own first line.
- Fenced code blocks and disabled xprompt regions: do not treat name-like text in those regions as launch directives.
- Long prompts: evaluate the 256-character copy limit after adding the retry name; use callback storage when the
  rewritten text is too long.
- Static copy text: Telegram copy buttons cannot allocate at tap time. The copied name is correct when the button is
  rendered and skips currently active `.r<N>` names, but an old button can become stale if the user later launches that
  same retry name and then taps the old copy button again. Callback retry buttons can avoid this only if allocation is
  delayed to callback time, but this plan keeps callback behavior aligned with copied text and avoids changing the UX
  contract in this pass.

## Tests

Core repo (`sase_13`):

- Add focused tests for `rewrite_retry_prompt_name(..., directive_alias="n")`:
  - prepends `%n:foo.r1` when no name exists;
  - replaces `%name:foo` with `%n:foo.r1`;
  - replaces `%n:foo` with `%n:foo.r1`;
  - ignores fenced and disabled-region name-like text.
- Keep existing default `%name:` tests unchanged.

Telegram repo (`sase-telegram_13`):

- Update launch retry keyboard tests so short Retry copy text becomes `%n:c.r1\nList all open beads` when
  `allocate_retry_name("c")` is patched to `c.r1`.
- Add/adjust a named-prompt launch test proving `%n:foo ...` becomes `%n:c.r1 ...`, not `%n:c.r1\n%n:foo ...`.
- Update long launch retry test so the pending `retry-c` payload stores the rewritten prompt and the callback button is
  used when the rewritten prompt exceeds `_COPY_TEXT_MAX`.
- Update kill-result tests for short and long prompts so both use `%n:a.r1...` in copy/pending text.
- Add an artifact fallback test where `raw_xprompt.md` contains `%n:a ...`; the kill Retry button should copy
  `%n:a.r1 ...`, proving the fallback no longer strips the name into an unnamed prompt.
- Leave `_handle_retry_from_callback()` tests focused on sending/removing the stored prompt; update the fixture prompt
  to include a retry `%n:` if needed.

## Verification

1. In the core repo:
   - `just install`
   - focused pytest for retry prompt/name tests
   - `just check` after code changes

2. In the Telegram repo:
   - `just install`
   - install the local core workspace editable into the Telegram venv if the new core helper API is used:
     `uv pip install -e /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_13`
   - focused `pytest tests/test_inbound.py`
   - `just check`

## Out Of Scope

- Adding a `/retry` slash command.
- Changing Fork/Wait/Kill button behavior.
- Reworking multi-model or repeat retry semantics beyond adding the retry-derived name to the existing retry source
  prompt.
- Changing SASE's retry allocator rules; this plan consumes the existing `.r<N>` allocator.
