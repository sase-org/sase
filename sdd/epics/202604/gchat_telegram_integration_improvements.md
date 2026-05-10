---
create_time: 2026-04-27 12:44:30
status: done
bead_id: sase-x
prompt: sdd/prompts/202604/gchat_telegram_integration_improvements.md
---
# retired chat plugin and sase-telegram Integration Improvement Plan

## Context

The implementation work spans external plugin repos adjacent to this repo:

- `../retired chat plugin`
- `../sase-telegram`

The main source of product/technical inspiration is `sdd/research/202604/gchat_integration_review.md`. Current spot-checks against
the repos show that most of the review is still accurate, with two important updates:

- `sase-telegram` already advances outbound notification high-water marks per delivered notification in
  `src/sase_telegram/scripts/sase_tg_outbound.py`, so that recommendation should be treated as already done unless tests
  reveal a regression.
- `retired chat plugin` already avoids auto-naming `%r:N` repeat prompts in `src/retired_chat_plugin/scripts/sase_gc_inbound.py`, matching
  the Telegram behavior.

Every phase below is intended to be executed by a distinct agent instance. Each phase should start by reading this plan,
`sdd/research/202604/gchat_integration_review.md`, and the relevant repo files before editing. If a phase modifies a plugin repo,
it must run `just install` if needed and then `just check` in that plugin repo before reporting completion.

## Guiding Goals

1. Make `retired chat plugin` feel like a first-class sibling of `sase-telegram`, not a minimal transport port.
2. Preserve platform-specific strengths: Google Chat should lean on threads and dot commands; Telegram should keep
   button-heavy workflows.
3. Keep each phase independently reviewable and low-conflict for parallel or sequential agent execution.
4. Treat tests as part of the feature, especially around stateful inbound actions and notification formatting.

## Phase 1: Google Chat Command UX and Agent Context

**Repo:** `../retired chat plugin`

**Primary files likely involved:**

- `src/retired_chat_plugin/scripts/sase_gc_inbound.py`
- `src/retired_chat_plugin/inbound.py`
- `tests/test_inbound.py`

**Objective:** Improve day-to-day command discoverability and agent selection context in Google Chat.

**Work:**

- Add `.help` as a supported dot command.
- Implement a concise help response listing `.list`, `.listx`, `.kill`, `.resume`, `.retry`, `.xprompts`, and `.help`,
  with command syntax examples.
- Add a CommonMark `_format_agent_description(...)` helper analogous to the Telegram HTML helper, including agent name,
  model, duration/status, and a short prompt snippet.
- Use rich agent descriptions in `.resume` output for both running and done agents while preserving copyable command
  snippets.
- Improve `.kill` with no args from a bare usage string into a useful list of killable running agents with descriptions
  and copyable `.kill <name>` lines.
- Keep `.kill <name> [...]` behavior focused on actually killing named agents.

**Acceptance criteria:**

- `.help` parses through `process_dot_command` and returns useful output from `_handle_dot_command`.
- `.kill` with no args gives enough context to choose an agent.
- `.resume` shows enough context to choose an agent without opening the TUI.
- Unit tests cover command parsing, help output, no-arg kill output, and rich resume formatting.
- `just check` passes in `../retired chat plugin`.

## Phase 2: Google Chat Retry and Resume Parity

**Repo:** `../retired chat plugin`

**Primary files likely involved:**

- `src/retired_chat_plugin/scripts/sase_gc_inbound.py`
- `src/retired_chat_plugin/formatting.py`
- `src/retired_chat_plugin/inbound.py`
- `tests/test_inbound.py`
- `tests/test_formatting.py`

**Objective:** Bring over Telegram's highest-value relaunch and resume behavior in a Google Chat-native way.

**Work:**

- Add `.retry <agent-name>` and a short alias `.r <agent-name>`.
- Implement `_get_agent_retry_prompt(name)` by finding the named agent, reading `raw_xprompt.md`, returning `None` if
  unavailable, and stripping only the leading auto `%n:<name>` directive so a retry gets a fresh name.
- On `.retry`, post or launch the recovered prompt through the same inbound launch path used for regular user messages.
  Prefer one launch path over duplicating launch logic.
- Add `.retry <name>` guidance to launch confirmations and, where appropriate, kill confirmations.
- Add `#pr`-aware resume targeting to gchat completion formatting: when the original prompt contains the `#pr` xprompt
  and a VCS workflow tag is present, replace the VCS ref with `@<agent_name>` before emitting the resume command.
- Audit launch confirmations for the same `#pr`/VCS behavior so the generated copyable commands are consistent with
  Telegram.

**Acceptance criteria:**

- `.retry missing-agent` returns a clear unavailable message.
- `.retry existing-agent` launches exactly once using the original prompt with auto `%n:` removed.
- `.r` is covered by parsing and dispatch tests.
- Completion formatting emits `#resume:@<agent>` where required for `#pr` prompts and keeps existing branch/CL behavior
  for non-`#pr` prompts.
- Tests cover long prompts, prompts with `%n:`, prompts with `%r:N`, and missing `raw_xprompt.md`.
- `just check` passes in `../retired chat plugin`.

## Phase 3: Google Chat Stateful Behavior and Formatting Coverage

**Repo:** `../retired chat plugin`

**Primary files likely involved:**

- `src/retired_chat_plugin/formatting.py`
- `src/retired_chat_plugin/scripts/sase_gc_inbound.py`
- `tests/test_formatting.py`
- `tests/test_inbound.py`
- `ROADMAP.md` or `plans/*.md`

