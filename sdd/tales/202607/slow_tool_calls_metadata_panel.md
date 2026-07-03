---
create_time: 2026-07-03 12:19:23
status: wip
prompt: sdd/prompts/202607/slow_tool_calls_metadata_panel.md
---
# Plan: Surface Slow Tool Calls in the Agent Metadata Panel

## Problem & Product Context

The `sase ace` TUI already surfaces every tool call an agent makes in the tools panel (`AgentToolsPanel`, toggled with
`]`). But the tools panel is a full timeline the user must opt into viewing, and it treats a 40-second `Bash` call the
same as a 12ms `Read`. When an agent looks stuck — or when a user is reviewing what a completed agent spent its time on
— the question they actually have is: **"which tool calls were slow?"**

This plan adds a **SLOW TOOL CALLS** section to the agent metadata panel (the prompt-panel header rendered by
`build_header_text()` in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`, which also powers the
metadata zoom modal). It shows:

1. **Live**: any tool call still in a waiting/pending state ("wait" in the tools panel) after 20 seconds, with a ticking
   elapsed time — so users can see at a glance what a running agent is stuck on.
2. **Historical**: every tool call that took ≥ 20 seconds, kept visible after completion — so users reviewing a finished
   agent can see which slow calls it made without opening the full tools timeline.

## Goals

- Intuitive: slow calls appear in the metadata panel users already read, with the same visual language as the existing
  `SASE CONTEXT` section; zero new keybindings to learn.
- Reliable: classification is **stateless** (derived from artifact data on every render), so slow calls survive TUI
  restarts, agent restarts, and cache eviction. A call that was pending ≥ 20s necessarily completes with
  `duration_ms ≥ 20s`, so "keep showing it after it completes" requires no remembered state.
- Beautiful: a compact, aligned lane layout with status glyphs, duration badges, and a summary line — consistent with
  the existing header sections.
- Performant: all disk I/O stays on worker threads; the j/k hot path (`cheap=True` header render) is untouched;
  refreshes route through the existing enrichment fast path.

## Non-Goals

- No configuration knob for the threshold in this iteration. `20s` becomes a single named constant
  (`SLOW_TOOL_CALL_THRESHOLD_MS`) so a config option can be added later.
- No changes to which tool calls the tools panel shows (an optional highlight there is listed as polish).
- No migration of tool-call artifact reading into `sase-core`. The whole tool-call reader stack
  (`src/sase/ace/tui/tools/`) currently lives in this repo's Python layer; the slow-call selection is a thin derivation
  over that existing reader, so splitting just the classifier into Rust would strand it away from its data source.
  If/when the tool-call reader migrates to `sase-core`, the threshold selection should move with it. (Noted per the
  Rust-core boundary rule; this is a deliberate, documented exception.)

## Definition of "Slow"

A tool call is _slow_ when its **effective in-flight duration ≥ 20 seconds**:

| Entry state (after `collapse_tool_use_pairs`)                        | Effective duration                                                                                               | Shown as                                                                       |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Completed (`success` / `failure` / `interrupted`) with `duration_ms` | `duration_ms`                                                                                                    | Frozen duration + final status glyph                                           |
| Completed, `duration_ms` missing                                     | `completed_at − recorded_at` (see below)                                                                         | Same                                                                           |
| Pending, agent still active                                          | `now − recorded_at`, live                                                                                        | "running · Xs" with ticking elapsed                                            |
| Pending, agent terminated (never completed)                          | `end_reference − recorded_at`, where `end_reference` = agent end time when known, else the artifact file's mtime | "did not complete" (no live counter — prevents phantom ever-growing durations) |

Additional rules:

- `SubagentStart` / `SubagentStop` marker rows (status `subagent`) are excluded — they are lifecycle markers, not tool
  calls. Long-running `Task`/agent tool calls still qualify via their normal pending → completed `ToolUse` records.
- Negative computed durations (clock skew between provider timestamps and local time) clamp to 0.
- Data source is the same lineage-aggregated read the tools panel uses (`read_tool_calls_for_agent` across related
  artifact dirs), so retries and follow-ups are covered identically in both surfaces.

To support the `duration_ms`-missing fallback, `ToolCallEntry` gains an optional `completed_at` field captured from the
`ToolResult` row's `recorded_at` inside `_merge_use_and_result()` (non-breaking; defaults to `None`).

## UX Design

A new major section in the metadata panel, rendered after `SASE CONTEXT` and before the `ERROR` section, hidden entirely
when there are no slow calls:

```
──────────────────────────────────────────────────
SLOW TOOL CALLS · ≥20s · 3 calls · 1 running
  14:02:11  ⏳ Bash        just test-cov                     1m 32s ● running
  13:58:40  ✔ Bash         cargo build --release             2m 14s
  13:55:02  ✘ WebFetch     https://example.com/api/v2/...       41s
  + 2 more · press ] for the full tools timeline
