# Antigravity Tools Panel Support Research

Date: 2026-06-20

## Scope

This note researches how SASE should add tools panel support for the new
Antigravity CLI provider (`agy`). It focuses on the current SASE tools panel
contract, what Antigravity CLI 1.0.10 exposes, which integration points are
stable enough to use, and which implementation path should be preferred.

## Executive summary

SASE's tools panel is already provider-neutral. It reads normalized
`tool_calls.jsonl` artifacts from the agent artifact directories and does not
need a TUI-specific integration for a new provider. The missing piece for
Antigravity is not a panel change; it is a stable way for the `agy` provider to
produce normalized tool-call records.

Antigravity CLI 1.0.10 does not currently expose a documented JSON event stream
or stable tool-call export format. The local CLI help exposes print mode,
conversation selection, log-file output, plugins, hooks, permissions, and
conversation history, but no `--json`, `--output-format stream-json`, or
equivalent stream flag. Official Antigravity CLI docs describe tool calling and
rich in-terminal views, but do not document a machine-readable tool-call stream
for CLI consumers.

The Antigravity SDK is the only official Antigravity surface found in this
research that clearly exposes typed tool-call streams, lifecycle hooks, token
usage, and thinking traces. That makes it a promising future implementation
route, but it is a different runtime integration from the CLI provider and
should be treated as either a separate provider or an explicitly chosen enhanced
mode after auth, permissions, model behavior, and workflow parity are verified.

The best default path is to keep the current `agy` CLI provider from fabricating
tool rows and add tools panel support only when SASE can consume a documented
Antigravity CLI stream or hook payload. Scraping stdout, `live_reply.md`, CLI
logs, local transcript files, or SQLite/protobuf cache internals would make the
tools panel brittle and could expose sensitive command output in surprising
ways.

## Current SASE tools panel contract

The tools panel path is intentionally provider-neutral:

- `src/sase/ace/tui/widgets/tools_panel.py` reads tool-call artifacts through a
  cached/background worker path.
- `src/sase/ace/tui/tools/reader.py` looks for `tool_calls.jsonl` in the current
  and related artifact directories.
- `src/sase/ace/tui/tools/_parser.py` parses normalized records and collapses
  `ToolUse` / `ToolResult` pairs.
- `src/sase/ace/tui/tools/_entry.py` formats provider-neutral display entries.

The normalized schema is defined in
`src/sase/llm_provider/_tool_call_common.py`. Records include common fields such
as:

- `schema_version`
- `recorded_at`
- `runtime`
- `source`
- `event`
- `status`
- `tool_name`
- `tool_use_id`
- `tool_input_summary`
- `tool_response_summary`
- `duration_ms`
- `session_id`
- `cwd`

Existing providers feed this schema from provider-specific machine-readable
events:

- Codex parses `codex exec --json` events in
  `src/sase/llm_provider/_tool_call_codex.py`.
- Claude parses `--output-format stream-json` events in
  `src/sase/llm_provider/_tool_call_claude.py`.
- Qwen parses `--output-format stream-json` events in
  `src/sase/llm_provider/_tool_call_qwen.py`.

The current Antigravity provider intentionally does not emit structured tool
artifacts:

- `src/sase/llm_provider/agy.py` invokes `agy --print ...` and streams plain
  stdout into the live reply artifact.
- It returns `usage=None`.
- It does not write `tool_calls.jsonl`, `usage.json`, or thinking artifacts.
- `tests/test_llm_provider_agy.py` pins that behavior.
- `tests/ace/tui/tools/test_reader_agy.py` explicitly avoids scraping
  `live_reply.md`, but confirms that if future normalized records with
  `runtime: "agy"` exist, the existing reader path works unchanged.

This is the right separation. The TUI should remain a consumer of normalized
artifacts. The provider should decide whether it has a trustworthy event source
from which to write those artifacts.

## Antigravity CLI 1.0.10 findings

Local `agy --version` reports `1.0.10`. Local `agy --help` exposes these
relevant flags and subcommands:

- `--print`, `--print-timeout`, `--prompt`, and `--prompt-interactive`
- `--conversation` and `--continue`
- `--log-file`
- `--model`
- `--sandbox`
- `--dangerously-skip-permissions`
- `plugins`, `changelog`, `models`, `install`, `update`, and `help`

It does not expose a documented JSON event flag such as `--json`,
`--output-format stream-json`, or an equivalent stream mode.

The official transition announcement says Antigravity CLI is the new terminal
experience replacing the consumer Gemini CLI path, that it is not intended to
have one-to-one parity with Gemini CLI, and that it retains important concepts
such as Agent Skills, Hooks, Subagents, and Extensions as plugins.

Official CLI documentation confirms the CLI supports multi-step reasoning,
multi-file editing, tool calling, conversation history, slash commands,
permissions, plugins, hooks, MCP config, and conversation resumption. The docs
also describe in-terminal displays for trajectories, subagents, artifacts, and
tool reasoning. However, they do not document a CLI output mode that emits typed
tool-use events to stdout or a stable file path containing typed tool-call
records.

### Status line and title hooks

