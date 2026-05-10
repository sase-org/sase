---
name: gchat_agent_launch_message
description: Send a "🚀 Launched" message to Google Chat when retired chat plugin's inbound
  chop spawns a new agent, mirroring sase-telegram's behavior. The message is posted
  directly via gchat_client.send_message — it is NOT a sase notification.
create_time: 2026-04-25 10:50:54
status: done
prompt: sdd/prompts/202604/gchat_agent_launch_message.md
---

# Google Chat — Agent Launch Message

## Problem

When the user prompts a new agent via Google Chat, nothing visible happens in the chat. They have to wait for the
eventual workflow-complete notification to confirm the launch worked. Telegram already sends a "🚀 _{label} Launched_"
confirmation the moment `launch_agent_from_cwd()` returns; gchat does not. Users want parity.

## Background

- Telegram's launch confirmation is sent at `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py:489-494`, inside
  `_launch_single_agent()`. It is sent **directly** via `telegram_client.send_message()` — it does **not** go through
  the sase notification framework (`sase.notifications.senders` has no `notify_agent_launch()` and we will not add one).
- The gchat counterpart `_launch_single_agent()` lives at
  `retired chat plugin/src/retired_chat_plugin/scripts/sase_gc_inbound.py:302-326`. It calls `launch_agent_from_cwd(prompt)` and only logs
  on exception — no message is sent to chat.
- The `gchat` CLI exposes `send_message(space, text, *, thread=None, markdown=True)` (see
  `retired chat plugin/src/retired_chat_plugin/gchat_client.py:137`). It supports CommonMark markdown and threading but **no inline
  buttons** — the module header in `formatting.py` makes this explicit. Telegram's interactive Resume / Wait / Kill /
  Retry buttons therefore have no equivalent here.
- `_format_workflow_complete()` in `retired chat plugin/src/retired_chat_plugin/formatting.py:228-283` already shows the established gchat
  pattern for rendering an agent: model label via `format_provider_model_label`, agent name as `_@name_`, and
  copy-pasteable follow-up commands inside fenced code blocks (since there are no buttons).
- `launch_agent_from_cwd()` returns an `AgentLaunchResult` with `workspace_num` (and `pid`) — same fields Telegram
  already uses.
- `get_space_id()` (already imported on line 25 of `sase_gc_inbound.py`) yields the destination space.

### Cross-repo note

The change lives in the **sibling `retired chat plugin` plugin repo** (`/home/bryan/projects/github/sase-org/retired chat plugin/`), not
the sase_100 main repo this workspace points at. No edits to the main repo are required.

## Goals

1. Post a "🚀 _{label} Launched_" confirmation to Google Chat each time `_launch_single_agent()` successfully launches
   an agent.
2. On launch failure, post a "Failed to launch agent: {error}" message to Google Chat instead of silently logging.
3. Behavior parity with Telegram for the visible content: model label, agent name (or repeat marker), workspace number,
   and a truncated prompt excerpt.
4. Stay strictly outside the sase notification framework — direct send only.

## Non-goals

- No interactive buttons. The gchat CLI does not support them; we will instead surface a copy-pasteable `.kill <name>`
  hint inside a fenced code block, matching the `_format_workflow_complete()` precedent.
- No new `notify_*` function in `sase.notifications.senders`.
- No changes to the outbound chop, no changes to the formatting module, no changes to the main sase_100 repo.
- Multi-model fan-out already loops through `_launch_single_agent()` per model; we get one message per agent for free,
  no special-casing needed.

## Design

### Single edit: `sase_gc_inbound.py:_launch_single_agent()`

Restructure the function to mirror Telegram's `_launch_single_agent()`:

1. After `expanded` / directive extraction and the auto-name prepend (existing logic), resolve the launch label using
   `sase.llm_provider.registry.{format_provider_model_label, get_default_provider_name, get_provider, resolve_model_provider}`
   — same imports Telegram uses.
2. Compute `is_repeat` from `extract_repeat_and_name(expanded)` (already done).
3. Wrap the `launch_agent_from_cwd(prompt)` call in a `try/except` that:
   - On success: builds the message text and calls `gchat_client.send_message(space, text, markdown=True)` (no `thread=`
     — launch messages are top-level, matching how Telegram's launch confirmation is sent to the chat root).
   - On failure: calls `gchat_client.send_message(space, f"Failed to launch agent: {e}", markdown=True)` and logs.
4. Use `get_space_id()` (already imported) to obtain `space`.

### Message format (CommonMark)

```
🚀 *{label} Launched*  _@{agent_name}_
workspace #{workspace_num}

{prompt_excerpt}

```

.kill {agent_name}

```

```

Variants:

- If `agent_name` is `None` and `is_repeat`: replace `_@{agent_name}_` with `_repeat×{N}_` and omit the `.kill` block.
- If neither name nor repeat: omit both the `_@..._` segment and the `.kill` block.
- `prompt_excerpt`: first 200 chars of `prompt`, with `"..."` appended when truncated — same threshold Telegram uses
  (`display = prompt[:200] + ...`).

CommonMark — no MarkdownV2 escaping. Single asterisks are bold under the gchat CLI's `--markdown` mode (consistent with
existing `formatting.py` strings).

### Why include `.kill <name>` and not `#resume:<name>`

- `.kill <name>` is a real gchat dot-command (already implemented in `_kill_agents` at `sase_gc_inbound.py:384`) and is
  the immediate-action analogue of Telegram's "🗡️ Kill" button.
- `#resume:<name>` is more useful **after** the agent finishes; it's already surfaced in the workflow-complete message
  (`formatting.py:_format_workflow_complete`). Duplicating it on launch adds noise. Skip on launch.

### Error path

Mirror Telegram's nested try: outer try wraps `launch_agent_from_cwd` and the launch-confirmation send; on exception,
post a failure message via `gchat_client.send_message`, swallowing any secondary error from the failure post (just log
it) so we never crash the inbound poller.

## Tests

In `retired chat plugin/tests/test_inbound.py`, add cases mirroring the sase-telegram parity tests in
`sase-telegram/tests/test_inbound.py:346+`:

1. `test_launch_single_agent_posts_launched_message`: patches `sase.agent.launcher.launch_agent_from_cwd` to return a
   stub `AgentLaunchResult(workspace_num=7, pid=123)` and patches `retired_chat_plugin.gchat_client.send_message`; calls
   `_launch_single_agent("hello")`; asserts the captured text contains `"🚀"`, `"Launched"`, `"workspace #7"`, the
   auto-assigned `_@<name>_` line, and the `.kill <name>` block; asserts `markdown=True` and no `thread=` argument.
2. `test_launch_single_agent_posts_failure_message`: patches `launch_agent_from_cwd` to raise `RuntimeError("boom")`;
   asserts `send_message` is called with text containing `"Failed to launch agent"` and `"boom"`.
3. `test_launch_single_agent_repeat_marker`: invokes with a `%r:3 ...` prompt; asserts the rendered text contains
   `"repeat×3"` and does **not** contain a `.kill` line (no agent name to address).
4. (Optional) `test_launch_single_agent_no_send_when_send_raises`: patches `send_message` to raise; asserts the inbound
   function does not propagate the exception (matches Telegram's swallow-and-log behavior).

## Validation

Per `AGENTS.md`, run `just check` in the retired chat plugin workspace before declaring done. Smoke check by sending a free-text
prompt to the bound Google Chat space and confirming the launch message appears.

## Out of scope

- Adding inline buttons to gchat (CLI does not support).
- Adding a `notify_agent_launch()` notification.
- Editing the main sase_100 repo.
- Changing the workflow-complete or HITL message rendering.
