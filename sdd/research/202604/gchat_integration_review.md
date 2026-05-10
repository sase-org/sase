# retired chat plugin Integration Review

**Date:** 2026-04-25
**Repos compared:**
- `~/projects/github/sase-org/retired chat plugin` (HEAD: `cc0eba3` — Phase 4 entry-point scripts + integration tests + docs)
- `~/projects/github/sase-org/sase-telegram` (HEAD: `927a16f` — Retry button on agent launch keyboard)

**Prior research:** `sdd/research/202602/telegram_integration.md`, `sdd/research/202603/telegram_improvements.md`, `sdd/research/202603/slash_command_migration.md`. None for gchat yet.

## 1. Architecture Overview

The two integrations are deliberately structured as siblings: same module names, same lumberjack-driven outbound/inbound chops, identical `~/.sase/<channel>/` state layout (`last_sent_ts`, `outbound.lock`, `pending_actions.json`, `rate_limit.json`, `awaiting_feedback.json`). Where they diverge is the transport and the callback model.

| Aspect | Telegram | Google Chat |
|---|---|---|
| Transport | `python-telegram-bot>=21.0` (async, wrapped sync) | `gchat` CLI subprocess + `--json` |
| Inbound | Long-polling `getUpdates(offset)` | One-shot `gchat list-messages --hours 24`, filter by `createTime > last_seen` |
| Auth | `pass show telegram_sase_bot_token` + chat-id env vars | Delegated to `gchat` binary (LOAS/Stubby on Cloudtop); only `SASE_GCHAT_SPACE_ID` needed |
| Markdown | MarkdownV2 with strict escaping + plain-text fallback | CommonMark via `gchat send-message --markdown` (no escaping) |
| Callback model | Inline keyboard buttons; 64-byte `action:prefix:choice` payload (`callback_data.py`) | Per-notification thread; user replies with a number 1–N; thread_id is the routing key (`option_codes.py` exists but is unused for the in-thread path) |
| Threading | One chat | Each notification gets its own thread |
| Slash commands | `/kill`, `/list`, `/listx`, `/resume`, `/xprompts` registered via `set_my_commands` (cached hourly) | Dot commands only: `.kill`, `.list`, `.listx`, `.resume`, `.xprompts` |
| LOC (src) | ~2.6k | 2421 |

**Key insight.** Telegram has to pack everything into a 64-byte callback string because a button click carries no other context. Google Chat's threading model gives free routing — the thread_id alone identifies the pending action — at the cost of losing inline buttons. That is a fundamental UX difference, not just a missing feature, and shapes most of the recommendations below.

## 2. Module-by-module Findings

### credentials.py
- `sase-telegram/src/sase_telegram/credentials.py:1-34` — `get_bot_token()` (LRU-cached `pass show`), `get_chat_id()`, `get_bot_username()`.
- `retired chat plugin/src/retired_chat_plugin/credentials.py:1-44` — `get_space_id()`, `get_gchat_bin()` (default `"gchat"`), `get_rate_limit()`.
- gchat is simpler because the CLI handles auth. Reasonable as-is.

### outbound.py + scripts
- Core logic (`get_unsent_notifications`, `mark_sent`, `try_acquire_outbound_lock`) is near-identical and reads `~/.sase/notifications/notifications.jsonl`, filters `read==False and silent==False`, and gates on `is_idle()`.
- gchat advances the high-water mark **per notification** (`sase_gc_outbound.py`), telegram batches it. The per-notification advance is safer against mid-batch failure — telegram should adopt the same pattern.
- Both honor the `silent` flag identically (`retired chat plugin/src/retired_chat_plugin/outbound.py:43`, `sase-telegram/.../outbound.py:44`).

### inbound.py + scripts
- Telegram entry point: `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py` (~1150 LOC). Includes slash-command registration, retry-button handling, rich `_format_agent_description` blocks for `/kill` and `/resume` keyboards.
- Google Chat entry point: `retired chat plugin/src/retired_chat_plugin/scripts/sase_gc_inbound.py` (582 LOC). Dot-command parsing, message-strike on TUI dismissal via `find_externally_handled` → `_strike_message`, per-thread `awaiting_feedback` state.
- gchat's per-thread awaiting-feedback (keyed by `thread_id`) is **better** than telegram's single-entry awaiting state — multiple two-step feedback flows can run concurrently. Telegram should consider adopting the per-key model.

