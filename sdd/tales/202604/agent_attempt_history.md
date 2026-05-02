---
create_time: 2026-04-22 15:53:20
status: wip
prompt: sdd/prompts/202604/agent_attempt_history.md
---

# Plan: Preserve and Display Prior Agent Attempts Across Retries

## Goal

When the axe retry loop retries an agent (context-overflow retry, user-configured retries, or fallback-model switch),
preserve each failed attempt's artifacts (partial reply, error, timestamps, model used) and surface them in the
`sase ace` Agents tab so the user can see the full history of what the agent tried, not just the final attempt.

The feature should be intuitive, reliable (durable on disk and backwards-compatible), and beautiful (reusing existing
divider/color idioms so it feels native).

## Context and Diagnosis

Today, when a retry happens:

1. `live_reply.md` is opened with `"w"` mode in `src/sase/llm_provider/_subprocess.py:43` — truncated on every fresh
   subprocess invocation. Same for `live_reply_timestamps.jsonl` (line 52).
2. `retry_state.json` is transient. It's overwritten on each retry and deleted in `_finalize_loop`
   (`src/sase/axe/run_agent_exec.py:99`).
3. `RetryTracker.retry_errors` captures only a 100-char snippet per attempt, saved into `done.json` as `retry_errors`.
   The full error text and the partial reply are lost.
4. The TUI's `AgentPromptPanel` only renders the _current_ / _final_ attempt's prompt and reply.

Net effect: users can see `Retries: 2/3` in the header, but not what each attempt produced or exactly why it failed.
With the recent changes (`08845c64` preserving workspace on Claude context-overflow retry, `56f50fdd` letting retries
fire across phase transitions), retried attempts now represent real, carried-forward work — losing the prior partial
replies is a meaningful visibility gap.

## Product Decisions

1. **Preserve every _failed_ attempt's artifacts on disk; the root dir continues to represent "current / final
   attempt".**
   - Snapshots are written for attempts that ended with a retryable error, a fallback-triggering error, or the final
     raised error. The successful (or killed) final attempt lives at the artifacts-dir root as today — no duplication.
   - This invariant (`root == current / final`) keeps all existing TUI and CLI consumers working unchanged.

