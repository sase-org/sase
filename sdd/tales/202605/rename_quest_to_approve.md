---
create_time: 2026-05-02 12:21:49
status: done
prompt: sdd/prompts/202605/rename_quest_to_approve.md
---
# Rename Quest Plan Option To Approve

## Goal

Rename the user-facing plan approval option currently shown as "Quest" to exactly "Approve" in the places users choose
the no-commit coder launch path:

- Telegram plan approval buttons in `../sase-telegram`.
- Google Chat plan approval numbered options in `../retired chat plugin`.
- Any current TUI surface in this repo that exposes the same path as a user-facing "Quest" option.

The behavior must not change. This option still approves the plan, does not commit the plan file, and starts the coder
agent.

## Current Findings

- The normal committed plan action is currently labeled "Tale" in all three surfaces and maps to internal payload/action
  `approve`.
- The no-commit coder-launch action is currently labeled "Quest" in Telegram and Google Chat and maps to internal
  payload `run`.
- The inbound handlers for `run` write a response equivalent to:
  - `action: "approve"`
  - `commit_plan: false`
  - `run_coder: true`
- Existing pending chat actions store payloads, not just display labels. Keeping `run` unchanged preserves compatibility
  for already-sent Telegram buttons and Google Chat numbered replies.
- The current TUI checkout does not contain a literal user-facing "Quest" in the plan approval modal. The TUI exposes
  the same behavior through `Tale Options` by toggling `Commit plan` off while leaving `Run coder agent` on. I should
  not rename the main TUI `Tale` action back to `Approve`; that would undo the earlier approval taxonomy and is outside
  this request.

## Implementation Plan

1. Update Telegram presentation only.
   - In `../sase-telegram/src/sase_telegram/formatting.py`, change the second plan approval button label from `🚀 Quest`
     to `Approve`.
   - Keep `callback_data=callback_data.encode("plan", prefix, "run")` unchanged.
   - Leave `../sase-telegram/src/sase_telegram/inbound.py` behavior unchanged, including the `run` payload handling and
     response fields.

2. Update Google Chat presentation only.
   - In `../retired chat plugin/src/retired_chat_plugin/formatting.py`, change `Option("🚀 Quest", "run")` to `Option("Approve", "run")`.
   - Keep numeric option ordering unchanged so existing mental models and tests remain stable: `Tale`, `Approve`,
     `Epic`, `Legend`, `Reject`, `Feedback`.
   - Leave `../retired chat plugin/src/retired_chat_plugin/inbound.py` behavior unchanged.

3. Handle the TUI carefully.
   - Re-run focused searches for `Quest` and `🚀 Quest` in `src/sase/ace/tui`, `tests`, and `docs` before editing.
   - If a current TUI label or fixture does contain the no-commit path as "Quest", rename that display label to
     `Approve` while preserving `PlanApprovalResult(action="approve", commit_plan=False, run_coder=True)` semantics.
   - If no TUI "Quest" surface exists, make no TUI code change. Document that the current TUI equivalent remains the
     options combination `Commit plan=OFF` and `Run coder agent=ON`.
   - Do not rename:
     - `Tale` labels,
     - internal `approve` methods/classes/dataclasses,
     - `%approve` autonomous-agent directive text,
     - `QUESTION`/`QUEST` timestamp or status labels.

4. Update tests.
   - Telegram:
     - Update `../sase-telegram/tests/test_formatting.py` so the plan approval keyboard expects `Approve` for the second
       button while callback data still ends in `:run`.
     - Keep inbound tests asserting the `run` behavior unchanged.
   - Google Chat:
     - Update `../retired chat plugin/tests/test_formatting.py`, `../retired chat plugin/tests/test_inbound.py`,
       `../retired chat plugin/tests/test_integration.py`, and `../retired chat plugin/tests/test_externally_handled_cleanup.py` fixtures
       and assertions that include `🚀 Quest`.
     - Preserve payload assertions for `run` and response assertions for `commit_plan: false` / `run_coder: true`.
   - Main TUI:
     - Only update tests if a real TUI "Quest" label is found. Existing tests proving `Tale` maps to internal `approve`
       should stay intact.

5. Update documentation.
   - Replace current user-facing plan option lists in:
     - `../sase-telegram/README.md`
     - `../sase-telegram/docs/outbound.md`
     - `../retired chat plugin/README.md`
     - `../retired chat plugin/docs/outbound.md`
   - Use `Tale / Approve / Epic / Legend / Reject / Feedback`.
   - Where docs discuss protocol details, keep the internal payload name `run` and clarify that the visible `Approve`
     option maps to the `run` payload for compatibility.
   - Do not bulk-edit historical SDD artifacts.

6. Verify.
   - Main repo:
     - If only this plan artifact changes in the main repo before implementation, no TUI tests are required yet.
     - After any main repo code/doc change, run `just install` if needed, then `just check` before final response.
   - Telegram plugin:
     - Run focused tests: `pytest tests/test_formatting.py tests/test_inbound.py tests/test_integration.py`.
     - Run `just check` before final response if the plugin is modified.
   - Google Chat plugin:
     - Run focused tests:
       `pytest tests/test_formatting.py tests/test_inbound.py tests/test_integration.py tests/test_externally_handled_cleanup.py`.
     - Run `just check` before final response if the plugin is modified.

## Non-Goals

- Do not rename the internal `run` payload.
- Do not change `plan_response.json` semantics.
- Do not change confirmation/status text such as "Running coder (no commit)" unless a product follow-up explicitly asks
  for that copy to change too.
- Do not rename normal "Tale" approval back to "Approve".