### formatting.py
- Telegram (`formatting.py:280–700+`): MarkdownV2 escaping, expandable blockquotes (Bot API 7.4+), `CopyTextButton` for resume, code-block-to-inline conversion for blockquote compatibility, parse-mode fallback.
- gchat (`formatting.py:103–304`): CommonMark, blockquote wrapping (line 175–176), numbered-options block at message tail (line 189), simpler. Both call `format_provider_model_label()` for the LLM provider/model header. Both italicize the agent name.
- Notification types covered: identical (`PlanApproval`, `HITL`, `UserQuestion`, `ImageGenerated`, `ErrorDigest`, `WorkflowComplete`, generic).

### Callback encoding: `callback_data.py` vs `option_codes.py`
- `callback_data.py` (telegram): colon-separated, hard 64-byte cap (Telegram constraint), used for **every** button.
- `option_codes.py` (gchat): pipe-separated, no cap, **intentionally narrower** (per docstring it's reserved for out-of-band actions like `.kill <name>` / `.retry`). In the current code it appears unused — a grep across `src/` only finds the file itself. This is the natural hook point for future non-thread callbacks (see recommendation R2).

### Client wrappers
- `telegram_client.py`: `_with_retry` decorator (RetryAfter / TimedOut / NetworkError), automatic 4096-char message splitting, `set_my_commands`, `answer_callback_query`, edit/photo/document/get-updates.
- `gchat_client.py:1-278`: `_with_retry` matching transient stderr markers ("timeout", "503", etc.), `_append_debug_log()` to `~/.sase/gchat/gchat_debug.log`, methods for send/edit/upload/download/list/get/react. No message-splitting (gchat handles it). Has `create_reaction` — a feature telegram doesn't surface.

### rate_limit.py / pending_actions.py
- Both pairs are essentially identical (sliding window default `8/15`, JSON-persisted; `pending_actions` with 24h cleanup).

## 3. Test Coverage

| Module | Telegram tests | gchat tests |
|---|---|---|
| credentials | 6 | 8 |
| formatting | **65** | **40** |
| inbound | 67 | 66 |
| integration | 12 | 12 |
| outbound | 13 | 9 |
| pending_actions | 6 | 6 |
| rate_limit | 6 | 6 |
| callback/option encoding | 7 (callback_data) | 9 (option_codes) |
| client wrapper | 0 | **17** (test_gchat_client.py) |
| **Total** | **~182** | **~173** |

The two notable gaps:
1. **gchat formatting tests trail by 25** — likely missing coverage for blockquote wrapping, options-block rendering, attachment list construction, and frontmatter stripping.
2. **No test for the inbound script's "strike message on TUI dismissal" path** (`_cleanup_externally_handled` → `_strike_message` in `sase_gc_inbound.py:458`). It is a non-trivial interaction worth pinning.

Conversely, gchat's `test_gchat_client.py` (17 tests) is something telegram lacks — the `python-telegram-bot` wrapper has no direct unit coverage, only integration tests.

## 4. Recent Telegram Features — Parity Audit

| Feature | Telegram impl | gchat status |
|---|---|---|
| 🔄 Retry button on agent launch (`927a16f`) | `sase_tg_inbound.py:455-486` (CopyTextButton ≤256 chars; falls back to callback for longer prompts via `pending_actions["retry-<name>"]`) | **Missing.** `option_codes.py` docstring already mentions `.retry` as the intended hook — no implementation exists. |
| `/xprompts` (`2654ef3`) | Slash command registered | `.xprompts` dot command at `inbound.py:460`, handler `_format_xprompts_summary` at `sase_gc_inbound.py:435`. ✅ |
| `%r:N` auto-name skip (`3103bb0`) | `sase_tg_inbound.py:397` strips `%n:<name>` only when no `%r:N` | **Not present.** gchat doesn't show evidence of `%r:N`-aware name handling in the launch path. Worth a deliberate check before recommending. |
| 🚀 Run button (`5639ff1`) | `formatting.py:406` | `formatting.py:184` (option label). ✅ |
| Silent notification filter (`2a19416`) | `outbound.py:44` | `outbound.py:43`. ✅ |
| LLM provider/model label (`527716d`) | `formatting.py:345-350` | `formatting.py:157-160`. ✅ |
| Agent descriptions in `/kill` & `/resume` (`e15eb5a`) | `_format_agent_description(name, model, duration, prompt)` at `sase_tg_inbound.py:603-643` | **Missing.** `_format_resume_targets` (`sase_gc_inbound.py:400-432`) and `_kill_agents` (`384-397`) only emit the agent name. No model/duration/prompt blocks. |
| Plan-button dismissal when approved in TUI (`f50e079`) | Edits inline keyboard | `find_externally_handled` + `_strike_message` (`sase_gc_inbound.py:458-478`) — **a different mechanism, but functionally equivalent.** ✅ |
| `#resume:@<name>` when prompt has `#pr` (`f961d4b`) | `sase_tg_inbound.py:366` `_has_pr_xprompt` + use in resume button | gchat formatting builds resume text at `formatting.py:270-282` using `extract_vcs_workflow_tag`/`replace_ref_in_vcs_tag`, but no `#pr`-conditional `@<name>` injection found. **Likely missing.** |
| Branch name in resume button (`43b6d08`) | `_get_agent_retry_prompt` and helpers in `sase_tg_inbound.py` | gchat does call `extract_vcs_workflow_tag` at `formatting.py:275`, so likely picks up branch from the same path. Worth confirming. |

Net: gchat is missing **retry**, **rich agent descriptions in `.kill`/`.resume`**, and **`#pr`-aware resume targeting**. Everything else is either present or intentionally adapted to gchat's threading model.

## 5. Slash / Bot Commands

Telegram registers (`sase_tg_inbound.py:1019-1025`):
```
kill, list, listx, resume, xprompts
```
plus dot-command equivalents accepted in plain text.

gchat accepts the same set as dot commands only (`inbound.py:460`):
```
{"list", "listx", "kill", "resume", "xprompts"}
```

There is no Google-Chat equivalent of `set_my_commands` — the gchat CLI doesn't surface bot commands. The closest UX win would be a `.help` command (see R5).

## 6. Plans / Roadmap

- `sase-telegram/plans/artifact_passing.md` exists but is essentially empty.
- `retired chat plugin/plans/` is empty.
- No documented roadmap in either repo. All future work is implicit in commits.

## 7. Config

- `sase.yml` is identical (`precommit_command: "just fmt"`).
- `pyproject.toml`:
  - telegram depends on `python-telegram-bot>=21.0`; gchat has no extra runtime dep.
  - telegram has `[[tool.mypy.overrides]] module = "telegram.*"`; gchat has none.
  - Entry-point names are parallel: `sase_chop_{tg,gc}_{outbound,inbound}`.

## 8. Recommendations

In priority order. Each item is scoped to keep PRs small.

### R1 — Add rich agent descriptions to `.kill` and `.resume`
**Why:** Single highest-value parity gap. Telegram's `_format_agent_description(name, model, duration, prompt)` (`sase_tg_inbound.py:603-643`) is the difference between "I see five agents named foo, bar, …" and "I can tell which one to kill at a glance."
**How:** Port the helper to `sase_gc_inbound.py`, used by both `_kill_agents` (line 384) and `_format_resume_targets` (line 400). Output as CommonMark blockquote per agent. The agent metadata source (`sase.ace.tui.models.agent_loader.load_all_agents` + `list_running_agents`) is already imported.

### R2 — Wire `.retry <name>` (or `.r <name>`) dot command
**Why:** Telegram's 🔄 Retry pattern is one of the highest-leverage features added recently — re-launching a killed agent without retyping the prompt. `option_codes.py:7` already calls out `.retry` as the intended hook, but no handler exists.
**How:** Reuse telegram's `_get_agent_retry_prompt` (`sase_tg_inbound.py:186-220`) — it reads `raw_xprompt.md` and strips auto-`%n:<name>` directives. Then post the prompt as a new message in the space (which the gchat inbound chop will pick up as a launch on next tick). No need for callback encoding because there's no button — the user types `.retry foo`. Add a corresponding entry in the post-completion message ("Reply `.retry <name>` to relaunch") similar to telegram's button.

### R3 — Backfill formatting tests to match telegram coverage
**Why:** 40 vs 65 tests is a real gap. Likely uncovered: blockquote wrapping at long boundaries, `format_provider_model_label` collapse/escape edge cases, options-block rendering with 0/1/N options, numbered-options renumbering when option labels contain digits, attachment list construction.
**How:** Mirror telegram's `test_formatting.py` tests one-for-one where the case is platform-agnostic. Skip MarkdownV2-specific escaping tests (irrelevant to CommonMark).

### R4 — Add `#pr`-aware resume targeting in `formatting.py`
**Why:** Telegram's `_has_pr_xprompt` check (`sase_tg_inbound.py:366`) emits `#resume:@<name>` when the original prompt contained `#pr`, which materially changes how the resumed agent finds its CL. gchat's `formatting.py:270-282` does the VCS-tag swap but not the `@`-prefix.
**How:** Add the same `_has_pr_xprompt`-style check next to the `extract_vcs_workflow_tag` call in `formatting.py:275`. The helper itself can be lifted unchanged.

### R5 — Add `.help` dot command
**Why:** Telegram users get auto-complete from `set_my_commands`. gchat users have to know the dot-command vocabulary. A `.help` listing the five commands closes most of the discoverability gap without any platform feature dependency.
**How:** Add `"help"` to `_DOT_COMMANDS` (`inbound.py:460`) and a small handler in `sase_gc_inbound.py` that returns a static command list.

### R6 — Pin "strike on TUI dismissal" behavior with a test
**Why:** `_cleanup_externally_handled` → `_strike_message` (`sase_gc_inbound.py:458-478`) is the gchat-specific equivalent of telegram's keyboard edit. It edits the original message text via `gchat edit-message`. There is no test for the strike rendering. A regression here is silent (the user just sees stale options).
**How:** Unit test in `test_inbound.py` that mocks `pending_actions` and `gchat_client.edit_message`, asserts the edit payload contains the `~Options consumed~` strike block.

### R7 — Adopt gchat's per-thread awaiting-feedback in telegram (cross-repo)
**Why:** Inverted lift. gchat's `awaiting_feedback.json` is keyed by `thread_id` and supports multiple concurrent two-step flows. Telegram is single-entry — start a feedback flow, then start another, the first is silently overwritten.
**How:** Out of scope for the gchat improvement effort, but worth filing against sase-telegram. Telegram's analog key would be the originating message_id.

### R8 — Adopt telegram's per-notification HWM advance everywhere (cross-repo, inverted)
**Why:** Telegram's outbound batches its high-water-mark advance, gchat's per-notification advance is strictly safer on mid-batch failures. (Actually telegram should learn from gchat here — re-check the wording in the doc when filing.)

### R9 — Create `retired chat plugin/ROADMAP.md`
Following the pattern of capturing future work; both `plans/` directories are essentially empty. Seed with R1–R6.

### Lower priority / parking lot
- Surface `gchat_client.create_reaction` somewhere — emoji reactions on plan-approval messages would be a unique gchat affordance that telegram can't match.
- Investigate whether gchat CLI exposes anything like a streaming/draft-message API (the equivalent of `sendMessageDraft` discussed in `sdd/research/202603/telegram_improvements.md`). If not, document the absence so it stops coming up.
- Consider whether the `option_codes.py` module is worth keeping if R2 is the only consumer — a single use site might fold inline.

## Appendix — File reference map

**retired chat plugin:**
- Inbound script: `src/retired_chat_plugin/scripts/sase_gc_inbound.py` (582 LOC)
- Outbound script: `src/retired_chat_plugin/scripts/sase_gc_outbound.py` (185 LOC)
- Core logic: `inbound.py` (620), `outbound.py` (105), `formatting.py` (304)
- Client: `gchat_client.py` (277)

**sase-telegram:**
- Inbound script: `src/sase_telegram/scripts/sase_tg_inbound.py` (~1150)
- Core logic: `inbound.py`, `outbound.py`, `formatting.py` (~700)
- Client: `telegram_client.py`