```

Visual language (mirrors `_agent_context_common.py` lane rows and tools-panel styling):

- **Section header**: `SLOW TOOL CALLS` in the standard major-section style (`bold #D7AF5F underline`) with a dim
  summary line: threshold, total count, and running count when non-zero.
- **Rows**: `HH:MM:SS` start time (dim) · status glyph · tool name (bold) · compact target
  (`ToolCallEntry.compact_target`, `#D7D7AF`, bounded) · right-aligned duration badge.
- **Status glyphs / colors** reuse the tools-panel status vocabulary: running/pending → `⏳` (`bold #FFD787`), success →
  `✔` (`bold green`), failure → `✘` (`bold red`), interrupted / did-not-complete → `◼` (`bold yellow`).
- **Duration badge**: new shared `format_long_duration()` helper that promotes the tools-panel `_format_duration()` to
  minutes (`92s → "1m 32s"`), styled `bold #FFAF5F` for completed rows and `bold #FFD787 ` + `● running` suffix for live
  rows.
- **Ordering**: still-running calls first (longest elapsed first — the actionable "what is my agent stuck on" rows),
  then completed calls slowest-first.
- **Cap**: `MAX_VISIBLE_SLOW_TOOL_CALLS = 8` rows, then a dim-italic overflow line
  (`+ N more · press ] for the full tools timeline`) — never silently truncated.
- The metadata **zoom modal** (`zoom_panel_modal.py` METADATA target) reuses `AgentPromptPanel`, so the section appears
  there automatically.

No new keymaps, footer entries, or help-modal changes are needed (the section is passive).

## Architecture

### 1. Shared cached tool-call fetch (extract, don't duplicate)

`AgentToolsPanel` currently owns the only cached fetch path (module-level `_tools_cache` with mtime watermarks + 0.5s
worker throttle in `widgets/tools_panel.py`). Extract that into the tools package — e.g.
`src/sase/ace/tui/tools/cache.py` exposing:

- `get_cache_key(agent)` (moved; `widgets/tools_panel.py` and `tui/memory_reads.py` re-import from the new home),
- `fetch_tool_calls_cached(agent) -> tuple[ToolCallEntry, ...] | None` — the body of today's
  `_fetch_tools_in_background()` (artifact-dir discovery cache, mtime watermark, re-read only on change),
- `peek_cached_tool_calls(agent)` — in-memory read with **no disk access**, for the render tick below.

Both the tools panel and the new metadata-section loader consume this one cache, so selecting an agent never reads
`tool_calls.jsonl` twice, and the two surfaces can never disagree.

### 2. Slow-call selection (pure + unit-testable)

New module `src/sase/ace/tui/tools/slow.py`:

- `SLOW_TOOL_CALL_THRESHOLD_MS = 20_000` and `MAX_VISIBLE_SLOW_TOOL_CALLS = 8` constants.
- `select_slow_tool_calls(entries, *, now, agent_is_active, agent_end_reference) -> tuple[SlowToolCall, ...]`
  implementing the semantics table above and the ordering rule. `SlowToolCall` is a small frozen dataclass carrying the
  underlying `ToolCallEntry` plus derived fields (`is_running`, `effective_duration_ms`, `did_not_complete`).

Selection runs **at render time** from candidate entries (all pending entries plus completed entries already ≥
threshold) so a pure re-render — with no worker and no disk — both updates live elapsed labels and admits pending calls
that just crossed 20s.

### 3. Plumbing into the metadata header

Follow the exact `SASE CONTEXT` pattern:

- `DetailHeaderSummary` (`_agent_display_state.py`) gains `slow_tool_candidates: tuple[ToolCallEntry, ...]` (+ the
  agent-activity snapshot needed by selection).
- `build_detail_header_summary()` (`_agent_display_header_summary.py`) populates it via `fetch_tool_calls_cached()` —
  this already runs on a worker thread with a 1s TTL, so no new I/O lands on the event loop.
- New renderer `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py` with
  `append_slow_tool_calls_section(text, *, candidates, agent, now)` reusing `_agent_context_common.py` helpers for
  alignment/truncation.
- `build_header_text()` calls it on the full path only (`not cheap and summary is not None`), preserving the one-frame
  j/k render guarantee.

### 4. Freshness: making the 20s crossing appear live

