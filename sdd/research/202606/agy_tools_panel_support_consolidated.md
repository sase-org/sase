---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Antigravity (`agy`) Tools Panel Support - Consolidated Research

## Request

Research the best way to add ACE Tools panel support for the new Antigravity
CLI provider. The current `agy` provider works as a plain-stdout provider, but
does not populate the Tools panel.

This consolidates the two independent research notes:

- `sdd/research/202606/agy_tools_panel_support.md`
- `sdd/research/202606/antigravity_tools_panel_support.md`

## Consolidated finding

The ACE Tools panel does not need an `agy`-specific UI integration. It already
renders provider-neutral `tool_calls.jsonl` artifacts from an agent's artifact
directory. The missing piece is entirely on the producer side: the `agy`
provider needs a trustworthy source of tool-use and tool-result events, then it
can normalize them into the existing SASE schema.

The two prior notes disagreed on the main implementation choice:

- One note recommended parsing Antigravity's local conversation SQLite database
  because it contains real structured tool trajectory data.
- The other recommended waiting for a documented CLI stream or using the
  Antigravity SDK because the SQLite/protobuf data is private and undocumented.

Both are partly right. Local `agy 1.0.10` does not expose a documented
stdout/JSON stream, but it does persist enough structured trajectory data to
populate the Tools panel today. The best SASE answer is therefore not "scrape
human output" and not "change the TUI"; it is a guarded provider-side
post-run extractor for Antigravity's conversation trajectory, with strict
version and fixture protections and a clean fallback to "no tools" when the
private format is not recognized.

## Current SASE boundary

The Tools panel path is intentionally provider-neutral:

- Runtime providers append normalized rows to
  `SASE_ARTIFACTS_DIR/tool_calls.jsonl`.
- The schema is built in `src/sase/llm_provider/_tool_call_common.py` and
  provider-specific normalizers such as `_tool_call_claude.py`,
  `_tool_call_codex.py`, and `_tool_call_qwen.py`.
- `src/sase/ace/tui/tools/reader.py` reads `tool_calls.jsonl`, parses entries,
  collapses `ToolUse` and `ToolResult` pairs, and returns `ToolCallEntry`
  objects for `src/sase/ace/tui/widgets/tools_panel.py`.

Important tests already pin the right boundary:

- `tests/ace/tui/tools/test_reader_agy.py` proves an `agy` run with no
  `tool_calls.jsonl` shows no tools and must not scrape tool-shaped text from
  `live_reply.md`.
- The same test file proves that future normalized rows with
  `runtime: "agy"` flow through the reader unchanged.
- `tests/test_llm_provider_agy.py` proves the current provider writes
  `live_reply.md`, returns `usage=None`, and creates no structured artifacts in
  plain-stdout mode.

This means an implementation should leave `src/sase/ace/tui/tools/*` and
`tools_panel.py` alone. It should write the existing artifact contract from the
provider path.

The TUI performance memory reinforces this boundary: do not add synchronous
disk, SQLite, JSON, or protobuf parsing on the Textual event loop. Any
extraction should happen in the provider/subprocess path or a background worker,
not during panel render or navigation.

## Verified Antigravity CLI surface

Local `agy` is `/home/bryan/.local/bin/agy`, version `1.0.10`.
`agy --help` exposes `--print`, `--print-timeout`, `--prompt`,
`--prompt-interactive`, `--conversation`, `--continue`, `--log-file`,
`--model`, `--sandbox`, `--dangerously-skip-permissions`, and plugin/model
subcommands. It does not expose `--json`, `--output-format`, `stream-json`, or
an equivalent machine-readable event stream.

Official CLI docs checked on 2026-06-20 agree with that shape:

- The CLI overview describes tool calling, multi-step reasoning, multi-file
  editing, and conversation history as terminal/TUI capabilities.
- The conversations docs describe workspace-scoped resume and
  `agy --conversation <id>`.
- The status line docs describe a JSON payload with `conversation_id`,
  `agent_state`, token context, artifacts, pending confirmations, and
  background tasks. It is useful for coarse state, but lacks tool name, args,
  result, stable tool id, status transitions, and duration.
- The plugin docs describe `hooks.json` as optional pre/post tool event hooks,
  but do not document a CLI hook payload schema that SASE can depend on.

The Antigravity SDK docs are stronger: they describe step-level streaming,
conversation usage tracking, built-in tool hooks, `ToolCall`/`ToolResult`
objects, and post-tool hook results. That is an official programmatic route,
but it is a different runtime integration from the current CLI provider.

## Local data surfaces

The useful local Antigravity state is under
`~/.gemini/antigravity-cli/`.

