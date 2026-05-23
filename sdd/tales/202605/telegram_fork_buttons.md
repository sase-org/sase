---
create_time: 2026-05-23 16:44:08
status: done
prompt: sdd/prompts/202605/telegram_fork_buttons.md
---
# Plan: Migrate Telegram Follow-Up Prompts From Resume to Fork

## Goal

Telegram follow-up controls should consistently use the current fork workflow instead of the legacy resume xprompt
workflow. In the screenshot, launch confirmation buttons still say `Resume` and copy prompts containing `#resume:...`.
The desired behavior is for those buttons and related command surfaces to say `Fork` and copy `#fork:...` prompts.

## Scope

Primary code changes belong in the `sase-telegram` workspace:

- Outbound workflow-complete notification formatting in `src/sase_telegram/formatting.py`.
- Inbound launch-confirmation keyboard construction in `src/sase_telegram/scripts/sase_tg_inbound.py`.
- The Telegram slash command that currently exposes resume copy text.
- Tests and docs in `tests/`, `README.md`, and `docs/` that encode the old Telegram behavior.

Core SASE `#resume` parser support is outside this change. The request is about Telegram UI/copy text and removing the
legacy xprompt workflow from that integration, not deleting compatibility behavior from SASE core.

## Implementation Approach

1. Replace Telegram-generated `#resume:<agent>` prompt fragments with `#fork:<agent>` while preserving existing VCS
   workflow prefix behavior and wait chaining (`%w:<agent>`).
2. Change visible Telegram button text from `▶️ Resume` to `🍴 Fork` on workflow-complete and launch-confirmation
   keyboards.
3. Rename the Telegram agent-management command surface from `/resume` to `/fork`, including handler naming, registered
   slash command metadata, empty-state text, descriptions, and docs.
4. Keep the surrounding launch, kill, wait, retry, VCS tag, PR-aware `@agent` ref replacement, and copy-text size logic
   unchanged.
5. Update tests to assert `#fork:` and `Fork`, and add/update command dispatch coverage so `/fork` is the registered
   command and `/resume` is no longer advertised.
6. Audit with `rg` so no Telegram-owned generated prompt, test expectation, or docs still refer to the legacy `#resume:`
   workflow or `Resume` button language.

## Verification

- Run focused tests covering formatting and inbound launch behavior:
  - `pytest tests/test_formatting.py tests/test_inbound.py`
- Run the repo check command after file changes:
  - `just check`
- Re-run `rg` in `sase-telegram` for `#resume:`, `▶️ Resume`, `/resume`, and resume-copy phrasing to verify the legacy
  Telegram workflow references are gone.
