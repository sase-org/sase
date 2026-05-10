---
create_time: 2026-04-24 22:41:34
status: done
bead_id: sase-p
prompt: sdd/prompts/202604/retired_chat_plugin.md
---
# Plan: `retired chat plugin` — Google Chat integration plugin

## Goal

Build a new `../retired chat plugin` plugin repository that mirrors the functionality of `../sase-telegram` but speaks Google
Chat instead of Telegram. The plugin ships two `sase` chops:

- `sase_chop_gc_outbound` — turns unread sase notifications into Google Chat messages.
- `sase_chop_gc_inbound` — polls Google Chat for replies (button presses, feedback, agent launches, slash/dot commands,
  photo/document uploads) and writes responses back into the sase notification store and/or launches agents.

## Background & key design decisions

### What sase-telegram does

`sase-telegram` is a pair of CLI scripts registered in `pyproject.toml` as `sase_chop_tg_outbound` /
`sase_chop_tg_inbound`. They are invoked by the sase Lumberjack scheduler with a `--context <json>` arg, and participate
in the chop contract defined in `src/sase/axe/chop_script_context.py`. The outbound script reads
`~/.sase/notifications/notifications.jsonl`, formats unread/non-stale notifications into MarkdownV2 messages with inline
keyboards, and pushes them to Telegram. The inbound script long-polls Telegram for updates, decodes button presses +
text replies, drives a two-step "feedback" flow, downloads photos/documents, launches agents (with xprompt expansion +
multi-model directives), and writes JSON response files that sase action handlers pick up.

The architecture splits cleanly:

- **Platform-agnostic** modules (high-water-mark + lock for outbound, pending-actions store, rate limiter, callback-data
  encoder, two-step feedback state machine, code-marker reconstruction, attachment dispatch, PDF conversion,
  integration-test scaffolding).
- **Telegram-specific** modules (`telegram_client.py`, MarkdownV2 escaping in `formatting.py`, callback-data packing
  into 64-byte strings, `InlineKeyboardButton` / `CopyTextButton` construction, photo/document file download via the
  python-telegram-bot SDK).

### What Google Chat changes

The reference CLI is `gchat` (binary at `/google/bin/releases/gemini-agents-gchat/gchat`, also installable via apt;
configurable in our plugin as `$SASE_GCHAT_BIN`, defaulting to `gchat` on `$PATH`). Key differences from Telegram that
drive design decisions:

| Concern                    | Telegram                                   | Google Chat (via `gchat` CLI)                                                                                                              |
| -------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Message format             | MarkdownV2 (heavy escaping)                | CommonMark via `--markdown` flag (or native gchat formatting `*bold*`/`_italic_`)                                                          |
| Inline buttons             | `InlineKeyboardButton` w/ callback_data    | **Not exposed by the CLI.** Use **numbered text options** the user replies to.                                                             |
| Copy-text buttons          | `CopyTextButton` (256-char native)         | Not available — print the text in a fenced code block that the user copies manually.                                                       |
| Threads                    | Optional, addressed by `thread_id`         | First-class. Each notification becomes its own thread; replies stay scoped to that thread.                                                 |
| Editing/removing keyboards | `edit_message_reply_markup()`              | `edit-message --space --message --text "..."` (replace text); we'll edit out the prompt block once a response is recorded.                 |
| Long messages              | Hard 4096-char limit                       | No comparable hard limit, but readability + Chat preview rendering still benefit from PDF attachments. Keep our existing PDF flow.         |
| Attachments / photos       | Native send_photo / send_document          | `gchat upload-file --space --file ... [--text ...] [--thread ...]` (REST upload, ≤200 MB). Inbound photos via `gchat download-attachment`. |
| Slash commands             | `set_my_commands()` populates the bot menu | No equivalent. Keep `.list`, `.kill`, `.listx`, `.resume`, `.xprompts` as **dot-commands** parsed in inbound.                              |
| Update polling             | `getUpdates(offset)` long-poll             | `gchat list-messages --space SPACE_ID --order DESC --max N` filtered by a stored last-seen `create_time`.                                  |
| Auth                       | Bot token in `pass` + chat-id env var      | LOAS/Stubby on Cloudtop (no creds needed at our layer); we just need the **target space ID** in env.                                       |

### Buttons → numbered options

