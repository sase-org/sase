---
create_time: 2026-05-16 10:03:20
status: done
prompt: sdd/prompts/202605/claude_tools_streaming.md
---
# Plan: Make Claude Tools Panel Data Stream-Backed

## Context

The Agents tab Tools panel reads normalized rows from each agent artifact directory's `tool_calls.jsonl`. Codex, Gemini,
and Qwen populate that file from the provider JSON/NDJSON stream while the subprocess is running. Claude already has a
stream-json parser capable of writing `ToolUse` and `ToolResult` rows from assistant/user stream events, but Claude also
installs a SASE-managed `PreToolUse`/`PostToolUse` hook collector for every workspace invocation and the reader/docs
currently describe hook rows as the preferred Claude source.

The target behavior is that Claude populates Tools panel data from `--output-format stream-json`, like the other
providers, without mutating `.claude/settings.local.json` to install SASE tool-call hooks. Historical hook artifacts
should remain readable so existing runs do not break.

## Goals

- Stop using Claude hooks to gather Tools panel data for new runs.
- Keep Claude tool capture based on the same `tool_calls.jsonl` stream schema used by the other providers.
- Avoid writing or restoring `.claude/settings.local.json` during normal Claude provider invocation.
- Preserve backward compatibility for old `source: "hook"` / schema-v3 artifacts.
- Keep unrelated provider hook support intact; this is only about the Tools panel data collector.

## Non-Goals

- Do not remove general runtime hook capabilities or commit/approval/question workflows.
- Do not change the Tools panel UI layout.
- Do not rewrite the shared artifact reader into Rust; this is a presentation/artifact ingestion change in the Python
  provider layer.
- Do not require live Claude CLI access in tests.

## Implementation Steps

1. Make Claude launch stream-only for Tools data.
   - Remove `claude_hooks_session(...)` from `ClaudeCodeProvider.invoke`.
   - Remove the provider dependency on `resolve_workspace_dir`.
   - Keep `--output-format stream-json`; this is the authoritative event stream.
   - Re-evaluate `--include-hook-events`: remove it unless a non-tools feature depends on it. The Tools panel should be
     driven by assistant `tool_use` and user `tool_result` stream events, not hook response events.

2. Narrow Claude tool-call normalization to stream events for new writes.
   - Keep `append_claude_tool_call_event(event)` writing rows from assistant/user stream events.
   - Avoid writing new tool rows from Claude `system` hook events in the normal stream path if `--include-hook-events`
     remains for another reason. If no other dependency exists, removing `--include-hook-events` is cleaner and avoids
     mixed source rows.
   - Keep schema-v3 hook normalization code only where needed for backward-compatible reads/tests or delete it if no
     public entry point still uses it after tests are adjusted.

3. Update reader documentation and precedence semantics.
   - Change `src/sase/ace/tui/tools/reader.py` module comments to describe stream rows as the primary cross-provider
     contract.
   - Keep `SUPPORTED_SCHEMA_VERSIONS` including `3` so old Claude hook artifacts remain readable.
   - Keep hook-vs-stream de-duplication only as a legacy compatibility rule, or adjust tests to assert that current
     mixed files still collapse without double-counting.

4. Remove or quarantine the Claude hook collector surface.
   - If nothing else imports `src/sase/llm_provider/_claude_hooks.py` or `src/sase/scripts/sase_claude_tool_hook.py`
     after provider changes, remove the console script entry from `pyproject.toml` and delete the dead collector module.
   - If keeping them for compatibility is safer, make them explicitly legacy and stop invoking them from provider code.
     The important contract is no new Claude Tools-panel collection through hook registration.

5. Update tests to lock the new contract.
   - Replace provider tests that assert hook installation with tests asserting no `.claude/settings.local.json` mutation
     and no hook session call during `ClaudeCodeProvider.invoke`.
   - Update command-argument tests so Claude still uses `--output-format stream-json` and no longer passes
     `--include-hook-events` if that flag is removed.
   - Keep or add stream-normalizer tests proving assistant `tool_use` and user `tool_result` rows are appended and
     collapse into one Tools panel entry.
   - Add a provider-level simulated run test where mocked Claude stream output writes `tool_calls.jsonl` without any
     hook collector involvement.
   - Retain focused legacy tests for reading existing schema-v3 hook rows if those modules stay, or move them to reader
     compatibility fixtures if hook writer code is removed.

6. Verification.
   - Run targeted tests first:
     - `pytest tests/llm_provider/test_tool_calls_writer.py`
     - `pytest tests/llm_provider/test_claude_hooks.py tests/test_llm_provider_providers.py`
     - `pytest tests/ace/tui/tools tests/ace/tui/widgets/test_tools_panel.py`
   - Because this repo requires it after code changes, run `just install` if needed and then `just check`.

## Risks and Mitigations

- Claude stream shape drift: existing tests use synthetic stream events, but there is no checked-in Claude fixture. Add
  a small fixture-style test around the event shapes SASE relies on so future changes do not silently reintroduce hooks.
- Lost metadata from hook rows: hook payloads included exact `duration_ms`, `cwd`, `transcript_path`, and permission
  mode. The stream path may not provide all of that. Prefer uniform provider behavior and best-effort stream fields over
  mutating user/project Claude settings.
- Existing hook artifacts: old runs should still display. Keep reader schema-v3 support and collapse behavior unless
  there is a strong reason to remove it in a separate migration.
- Hidden dependency on `--include-hook-events`: before removing the flag, confirm no non-tools path consumes those
  system events. Current code search shows only the tool-call writer uses them.

## Expected Outcome

New Claude agents populate the Tools panel exclusively from Claude Code stream-json events, matching Codex/Gemini/Qwen
collection style. SASE no longer installs temporary Claude tool hooks or mutates workspace Claude settings for this
feature. Existing hook-backed artifacts remain readable without double-counting.
