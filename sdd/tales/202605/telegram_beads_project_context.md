---
create_time: 2026-05-02 21:26:42
status: wip
prompt: sdd/prompts/202605/telegram_beads_project_context.md
---
# Fix Telegram `/beads` Project Context

## Root Cause

The `/bead` and `/beads` Telegram commands currently run `sase bead list` through `_run_bead_command()`, which resolves
a working directory with `_resolve_bead_cwd()`. That resolver chooses the first project it can extract from the newest
pending Telegram actions.

This is the wrong source of truth for a global slash command:

- The visible Telegram context in the screenshot is a completed `zorg` agent.
- The `zorg` primary workspace has open beads: `zorg-1`, `zorg-2`, `zorg-1.8`, and several in-progress child beads.
- The `sase` and `sase-telegram` workspaces currently return `No issues found.`
- Pending actions are global and can contain unrelated projects; the newest pending entries right now are `#gh_sase`
  actions, so the resolver can pick `sase` even when the user is interacting with a recent `zorg` completion.
- Completed agent notifications are not pending actions, so the resolver loses the actual project context at exactly the
  moment the user naturally sends `/beads`.

There is also a secondary weakness: image-message prompts wrap the caption in boilerplate text, so
`_extract_project_from_prompt()` only works when the VCS workflow tag is at the very start of the full prompt.

## Goals

1. Make `/bead` and `/beads` resolve against the same project the user most recently launched from Telegram, scoped to
   the Telegram chat.
2. Preserve the explicit `SASE_TELEGRAM_BEAD_PROJECT` override as the highest priority.
3. Keep `/bead <id>` rendering and `/bead` picker behavior unchanged after cwd resolution.
4. Keep pending-action scanning only as a fallback, and make it chat-scoped when the command message provides a chat id.
5. Add focused tests that reproduce the current failure mode: a stale/newer pending `sase` action must not override a
   more recent chat-scoped `zorg` launch context.

## Design

Add a small persisted chat project context file under `~/.sase/telegram/`, for example `project_context.json`.

Shape:

```json
{
  "<chat_id>": {
    "project": "zorg",
    "workspace": "/home/bryan/projects/github/zettel-org/zorg",
    "updated_at": 1777770889.0,
    "source": "launch_prompt"
  }
}
```

Whenever the inbound handler launches an agent from Telegram text, photo caption, or image-document caption, extract the
first VCS workflow project tag from the launch prompt and persist it for that chat. This records the project at launch
time and keeps it available after the agent completes and its pending kill/retry buttons are gone.

Update command dispatch to pass command message context through:

- `_handle_text_message(message)` calls `_handle_command(text, message)`.
- `_handle_command(text, message=None)` passes the message to `_handle_bead_command(args, message)`.
- `_handle_bead_command()` and `_show_bead_selection()` call `_run_bead_command(..., message=message)`.
- `_run_bead_command()` calls `_resolve_bead_cwd(message=message)`.

Resolver priority:

1. `SASE_TELEGRAM_BEAD_PROJECT`, unchanged.
2. The persisted project context for `message.chat.id` or the configured chat id.
3. Pending Telegram actions for the same chat id, newest first.
4. Pending Telegram actions without chat filtering, as the existing compatibility fallback.
5. Current process cwd.

Make `_extract_project_from_prompt()` find a VCS workflow project tag in wrapped Telegram photo prompts as well as at
the beginning of normal prompts. It should still ignore non-project xprompt tags like `#resume` and `#sase__research`;
keep the existing workflow/ref shape (`#gh:sase`, `#gh_sase`, `#gh(sase)`).

## Files to Change

In `../sase-telegram`:

- `src/sase_telegram/scripts/sase_tg_inbound.py`
  - Add project-context load/save helpers.
  - Record project context before `_launch_agent()` for text and image prompts.
  - Thread message context into bead command handling.
  - Make pending prompt resolution chat-aware.
  - Broaden project-tag extraction to wrapped prompts.
- `tests/test_inbound.py`
  - Add chat-scoped context tests.
  - Add regression test where latest pending action is `sase` but persisted chat context is `zorg`; `/beads` must use
    the `zorg` cwd.
  - Add extraction tests for wrapped image prompts containing `#gh_sase` or `#gh:zorg`.
- `README.md` and `docs/inbound.md`
  - Update `/bead` context documentation to describe the chat-scoped remembered project before pending-action fallback.

No `sase_100` source changes are expected for this issue unless tests reveal a core bead regression. The `zorg` bead CLI
already returns the expected open beads from the `zorg` workspace.

## Verification

1. In `../sase-telegram`, run `just install` if needed, then targeted tests for inbound bead context and finally
   `just check`.
2. In this repo, run `just install` if needed and `just check` only if source files here are changed.
3. Manual smoke:
   - Launch or simulate a Telegram prompt with `#gh:zorg`.
   - Ensure a newer unrelated pending `#gh_sase` action exists.
   - Send `/beads`.
   - Expected: the command runs `sase bead list` in `/home/bryan/projects/github/zettel-org/zorg` and returns the open
     `zorg-*` picker instead of `No open beads.`

## Risks

- A global bot chat can interleave multiple projects. Chat-scoped “last project” matches the current UX and is better
  than unrelated global pending actions, but users may still need an explicit override for uncommon cross-project
  workflows. `SASE_TELEGRAM_BEAD_PROJECT` remains available for that.
- Persisted context can become stale if the workspace is deleted. The resolver should validate the workspace still
  exists and fall through when it does not.
