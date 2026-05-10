---
name: gchat_self_message_filter
description: Stop retired chat plugin from launching agents in response to its own outbound
  messages. The current ``sender.type == "BOT"`` filter never matches because the
  gchat CLI authenticates as the user, so sase's own posts appear as inbound user
  prompts and self-feed an infinite agent-launch loop. Replace the broken sender-based
  filter with a sent-message-id allowlist recorded centrally inside ``gchat_client``.
create_time: 2026-04-25 11:00:50
status: done
prompt: sdd/prompts/202604/gchat_self_message_filter.md
---

# retired chat plugin — Stop Self-Triggering Agent Launches

## Problem

retired chat plugin is launching agents in response to messages **sase itself just posted** to the chat space. The user's
`sase ace` snapshot showed multiple `home (RUNNING)` agents whose AGENT PROMPT was the verbatim text of an outbound
`_format_workflow_complete()` notification ("✅ _Agent Complete_ _@l_ … ▶️ _Resume — copy from below:_ `resume:l`").

The recently merged "🚀 Launched" confirmation (plan `gchat_agent_launch_message`, status: done) makes the bug
self-feeding: every successful launch posts a "🚀 Launched" message; that message becomes the prompt of a new agent on
the next inbound poll; that agent's launch posts another message; and so on.

## Root cause

The gchat CLI (`/google/bin/releases/gemini-agents-gchat/gchat`) authenticates via LOAS/Stubby on Cloudtop as the
**user's own Google identity** — there is no separate bot account. So when sase posts via `gchat_client.send_message()`,
the message comes back from `list_messages` with `sender.type == "HUMAN"` (the user themselves), indistinguishable from
a real reply.

The self-message filter `_is_self_message()` at `sase_gc_inbound.py:117-127` checks `sender.type == "BOT"` and never
matches. Self-posted messages flow through `_dispatch_message()` (no thread-reply, no dot-command, no attachment) and
fall through to the fallback at `sase_gc_inbound.py:619-620`:

```python
# 5. Plain text → launch a new agent with that prompt.
if text:
    _launch_agent(text)
```

There is no sender field that can distinguish "sent by sase as me" from "typed by me directly" — both are the same
Google identity. The only reliable signal is **the message ID returned by `send_message()` at the moment we sent it**.

## Background

- All sase → chat traffic flows through one of three message-creating wrappers in `retired_chat_plugin/gchat_client.py`:
  - `send_message()` — text posts (notifications, launch confirmations, dot-command replies, two-step prompts, response
    confirmations).
  - `upload_file()` — attachment uploads from outbound and `_handle_photo`.
  - `edit_message()` — edits in place; **does not create a new message**, so does not need recording.
  - `create_reaction()` — adds a reaction; verify whether the returned `name` corresponds to a chat message that
    re-appears in `list_messages` (likely no, but worth a one-line check).
- All three message-creators return the parsed message dict whose `name` field is the canonical message ID (same field
  used in `_msg_id` on the inbound side and in `_extract_message_ids` in outbound).
- The existing storage pattern lives in `retired_chat_plugin/pending_actions.py`: a single JSON file under `~/.sase/gchat/`,
  atomic-write via tempfile + `os.replace`, 24-hour staleness cleanup. Reuse that pattern for the new store.
- `_is_self_message()` is harmless when it never matches and remains correct in a hypothetical future where sase runs as
  a real bot account. Keep it as defense-in-depth.

## Goals

1. retired chat plugin must never treat a message it just sent as a fresh inbound user prompt — for any payload type
   (workflow-complete, launch confirmation, response confirmation, two-step prompt, dot-command reply, attachment
   upload).
2. Real user messages continue to be forwarded to `_launch_agent` as before.
3. The fix is centralized so future call sites cannot regress: every `gchat_client` message-creating call records the
   resulting ID automatically.
4. The persistent store self-prunes so the JSON file does not grow unbounded.

## Non-goals

- No changes to the main `sase_100` repo. All edits live in the sibling `retired chat plugin` plugin repo at
  `/home/bryan/projects/github/sase-org/retired chat plugin/`.
- No changes to telegram or any other plugin.
- No removal of `_is_self_message()` — it stays as a defense-in-depth check for a future bot-account deployment.
- No new gchat CLI features, no auth changes, no message-format changes.

## Design

### Approach: track sent message IDs, recorded centrally in `gchat_client`

Picked over the sentinel-marker alternative because (a) it does not depend on any rendering / normalization behavior of
the chat backend, (b) it cannot be tripped by user-typed text that happens to contain the marker, and (c) wrapping
inside `gchat_client` makes it impossible for a future call site to forget to record.

### New module: `retired_chat_plugin/self_messages.py`

A new file (rather than extending `inbound.py`) so the helpers can be imported by `gchat_client` without creating a
circular dependency (`inbound.py` would otherwise be importable from a module that `inbound.py` itself transitively
uses). Mirrors `pending_actions.py` style:

- `SELF_MESSAGE_IDS_PATH = Path.home() / ".sase" / "gchat" / "self_message_ids.json"` — JSON object mapping
  `message_id (str) -> sent_at (float, unix epoch)`.
- `STALE_THRESHOLD_SECONDS = 24 * 60 * 60`.
- `record(message_id: str) -> None` — no-op on empty/missing IDs; atomic write via tempfile + `os.replace`.
- `is_self(message_id: str) -> bool` — cheap lookup (load + membership test).
- `cleanup_stale() -> list[str]` — drop entries older than 24 h, returning removed IDs (mirrors
  `pending_actions.cleanup_stale`).