The CLI status line and title command integrations receive JSON on stdin when
agent state changes. The documented JSON includes fields such as:

- `cwd`
- `conversation_id`
- model, workspace, version, and plan metadata
- context-window usage
- `agent_state`, including values such as `idle`, `thinking`, `working`,
  `tool_use`, and `initializing`
- VCS, sandbox, subagent, artifact, pending-input, and background-task state
- terminal width

This is useful for shell UI decoration, but it is not enough for SASE's tools
panel. It lacks the tool name, input, result, stable tool ID, status transition,
duration, and response summary needed to populate normalized `ToolUse` /
`ToolResult` rows.

### Plugins and hooks

Official CLI plugin docs show plugin directories under
`~/.gemini/antigravity-cli/plugins/<name>/` and plugin-provided files such as
`hooks.json`, `mcp_config.json`, skills, agents, and rules. The docs also say
hooks can be inspected with `/hooks` and can be used by plugins.

This is a possible future route if the CLI hook payloads are documented or if
Antigravity publishes a stable hook contract equivalent to the SDK hook model.
At the moment, the public CLI docs do not provide enough payload detail to build
a robust SASE hook writer from documentation alone.

## Local Antigravity cache and transcript findings

Local Antigravity state under `~/.gemini/antigravity-cli` contains conversation
databases, brain directories, transcript JSONL files, and diagnostic CLI logs.
These files show that Antigravity records internal step information, including
tool-like steps such as `RUN_COMMAND`, `VIEW_FILE`, and `LIST_DIRECTORY`.

The useful-looking transcript JSONL shape is still not a good provider
contract:

- Records are presentation-oriented rather than typed API events.
- The `content` payload is a rendered string, not structured input/result data.
- Tool start/result pairing is not represented as a stable public schema.
- There is no documented compatibility guarantee for field names, paths, enum
  values, or content formatting.
- The rendered content can include raw command output and file contents, so
  parsing it into a visible tools panel could unexpectedly surface sensitive
  data.
- The SASE provider does not receive a stable path to these internals from
  `agy --print`.

Conversation SQLite databases are also not a suitable default integration
point. The database schema includes internal tables such as `steps`,
`trajectory_meta`, and metadata/blob tables, with protobuf-like BLOB payloads.
Decoding those would require reverse engineering private Antigravity internals,
including enums and binary message layouts that can change across CLI releases.

CLI logs are similarly diagnostic rather than semantic. `--log-file` controls
where logs are written, but those logs are not a documented stream of model
steps and tool results.

## Antigravity SDK findings

The Antigravity SDK documentation describes an official programmatic surface
that extends the same core agent harness as the CLI and Antigravity app. The SDK
explicitly includes:

- built-in file and system tools
- custom Python function tools
- MCP servers
- agent skills
- lifecycle hooks
- streaming
- token usage
- thinking traces

The SDK README includes an advanced tool-call stream pattern where code can
iterate `response.tool_calls` and receive typed call objects, including tool
names. The conversation docs describe step-level streaming through
`receive_steps()`. The hooks docs describe pre/post tool-call hooks and
`ToolCall` / `ToolResult`-style objects for built-in tools and subagents.

This is the strongest official signal that Antigravity can provide the data
SASE needs. The catch is that it is SDK integration, not CLI stdout parsing. A
SASE SDK-based provider would need to answer several practical questions before
it could replace or enhance the current CLI provider:

- Does SDK auth match the CLI user's expected auth flow?
- Does model selection match `agy --model` behavior?
- Are CLI skills, rules, MCP config, hooks, sandboxing, and permissions
  equivalent enough for SASE workflows?
- Can SASE preserve the same cancellation, timeout, artifact, and subprocess
  supervision behavior?
- Does the SDK support the exact noninteractive prompt-and-return workflow SASE
  needs?
- Does using the SDK create packaging or environment constraints that are
  inappropriate for the existing CLI provider?

Until those are answered, the SDK should be treated as a promising separate
provider spike, not as a transparent implementation detail for `agy`.

## Candidate integration options

| Option | Summary | Fit |
| --- | --- | --- |
| Keep current no-tools behavior | Continue to stream plain stdout and omit `tool_calls.jsonl` for `agy`. | Correct default until a stable event source exists. |
| Scrape stdout or `live_reply.md` | Parse human-facing output for tool names and results. | Not recommended. Brittle and already rejected by tests. |
| Parse local transcript JSONL | Read `~/.gemini/antigravity-cli/brain/.../transcript*.jsonl`. | Not recommended for default support. Internal, presentation-oriented, and privacy risky. |
| Decode SQLite/protobuf cache | Reverse engineer conversation DB BLOBs. | Not recommended. Private binary internals with no compatibility contract. |
| Use statusLine/title JSON | Capture state changes from documented shell UI integrations. | Insufficient. Provides `tool_use` state but not tool details. |
| Use CLI hooks/plugins | Install a SASE hook that writes normalized events. | Good future route if hook payloads are documented and stable. Not enough public contract today. |
| Use future CLI JSON stream | Parse an official `agy` JSON/stream mode if Google adds one. | Best CLI-native route. Minimal TUI impact. |
| Add SDK-based provider | Use Antigravity SDK typed streams/hooks to write `tool_calls.jsonl`. | Strong long-term route, but should be a separate provider or opt-in enhanced mode after parity research. |