| Surface | Tool data? | Assessment |
| --- | --- | --- |
| `agy --print` stdout | No | Final/plain assistant text only for SASE's current mode. |
| `history.jsonl` | No | Prompt/history metadata, not tool events. |
| `log/cli*.log` / `--log-file` | No | Diagnostic logs, not a semantic tool timeline. |
| Status line JSON | Partial | Has `agent_state: "tool_use"` and `conversation_id`, but no tool details. |
| Plugin hooks | Potential | Docs mention hooks, but not enough payload contract for implementation. |
| SDK | Yes | Official typed streams/hooks, but a separate provider-level integration. |
| `conversations/<uuid>.db` | Yes | Real trajectory data, but private SQLite + protobuf internals. |
| `cache/last_conversations.json` | Association only | Maps workspace cwd to latest conversation id. |

Metadata-only verification of recent local conversation DBs found:

- 17 local `conversations/*.db` files.
- Each recent DB is SQLite with tables including `steps`, `trajectory_meta`,
  `gen_metadata`, `executor_metadata`, `parent_references`,
  `trajectory_metadata_blob`, and `battle_mode_infos`.
- `steps` has columns `idx`, `step_type`, `status`, `has_subtrajectory`,
  `metadata`, `error_details`, `permissions`, `task_details`, `render_info`,
  `step_payload`, and `step_format`.
- Recent `step_type` histograms include values such as `14`, `15`, `21`, `23`,
  `98`, and `132`.
- Payload bytes in recent DBs contain known tool names such as `run_command`,
  `view_file`, `read_file`, `write_file`, `list_permissions`, and `list_dir`.

The stronger prior-agent evidence used `protoc --decode_raw` on captured
`step_payload` blobs and found tool-call ids, tool names, JSON-encoded
arguments, timestamps, conversation ids, tool outputs, permission decisions,
and token counters. That supports the central feasibility claim: the
conversation DB is structured trajectory data, not rendered TUI prose.

The risk is also real. The SQLite schema, `step_type` enum, protobuf field
numbers, and blob meanings are not public compatibility contracts. Google can
change them in a new `agy` release without notice.

## Run to conversation association

SASE needs to associate one `agy --print` invocation with one
`conversations/<uuid>.db`.

Use two signals together:

1. Snapshot `~/.gemini/antigravity-cli/conversations/*.db` paths and mtimes
   before launching `agy`; after the process exits, pick DBs created or updated
   during the run.
2. Read `~/.gemini/antigravity-cli/cache/last_conversations.json` after the run
   and use the cwd entry as a cross-check. Local verification found this file
   exists and contains cwd to conversation-id mappings.

Because SASE normally runs agents in distinct workspace clones, cwd mapping is
usually enough. The pre/post DB diff covers shared-cwd races such as resume,
interrupt, or finalizer runs.

Do not rely on `--conversation <new-id>` for v1. The docs say it resumes an
existing conversation by ID. A separate one-call spike can test whether an
unknown ID creates a pinned conversation, but the DB diff plus cwd map works
without that assumption.

## Implementation shape

Add a provider-side extractor, not a TUI feature.

1. Add `src/sase/llm_provider/_tool_call_agy.py`.
   - Keep it pure and fixture-tested.
   - Decode only the small protobuf-wire subset needed for known trajectory
     fields: varints and length-delimited values; ignore unknown fields.
   - Do not shell out to `protoc` at runtime.
   - Recognize only fixture-proven `step_type` and field paths.
   - Convert Antigravity tool names to SASE display names, for example
     `run_command` to `Bash`, file-view tools to `Read`, file-write/edit tools
     to `Write`/`Edit`, and unknown tools to their original names.
   - Reuse existing summarizers from `_tool_call_common.py` so command output,
     file contents, and secrets are bounded/redacted the same way as other
     providers.
   - Emit `runtime: "agy"` and `source: "trajectory"`.

2. Add `src/sase/llm_provider/_subprocess_agy.py` or a narrow helper called by
   `AgyProvider._run_subprocess`.
   - Before `Popen`, snapshot conversation DB paths and mtimes.
   - Run the existing plain stdout path to keep `live_reply.md` behavior.
   - After process exit, resolve the DB using cwd map plus DB diff.
   - Open SQLite read-only with `file:<path>?mode=ro` after `agy` has exited.
   - Iterate `steps` ordered by `idx`, normalize recognized tool-use and
     tool-result steps, and append rows to `tool_calls.jsonl`.
   - Treat every extraction failure as best-effort artifact loss, not an agent
     failure.

3. Keep current fallback behavior.
   - Unsupported `agy` versions, missing DBs, unknown schema, SQLite locks,
     malformed payloads, or unmatched conversations should leave
     `tool_calls.jsonl` absent or partial.
   - Emit writer diagnostics where useful, but never fabricate rows.