The 24-hour TTL comfortably exceeds the inbound poller's 24-hour `list_messages` window, so no self-message ever escapes
the filter while still in the poll horizon.

### Centralized recording inside `gchat_client.py`

Add a small helper, e.g. `_record_self_message(result: Any) -> None`, that extracts `result["name"]` if present and
calls `self_messages.record(...)`. Invoke it from inside the existing `send_message()`, `upload_file()` (covers
attachments), and — defensively — `create_reaction()` after the `_run(...)` call. Do NOT call from `edit_message()` (no
new message created); confirm by reading the function body.

Because every message we post goes through `gchat_client`, this single change captures all five inbound-side call sites
the bug spec lists (`_post_confirmation`, `_handle_dot_command`, `_handle_two_step` / `save_awaiting_feedback` companion
post, `_handle_photo`'s downstream send, and `_launch_single_agent`'s launch confirmation), plus
`sase_gc_outbound._run_outbound`'s notification + attachment loop, with no changes at the call sites.

### Inbound filter wiring

In `sase_gc_inbound.py`:

1. Import `self_messages`.
2. Add a top-level helper (e.g. `_is_recorded_self_message(message)`) that resolves the message's `name` via the
   existing `_msg_id` accessor and consults `self_messages.is_self`. Keep it cheap by loading the JSON once per
   `_filter_and_sort` call rather than per message — pass the loaded set in.
3. In `_filter_and_sort`, drop messages where either `_is_self_message(m)` (defense-in-depth) **or** the new ID-based
   check matches. Load the recorded-IDs set once at the top of `_filter_and_sort` and close over it.
4. In `main()`, call `self_messages.cleanup_stale()` alongside the existing `pending_actions.cleanup_stale()` near the
   top.

### Edge cases

- `send_message` returning a dict without a `name` (CLI rate-limited, partial failure): record helper no-ops; the
  message presumably wasn't posted, so the filter not knowing it is fine. If it WAS posted but we got no ID back, the
  filter will fail open and a stray agent could launch — log this case at INFO so it's diagnosable. This is the same
  failure mode the existing code already has for attachment ID extraction.
- Concurrent inbound + outbound runs: `_save` uses atomic `os.replace`, but a non-locking read-modify-write pattern can
  still drop concurrent updates. `pending_actions.py` accepts this same trade-off; mirror it. If we see issues in
  practice, add the same `try_acquire_outbound_lock` discipline; out of scope here.
- Bootstrap path (`last_seen is None`): the bootstrap branch returns 0 without dispatching, so self-messages already
  cannot trigger launches on the first run. The filter applies correctly on every subsequent run.
- Future call sites: any new send must go through `gchat_client`; if a contributor adds a _direct_ `subprocess`-based
  send bypassing `gchat_client`, the filter won't know about it. Add a one-line module-docstring comment in
  `gchat_client.py` calling out the recording contract so this is hard to miss.

## Tests

Add to `retired chat plugin/tests/test_inbound.py` and `retired chat plugin/tests/test_gchat_client.py` (and a new
`tests/test_self_messages.py` for the storage helpers):

1. `test_self_messages_record_and_lookup` — `record(id)` then `is_self(id)` returns `True`; unrecorded IDs return
   `False`; empty/missing IDs are no-ops on record.
2. `test_self_messages_cleanup_stale` — entries older than 24 h are dropped; recent entries are kept; the returned list
   matches the dropped IDs.
3. `test_send_message_records_self_id` — patch `_run` to return `{"name": "spaces/X/messages/abc", ...}`; call
   `gchat_client.send_message(...)`; assert `self_messages.is_self("spaces/X/messages/abc")` is `True`.
4. `test_upload_file_records_self_id` — same shape for `upload_file`.
5. `test_edit_message_does_not_record` — `edit_message` does not call `self_messages.record` (paranoia regression test).
6. `test_filter_and_sort_drops_recorded_self_message` — record an ID, then pass a `list_messages`-shaped dict containing
   that message; assert it is filtered out even when `sender.type == "HUMAN"`.
7. `test_filter_and_sort_keeps_user_message` — a normal `HUMAN` sender with an ID NOT in the store passes through.
8. `test_dispatch_message_does_not_launch_for_self_message` (integration-flavored) — feed `_dispatch_message` a message
   whose ID was just recorded; assert `_launch_agent` is NOT called. (May be subsumed by #6 + the existing dispatch
   tests, but worth a direct assertion since the bug surface is launch.)

## Validation

Per `AGENTS.md`:

1. Edits made in the sibling `retired chat plugin` repo workspace; run `just install && just check` in that workspace before
   declaring done.
2. Smoke check: bind to the live Google Chat space and (a) trigger any sase notification (e.g. complete a workflow), (b)
   confirm the next inbound poll does NOT spawn an agent for that text. Then send a real free-text user message and
   confirm the agent IS launched normally.
3. Inspect `~/.sase/gchat/self_message_ids.json` to confirm IDs are appearing and stale entries are pruned after 24 h.

## Out of scope

- Removing or replacing `_is_self_message()`.
- Migrating `pending_actions` to share storage with the new self-messages store.
- Cross-process locking around the JSON file.
- Any change to the main sase_100 repo or to other plugin repos.
- Changing the inbound polling cadence or message window.
