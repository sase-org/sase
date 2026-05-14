---
create_time: 2026-05-14 19:30:49
status: done
prompt: sdd/prompts/202605/codex_tools_panel.md
---
# Plan: Add Codex Support To The Agents Tools Panel

## Context

The Agents tab Tools panel is already runtime-neutral at the TUI boundary: it reads per-run `tool_calls.jsonl` artifacts
through `sase.ace.tui.tools.reader` and renders `ToolCallEntry` rows. The current MVP only produces those artifacts for
Claude, by normalizing `--include-hook-events` stream records in `src/sase/llm_provider/_tool_calls.py`.

Codex already streams structured NDJSON in `src/sase/llm_provider/_subprocess_codex.py`. The parser handles assistant
messages, errors, and `function_call` items for the thinking sidecar, but it does not write normalized tool-call
records. Codex support should therefore be added as a second producer of the same artifact contract, not as a TUI
special case.

Relevant constraints:

- Preserve the existing schema version `1` and `tool_calls.jsonl` reader contract.
- Keep capture best-effort: tool-call logging must not affect Codex subprocess behavior.
- Respect the repo memory that runtimes should be treated uniformly; do not make the UI assume Claude-only capability.
- Avoid storing full tool inputs/outputs by default; reuse the existing bounded summaries and redaction policy.

## Approach

1. Extend the shared tool-call writer.
   - Add a Codex-specific append entrypoint in `src/sase/llm_provider/_tool_calls.py`.
   - Normalize Codex `item.completed` records where `item.type == "function_call"` into schema-v1 records with
     `runtime: "codex"` and an event such as `FunctionCall`.
   - Parse `item.arguments` whether Codex provides it as JSON text or an object.
   - Preserve useful identifiers such as `item.id` and `item.call_id` as `tool_use_id` when present.
   - Map common Codex tool names into display-friendly names that the existing summaries understand, especially: `shell`
     / `container.exec` -> `Bash`, `read_file` -> `Read`, `write_file` / `apply_patch` / `apply_diff` -> edit style
     tools.
   - Keep unknown Codex tool names intact and summarize them via existing `input_keys` fallback.

2. Wire Codex parsing to the writer.
   - In `_process_codex_json_line`, route every parsed mapping to the Codex tool-call append helper.
   - Keep assistant text extraction, error collection, reasoning buffering, and `following_action` behavior unchanged.
   - Do not depend on Codex hooks for this MVP. The NDJSON stream path matches the Claude Strategy B idea: SASE-launched
     provider streams produce SASE-owned artifacts.

3. Improve summary coverage where needed.
   - Reuse existing `_summarize_tool_input` / `_summarize_tool_response` defaults where possible.
   - If Codex shell arguments use `command` as a list, normalize it to a single command string before summary/redaction
     so the Tools panel target is useful.
   - For Codex edit-like tools, map `path` to `file_path` for compact targets.
   - If Codex emits function output events in the future, keep the current implementation tolerant, but avoid inventing
     unverified response capture without a stable local fixture.

4. Add focused tests.
   - Unit-test Codex function-call normalization and JSONL writing with `SASE_ARTIFACTS_DIR`.
   - Test shell command redaction and list-command normalization.
   - Test read/edit path mapping and unknown-tool fallback.
   - Extend Codex parser tests to prove tool-call writing does not break assistant text, error handling, or reasoning
     action capture.
   - Add/adjust a reader display test for a Codex record if necessary, but avoid TUI churn because the panel already
     consumes runtime-neutral records.

5. Verify.
   - Run focused tests for `_tool_calls`, Codex parser/thinking, and Tools reader/panel.
   - Run `just install` first if needed, then `just check` before the final response because this repo requires it after
     file changes.

## Acceptance Criteria

- A SASE-launched Codex run that emits `function_call` NDJSON items creates `SASE_ARTIFACTS_DIR/tool_calls.jsonl`.
- The artifact records use schema version `1`, `runtime: "codex"`, bounded summaries, and useful tool names/targets.
- Missing `SASE_ARTIFACTS_DIR`, malformed arguments, and unknown tools are no-ops or safe fallbacks.
- Existing Claude Tools panel behavior and Codex reply/thinking parsing remain green.
