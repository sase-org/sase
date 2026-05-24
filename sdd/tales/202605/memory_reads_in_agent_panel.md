---
create_time: 2026-05-24 13:13:02
status: done
prompt: sdd/prompts/202605/memory_reads_in_agent_panel.md
---
# Surface Audited Memory Reads in the Agents Tab Metadata Panel

## Goal

When an agent calls `sase memory read <path> --reason "..."`, the read is appended to
`~/.sase/projects/<project>/memory_reads.jsonl` (one shared JSONL per project). Today, nothing in the `sase ace` TUI
shows this. This plan adds a beautiful, compact **MEMORY READS** section to the agent metadata panel (the prompt panel
on the Agents tab), so users can see at a glance which long-term memory files the selected agent has consulted and why.

## Why this matters

Memory reads are _audited_ for a reason: they encode the agent's reasoning trail ("I needed to know how generated skills
work because I'm editing the commit hook"). Today that signal is buried in JSONL on disk. Surfacing it in the panel
makes agent behavior legible — a reviewer can verify the agent grounded itself in the right context before changing the
code.

## Where in the UI

The Agents tab right-side detail is composed of:

1. The **prompt panel** (`widgets/prompt_panel/`) — renders the AGENT DETAILS header (Step / Workspace / Model /
   Timestamps / Deltas / Artifacts / STEP METADATA / ERROR), then the prompt body + reply.
2. The **file panel** — current files in flight.
3. The **tools panel** — timeline of tool calls.

Memory reads are conceptually closer to "tool calls" (a timeline of agent actions) than to "step metadata" (intrinsic
step facts). But the _signal density_ is much lower than tool calls (often <10 reads per agent), and reads carry rich
reasoning (the `--reason` string) that benefits from being visible next to other agent context rather than buried in a
secondary panel.

**Decision:** Render as a new compact section inside the prompt panel header, placed **after Artifacts and before STEP
METADATA**. Tight, capped at a few entries, with a "+N more" hint when truncated. No new panel/tab.

## UX design

### Section anatomy

```
MEMORY READS
4 reads · 3 files · last 14:22:08

  14:22:08  long/generated_skills.md          ↩ frontmatter
            ↳ needed commit hook contract for runtime parity refactor
  14:18:51  long/tui_jk_baseline.md
            ↳ verify jk latency budget before touching agent_detail
  14:11:02  long/generated_skills.md
            ↳ confirm CLI/skill sync rule
  + 1 more  (15:11 earliest)
```

- **Section header**: `MEMORY READS` — `bold #D7AF5F underline` (same gold as `AGENT DETAILS` and `STEP METADATA` for
  visual consistency).
- **Summary line** (dim): total reads · distinct paths · "last HH:MM:SS".
- **Per-entry row 1** (one line):
  - Timestamp `HH:MM:SS` in `dim` (matches tools panel).
  - Memory path in `#87D7FF` (light cyan — same as field labels; signals "this is a name worth scanning").
  - Optional trailing marker `↩ frontmatter` in `dim italic` when frontmatter was stripped (lightweight; gives reviewers
    a hint that the file had structured metadata).
- **Per-entry row 2**: the `--reason` string indented under a `↳` glyph (U+21B3), in `#D7D7AF` (the same khaki used for
  tool-call targets). Truncated to ~88 chars (reuse `_append_bounded` semantics).
- **Truncation footer**: when more than `MAX_VISIBLE_READS = 5` rows exist, render `+ N more  (HH:MM earliest)` in
  `dim italic`.

### Empty state

Match the existing "only show if applicable" convention used by `Retries` and `STEP METADATA`: **if the agent has zero
memory reads, the section is not rendered at all.** Avoid a placeholder row — it adds visual noise to every agent that
hasn't read memory.

### Ordering

Most recent first. (Matches how the tools panel reads bottom-up in users' expectations, and surfaces the reasoning trail
leading to the current step.)

### What we deliberately leave out

- **Byte count** — noisy; users care about the _file_ and _why_, not size.
- **Resolved absolute path** — already implied by canonical path.
- **Agent source** (env var vs. agent_meta) — audit-only; not useful for a reader scanning context.
- **Long-form reason expansion** — full text always available via the JSONL. We truncate at ~88 chars; the user can fall
  back to `sase memory ...` queries if they need the audit dump.

### Color/typography rationale

The metadata panel already uses a stable palette: gold for section headers, cyan-bold for labels, dim for timestamps,
khaki for tool-call targets, dim for counts. Reusing those colors means the new section "lands" inside the panel instead
of competing with it. No new colors, no emoji, no boxes — just rhythm and indentation. That is what "beautiful" looks
like in this codebase.

## Data flow

### Filtering events to the selected agent

`memory_reads.jsonl` is project-scoped; multiple agents share it. We need to map each `MemoryReadEvent` to one TUI
`Agent`. Available join keys:

| Field on event  | Field on Agent                 | Reliability                               |
| --------------- | ------------------------------ | ----------------------------------------- |
| `artifacts_dir` | `agent.get_artifacts_dir()`    | Strongest — written by the agent itself   |
| `agent_name`    | `agent.agent_name` / step name | Weaker — collisions when same name reused |

**Strategy:** prefer `artifacts_dir` (exact string match after normalizing with `Path(...).resolve(strict=False)`). Fall
back to `agent_name` only when the event has no `artifacts_dir` (older agents, or agents that set `SASE_AGENT_NAME`
without an artifacts dir).

### Caching

Following the `tools_panel` pattern (`_tools_cache` keyed by agent cache key, invalidated on `mtime_ns` of the artifact
file):