**Objective:** Pin the fragile Google Chat-specific behaviors and close the largest test/documentation gaps.

**Work:**

- Add focused formatting tests inspired by Telegram's richer formatting suite, excluding MarkdownV2-only cases.
- Cover blockquote wrapping, frontmatter stripping, provider/model label edge cases, option block rendering, attachment
  list construction, generic notification fallback behavior, and completion resume block rendering.
- Add a test for `_cleanup_externally_handled` calling `_strike_message` and removing pending/awaiting state when the
  TUI has already handled a pending action.
- Review whether `option_codes.py` is still useful after Phase 2. Keep it if it has a clear documented future role;
  otherwise remove it with tests adjusted.
- Create a small roadmap document for remaining Google Chat-only ideas, such as reactions on plan approvals and any
  confirmed limitation around draft or streaming APIs.

**Acceptance criteria:**

- Formatting tests materially narrow the coverage gap with Telegram.
- The TUI-dismissal strike path is covered by a direct unit test.
- Roadmap/documentation reflects what was implemented in Phases 1-3 and what is intentionally deferred.
- `just check` passes in `../retired chat plugin`.

## Phase 4: Telegram Concurrent Feedback State

**Repo:** `../sase-telegram`

**Primary files likely involved:**

- `src/sase_telegram/inbound.py`
- `src/sase_telegram/scripts/sase_tg_inbound.py`
- `tests/test_inbound.py`
- `tests/test_integration.py`

**Objective:** Adopt Google Chat's stronger per-conversation awaiting-feedback model so multiple two-step flows do not
overwrite each other.

**Work:**

- Replace the single-entry `awaiting_feedback.json` model with a keyed mapping. A practical key is the originating
  Telegram `message_id` when available, with a conservative fallback for legacy flows.
- Preserve backward compatibility by reading the old single-entry file shape and normalizing it in memory.
- Update callback handling, plain-text feedback handling, and stale-button cleanup to save/load/clear the correct
  awaiting entry.
- Avoid broad rewrites of callback encoding; this phase is about state cardinality, not Telegram button UX.

**Acceptance criteria:**

- Starting a second feedback flow no longer overwrites the first.
- A reply to one pending flow completes and clears only that flow.
- TUI-handled cleanup clears the matching awaiting entry while leaving unrelated entries intact.
- Existing single-entry state files still load gracefully.
- `just check` passes in `../sase-telegram`.

## Phase 5: Telegram Client Wrapper and Parity Hardening

**Repo:** `../sase-telegram`

**Primary files likely involved:**

- `src/sase_telegram/telegram_client.py`
- `tests/test_telegram_client.py` or equivalent new test file
- `tests/test_outbound.py`
- `tests/test_inbound.py`

**Objective:** Add direct test coverage around Telegram's transport wrapper and lock in parity behaviors that gchat
already tests directly.

**Work:**

- Add direct unit tests for `telegram_client.py`, mirroring the intent of gchat's `test_gchat_client.py` where
  reasonable.
- Cover retry handling for `RetryAfter`, `TimedOut`, and `NetworkError`, plus no-retry behavior for hard errors.
- Cover message splitting around Telegram's message length limit, parse-mode fallback behavior if present in the
  wrapper, photo/document send delegation, callback answering, command registration, and edit operations.
- Add or update outbound tests that explicitly assert per-notification high-water mark advancement in the script-level
  send loop, since this is now an important behavior to keep.

**Acceptance criteria:**

- Telegram has direct client-wrapper tests comparable in spirit to gchat's.
- Retry and length-splitting behavior are pinned without making real network calls.
- Existing integration tests still pass.
- `just check` passes in `../sase-telegram`.

## Phase 6: Cross-Integration Consistency Pass

**Repos:** `../retired chat plugin` and `../sase-telegram`

**Objective:** Land the work as a coherent sibling integration improvement rather than a set of unrelated patches.

**Work:**

- Compare final command vocabularies and user-facing terminology across both integrations.
- Ensure any new docs, help text, and tests agree on command names and expected behavior.
- Run `just check` in both plugin repos.
- If either repo now needs changes in this main `sase_100` repo, make them in a small, clearly justified patch and run
  `just install` then `just check` here.
- Produce a short final implementation summary suitable for a reviewer: user-visible changes, notable technical changes,
  tests run, and deferred follow-ups.

**Acceptance criteria:**

- Both plugin repos pass `just check`.
- User-facing command/help text is consistent where the platforms overlap.
- Deferred work is documented rather than left implicit.

## Suggested Dependency Order

Phases 1 and 3 can be done before Phase 2, but Phase 2 should rebase or adapt to Phase 1's command parser changes. Phase
4 and Phase 5 are independent of the Google Chat work and can run in parallel with Phases 1-3. Phase 6 should run last.

## Risks and Notes for Implementing Agents

- Google Chat has no Telegram-style inline callbacks. Prefer thread-aware dot commands and copyable command snippets
  instead of trying to emulate buttons.
- Be careful with `#pr` resume behavior. The important distinction is replacing the VCS workflow ref with
  `@<agent_name>` only when the original prompt contains the `#pr` xprompt.
- Do not regress `%r:N` handling. Repeat launches should continue to avoid prepending an auto `%n:` directive before
  fan-out.
- The plugin repos may have independent virtualenv state. Run `just install` before checks if dependencies are missing.
- Do not commit unless explicitly asked. If changes span multiple repos, report verification separately for each repo.
