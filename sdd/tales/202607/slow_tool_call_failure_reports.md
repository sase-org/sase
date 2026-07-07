---
create_time: 2026-07-07 17:05:39
status: done
prompt: sdd/prompts/202607/slow_tool_call_failure_reports.md
---
# Plan: `v` Hints for Failed SLOW TOOL CALLS (On-the-fly Failure Reports)

## Goal

Extend the `v` (view) keymap on the Agents tab so that failed rows (`✗`) in the SLOW TOOL CALLS section of the agent
metadata panel become selectable hints. Selecting such a hint builds a Markdown "failure report" file on the fly —
containing the tool call's metadata and its recorded failed output — and views it through the existing view flow (pager
/ `$EDITOR` / clipboard), exactly like any other hinted file.

## Current Shape

- SLOW TOOL CALLS rendering lives in
  `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py::append_slow_tool_calls_section()`, called from
  `_agent_display_header.py::build_header_text()`. Failed rows already render a `✗` glyph (`entry.status == "failure"`).
- `build_header_text()` already threads an optional `HeaderHintState` (mutable `hint_counter` + `hint_mappings`) into
  the DELTAS and ARTIFACTS sections, which insert `[N]` markers and register `hint number -> absolute path`. The SLOW
  TOOL CALLS call site does not receive `hint_state` yet.
- Agent `v` flow: `actions/hints/_files.py::_view_agent_files()` → `AgentDetail.update_display_with_hints(agent)` →
  prompt panel `_agent_display_hints.py::update_display_with_hints()` → returns `dict[int, str]` of hint mappings; the
  app stores them and mounts `HintInputBar(mode="view")`. Submission goes to
  `actions/hints/_processing.py::_process_view_input()`, which calls `parse_view_input()` (`src/sase/ace/hints.py`) and
  then views the selected files via pager (`bat`/`cat | less`), editor (`@` suffix), artifact viewer (media), or copies
  paths (`%` suffix). The whole downstream machinery operates on plain file paths — a generated report only needs to _be
  a file_ by the time viewing starts.
- Tool-call data: `ToolCallEntry` (`src/sase/ace/tui/tools/_entry.py`) is an in-memory snapshot of one artifact record
  and already carries everything a report needs: timestamps, duration, runtime, status, `error`, `tool_input_summary`,
  `tool_response_summary` (bounded 512-char previews of stdout/stderr/output/content, per
  `src/sase/llm_provider/_tool_call_common.py`), plus provenance (`source_path`, `line_number`, `artifact_dir`,
  `transcript_path`, `tool_use_id`, `session_id`, `cwd`, `permission_mode`).
- Generated/state files convention: `~/.sase/<subdir>/` via `sase.core.paths.ensure_sase_directory()` (precedent:
  `diffs/`, `chats/`, `commit_state/`).

## Design

### UX (intuitive)

1. User presses `v` on the Agents tab. In the hint render, every _visible failed_ SLOW TOOL CALLS row gains a numbered
   `[N]` marker (standard hint style `bold #FFFF00`), inserted right after the `✗` glyph. Numbering continues the
   panel-wide hint counter, so it composes naturally with DELTAS/ARTIFACTS/file-path hints.
2. User types the number and Enter — or uses the existing `@` (editor) / `%` (copy path) suffixes and ranges. No new
   input grammar, no new keymap, no new modal.
3. The report file is built at that moment and opens in the pager/editor like any other file. Re-selecting the same call
   later rebuilds the report fresh at the same deterministic path.

Scope: hints attach to rows with `entry.status == "failure"` (the `✗` rows), matching the request. The eligibility check
is a single predicate so extending to `interrupted` / "did not complete" rows later is a one-line change. Failed calls
hidden behind the "+ N more" overflow are not hinted (hints select what is visible; the `]` tools timeline remains the
deep-dive surface).

### Visual polish (beautiful)

- Marker placement: `  14:35:02  ✗ [12] Bash          cargo test --workspace   2m 14s`.
- Column alignment is preserved: compute the marker cell width from the largest hint number that will be assigned in
  this section (start counter + failed-row count), and pad non-failed rows with equivalent spaces so tool-name / target
  / duration columns stay crisp across hinted and unhinted rows.
