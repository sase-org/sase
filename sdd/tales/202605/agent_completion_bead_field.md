---
create_time: 2026-05-02 16:18:24
status: done
prompt: sdd/prompts/202605/agent_completion_bead_field.md
---
# Plan: Add `Bead:` to Telegram and Google Chat agent completion messages

## Goal

Show the same bead metadata value in Telegram and Google Chat agent completion notifications that the TUI Agents-tab
metadata panel currently renders as:

- `Bead: <id>`
- `Bead: <id> - <collapsed description>`
- `Bead: <epic_id> - Land epic: <title>` for epic land agents when there is no description

The chat integrations should not independently infer or look up bead state. They should receive a stable notification
payload field from `sase` and render it consistently.

## Current Shape

- TUI formatting lives in `src/sase/ace/tui/models/agent_bead.py` and is rendered by
  `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`.
- Agent completion notifications are created by
  `src/sase/axe/run_agent_runner_finalize.py::send_completion_notification()` and stored through
  `notify_workflow_complete()` as `Notification.action_data`.
- Telegram renders user-agent completion notifications in
  `../sase-telegram/src/sase_telegram/formatting.py::_format_workflow_complete()`.
- Google Chat renders the same notification class in
  `../retired chat plugin/src/retired_chat_plugin/formatting.py::_format_workflow_complete()`.

## Design

1. Extract bead display logic out of the TUI-only module into a shared Python adapter, tentatively
   `src/sase/agent/bead_display.py`.
   - Provide `derive_agent_bead_id_from_name(agent_name: str | None) -> str | None`.
   - Provide
     `format_agent_bead_display_for_name(agent_name: str | None, include_description: bool = True) -> str | None`.
   - Preserve the existing normalization rules:
     - strip one dismissed-agent date prefix like `260428.`;
     - `<epic>.land` maps to `<epic>`;
     - names ending in `.<number>` are phase bead agents;
     - top-level names matching `^[^\s.]+-[0-9a-z]+$` are top-level bead agents.
   - Keep bead storage access behind the existing `get_read_view()` path, which already routes read operations through
     the Rust-backed bead facade/merged view. This avoids importing TUI types into runner code and avoids duplicating
     lookup behavior inside chat plugins.

2. Rewire the TUI helper to delegate to the shared adapter.
   - Keep the public TUI functions if tests/imports use them, but make them thin wrappers around the shared functions.
   - Existing TUI tests should remain the parity guard for the visual `Bead:` value.

3. Add a notification payload field from the runner.
   - In `send_completion_notification()`, compute
     `bead_display = format_agent_bead_display_for_name(agent_name, include_description=True)`.
   - If present, add `action_data["bead_display"] = bead_display` for both `JumpToAgent` and failed `ViewErrorReport`
     terminal notifications.
   - Do not add the field when no bead is inferable or lookup fails and only the id is not derivable.
   - Keep `notes` unchanged so existing notification list/search behavior and old consumers remain compatible.

4. Render the field in both chat plugins.
   - Telegram: in `_format_workflow_complete()`, read `n.action_data.get("bead_display")` and render a separate
     `*Bead:* ...` line near the header, directly after the optional `@agent` header line and before notes. Escape the
     value with the existing MarkdownV2 helper.
   - Google Chat: render `*Bead:* ...` in the same position, using normal Google Chat markdown.
   - Keep prompt, PR URL, attachments, and resume controls exactly as they are.

## Edge Cases

- Agents with no name: no bead field.
- Named non-bead agents: no bead field.
- Missing bead store or missing issue: keep the id-only fallback when a bead id can be derived from the name, matching
  the TUI fallback.
- Empty or whitespace-only descriptions: fall back to `Bead: <id>`.
- Land agents and exact epic agents: preserve the current land/title fallback behavior.
- Dismissed done agents with a date prefix: derive the underlying bead id, matching the TUI.

## Tests

Main `sase` repo:

- Add focused tests for the new shared adapter or update existing TUI bead tests to cover the extracted helper.
- Add `send_completion_notification()` tests that:
  - include `bead_display` in `action_data` when the agent name maps to a bead;
  - omit it for ordinary names;
  - include it on the failure/error-report path.
- Keep existing TUI header tests passing to prove no visual regression.

Telegram plugin:

- Add formatting tests for a user-agent completion notification with
  `action_data={"agent_name": "sase-x.3", "bead_display": "sase-x.3 - Fix the thing"}`.
- Assert the rendered message contains the escaped `*Bead:*` line and still includes the resume button.
- Add a no-`bead_display` case if existing coverage does not already prove no extra line appears.

Google Chat plugin:

- Add the equivalent `_format_workflow_complete()`/`format_notification()` tests.
- Assert the rendered message contains `*Bead:* sase-x.3 - Fix the thing` and preserves the resume block.

## Verification

After implementing source changes:

1. In `/home/bryan/projects/github/sase-org/sase_102`, run `just install`, targeted pytest for the touched tests, then
   `just check`.
2. In each modified plugin repo, run its targeted tests and then `just check`.
3. If a Rust-core change becomes necessary during implementation, run the relevant `cargo test` coverage in
   `../sase-core` before rerunning the Python checks that depend on the rebuilt binding.

## Non-Goals

- Do not make Telegram or Google Chat query bead state at send time.
- Do not change notification notes, attachment ordering, resume prompts, PR link rendering, or prompt truncation.
- Do not add `Bead:` to plan approval, HITL, question, `/resume`, or generic notification messages in this pass.
