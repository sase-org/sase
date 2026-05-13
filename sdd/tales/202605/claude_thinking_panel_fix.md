---
create_time: 2026-05-12 22:33:58
status: done
prompt: sdd/prompts/202605/claude_thinking_panel_fix.md
---
# Plan: Restore Claude thinking panel content

## Problem

The thinking panel for Claude agents has been silent for "a very long time" — no thoughts ever appear, even though
Codex/Gemini agents still show their thinking. The user wants the panel restored.

## Root cause (empirically confirmed)

Claude Code session transcripts at `~/.claude/projects/<hash>/*.jsonl` _do_ contain `thinking` content blocks for
assistant messages — but every block in recent transcripts has the shape:

```json
{ "type": "thinking", "thinking": "", "signature": "EvsBClkIDR...<long base64>" }
```

The `thinking` field is **always empty**; the actual reasoning is in `signature`, an opaque encrypted blob the model
emits to enable context continuation. Sampling across all recent sessions:

- All transcripts in `-home-bryan-projects-github-sase-org-sase-102/` (May 12): every thinking block has
  `"thinking":""`.
- Other May/April sessions across multiple projects: same — empty `thinking`, non-empty `signature`.
- An older sase-101 sub-agent transcript from **March 11, 2026**: `thinking` field contains plaintext ("The user wants
  me to add tests...").

So the cutover happened sometime between mid-March and early May 2026 — which lines up with the rollout of
`claude-opus-4-7` (the `message.model` in every recent transcript) and its server-side encryption of extended-thinking
content.

The downstream effect: `src/sase/ace/tui/thinking/parser.py:395-397` reads `block["thinking"]`, calls `.strip()`, and
**skips** blocks where it's empty. That filter — correct when the field carried plaintext — now silently drops every
Claude thought, so the panel reports zero blocks even when the model thought heavily.

This is unrelated to:

- The auto-show behavior change in `ac259a71f` (that touched panel visibility, not content).
- `_subprocess_claude.py` — it doesn't write the session transcript; Claude Code itself does.
- The session resolver — it finds the right files; they just contain redacted blocks.

Configuration crosscheck: `~/.claude/settings.json` has `alwaysThinkingEnabled: true` and
`CLAUDE_CODE_EFFORT_LEVEL=high`. Thinking _is_ on; it's just being encrypted before reaching the persisted transcript.

## Why a fix is possible (and what kind)

The `claude` CLI supports `--include-partial-messages` (visible in `claude --help`), which emits partial chunks via
stream-json. In Anthropic's streaming protocol, partial messages carry `content_block_delta` events with
`thinking_delta` deltas — and these deltas historically contain the plaintext reasoning even when the final assembled
`thinking` block is redacted in the persisted transcript. This is the same mechanism Codex uses (`_subprocess_codex.py`
captures streamed `reasoning` items into a sidecar `codex_thinking.jsonl` that the parser already reads).

So the architectural fix is: **mirror what Codex does for Claude.** Capture plaintext thinking from the live stream and
write a sidecar artifact the parser can read.

If `--include-partial-messages` doesn't expose plaintext (i.e. Anthropic redacts at the streaming layer too for Opus
4.7), we fall back to a placeholder-block fix so the panel at least surfaces _that_ Claude thought N times, with
timestamps and the following tool call — better than the current silent-failure UX.

## Proposed approach

Two-stage plan, ordered cheapest-first:

### Stage 1 — Investigate whether streamed deltas carry plaintext

Before writing code, empirically determine whether `--include-partial-messages` exposes plaintext thinking for
`opus`/`claude-opus-4-7`. One-off experiment: invoke the same command line `claude.py` uses, adding
`--include-partial-messages`, with a prompt that forces visible reasoning. Inspect stdout for `content_block_delta`
events with `delta.type == "thinking_delta"` and `delta.thinking` text.

- **If plaintext arrives in the stream** → Stage 2A (capture into sidecar).
- **If even streamed deltas are empty/encrypted** → Stage 2B (placeholder blocks). The capability ceiling is set by
  Anthropic, not by sase.