2. **Chronological merged view by default; collapsible to current-only.**
   - When prior attempts exist, the Agent Detail prompt panel renders them in order with styled dividers, ending with
     the current/final attempt. One scroll shows the whole arc.
   - A keymap (`H`, conditional on prior attempts existing) cycles between two modes: `merged` (default) and
     `current-only` (today's behavior).
   - For agents that never retried, the view is byte-identical to today — zero visual regression for the common case.

3. **Header shows compact per-attempt summary.**
   - The existing `Retries: N/M` line in `build_header_text` grows dim sub-lines listing each attempt's start time and
     failure reason, plus which one used the fallback model. Keeps the at-a-glance reading fast while making the
     detailed reply content one scroll away.

4. **Retries and fallback transitions are unified under one "attempt" concept.**
   - A fallback-model switch is treated as a continuation (attempt N+1 with `used_fallback=true`), not a fresh counter
     reset. This matches how `RetryTracker.retry_count` is used today.

5. **Zero changes to retry _decision_ logic.** `handle_workflow_error` keeps its current branching (retry / fallback /
   raise). The snapshot step is added at the three outbound paths; nothing about when-to-retry is touched.

6. **Backwards-compatible.** No migration. Agents without an `attempts/` subdirectory render identically to today. The
   existing `retry_errors` list in `done.json` is retained as a lightweight summary (useful for CLI and telemetry); the
   new `attempts/<N>/attempt_meta.json` records are the rich source.

## Technical Design

### 1) Storage model: per-attempt subdirectory under the step's artifacts dir

```
<artifacts_dir>/
  attempts/
    01/
      live_reply.md                  # moved from root at snapshot time
      live_reply_timestamps.jsonl    # moved from root at snapshot time
      attempt_meta.json              # new per-attempt record (see below)
    02/
      ...
  live_reply.md                      # CURRENT attempt (or final, after loop ends)
  live_reply_timestamps.jsonl
  retry_state.json                   # transient, unchanged
  done.json                          # unchanged
```

`attempt_meta.json` fields:

```
attempt_number: int            # 1-indexed
status: "failed" | "raised"    # "failed" = retry consumed; "raised" = final raise
start_epoch: float             # tracker-owned; for attempt 1, set at loop entry
end_epoch: float               # set at snapshot time
model: str | None              # model active when attempt ran
used_fallback: bool
error_snippet: str             # matches current truncated snippet
error_full: str                # full str(exc) (may include traceback)
```

Multi-step workflow note: the `attempts/` directory lives under whichever artifacts dir owns the current
`SASE_ARTIFACTS_DIR` (i.e., `state.current_artifacts_dir`). Each workflow step keeps its own attempt history. Retries
are inherently per-step; this matches the mental model.

Atomicity: write a new attempt via `attempts/<N>.tmp/` then `os.rename` to `attempts/<N>/` so a crash mid-snapshot
leaves no half-state.

### 2) Capture logic (axe side)

Add
`snapshot_attempt(artifacts_dir, attempt_number, *, status, start_epoch, end_epoch, error_full, error_snippet, model, used_fallback)`
— either in `src/sase/axe/run_agent_exec_retry.py` or a new `src/sase/axe/run_agent_exec_attempts.py` (prefer the latter
if the retry file is already large; decide during implementation).

Behavior:

- `mkdir -p attempts/<N>.tmp`, move (not copy) the root `live_reply.md` and `live_reply_timestamps.jsonl` into it (if
  they exist; missing files handled gracefully), write `attempt_meta.json`, then rename `.tmp` → final.
- Truncate root `live_reply.md` and `live_reply_timestamps.jsonl` to empty after the move, so attempt N+1 streams into a
  clean file from the first byte.

Call sites in `handle_workflow_error`:

- **Retry branch** (before `RetryState(status="retrying").write_to(...)`): snapshot the just-failed attempt as
  `status="failed"`.
- **Fallback branch**: same — snapshot as `status="failed"` (even though it's the boundary into fallback; the attempt
  itself failed on the primary model).
- **Raise branch** (before re-raising, i.e., the `return "raise"` path after `retry_errors.append`): snapshot as
  `status="raised"`. This ensures every failed attempt has a record; the final raised attempt is then available as an
  attempts/ entry _even though_ the root `live_reply.md` may also hold the same content (acceptable — the UI
  de-duplicates at render by treating the last attempts/<N>/ with `status="raised"` as _the_ final attempt and skipping
  the root rendering for that case).

`RetryTracker` gains:

- `attempt_start_epoch: float` — set at `run_execution_loop` entry to `time.time()`; reset to `time.time()` right before
  each `return "continue"` so attempt N+1's start time is accurate.
- `attempt_number` is not stored separately; it's `retry_count + 1` at the moment of snapshot (before increment).

Edge cases:

- **Killed mid-attempt**: `handle_workflow_error` is never called. Root `live_reply.md` stays as-is and
  `done.json.outcome=="killed"` covers the label. No snapshot. The TUI simply renders what's at the root.
- **Non-retryable exception** (falls through `is_retryable_error` returning false): `return "raise"` without snapshot.
  No attempts/ entry is created for this case either — there was only one attempt, and it's at the root. The TUI renders
  identically to today.
- **Retry succeeds on attempt N+1**: attempts/01..N/ contain failed records. Attempt N+1 is at the root (successful).
  `done.json.retry_count == N` makes it unambiguous that the root is "attempt N+1".

### 3) TUI data model

`src/sase/ace/tui/models/agent.py`:

- New frozen dataclass `AttemptRecord` mirroring `attempt_meta.json` plus resolved `live_reply_path` and
  `timestamps_path`. Add `get_reply_content()` and `get_timestamped_reply_chunks()` methods that mirror the Agent- level
  artifact helpers.
- New field on `Agent`: `attempt_history: list[AttemptRecord] = field(default_factory=list)`.

`src/sase/ace/tui/models/agent_artifacts.py`:

- New `load_attempt_history(artifacts_dir) -> list[AttemptRecord]` — scans `attempts/`, reads each `attempt_meta.json`,
  sorts by `attempt_number`. Tolerates missing dir, missing/malformed meta (skips entry; logs nothing — silent tolerance
  matches `RetryState.read_from` style).

`src/sase/ace/tui/actions/agents/_loading_helpers.py`:

- After the `RetryState` load around lines 132–152, call `load_attempt_history` and assign to `agent.attempt_history`.
  This runs on every TUI refresh, so retried-but-still-running agents get new entries as the snapshot appears on disk.

### 4) TUI rendering

`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`:

- New `render_attempt_divider(attempt: AttemptRecord | None, is_current: bool) -> Text` — reuses the visual language of
  `render_phase_divider` (`───`-bracketed labels with a trailing timestamp). Failed attempts in `#FF8700` (orange,
  matches existing retry-count color); fallback label appends `via fallback → <model>`; current/final attempt uses
  `#AF87FF`. Error snippet for failed attempts is rendered below the divider in dim italic before the reply content.
- Upgrade `build_header_text`'s retry section (currently lines 259–270): when `agent.attempt_history` is non-empty, add
  indented dim sub-lines — one per attempt — `  Attempt N · HH:MM:SS · failed: <snippet>` (or `current`).

`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`:

- New helper `render_merged_attempt_history(agent) -> list[Text | Syntax]` — iterates `attempt_history` emitting a
  divider then the attempt's reply content (via `get_timestamped_reply_chunks` → `get_reply_content` fallback chain,
  mirroring `render_agent_reply_content`). Appends the current-attempt divider + the existing
  `render_agent_reply_content(agent)` output.
