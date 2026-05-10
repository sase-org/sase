---
create_time: 2026-05-02 00:58:36
status: done
prompt: sdd/prompts/202605/rename_run_to_quest.md
---
# Rename Plan Approval Run Option To Quest

## Goal

Rename the user-facing plan approval option currently shown as "Run" to "Quest" in the Telegram and Google Chat
integrations. This option approves the plan, skips committing the plan to the repo, and starts the coder agent. The
behavior must stay the same; only the visible label and supporting documentation/tests should change.

## Current Findings

- Telegram lives in `../sase-telegram`.
  - The visible inline button label is in `src/sase_telegram/formatting.py` as `🚀 Run`.
  - The callback payload is `run`, and `src/sase_telegram/inbound.py` maps it to:
    - `action: approve`
    - `commit_plan: false`
    - `run_coder: true`
  - Tests and docs explicitly mention `Run`.
- Google Chat lives in `../retired chat plugin`.
  - Google Chat cannot render buttons, so the formatter renders numbered options.
  - The visible option label is in `src/retired_chat_plugin/formatting.py` as `🚀 Run`.
  - The persisted payload is `run`, and inbound maps it to the same no-commit coder launch behavior.
  - README/docs/tests explicitly mention `Run`.
- The core `sase` repo handles the `run` response semantics but does not own these external chat labels.

## Implementation Plan

1. Update Telegram presentation.
   - Change the plan approval inline keyboard label from `🚀 Run` to `🚀 Quest` in
     `../sase-telegram/src/sase_telegram/formatting.py`.
   - Keep callback data choice `run` unchanged so existing pending actions and inbound routing remain compatible.

2. Update Google Chat presentation.
   - Change the plan approval numbered option label from `🚀 Run` to `🚀 Quest` in
     `../retired chat plugin/src/retired_chat_plugin/formatting.py`.
   - Keep the payload `run` unchanged so persisted pending actions, thread replies, and inbound processing remain
     stable.

3. Update tests.
   - In `../sase-telegram`, update formatting tests that assert the visible label and any plan-option fixtures that
     include the display text.
   - In `../retired chat plugin`, update tests and fixtures that assert or persist option labels while preserving payload
     assertions for `run`.
   - Do not change inbound behavior tests beyond display-label fixtures; assertions for `commit_plan: false` and
     `run_coder: true` should continue to pass.

4. Update documentation.
   - In both plugin repos, replace references to the user-facing "Run" option with "Quest".
   - Where docs describe payloads or implementation details, keep `run` as the internal payload name and clarify only if
     needed that the Quest option maps to the `run` payload.

5. Verify.
   - Run focused tests first:
     - `just test tests/test_formatting.py tests/test_inbound.py tests/test_integration.py` in `../sase-telegram`
     - `just test tests/test_formatting.py tests/test_inbound.py tests/test_integration.py` in `../retired chat plugin`
   - Run `just check` in each modified plugin repo, per the external repo memory instructions.
   - No main `sase` code changes are expected beyond this plan artifact; if the plan artifact counts as a repo change,
     run the required main-repo `just install` / `just check` before finalizing.

## Non-Goals

- Do not rename the internal `run` callback payload or pending action payload.
- Do not alter `plan_response.json` semantics.
- Do not change the TUI approve-options modal wording unless a later search finds that the user-facing chat label is
  sourced from core UI text rather than plugin formatters.
