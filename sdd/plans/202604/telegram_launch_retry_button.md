---
create_time: 2026-04-24 21:42:27
status: done
prompt: sdd/prompts/202604/telegram_launch_retry_button.md
---
# Add Retry Copy Button to Telegram Agent Launch Message

## Product Context

When a user launches a sase agent from Telegram (e.g. by sending a prompt to the bot), the bot replies with a "🚀 _MODEL
Launched_" message that carries an inline keyboard:

- Row 1: ▶️ Resume | ⏳ Wait — both `CopyTextButton` (tap copies text into the chat input)
- Row 2: 🗡️ Kill — callback button

Today, if the user wants to re-run the same prompt (after killing, after a transient failure, or just to spawn a
parallel agent with the same task), they have to scroll back to the original message they sent and copy it manually. The
kill-result message already shows a "🔄 Retry" button that copies the original prompt — we want the same affordance
directly on the launch message so users don't have to kill the agent first.

**Goal:** add a "🔄 Retry" button to the launch keyboard that, when tapped, copies the original prompt the user sent to
the bot.

## Repo & Files

- Primary repo: `/home/bryan/projects/github/sase-org/sase-telegram/`
- Source: `src/sase_telegram/scripts/sase_tg_inbound.py`
  - `_launch_single_agent()` — launch keyboard construction (lines ~442–490)
  - `_send_kill_result()` — existing Retry-button pattern to mirror (lines ~244–273)
  - `_handle_retry_from_callback()` — already-in-place callback handler we will reuse (lines ~322–337)
- Tests: `tests/test_inbound.py`
  - `TestLaunchAgent::test_launch_includes_wait_keyboard` — current launch-keyboard test (lines ~489–528). Will need
    updating since row 2 grows from 1 to 2 buttons.
  - `TestSendKillResult` (lines ~858+) and `TestHandleRetryFromCallback` (lines ~916+) — reference patterns for the new
    tests.

## Design

### Button placement

```
Row 1: ▶️ Resume | ⏳ Wait
Row 2: 🗡️ Kill   | 🔄 Retry
```

Keep Resume/Wait on row 1 untouched (they're the high-frequency actions). Group destructive/launcher actions on row 2.

### Copy vs. callback (256-char rule)

Telegram's `CopyTextButton` accepts at most 256 chars. The launch path already has `_COPY_TEXT_MAX = 256`; reuse it.

- `len(original_prompt) <= 256` → `CopyTextButton(text=original_prompt)`
- `len(original_prompt) > 256` → register
  `pending_actions[f"retry-{agent_name}"] = {"action": "retry", "prompt": original_prompt}` and use
  `callback_data=encode("retry", agent_name, "go")`. The existing `_handle_retry_from_callback` already services that
  callback (sends the prompt as a chat message and clears the pending action). No new handler needed.

### What gets copied

Use `original_prompt` (the variable already captured at line 395 of `_launch_single_agent`, before `%n:<auto>` is
prepended). This matches the semantics of the kill-result Retry button — re-launching from a copied prompt should pick
up a fresh auto-name, not collide with the just-killed agent's name.

### Multi-model launches

`_launch_multi_model_agents` (line 502) calls `_launch_single_agent` per model, so the new button automatically appears
on each per-model launch message. No separate change required.

### Why `pending_actions[f"retry-{name}"]` is safe alongside `kill-{name}`

The Kill button already stores `original_prompt` under the `kill-{name}` key (used as the prompt fallback for the
post-kill Retry button). The new long-prompt branch will _also_ store under `retry-{name}` — they're independent keys
with independent lifetimes. The kill flow tolerates a missing entry by reading `_get_agent_retry_prompt(name)` from
`raw_xprompt.md`, so no coupling concerns.

## Implementation Steps

1. **Edit `_launch_single_agent` in `sase_tg_inbound.py`** (inside the `if agent_name:` block, around line 454 where
   `keyboard` is built):
   - Construct the new Retry button:
     - If `len(original_prompt) <= _COPY_TEXT_MAX`:
       `InlineKeyboardButton("🔄 Retry", copy_text=CopyTextButton(text=original_prompt))`
     - Else: register `pending_actions.add(f"retry-{agent_name}", {"action": "retry", "prompt": original_prompt})` and
       use `InlineKeyboardButton("🔄 Retry", callback_data=encode("retry", agent_name, "go"))`
   - Append the Retry button to the existing Kill row (row 2) so the row becomes `[Kill, Retry]`.

2. **Update `tests/test_inbound.py::test_launch_includes_wait_keyboard`** to reflect the new row-2 layout:
   - `assert len(buttons[1]) == 2`
   - `assert buttons[1][0].text == "🗡️ Kill"` (unchanged)
   - `assert buttons[1][1].text == "🔄 Retry"`
   - `assert buttons[1][1].copy_text.text == "List all open beads"` (the original prompt — short, so CopyTextButton
     path)

3. **Add a new test `test_launch_retry_button_uses_callback_for_long_prompt`** in `TestLaunchAgent` that:
   - Calls `_launch_single_agent` with a >256-char prompt
   - Asserts `buttons[1][1].callback_data == "retry:<name>:go"`
   - Asserts `buttons[1][1].copy_text is None`
   - Asserts `pending_actions.add` was called with `f"retry-{name}"` and the correct payload

4. **Update VCS-tag launch tests** (`test_launch_wait_keyboard_includes_vcs_tag`,
   `test_launch_vcs_tag_uses_at_name_when_pr_present`, `test_launch_vcs_tag_unchanged_without_pr`) only if they assert
   on row-2 length/content. If they only assert row-0 buttons, leave them alone. Verify during implementation.

5. **Run validation in the sase-telegram repo:**
   ```bash
   cd /home/bryan/projects/github/sase-org/sase-telegram && just check
   ```

## Out of Scope

- No changes to the kill-result Retry button or `_handle_retry_from_callback`.
- No new top-level `/retry` slash command.
- No changes to the photo/document message launch paths beyond what `_launch_single_agent` already covers (they funnel
  through it).
- No change to the message text or formatting; only the keyboard.

## Risks / Edge Cases

- **Row width on small screens:** Telegram inline buttons reflow to fit; two buttons on row 2 are visually consistent
  with row 1.
- **Empty/whitespace prompts:** Telegram won't allow sending an empty `CopyTextButton`. `original_prompt` always has
  content (it's the message body that triggered the launch), so this isn't reachable in practice.
- **Pending-action staleness:** The `retry-{name}` entry is only consumed by the callback handler when the user taps the
  long-prompt callback button. If the user never taps, the entry persists until cleared. This mirrors the existing
  kill-result long-prompt behavior — acceptable.

## Acceptance

- Telegram launch message shows a 🔄 Retry button on row 2 next to Kill.
- Tapping Retry on a short-prompt launch copies the original prompt into the chat input.
- Tapping Retry on a long-prompt launch sends the original prompt back as a new chat message (via existing callback
  handler).
- `just check` passes in `sase-telegram`.