- Gate: only called when `attempt_history` is non-empty _and_ `agent.attempt_view_mode == "merged"` (see
  `agent_detail.py` below). Otherwise falls through to current `render_agent_reply_content` behavior.

`src/sase/ace/tui/widgets/agent_detail.py`:

- New `attempt_view_mode` reactive/instance field (default `"merged"`). Add `action_toggle_attempt_view` that cycles
  `merged` ↔ `current-only`, triggers a re-render.
- New `H` binding on `AgentDetail` (or bubbled up from the prompt panel). Confirm `H` is not already taken; worst case
  use another available letter. Lowercase `h` is preserved for its current use.

`src/sase/ace/tui/widgets/keybinding_footer.py`:

- Add a conditional entry `<H> attempt view` that appears only when the currently-selected agent has `attempt_history`.
  Honors the alphabetical / symbol-first ordering rule from `src/sase/ace/AGENTS.md`.

`src/sase/ace/tui/widgets/help_modal.py`:

- Document `H` in the Agent Detail section. Keep the 57-char box width invariant.

### 5) Config

If the `H` binding is owned by `src/sase/default_config.yml` (per the gotcha in `memory/short/gotchas.md` — changing
keymaps requires updating that file), add the entry in the appropriate section. If `agent_detail.py` binds it directly
as a Textual `BINDING`, no config change is needed.

## Open Questions (resolve before implementation)

1. **Root `live_reply.md` after a final raise**: After snapshotting attempt N as `status="raised"`, should we (a) leave
   the root `live_reply.md` intact so the default view still shows the failure content, or (b) clear the root so the TUI
   falls back to the chat/response path?
   - Current lean: **(a)** — simpler, and the default view keeps showing failure content as users expect.
   - Implication for the de-dup rule in §2 "Raise branch": when rendering, if the last attempts/<N>/ has
     `status="raised"` and its content matches the root, we render it once (as the current/final attempt in the divider
     sequence), not twice.

2. **`H` keymap availability**: confirm `H` is not bound elsewhere in the agents tab before committing. If taken,
   candidates (in order of preference): `V` (attempt view), `A` (attempts), `T` (timeline).

3. **`attempts/` location in multi-step workflows**: per-step (my recommendation) vs. root. Going per-step means a
   failed-then-retried planner and a failed-then-retried coder each have their own attempts/ subdirectory under their
   step's artifacts dir. This matches per-step `retry_state.json` semantics.

## Test Plan