- No change at all to the normal (non-hint) render: `hint_state=None` keeps today's output byte-identical.

### Report file (reliable + beautiful)

New module `src/sase/ace/tui/tools/report.py`:

- `SlowToolCallReportSpec` — frozen dataclass: `entry: ToolCallEntry`, `source_label: str | None`,
  `agent_name: str | None`, `report_path: str`.
- `failed_tool_call_report_path(entry) -> str` — deterministic, I/O-free:
  `~/.sase/tool_call_reports/<tool>-<HHMMSS>-<digest8>.md`, digest over `(source_path, line_number, tool_use_id)`.
  Deterministic paths mean re-views overwrite (always fresh) and never litter temp dirs. `.md` gives syntax highlighting
  in `bat`, editors, and the artifact viewer's Markdown mode.
- `build_failed_tool_call_report(spec) -> str` — pure function (easily unit-tested), Markdown:

  ```markdown
  # ✗ Bash — failed after 2m 14s

  - **Agent**: crs-web--code (chip: `fb1`)
  - **Runtime**: claude · **Session**: <session_id>
  - **Started**: 2026-07-07 14:35:02 · **Completed**: 14:37:16 (local)
  - **Cwd**: /path/to/workspace
  - **Permission mode**: acceptEdits · **Tool use ID**: toolu_abc123

  ## Target

  `cargo test --workspace`

  ## Tool Input

  (pretty-printed JSON of tool_input_summary)

  ## Error

  (entry.error and/or tool_response_summary["error"], fenced)

  ## Recorded Output

  (one fenced block per recorded channel: exit_code, stderr_preview, stdout_preview, output_preview, content_preview —
  verbatim, preserving the writer's "...[truncated N chars]" markers, with a note when truncated)

  ## Full Output (transcript)

  (best-effort recovery — see below — or a one-line "not recovered" note)

  ## Provenance

  - Artifact: <source_path>:<line_number>
  - Transcript: <transcript_path or "unavailable">
  ```

- `write_failed_tool_call_report(spec) -> str | None` — builds content, `mkdir -p` the reports dir
  (`ensure_sase_directory("tool_call_reports")`), atomic write, then prunes the directory to the newest ~50 reports so
  it can never grow unbounded. Returns the path, or `None` on OSError (caller notifies).
- Best-effort full-output recovery (runtime-neutral, per the uniform-runtimes rule — no per-runtime branching): when
  `entry.transcript_path` exists and is under a hard size cap (~16 MB), scan JSONL lines with a cheap substring test for
  `tool_use_id` first, JSON-parse only matching lines, and generically walk the parsed value for a mapping that
  references the same `tool_use_id`, extracting text-ish result fields (`content`/`output`/ `stderr`/`text`). Cap
  extracted output (~64 KB) in the report. Any miss degrades to the "not recovered" note — the report is always complete
  and useful from recorded data alone.

This stays on the Python/TUI side of the Rust core boundary: it is presentation glue over the existing `ace/tui/tools`
artifact reader — no shared domain behavior moves.

### Plumbing (hint render → selection → materialization)

1. `HeaderHintState` (`_agent_display_state.py`) gains `tool_call_reports: dict[str, SlowToolCallReportSpec]` (keyed by
   report path, default empty).
2. `append_slow_tool_calls_section()` gains `hint_state: HeaderHintState | None = None` (passed from
   `build_header_text()`, mirroring DELTAS/ARTIFACTS). For each visible failed row it inserts the `[N]` marker, sets
   `hint_mappings[N] = report_path`, and registers the spec (entry + source label + agent name) in
   `hint_state.tool_call_reports`. Render time does **zero** disk I/O — only string/hash work.
3. Return plumbing: prompt-panel `update_display_with_hints()` and the `AgentDetail` wrapper return a small frozen
   result `AgentHintRender(file_hints: dict[int, str], tool_call_reports: dict[str, SlowToolCallReportSpec])` instead of
   the bare dict (precedent: the ChangeSpec variant already returns a 4-tuple of hint tables). Caller and test updates
   are mechanical.