Two update paths, matched to how the data actually changes:

- **New/completed rows** append lines to `tool_calls.jsonl`, which the existing artifact watcher + auto-refresh already
  turn into `update_display` → header enrichment (1s TTL). No new machinery.
- **A pending call crossing 20s produces no filesystem event.** Add a coarse selected-agent-only render tick in the
  prompt panel: a ~5s Textual timer that is armed only while (a) the selected entry is an agent, (b)
  `peek_cached_tool_calls()` shows at least one pending call, and (c) the navigation gate is idle. The tick re-renders
  the header from the cached summary and cached entries — pure in-memory Rich Text rebuild, no disk, no worker — which
  both surfaces newly-crossed calls and advances the `● running` elapsed labels. The timer is cancelled on selection
  change and unmount, and never outlives pending calls (it disarms itself when none remain).

This honors the TUI perf memory: no event-loop blocking work, no new disk-refresh path, debounced detail updates, and
selective (header-only) repaints.

### 5. Optional polish (small, include if cheap)

- In the tools panel timeline, render duration badges ≥ threshold in the same `bold #FFAF5F` accent so slow calls pop in
  both surfaces.
- Include the SLOW TOOL CALLS section in the header's markdown/export representation used by editor actions, mirroring
  how other sections export.

## File-Level Change Map

| File                                                                     | Change                                                           |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| `src/sase/ace/tui/tools/_entry.py`                                       | Add optional `completed_at` field                                |
| `src/sase/ace/tui/tools/_parser.py`                                      | Capture `completed_at` in `_merge_use_and_result`                |
| `src/sase/ace/tui/tools/_constants.py`                                   | Add threshold + visible-cap constants                            |
| `src/sase/ace/tui/tools/cache.py` (new)                                  | Shared cached fetch extracted from `tools_panel.py`              |
| `src/sase/ace/tui/tools/slow.py` (new)                                   | `SlowToolCall`, `select_slow_tool_calls`, `format_long_duration` |
| `src/sase/ace/tui/widgets/tools_panel.py`                                | Consume shared cache; optional slow-duration accent              |
| `src/sase/ace/tui/memory_reads.py`                                       | Update `get_cache_key` import to new home                        |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_state.py`          | Extend `DetailHeaderSummary`                                     |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header_summary.py` | Populate candidates in worker build                              |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py` (new)       | Section renderer                                                 |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`         | Render section (full path only)                                  |
| Prompt panel / `AgentDetail` display module                              | Arm/disarm the pending-call render tick                          |

## Testing

- **Unit — selection** (`tests/ace/tui/tools/test_slow_selection.py`): pending crossing the threshold; completed just
  under/over; missing `duration_ms` with `completed_at` fallback; pending + terminated agent ("did not complete",
  end-reference math); subagent-marker exclusion; clock-skew clamping; ordering (running-first, then slowest-first);
  cap + overflow counts.
- **Unit — renderer** (`tests/ace/tui/widgets/test_agent_slow_tools.py`, mirroring `test_agent_context.py` /
  `test_agent_skill_uses.py`): empty → renders nothing; summary line contents; running badge; overflow line; truncation
  bounds.
- **Header integration** (`test_prompt_panel_header.py` additions): section appears on the full path with a populated
  summary and is absent on the `cheap=True` path.
- **Cache extraction**: existing `tests/ace/tui/tools/` reader tests keep passing; add a test that the tools panel and
  header loader share one cache entry (single read per mtime).
- **Tick behavior**: with a frozen cached pending entry, advancing time past the threshold and firing the tick makes the
  section appear without any new artifact writes; tick disarms when no pending calls remain and on selection change.
- **PNG visual snapshots**: new golden(s) — metadata panel with a mixed running/completed/did-not-complete slow section
  (e.g. `agents_slow_tools_metadata_120x40.png`), accepted via `--sase-update-visual-snapshots`. Audit existing fixtures
  first: any fixture with a ≥ 20s `duration_ms` will now grow a new header section, so affected goldens (e.g. metadata
  zoom modal, tools panel scenes) must be reviewed and intentionally re-accepted.
- Full `just check` before completion.

## Risks & Mitigations

- **Fixture/golden churn**: existing visual fixtures may contain ≥ 20s durations → explicit golden audit step above.
- **Header length growth** for tool-heavy agents → hard cap at 8 rows + overflow line.
- **Timer leakage / event-loop pressure** → single coarse timer, selected-agent-only, in-memory work, cancelled on
  selection change/unmount, gated on the navigation gate.
- **`get_cache_key` relocation** breaking imports → keep a re-export at the old `tools_panel` location during the
  change.
