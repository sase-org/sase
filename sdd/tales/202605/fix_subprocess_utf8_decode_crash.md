---
create_time: 2026-05-11 11:45:37
status: done
prompt: sdd/prompts/202605/fix_subprocess_utf8_decode_crash.md
---
# Fix: LLM subprocess crash on partial multi-byte UTF-8 across non-blocking reads

## Background

The `refresh_docs.sase.c49b08f97325.update` agent failed mid-run with:

```
Step 'main' failed: LLMInvocationError: Error: 'utf-8' codec can't decode byte 0xe2
in position 0: unexpected end of data
```

The traceback originates in `ClaudeCodeProvider.invoke` → `_run_subprocess` → `stream_and_parse_json_output` →
`stream_json_lines`. No JSON, business, or LLM logic produced this — it's a Python stdlib decode error coming out of the
subprocess stdout pipe.

## Root cause

`src/sase/llm_provider/claude.py:246` opens the Claude CLI subprocess in **text mode**
(`subprocess.Popen(..., text=True)`), so `process.stdout` and `process.stderr` are `TextIOWrapper`s with the default
`'strict'` UTF-8 error handler.

`src/sase/llm_provider/_subprocess_stream.py:18-21` (also `_subprocess_plain.py:80-83`) then flips the underlying file
descriptors to **non-blocking** mode and drives them with a `select` + `readline()` loop.

When the OS has data available but a multi-byte UTF-8 sequence (e.g. `0xe2 0x80 0x94` for an em-dash, or smart quotes —
extremely common in Claude output) lands at the read boundary, the `TextIOWrapper`'s incremental decoder ends a chunk
with a partial sequence in its buffer. On the next read it can end up calling the decoder with `final=True`, which
raises `UnicodeDecodeError: ... unexpected end of data`. That exception escapes the `readline()` call, bypasses the
JSON-decode `try/except` in `_process_json_line` (which only catches `JSONDecodeError`), and propagates all the way up
as `LLMInvocationError`, killing the agent.

This affects every provider that goes through `stream_json_lines` or `stream_process_output`: Claude, Codex, OpenCode,
Qwen, and the "plain" path. The bug is latent and intermittent — it only triggers when a multi-byte glyph happens to
straddle a non-blocking read boundary.

## Proposed fix (Option A2 — minimal blast radius)

Reconfigure the `TextIOWrapper`s with `errors='replace'` inside the two streaming helpers themselves, immediately before
(or alongside) the `os.set_blocking(..., False)` calls. This is a single-line change per stream, in two files, and
covers every caller without touching any `Popen(...)` call site.

A bad partial byte becomes `U+FFFD` rather than an exception. Effects:

- `json.loads` in `_process_json_line` still catches `JSONDecodeError` and drops the malformed line, so corrupted JSON
  events are silently skipped (same behavior as today for any other bad line).
- Worst case is one assistant text block losing a single character to a replacement glyph — the agent run survives
  instead of failing outright.

The existing fix from commit `9639508a` (flipping FDs back to blocking before the final drain) remains in place and
continues to guarantee the final read isn't truncated.

### Why not Option B (binary mode + manual incremental decoder)

Cleaner semantically (no replacement chars ever) but requires changing every `_subprocess_*.py` parser to operate on
`bytes` lines and own a per-stream `codecs.getincrementaldecoder('utf-8')()` state machine. The line-splitting logic,
the `IO[str]` typed `live_reply_file` writes, and several test helpers would all need to migrate. Not worth the surface
area for this fix.

### Why not Option A1 (`errors='replace'` at every Popen call site)

Same net behavior as A2 but touches every provider file. A2 keeps the fix centralized in the streaming helpers that own
the non-blocking switch — the place that _creates_ the hazard.

## Implementation steps

1. **`src/sase/llm_provider/_subprocess_stream.py`** — in `stream_json_lines`, before each
   `os.set_blocking(..., False)`, call `process.stdout.reconfigure(errors='replace')` and
   `process.stderr.reconfigure(errors='replace')`. Guard with the same `if process.stdout:` / `if process.stderr:`
   checks that already exist.

2. **`src/sase/llm_provider/_subprocess_plain.py`** — apply the same `reconfigure(errors='replace')` calls in
   `stream_process_output` next to its `os.set_blocking(..., False)` lines.

3. If both call sites end up identical, factor out a tiny helper `_prepare_nonblocking_text_stream(stream)` in
   `_subprocess_stream.py` (or a small shared module) that does both `reconfigure` + `set_blocking(False)`. Optional —
   only if it improves clarity.

4. **Regression test** under `tests/llm_provider/` (new file `test_subprocess_utf8_decode.py` or appended to
   `test_usage_parsing.py`):
   - Build a fake `subprocess.Popen[str]`-shaped object whose `stdout.readline` raises
     `UnicodeDecodeError("utf-8", b"\xe2", 0, 1, "unexpected end of data")` on its first call and yields a normal JSON
     line on the second.
   - Stub `os.set_blocking`, `select.select`, and the new `reconfigure` call to no-op in
     `sase.llm_provider._subprocess`.
   - Assert: no exception escapes; the second JSON line's assistant text is returned; the failure of the first read is
     swallowed.
   - Bonus: a positive test that asserts `reconfigure('replace')` was called on both stdout and stderr (use
     `MagicMock.assert_called_with(errors='replace')`).

5. **`just install && just check`** in the workspace before reporting back.

## Deliverables

- Edits to `_subprocess_stream.py` and `_subprocess_plain.py` applying `reconfigure(errors='replace')` to each
  TextIOWrapper.
- One new regression test under `tests/llm_provider/`.
- `just check` passes (ruff + mypy + pytest).

## Out of scope

- Migrating any provider to binary-mode reads + manual incremental decoders (Option B).
- Re-running or recovering the already-failed `@refresh_docs.sase.c49b08f97325.update` agent — user can relaunch.
- Auditing every other `Popen(..., text=True)` in the repo outside `llm_provider/` (the panic is specifically the
  non-blocking + text-mode combination, which is unique to the streaming helpers).