Because the gchat CLI cannot render interactive buttons, every place sase-telegram uses an inline keyboard, retired chat plugin
will append a `*Reply with a number:*` block:

```
*Reply with a number (in this thread):*
1. ✅ Approve
2. ▶️ Run
3. 📚 Epic
4. ❌ Reject
5. ✏️ Feedback (then send your reason in this thread)
```

When the inbound chop sees a numeric reply scoped to a notification's thread, it maps the number to the recorded option
list (persisted in `pending_actions.json`) and writes the same response file sase-telegram would have written. For the
two-step "Feedback / Custom" path, the inbound script flips the pending action into an `awaiting_feedback` state keyed
by `(space_id, thread_id)` and waits for the next non-numeric message in that thread.

Threading is the key simplification over Telegram: callback_data encoding is no longer needed because the
`(space_id, thread_id)` pair plus the user's message uniquely identifies "which notification is being answered." We keep
a thin `callback_data.py`-equivalent for `kill`/`retry`/dot-commands that operate outside a notification thread.

### Plugin contract reminder

Per `docs/axe.md`, chops are **not pluggy plugins**. They are stand-alone executables on `$PATH` named
`sase_chop_<chop_name>`, invoked as `sase_chop_<name> --context <json>`, returning exit code 0 on success. The
`ChopScriptContext` JSON gives `state_dir`, `query`, `lumberjack_name`, etc. We mirror sase-telegram's contract
verbatim.

## Repo layout (target)

```
retired chat plugin/
├── AGENTS.md                  # short — link to architecture.md and naming conventions
├── CLAUDE.md                  # one-liner: @AGENTS.md
├── Justfile                   # install / lint / fmt / test / check / build / clean
├── pyproject.toml             # name=retired chat plugin, hatchling, scripts = sase_chop_gc_{outbound,inbound}
├── README.md                  # written in the FINAL phase, after impl is settled
├── sase.yml                   # precommit_command: "just fmt"
├── docs/
│   ├── architecture.md        # module dep graph, data flow
│   ├── outbound.md            # outbound pipeline + numbered-options spec
│   └── inbound.md             # inbound pipeline + dot-commands + threading model
├── plans/                     # placeholder dir for follow-up work
├── src/retired_chat_plugin/
│   ├── __init__.py
│   ├── credentials.py         # SASE_GCHAT_SPACE_ID, SASE_GCHAT_BIN, optional SASE_GCHAT_RATE_LIMIT
│   ├── gchat_client.py        # subprocess wrapper around the gchat CLI (send/edit/upload/download/list/react)
│   ├── option_codes.py        # encode/decode option lists per notification (replaces callback_data.py)
│   ├── pending_actions.py     # ported from sase-telegram, paths under ~/.sase/gchat/
│   ├── rate_limit.py          # ported, paths under ~/.sase/gchat/
│   ├── outbound.py            # high-water mark + exclusive lock, paths under ~/.sase/gchat/
│   ├── inbound.py             # pure logic: numbered-reply parsing, two-step feedback, thread routing
│   ├── formatting.py          # notification → gchat-flavored markdown + numbered options block
│   ├── pdf_convert.py         # ported verbatim
│   ├── pdf_style.css          # ported verbatim
│   └── scripts/
│       ├── __init__.py        # outbound_main / inbound_main re-exports
│       ├── sase_gc_outbound.py
│       └── sase_gc_inbound.py
└── tests/
    ├── test_credentials.py
    ├── test_option_codes.py
    ├── test_gchat_client.py    # subprocess invocations w/ patched runner
    ├── test_pending_actions.py
    ├── test_rate_limit.py
    ├── test_formatting.py
    ├── test_inbound.py
    ├── test_outbound.py
    └── test_integration.py
```

State directory: `~/.sase/gchat/` containing the same files as `~/.sase/telegram/` (rate_limit.json,
pending_actions.json, awaiting_feedback.json, last_seen_create_time, outbound.lock, outbound_debug.log, images/).

## Phase plan

Each phase is a self-contained agent run. Phases are ordered so a phase only depends on artifacts produced by prior
phases. Each phase ends with `just check` passing in the `retired chat plugin` repo.

### Phase 1 — Repo scaffolding + gchat CLI client + reusable infrastructure

**Deliverables**