4. App state: `HintMixinBase` declares `_hint_tool_call_reports: dict[str, SlowToolCallReportSpec]`.
   `_view_agent_files()` stores the fresh table; the ChangeSpec-tab `action_view_files()` resets it to `{}` (mirroring
   how `_hint_mappings` is assigned fresh at each hint-mode entry — note `_remove_hint_input_bar()` runs _before_ input
   processing, so the table must not be cleared there).
5. Materialization: at the top of `_process_view_input()`, after `parse_view_input()` resolves selected files, a new
   `_materialize_tool_call_reports(files)` helper writes any selected paths present in `_hint_tool_call_reports`.
   Failures notify (`severity="error"`) and drop that path from the view list. All three branches
   (pager/editor/clipboard) then proceed unchanged on real files — including `%`, which must copy a path that actually
   exists.

### Performance guardrails (per tui_perf memory)

- Normal render path and cheap j/k header path: untouched (`hint_state is None`; slow tools already render only on the
  full, summary-backed path).
- `v`-press render: pure in-memory work; no report writes.
- Materialization is bounded to the selected hints (typically one call): report body comes from the in-memory
  `ToolCallEntry` snapshot; only the optional transcript scan touches larger files and it is size-capped with a
  substring pre-filter. Pager/editor branches run adjacent to `self.suspend()` where the TUI is already yielded; the
  clipboard branch already runs a synchronous subprocess today, so one small capped write is consistent.

## Files to Touch

| File                                                             | Change                                                                                               |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/tools/report.py` (new)                         | Spec, deterministic path, pure Markdown builder, atomic writer + pruning, capped transcript recovery |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_state.py`  | `HeaderHintState.tool_call_reports` field; `AgentHintRender` result type                             |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py`     | Optional `hint_state` param; `[N]` markers on failed rows; alignment padding; spec registration      |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py` | Pass `hint_state` into `append_slow_tool_calls_section()`                                            |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_hints.py`  | Return `AgentHintRender`                                                                             |
| `src/sase/ace/tui/widgets/agent_detail.py`                       | Wrapper return type update                                                                           |
| `src/sase/ace/tui/actions/hints/_types.py`                       | Declare `_hint_tool_call_reports`                                                                    |
| `src/sase/ace/tui/actions/hints/_files.py`                       | Store/reset the report table in both `v` entry points                                                |
| `src/sase/ace/tui/actions/hints/_processing.py`                  | `_materialize_tool_call_reports()` step in `_process_view_input()`                                   |
| `src/sase/ace/tui/modals/help_modal/agents_bindings.py`          | Document `v` under Agent Actions (≤32-char description, e.g. "View file/failed-tool hints")          |

No new keymap, so no `default_config.yml` change. `v` stays out of the footer (it is unconditionally available on the
Agents tab; the footer only lists conditional keymaps). No CLI surface changes.

## Test Plan

- `tests/ace/tui/tools/test_report.py` (new):
  - builder renders every section for a Bash failure (exit code, stderr preview, error, provenance);
  - minimal entry (no summaries, no tool_use_id) still yields a complete, readable report;
  - writer's truncation markers surface a truncation note;
  - deterministic path stability + digest fallback without `tool_use_id`;
  - write + overwrite + pruning behavior (tmp_path-based `SASE_HOME`);
  - transcript recovery: found, absent id, missing file, oversized file → capped/degraded gracefully.
- `tests/ace/tui/widgets/test_agent_slow_tools.py` (extend):
  - failed rows get sequential `[N]` markers continuing an existing counter; specs registered by path;
  - success / running / did-not-complete rows are unhinted but column-aligned with hinted rows;
  - `hint_state=None` output unchanged (regression guard).
- Agent hints display tests (`tests/ace/tui/widgets/test_agent_display_*`): `update_display_with_hints()` returns report
  mappings alongside regex file hints; mechanical updates for the new return type (including the hint-bar
  duplicate-guard fake).
- View-input processing tests: selected report hints are materialized before pager/editor/clipboard branches; build
  failure drops the path with an error notification; ChangeSpec-tab view flow (empty report table) is a no-op.
- Finish with `just install` (fresh workspace) and `just check`.