- New cache `_memory_reads_cache: dict[str, _MemoryReadsCacheEntry]` keyed by `(project, agent_cache_key)`.
- Invalidate when `memory_reads.jsonl`'s `mtime_ns` advances.
- Throttle reread to once per `_MIN_REREAD_INTERVAL_S = 0.5`.
- Bound result to `MAX_KEPT_READS = 50` per agent in memory (more than enough for the visible truncation budget).

Because the JSONL is append-only and reading it is cheap (text lines, already parsed by `read_memory_read_events`), no
async worker is needed for the metadata panel — we can compute on the synchronous "summary precompute" path inside
`build_detail_header_summary()`.

### Integration into the existing summary

`DetailHeaderSummary` (the cached enrichment record passed into header rendering) gains one field:

```python
memory_reads: tuple[MemoryReadEvent, ...] = ()
```

`build_detail_header_summary()` populates it via a new helper `load_memory_reads_for_agent(agent)`. Rendering reads the
precomputed tuple, so the j/k hot path stays cheap.

## Implementation plan

### New module: `src/sase/ace/tui/memory_reads.py`

- `load_memory_reads_for_agent(agent: Agent, *, limit: int = MAX_KEPT_READS) -> tuple[MemoryReadEvent, ...]`
  - Resolves project name via `project_memory_name(Path(agent.workspace_dir))` (or current cwd fallback).
  - Calls `read_memory_read_events(project=...)`.
  - Filters by normalized `artifacts_dir` first, then `agent_name` fallback.
  - Returns reverse-chronological tuple capped at `limit`.
- mtime-keyed cache and `_MIN_REREAD_INTERVAL_S` throttle (mirroring `tools_panel`).
- Pure data; no Textual imports.

### Renderer helper: `_agent_memory_reads.py`

Sits next to `_agent_artifacts.py`, `_agent_deltas.py`. Exports:

- `append_agent_memory_reads_section(text: Text, *, events: tuple[MemoryReadEvent, ...]) -> None`
- Constants: `MAX_VISIBLE_READS = 5`, `REASON_LIMIT = 88`, `PATH_LIMIT = 64`.
- Uses the existing `Text.append(..., style=...)` patterns; no new style primitives.

### Wiring in `_agent_display_parts.py`

1. Add `memory_reads: tuple[MemoryReadEvent, ...] = ()` to `DetailHeaderSummary`.
2. Populate in `build_detail_header_summary()` via the loader.
3. In `build_header_text()`, after the existing `append_agent_artifacts_section` block (around line 467) and before the
   STEP METADATA conditional, call `append_agent_memory_reads_section(header_text, events=summary.memory_reads)`.
4. Guard with `if not cheap and summary is not None` (same gate as deltas / artifacts), so the immediate j/k path skips
   it.

### Tests

- **Unit (`tests/ace/tui/test_memory_reads_loader.py`)**:
  - Filter by `artifacts_dir` exact match.
  - Fallback to `agent_name` when `artifacts_dir` is null.
  - Most-recent-first ordering.
  - Cap respected.
  - Empty project (no JSONL file) → empty tuple, no exception.
  - Cache invalidates on mtime change.
- **Rendering (`tests/ace/tui/widgets/test_agent_memory_reads.py`)**:
  - Empty events → section not appended.
  - Single event renders timestamp, path, reason, no truncation footer.
  - > MAX_VISIBLE_READS events → footer present with correct overflow count and earliest timestamp.
  - Long reason truncated to REASON_LIMIT with ellipsis.
  - `frontmatter_stripped=True` adds the `↩ frontmatter` marker.
- **Integration (`tests/ace/tui/widgets/test_prompt_panel_header.py` extension)**: a header snapshot test that includes
  a synthetic JSONL fixture and confirms the MEMORY READS section appears between Artifacts and STEP METADATA.
- **PNG visual snapshot**: extend the existing visual snapshot suite with a fixture agent that has 3 memory reads, so
  the rendered styling is locked.

### Files touched

| File                                                            | Change                                                      |
| --------------------------------------------------------------- | ----------------------------------------------------------- |
| `src/sase/ace/tui/memory_reads.py`                              | NEW — loader + cache                                        |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_memory_reads.py`  | NEW — render helper                                         |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` | Add field to `DetailHeaderSummary`, populate, call renderer |
| `tests/ace/tui/test_memory_reads_loader.py`                     | NEW                                                         |
| `tests/ace/tui/widgets/test_agent_memory_reads.py`              | NEW                                                         |
| `tests/ace/tui/widgets/test_prompt_panel_header.py`             | EXTEND                                                      |
| `tests/ace/tui/visual/...`                                      | EXTEND with one snapshot                                    |

No changes needed to `src/sase/memory/read_log.py` — its read helpers (`read_memory_read_events`,
`filter_memory_read_events`) already support exactly what we need.

## Out of scope (deferred)

- A dedicated full-history panel (like `tools_panel`) for memory reads. Revisit if users start asking to scroll past 5.
- Cross-agent aggregation views (e.g., "which agents read this file?").
- Memory-read entries on workflow root agents that aggregate child reads. Initially each agent shows only its own reads.
- Live-refresh polling — the prompt panel already refreshes when the user navigates; that's enough cadence for an event
  stream this slow.

## Risk register

- **Path-equality fragility on `artifacts_dir`**: agents may write paths with trailing slashes or symlink variants.
  Normalize both sides with `os.path.realpath` before comparing. Tested explicitly.
- **JSONL growth**: project-wide log can accumulate over months. Reading everything per panel refresh is fine at
  thousands of lines, but if a user has a very long-running project (>100k entries) the read becomes noticeable. Cache +
  mtime check makes the steady-state cost zero. Acceptable for v1.
- **Empty `agent_name` collisions**: two agents with the same name in the same project + no artifacts dir would share
  reads. Documented as a fallback limitation; the recommended fix (always set artifacts dir) is already the norm.