- `pyproject.toml`, `Justfile`, `CLAUDE.md`, `AGENTS.md` (short stub), `sase.yml`, `.gitignore` modeled on sase-telegram
  (deps: `sase>=0.1.0` only — no SDK; the gchat CLI is the SDK).
- `src/retired_chat_plugin/credentials.py` — env-var helpers (`get_space_id()`, `get_gchat_bin()`, `get_rate_limit()`); no `pass`
  integration needed because the CLI handles auth.
- `src/retired_chat_plugin/gchat_client.py` — sync subprocess wrapper exposing the verbs we need:
  `send_message(space, text, *, thread=None, markdown=True) -> Message`, `edit_message(space, message_id, text)`,
  `upload_file(space, file_path, *, text=None, thread=None) -> Message`,
  `download_attachment(space, message_id, output_path, *, index=0)`,
  `list_messages(space, *, max=N, hours=N, order="DESC") -> list[Message]` returning structured dicts (parsed from the
  CLI's `--json` output), `create_reaction(space, message_id, emoji)`,
  `get_message(space, thread, message_id) -> Message`. Uniform retry with exponential backoff on transient CLI failures
  (non-zero exit + stderr keywords). Capture stderr into a debug log.
- `src/retired_chat_plugin/option_codes.py` — encode/decode for "out-of-band" actions that don't live in a notification thread
  (kill, retry, dot-command callbacks if we ever need them). Mostly a much smaller reimplementation of
  `callback_data.py`.
- `src/retired_chat_plugin/pending_actions.py`, `src/retired_chat_plugin/rate_limit.py`, `src/retired_chat_plugin/pdf_convert.py`,
  `src/retired_chat_plugin/pdf_style.css` — ported from sase-telegram with paths rewritten to `~/.sase/gchat/`.
- `tests/test_credentials.py`, `tests/test_gchat_client.py` (subprocess mocked via `pytest-mock`),
  `tests/test_option_codes.py`, `tests/test_pending_actions.py`, `tests/test_rate_limit.py`.

**Exit criteria**: `just install && just check` passes.

### Phase 2 — Outbound formatting (notification → Google Chat markdown + numbered options)

**Deliverables**

- `src/retired_chat_plugin/formatting.py` containing:
  - `format_notification(n) -> FormattedMessage` returning `(text, options, attachments)` where `options` is the ordered
    list of (label, response_payload) used by inbound to map numeric replies, and `attachments` is the list of files to
    upload after the main message.
  - Per-notification-type formatters mirroring sase-telegram: PlanApproval, HITL, UserQuestion, WorkflowComplete,
    AgentLaunched, AgentKilled, ErrorDigest, ImageGenerated, generic fallback.
  - Markdown rendering helpers: minimal escaping (gchat's native syntax tolerates most CommonMark when `--markdown` is
    used), `_render_options_block(options)` to produce the numbered list, and a `_truncate_to_pdf(text, threshold)`
    helper that replicates the 500/3500-char inline → blockquote → PDF cascade adapted for Chat preview behavior.
- `tests/test_formatting.py` — covers each notification type, the numbered-options block, the long-content fallbacks,
  and round-trips a sample plan/HITL through to a parsed `Message`-shape struct.

**Exit criteria**: `just check` passes; tests pin every formatter's option-list output (so inbound can rely on
ordering).

### Phase 3 — Inbound logic (pure functions over `gchat list-messages` output)

**Deliverables**

- `src/retired_chat_plugin/outbound.py` — port of high-water-mark + lock from sase-telegram, paths rewritten.
- `src/retired_chat_plugin/inbound.py` (pure logic, no CLI calls):
  - `process_thread_reply(message, pending) -> ResponseAction | TwoStepStart | None` — given a Chat message dict and the
    pending-actions store, identify which pending notification owns this thread and map a numeric reply to a
    `ResponseAction`, or detect "feedback / custom" entries and return `TwoStepStart`.
  - `process_text_completion(message, awaiting) -> ResponseAction | None` — completes a two-step feedback flow when a
    non-numeric message arrives in an `awaiting_feedback` thread.
  - `process_dot_command(text) -> DotCommand | None` — parses `.list`, `.listx`, `.kill <name>`, `.resume`, `.xprompts`.
  - `process_attachment(message) -> PhotoIntent | None` — for messages with `attachments[].content_type` starting with
    `image/`, returns the metadata needed for the entry-point script to call `gchat download-attachment` and launch an
    agent.
  - `find_externally_handled(pending)` — same semantics as Telegram (TUI dismissal short-circuits).
  - `confirmation_text(response)` — human-readable confirmation string for the inbound script to send back.