### Stage 2A — Capture streamed thinking to a sidecar (preferred)

If Stage 1 confirms plaintext deltas, mirror the Codex implementation:

1. Add `--include-partial-messages` to the Claude argv in `src/sase/llm_provider/claude.py:175-186`.
2. In `src/sase/llm_provider/_subprocess_artifacts.py`, add an `open_claude_thinking_file()` analogous to
   `open_codex_thinking_file()` that writes to `$SASE_ARTIFACTS_DIR/claude_thinking.jsonl`.
3. In `src/sase/llm_provider/_subprocess_claude.py:_process_json_line`, recognize `content_block_delta` events with
   `thinking_delta` deltas and buffer them per `index`; on `content_block_stop` (or the next `assistant` event), flush
   the buffered thinking text plus a synthesized `following_action` (the next `tool_use` block) to the sidecar — same
   shape Codex writes.
4. In `src/sase/ace/tui/thinking/parser.py`, add a `read_claude_thinking(artifacts_dir)` mirror of `read_codex_thinking`
   (lines 274-313).
5. In the parser entry point used by `AgentThinkingPanel.update_display()`, prefer the sidecar when present, fall back
   to the persisted JSONL otherwise. (This keeps the old code path live for sessions whose sidecar doesn't exist — e.g.
   Sonnet/Haiku, third-party tools, historical agents.)
6. Tests: add `test_claude_thinking_sidecar_*` tests in `tests/test_thinking_parser.py` covering empty file, malformed
   lines, ordering, and following-action assembly — same shape as the existing Codex tests.

This keeps Claude on the same architecture as Codex (uniform agent runtimes per `memory/short/gotchas.md`) and resolves
the "silent panel" entirely.

### Stage 2B — Placeholder blocks (fallback only)

If even streamed deltas are encrypted, treat the presence of a non-empty `signature` as evidence-of-thought:

1. In `parser.py:_extract_thinking_blocks`, when `thinking` text is empty but `signature` is non-empty, emit a
   placeholder `ThinkingBlock` whose `text` is something like `"[encrypted thought · ~N output tokens]"` (with `N`
   pulled from the event's `message.usage.output_tokens`).
2. The renderer in `widgets/thinking_panel.py` already handles arbitrary text — no widget changes needed; the panel will
   show timestamps, counts, and the following tool call as before, just with placeholder bodies.
3. Tests: extend `test_thinking_parser.py` with a fixture asserting that signature-only blocks produce a placeholder
   rather than being skipped.

This is a smaller change but a worse UX — the user gets "Claude thought here" instead of the actual reasoning. Document
it as a workaround pending an Anthropic API change.

## Out of scope

- Adding a model toggle to force Sonnet for thinking visibility — model selection is a separate axis.
- Rewriting the parser around streaming events (the existing JSONL-batch approach is fine; only the source-of-truth file
  changes).
- Touching Gemini/Codex flows.

## Risks

- **Stage 2A risk: streamed `thinking_delta` content also turns out to be empty/encrypted.** Mitigated by Stage 1's
  empirical check before any code changes — if the experiment shows no plaintext, we cut to 2B.
- **Sidecar growth.** Claude thoughts can be large; cap or rotate if files exceed some threshold. The parser's existing
  tail-read for files >500KB (`parser.py:_TAIL_THRESHOLD`) already covers display-side concerns; we just need to not
  blow up disk during long runs.
- **Old transcripts won't gain thinking retroactively.** Acceptable — the panel will start working for _new_ Claude
  runs, matching the user's "going forward" mental model.

## Acceptance criteria

- Running a Claude agent and opening its thinking panel shows non-empty thought text (Stage 2A) or at least one
  placeholder block per actual thought event (Stage 2B).
- The visible source label still reads "CLAUDE THINKING" with the existing purple styling.
- Codex and Gemini panels continue to render identically to before.
- `just check` passes.
