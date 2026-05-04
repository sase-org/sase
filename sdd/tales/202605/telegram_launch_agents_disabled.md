---
create_time: 2026-05-04 17:49:34
status: done
prompt: sdd/prompts/202605/telegram_launch_agents_disabled.md
---
# Telegram Launch Disable Environment Variable

## Goal

Add support to the `sase-telegram` inbound integration for `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED`. When this environment
variable is present with any value, Telegram inbound processing should continue to receive and handle non-launch
interactions, but should not start new SASE agents from new Telegram user messages.

This supports multi-machine setups where several hosts run `sase axe` with the Telegram plugin installed. All machines
can still deliver outbound agent notifications and process action responses, while only hosts without the variable set
can turn free-form Telegram messages into new agents.

## Current Behavior

The plugin lives in `../sase-telegram`.

Inbound message handling is implemented in `src/sase_telegram/scripts/sase_tg_inbound.py`.

- `_handle_text_message()` first completes pending two-step feedback flows.
- It then dispatches slash commands.
- Any remaining text records project context and calls `_launch_agent(text)`.
- `_handle_photo_message()` and `_handle_document_image()` download the image, build an image prompt, record project
  context, and call `_launch_agent(prompt)`.
- `_launch_agent()` expands xprompts, handles multi-model directives, and calls `_launch_single_agent()` one or more
  times.

The pure `src/sase_telegram/inbound.py` module does not launch agents directly; this is script-level orchestration.

## Intended Behavior

When `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` is present in `os.environ`:

- Telegram callbacks still work for plan approvals, HITL responses, questions, kill/retry callbacks, and bead callbacks.
- Two-step text replies still complete feedback/custom response flows.
- Slash commands still run normally, including `/list`, `/kill`, `/resume`, `/changes`, `/xprompts`, `/bead`, and
  `/update`.
- Plain text that would otherwise launch an agent is ignored after logging.
- Photo messages and image documents that would otherwise launch an agent are ignored before download, avoiding
  unnecessary local files and Telegram file API calls.
- Disabled machines should not send a Telegram acknowledgement for ignored launch messages, because in the multi-machine
  use case that would create duplicate chat noise. The enabled machine's normal launch confirmation is enough.

The check is presence-based, not truthiness-based: an empty string still counts as set.

## Implementation Plan

1. Add a small script-local helper in `src/sase_telegram/scripts/sase_tg_inbound.py`, for example:
   `def _telegram_agent_launches_disabled() -> bool`. It should return whether `"SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED"`
   is a key in `os.environ`.

2. Use the helper at the launch decision points:
   - In `_handle_text_message()`, after feedback and slash-command handling but before `_record_project_context()` and
     `_launch_agent()`.
   - In `_handle_photo_message()`, before downloading the Telegram file.
   - In `_handle_document_image()`, before downloading the Telegram file.

3. Keep `_launch_agent()` as the centralized actual launcher, but prefer guarding in the message handlers so
   launch-disabled mode does not mutate project context or download images for ignored launch messages.

4. Add focused tests in `tests/test_inbound.py`:
   - Plain text launches when the env var is absent.
   - Plain text does not call `_record_project_context()` or `_launch_agent()` when the env var is present, including
     when set to an empty string.
   - Feedback completion still writes a response and does not launch when the env var is present.
   - Slash command dispatch still runs when the env var is present.
   - Photo/image-document handlers return before download and launch when the env var is present.

5. Update documentation:
   - Add `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` to the README environment variable table.
   - Mention the disabled launch behavior in `docs/inbound.md`, especially that callbacks, feedback, and slash commands
     still work.

6. Verify in `../sase-telegram`:
   - Run targeted inbound tests first while iterating.
   - Run `just check` before reporting completion, per the plugin repo instructions.

## Risks And Notes

- Sending an explicit "launch disabled" Telegram message from every disabled host would be counterproductive in the
  target multi-machine setup, so logging only is intentional.
- Guarding photo/document handling before download means disabled machines will not keep local copies of images. That
  matches the feature's purpose because the images only exist to build launch prompts.
- This change should not touch the outbound path; receiving notifications from all machines remains unchanged.