- State paths: `~/.sase/gchat/awaiting_feedback.json`, `~/.sase/gchat/last_seen_create_time`, `~/.sase/gchat/images/`.
- `tests/test_inbound.py` and `tests/test_outbound.py` — fixture-driven tests covering numeric replies, two-step flows,
  dot-commands, attachments, externally-handled cleanup, lock acquisition, high-water-mark advancement.

**Exit criteria**: `just check` passes; pure-logic functions are fully unit-tested without invoking subprocess.

### Phase 4 — Entry-point scripts + integration tests + docs + final README

**Deliverables**

- `src/retired_chat_plugin/scripts/sase_gc_outbound.py`:
  - Acquires lock; `is_idle()` gate; loads unsent notifications; for each, formats via Phase 2, sends with
    `gchat_client.send_message(..., markdown=True)`, captures the resulting message+thread IDs, persists a pending
    action immediately (race-window protection), uploads each attachment in the same thread, advances the high-water
    mark on success, sleeps to satisfy the rate limit between notifications.
  - `--dry-run` flag prints intended sends; `--context` accepts the chop context JSON.
- `src/retired_chat_plugin/scripts/sase_gc_inbound.py`:
  - Acquires offset (`last_seen_create_time`); calls
    `gchat_client.list_messages(space, --hours 24, --order DESC, --json)` filtered by stored offset (advance offset
    _before_ processing for at-most-once on overlap).
  - Dispatches each message: thread reply → `process_thread_reply`; awaiting completion → `process_text_completion`;
    dot-command → handler; attachment → download + launch agent; otherwise → "launch agent from text" with xprompt
    expansion + multi-model directive support (port from sase-telegram).
  - On dispatch, edits the original notification message (via `gchat_client.edit_message`) to strike-through the options
    block once consumed, and posts a confirmation reply in the thread.
  - `--once` flag for one-shot polling; `--context` accepts the chop context JSON.
- `src/retired_chat_plugin/scripts/__init__.py` re-exports `outbound_main`, `inbound_main`.
- `tests/test_integration.py` — end-to-end-style scenarios with the gchat CLI patched to deterministic responses:
  plan-approval round trip, HITL feedback two-step, agent-launch from text, photo upload → agent prompt, dot-command
  `.list`.
- `docs/architecture.md`, `docs/outbound.md`, `docs/inbound.md` — written from the implemented behavior.
- **Final README.md** at repo root — overview, install instructions (`uv pip install -e .[dev]`), required env vars
  (`SASE_GCHAT_SPACE_ID`, optional `SASE_GCHAT_BIN`, optional `SASE_GCHAT_RATE_LIMIT`), example `axe.lumberjacks`
  snippet, list of supported notification types, numbered-options conventions, dot-commands, troubleshooting (CLI not on
  PATH / authentication), reference link to the gchat CLI binary source.

**Exit criteria**: `just check` passes; integration tests green; README documents the actual implemented surface (no
aspirational features).

## Cross-cutting conventions

- **Python 3.12+, hatchling build, ruff + mypy strict** — match sase-telegram tooling exactly so future refactors that
  touch both repos use the same conventions.
- **Short CLI options on every flag** — per project gotcha, every entry-point flag must have a short option.
- **Treat all sase agent runtimes uniformly** — no Claude/Gemini/Codex special-casing in agent-launch code ported from
  sase-telegram.
- **`just check` before reply** — every phase's agent must run `just check` in `../retired chat plugin` and (because this repo is
  itself a workspace clone) NOT need to touch the `sase` repo at all unless adding/modifying a glossary entry.
- **No new sase core changes** — the chop interface is stable; this plugin only consumes existing sase APIs.

## Out of scope (explicitly)

- Interactive Card v2 / `cards_v2` support — would require a Chat App registration and webhook plumbing that the gchat
  CLI doesn't expose. Numbered-options is the chosen substitute.
- `pass`-based credential lookup — auth is delegated to the gchat CLI's LOAS/Stubby flow.
- Slash-command registration with the Chat platform — handled as inbound dot-commands instead.
- Migration tooling from existing sase-telegram state — both plugins can run in parallel; no shared state.