4. Add focused tests.
   - Golden DB or extracted blob fixtures for `run_command`, read, write/edit,
     success, failure, and unknown step cases.
   - Association tests for cwd-map success and shared-cwd DB-diff
     disambiguation.
   - Provider tests proving extraction is best-effort and failures do not fail
     `AgyProvider.invoke`.
   - Keep the existing no-scraping tests: an `agy` run with no valid structured
     source still shows nothing.

## Stability and privacy guards

The implementation should be explicit that this is private trajectory
extraction, not an official Antigravity CLI contract.

- Gate extraction by `agy --version`; start with exact `1.0.10` support unless
  fixtures prove a wider range.
- Add golden fixtures so field drift fails loudly in tests.
- Skip unknown steps and unknown fields.
- Use existing SASE summaries, not raw full tool output, unless an existing
  full-log opt-in such as `SASE_TOOL_LOG_FULL=1` is intentionally honored.
- Open DBs read-only and only after the process exits.
- Do not modify global Antigravity settings or install global plugins for this
  path.
- Document the fallback: if the private format drifts, the Tools panel returns
  to the current empty state for `agy`.

## Rejected or deferred alternatives

Scraping stdout, `live_reply.md`, transcript JSONL, or rendered TUI text should
stay rejected. It is presentation data, it can expose surprising raw output, and
the current tests intentionally prevent this.

Waiting for a documented CLI JSON stream is the cleanest official CLI-native
future, but it leaves the panel empty indefinitely. Still open or track an
upstream request for a typed `agy` event stream or documented pre/post tool hook
payload.

CLI status line JSON is insufficient because it exposes state and
`conversation_id`, not tool call details.

CLI plugins/hooks are promising only after Antigravity documents the hook
payload. A SASE-managed hook should not be installed silently into a user's
global Antigravity config.

An SDK-backed provider is a good parallel spike. The SDK appears to expose the
right official typed surfaces, including step streaming, tool hooks, token
usage, and built-in tool results. But it must prove parity with CLI auth, model
selection, skills/rules/plugins, MCP config, sandboxing, permissions,
cancellation, timeout, and noninteractive execution before it can replace or
enhance the CLI provider.

## Sources and verification

Repository files checked:

- `src/sase/llm_provider/agy.py`
- `src/sase/llm_provider/_subprocess_plain.py`
- `src/sase/llm_provider/_tool_call_common.py`
- `src/sase/llm_provider/_tool_calls.py`
- `src/sase/ace/tui/tools/reader.py`
- `tests/test_llm_provider_agy.py`
- `tests/ace/tui/tools/test_reader_agy.py`
- `sdd/epics/202606/agy_provider_mvp.md`
- `sdd/research/202606/agy_migration_consolidated.md`
- `sdd/research/202606/agy_e2e_hardening.md`

Local commands checked:

- `command -v agy`
- `agy --version`
- `agy --help`
- metadata-only SQLite inspection of
  `~/.gemini/antigravity-cli/conversations/*.db`
- metadata-only inspection of
  `~/.gemini/antigravity-cli/cache/last_conversations.json`

Official docs checked:

- https://antigravity.google/assets/docs/cli/cli-overview.md
- https://antigravity.google/assets/docs/cli/cli-reference.md
- https://antigravity.google/assets/docs/cli/cli-conversations.md
- https://antigravity.google/assets/docs/cli/cli-plugins.md
- https://antigravity.google/assets/docs/cli/cli-statusline.md
- https://raw.githubusercontent.com/google-antigravity/antigravity-sdk-python/main/google/antigravity/conversation/README.md
- https://raw.githubusercontent.com/google-antigravity/antigravity-sdk-python/main/google/antigravity/hooks/README.md
- https://raw.githubusercontent.com/google-antigravity/antigravity-sdk-python/main/google/antigravity/tools/README.md

## Recommended solution

Implement guarded post-run trajectory extraction from Antigravity's local
`conversations/<uuid>.db` into the existing SASE `tool_calls.jsonl` schema.
Keep the change entirely provider-side: add an `agy` trajectory normalizer and a
subprocess helper that resolves the conversation DB after `agy --print` exits,
reads it read-only, normalizes fixture-proven tool steps, and writes
`runtime: "agy"`, `source: "trajectory"` rows.

Ship it behind strict safety rails: exact supported `agy` version detection,
golden DB/blob fixtures, best-effort failure handling, bounded/redacted
summaries, and fallback to the current empty Tools panel when the private format
is unavailable or drifts. Do not scrape `live_reply.md`, do not change the ACE
Tools panel, and do not silently install global Antigravity hooks.

In parallel, request a documented Antigravity CLI event stream or hook payload
and run a separate `agy_sdk` spike. Those official surfaces are better long-term
contracts, but the guarded DB trajectory reader is the best practical way to add
Tools panel support to the current CLI provider now without inventing data.
