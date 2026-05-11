---
name: telegram_resume_running_only
description: Trim /resume to running agents with copy buttons, matching /kill's scope
create_time: 2026-05-11 16:44:48
status: done
prompt: sdd/prompts/202605/telegram_resume_running_only.md
---

# /resume — running agents only

## Problem

The Telegram `/resume` slash command currently shows too many agents. It lists:

1. **Running agents** (🏃) — `list_running_agents()`
2. **Done / Failed / PLAN DONE agents** (✅) — `load_all_agents()` filtered to
   `_DISMISSABLE_STATUSES = {"DONE", "FAILED", "PLAN DONE"}`, minus dismissed, workflow children, and already-running
   names

The dismissable bucket is the noisy one — it pulls every undismissed terminal agent in the workspace and can produce a
long, mostly-irrelevant list. The user wants `/resume` to behave like `/kill`: show only currently-running agents.

Each row is already a Telegram inline `copy_text` button (taps copy `#resume:<name> %w:<name> ` to clipboard). The user
wants to keep that — buttons should remain copy buttons, not change to callback buttons like `/kill` uses. The "only
produce copy buttons" phrasing reinforces _don't add other button kinds_; it doesn't ask us to switch to callbacks.

## Reference points

All in `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`:

- `_show_kill_selection` (lines 1224–1253) — the model: lists running agents only, builds one button per named running
  agent, sends header + descriptions + keyboard.
- `_handle_resume_command` (lines 1304–1419) — the function to edit.

## Scope of change

Edit `_handle_resume_command` only. Reduce it to roughly the structure of `_show_kill_selection`, but keeping the
`copy_text=CopyTextButton(...)` button style and the `vcs_prefix` + `extract_vcs_workflow_tag` logic that builds the
resume payload.

After the change the function should:

1. Call `list_running_agents()`.
2. Drop entries without `a.name`.
3. If nothing remains, send `"No running agents to resume."` and return.
4. For each named running agent, compute `resume_text = f"{vcs_prefix}#resume:{a.name} %w:{a.name} "` (unchanged) and
   build a single `🏃 <name>` copy button.
5. Build descriptions with the existing `_format_agent_description(...)` helper.
6. Send `"Select an agent to resume:\n\n" + "\n\n".join(descriptions)` plus the keyboard, `parse_mode="HTML"`.

## What gets deleted

- The entire "Done / undismissed agents" block (the `load_all_agents()` loop building `done_buttons`).
- The second `load_all_agents()` loop building `done_descs`.
- The `_DISMISSABLE_STATUSES` local set.
- The "Running:" / "Done:" sectioning in the text output (no longer needed with one bucket).
- The imports `load_dismissed_agents` and `load_all_agents` from this function (still used elsewhere in the file if
  applicable — check before removing at module scope; these are function-local imports anyway).

## What stays

- `from sase.xprompt import extract_vcs_workflow_tag` — still needed for the `vcs_prefix`.
- `CopyTextButton` usage and the `🏃 <name>` button label.
- The `resume_text` format string (preserves the `%w:<name>` workspace tag, which is the running-agent variant).
- The `_format_agent_description(name, model or "?", duration, prompt)` call.

## Docstring

Update the docstring from `"Handle /resume — show copy buttons to resume running or done agents."` to something like
`"Handle /resume — show copy buttons to resume currently-running agents."`

## Out of scope

- `_handle_kill_command` is untouched.
- The notification-level `▶️ Resume` button produced by `format_notification` (covered by the four tests in
  `tests/test_formatting.py`) is unaffected and must keep working — it's a different code path.
- No new tests required: there are no existing tests on `_handle_resume_command` directly, and adding inbound-handler
  tests is beyond the scope of this bug-trim. Test pass for `test_formatting.py` should remain green because we don't
  touch that path.

## Verification

After editing:

- Run the sase-telegram test suite (`just test` from `../sase-telegram`) to confirm `tests/test_formatting.py` still
  passes.
- Quick read of the diff: confirm only one bucket builds buttons, no `load_all_agents` / `load_dismissed_agents`
  references remain inside `_handle_resume_command`, and the empty-state message reads "No running agents to resume."

## Risk

Low. Single function, no shared helpers changed, no schema changes, no callers of `_handle_resume_command` other than
the inbound command dispatcher.