## Implementation shape when a stable source exists

If Antigravity CLI adds a documented stream mode, the implementation should
mirror the Codex, Claude, and Qwen providers:

1. Add `src/sase/llm_provider/_tool_call_agy.py` to normalize official
   Antigravity event objects into SASE's existing schema.
2. Add an Antigravity stream runner, likely
   `src/sase/llm_provider/_subprocess_agy.py`, that:
   - executes `agy` with the documented stream flag,
   - writes assistant text to `live_reply.md`,
   - appends normalized tool events to `tool_calls.jsonl`,
   - writes usage/thinking artifacts only if exposed by the official stream,
   - preserves timeout and cancellation behavior from the current provider.
3. Keep `runtime: "agy"` and choose `source: "stream"` for stream-derived
   records.
4. Keep the tools panel unchanged.
5. Add parser fixture tests for every documented Antigravity tool-event shape.
6. Add provider tests that fake the CLI stream and assert `tool_calls.jsonl`
   rows are produced.
7. Keep a fallback path for CLI versions without the documented stream flag:
   plain stdout, no fabricated tool artifacts.

If documented CLI hooks become available before a stream mode, the same schema
can still be used:

1. Add a SASE-managed Antigravity plugin or hook writer that receives documented
   pre/post tool payloads.
2. Have the hook append normalized records directly to the current SASE
   artifact directory.
3. Use `source: "hook"`.
4. Require explicit setup or version detection so SASE never silently modifies a
   user's global Antigravity config.
5. Test against captured official hook payload fixtures.

If the SDK route is selected, it should be implemented as a separate spike:

1. Add an opt-in SDK-backed provider, for example `agy_sdk`, rather than
   changing the CLI provider in place.
2. Use SDK `response.tool_calls`, step streaming, and post-tool hooks to produce
   normalized `tool_calls.jsonl`.
3. Compare CLI and SDK behavior on auth, models, permissions, skills, MCP,
   sandboxing, cancellation, and artifact output.
4. Promote it only if it preserves the workflows that made the CLI provider
   useful.

## Sources

- Google Developers Blog: "An important update: Transitioning Gemini CLI to
  Antigravity CLI" -
  https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/
- Antigravity CLI overview -
  https://antigravity.google/assets/docs/cli/cli-overview.md
- Antigravity CLI reference -
  https://antigravity.google/assets/docs/cli/cli-reference.md
- Antigravity CLI conversations -
  https://antigravity.google/assets/docs/cli/cli-conversations.md
- Antigravity CLI plugins -
  https://antigravity.google/assets/docs/cli/cli-plugins.md
- Antigravity CLI permissions -
  https://antigravity.google/assets/docs/cli/cli-permissions.md
- Antigravity CLI status line -
  https://antigravity.google/assets/docs/cli/cli-statusline.md
- Antigravity SDK overview -
  https://antigravity.google/assets/docs/sdk/sdk-overview.md
- Antigravity SDK Python README -
  https://github.com/google-antigravity/antigravity-sdk-python
- Antigravity SDK conversation README -
  https://github.com/google-antigravity/antigravity-sdk-python/blob/main/google/antigravity/conversation/README.md
- Antigravity SDK hooks README -
  https://github.com/google-antigravity/antigravity-sdk-python/blob/main/google/antigravity/hooks/README.md
- Antigravity SDK tools README -
  https://github.com/google-antigravity/antigravity-sdk-python/blob/main/google/antigravity/tools/README.md

## Recommended solution

Do not add default tools panel support for the current Antigravity CLI by
scraping stdout, `live_reply.md`, logs, transcript JSONL, or SQLite/protobuf
cache internals. Keep the existing `agy` provider behavior: stream the assistant
reply, omit `tool_calls.jsonl`, and let the tools panel show no data for this
runtime unless normalized records exist.

For CLI-native support, wait for or request one documented Antigravity CLI
contract:

- a JSON/stream output mode that emits typed tool-use and tool-result events, or
- a documented pre/post tool hook payload that a SASE-managed hook can consume.

Once one of those exists, implement a narrow provider-side normalizer that
writes the existing SASE `tool_calls.jsonl` schema with `runtime: "agy"`. The
TUI reader and tools panel should not need changes.

In parallel, run a separate spike for an SDK-backed provider, tentatively
`agy_sdk`, because the Antigravity SDK already exposes the kind of typed
tool-call streams and hooks SASE needs. Treat that as a separate provider or
explicit enhanced mode until it proves equivalent to the CLI provider for auth,
models, permissions, skills, MCP, sandboxing, cancellation, and noninteractive
execution.

The practical next step is to keep the current tests that forbid fabricated
`agy` tool artifacts, then open an upstream request or local experiment for a
documented CLI tool-event contract. If immediate dogfood visibility is required,
add only an explicitly marked experimental transcript parser behind a disabled
feature flag, with no promise of completeness or compatibility.