1. `tests/axe/test_run_agent_exec_retry_attempts.py`:
   - `snapshot_attempt` happy path — files moved, meta written, root cleared, `.tmp` renamed.
   - Missing source files — does not crash, meta still written.
   - Idempotent against re-call with the same N (should not double-write; second call is a no-op).

2. `tests/axe/test_run_agent_exec_attempts_integration.py`:
   - Patch `execute_workflow` to raise a retryable error on the first call and succeed on the second; verify
     `attempts/01/` exists with correct `attempt_meta.json`, root has the successful attempt's artifacts.
   - Exhausted-retry case: raise on every call; verify `attempts/01/`, `attempts/02/`, ...
     `attempts/<max>/attempt_meta.json.status == "raised"`.
   - Fallback case: verify the attempt that triggered fallback has `used_fallback=false` on the _snapshot_ (it was the
     primary model that failed), and the subsequent attempt's snapshot (if it also fails) has `used_fallback=true`.

3. `tests/ace/tui/test_attempt_history_loader.py`:
   - Reads a well-formed `attempts/` tree.
   - Handles missing `attempts/` dir (returns empty list).
   - Skips malformed `attempt_meta.json` entries silently.
   - Sorts by `attempt_number` even if the filesystem returns names out of order.

4. `tests/ace/tui/test_agent_display_attempts.py`:
   - Agent with 3 attempts (2 failed + 1 current) renders with two divider blocks plus the live content.
   - Header sub-lines are present and reflect each attempt's timestamp and failure reason.
   - `attempt_view_mode="current-only"` renders identically to today (no dividers, no extra content).
   - Agent with empty `attempt_history` renders byte-identical to today (backwards-compat guard test).

5. Conditional-footer test: `<H> attempt view` appears only when `attempt_history` is non-empty.

## Files Expected To Change

- `src/sase/axe/run_agent_exec_retry.py` (or new `src/sase/axe/run_agent_exec_attempts.py`) — `snapshot_attempt` helper,
  three call sites, extend `RetryTracker` with `attempt_start_epoch`.
- `src/sase/axe/run_agent_exec.py` — initialize `RetryTracker.attempt_start_epoch` at loop entry; no other changes.
- `src/sase/ace/tui/models/agent.py` — add `AttemptRecord` dataclass and `attempt_history` field.
- `src/sase/ace/tui/models/agent_artifacts.py` — add `load_attempt_history`.
- `src/sase/ace/tui/actions/agents/_loading_helpers.py` — call `load_attempt_history` after `RetryState` load.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` — `render_attempt_divider`, upgrade retry header
  section.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` — `render_merged_attempt_history` orchestration.
- `src/sase/ace/tui/widgets/agent_detail.py` — `attempt_view_mode` state and `H` binding.
- `src/sase/ace/tui/widgets/keybinding_footer.py` — conditional `<H> attempt view` entry.
- `src/sase/ace/tui/widgets/help_modal.py` — document `H` toggle.
- `src/sase/default_config.yml` — only if `H` is owned via config-level keymaps.
- Tests as enumerated above.

## Validation

- Targeted unit tests for each module above.
- Manual TUI smoke test: trigger a context-overflow retry against Claude (e.g., stuff a prompt or use a small-context
  model override), confirm the attempts/ dir fills, and the merged view renders with dividers; toggle `H` and confirm
  collapse.
- `just check` per `memory/short/build_and_run.md`. Run `just install` first if this is a fresh ephemeral workspace.

## Expected Outcome

A user whose Claude coder hits two context-overflow retries before succeeding sees, in the Agents tab:

- An agent detail view that unfolds into three clearly-labeled sections (Attempt 1, Attempt 2, Attempt 3 current) with
  colored dividers — one scroll showing the full arc of the agent's work.
- A header showing `Retries: 2/3` with three indented sub-lines listing each attempt's time and outcome.
- Press `H` to collapse to today's single-final-attempt view if they want a clean reading pane.
- All prior partial replies are preserved on disk under `<artifacts_dir>/attempts/` and survive TUI restart.

Agents that never retry render identically to today — zero regression risk for the common case.
