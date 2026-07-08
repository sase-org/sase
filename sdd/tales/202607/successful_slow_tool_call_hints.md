---
create_time: 2026-07-07 20:40:01
status: done
prompt: sdd/prompts/202607/successful_slow_tool_call_hints.md
---
# Plan: `v` Hints for Successful SLOW TOOL CALLS

## Goal

Extend the existing Agents-tab `v` hint flow for SLOW TOOL CALLS so that visible successful tool-call rows (`✔`) get
selectable report hints, just like failed rows already do. Selecting a success-row hint should materialize a Markdown
tool-call report at a deterministic path and route it through the existing pager / editor / clipboard view flow.

This is a follow-up to the failed slow-tool-call report feature. The implementation should preserve that behavior while
removing failure-specific naming and report assumptions where they now apply to any completed reportable tool call.

## Current Shape

- `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py` already receives a `HeaderHintState` in hint mode and
  registers deferred report specs for visible failed rows only:
  - `_is_failed_hint_eligible()` returns `entry.status == "failure"`.
  - `_hint_marker_width()` counts only failed rows.
  - `_register_failed_tool_hint()` inserts `[N]`, maps the hint number to a report path, and stores a
    `SlowToolCallReportSpec`.
- `src/sase/ace/tui/tools/report.py` is structurally useful for success reports, but its public API and Markdown builder
  are failure-specific:
  - `failed_tool_call_report_path()`
  - `write_failed_tool_call_report()`
  - `_build_failed_tool_call_report()`
  - `_recover_failed_tool_call_output()`
  - module/class docs say “failed”.
- `src/sase/ace/tui/actions/hints/_processing.py` materializes deferred tool-call reports after `parse_view_input()`.
  That plumbing is already generic at the state level: selected paths are looked up in `_hint_tool_call_reports` and
  replaced with real generated files before pager/editor/clipboard routing.
- `ToolCallEntry` has the same normalized metadata for successful calls as failed calls: timestamps, runtime/session,
  cwd, permission mode, tool input summary, response summary previews, transcript path, source path, line number, and
  `tool_use_id`.
- The help modal currently describes `v` as `View file/failed-tool hints`, which will become inaccurate once successful
  rows are hinted.

## UX

1. User presses `v` on the Agents tab.
2. Every visible successful (`✔`) or failed (`✘`) SLOW TOOL CALLS row receives a normal numbered `[N]` marker directly
   after the status glyph.
3. Numbering continues from any earlier header hints and composes with file-path, delta, and artifact hints.
4. Successful and failed rows are selectable with the same existing grammar: single numbers, ranges, `@` for editor, and
   `%` for copying generated paths.
5. Running (`⏳`), did-not-complete (`◼`), pending/incomplete, interrupted, and overflow-hidden rows stay unhinted.
   Overflow still points users to the full tools timeline with `]`.

Example hinted rows:

```text
  14:35:02  ✔ [12] Bash          cargo test --workspace           2m 14s
  14:36:10  ✘ [13] Bash          just check                       1m 04s
  14:36:30  ⏳      Bash          pytest tests                     34s ● running
```

Column alignment should stay crisp by computing marker width from all visible report-eligible rows, not just failures.
The normal non-hint render path must stay visually unchanged.

## Technical Design

### 1. Generalize Report API

Update `src/sase/ace/tui/tools/report.py` from “failed report” to “tool-call report” terminology:

- Keep `SlowToolCallReportSpec` as the spec type, but update its docstring to remove “failed”.
- Rename public helpers:
  - `failed_tool_call_report_path()` → `tool_call_report_path()`
  - `write_failed_tool_call_report()` → `write_tool_call_report()`
- Rename private helpers:
  - `_build_failed_tool_call_report()` → `_build_tool_call_report()`
  - `_recover_failed_tool_call_output()` → `_recover_tool_call_output()`
- Update `__all__`, imports, tests, and monkeypatch targets accordingly.

No compatibility alias is needed unless implementation finds external package usage. These helpers were introduced for
the TUI report flow and are imported internally.

### 2. Make Report Content Status-Aware

The report builder should derive title glyph/label from `entry.status`:

- `success` → `# ✔ <tool> - succeeded after <duration>`
- `failure` / `failed` → `# ✘ <tool> - failed after <duration>`
- fallback → a neutral glyph/label for unexpected completed statuses

Keep shared sections:

- Metadata
- Target
- Tool Input
- Recorded Output
- Full Output (transcript)
- Provenance

Handle the error section status-sensibly:

- Failed reports keep `## Error`, including explicit `entry.error` and `tool_response_summary["error"]`, with the
  current fallback text when no explicit error was recorded.
- Successful reports omit `## Error` when no error-like fields exist, so a success report does not say “No explicit
  error recorded.”
- If a successful record unexpectedly carries an error-like field, include `## Error` so the report does not hide data.

Transcript recovery can stay runtime-neutral and keyed by `tool_use_id`; rename it generically and keep the same size
caps, substring pre-filter, JSONL scan, and text-field extraction.

### 3. Broaden Slow-Tool Hint Eligibility

In `_agent_slow_tools.py`:

- Replace `_is_failed_hint_eligible()` with a generic predicate such as `_is_report_hint_eligible()`.
- Make it return true for `entry.status in {"success", "failure"}`.
- Rename `_register_failed_tool_hint()` to `_register_tool_call_report_hint()`.
- Use `tool_call_report_path()` when registering the deferred spec.
- Update `_hint_marker_width()` to count all report-eligible visible rows.

This keeps the hint render cheap: no report writes, no transcript reads, no artifact reads, only in-memory status
checks, counter updates, and deterministic path hashing.

### 4. Keep View Materialization Generic

In `actions/hints/_processing.py`:

- Import and call `write_tool_call_report()`.
- Keep `_materialize_tool_call_reports()` behavior otherwise unchanged: selected report paths are written just before
  view routing; failed writes notify and are dropped; non-report file paths pass through unchanged.
- Update the error notification wording if needed from “failed tool-call report” to “tool-call report”.

No new state field is needed. `_hint_tool_call_reports` already stores the deferred specs for the active hint render.

### 5. Update User-Facing Help Text

Change the Agents help modal entry from:

```text
View file/failed-tool hints
```

to a status-neutral description, for example:

```text
View file/tool-call hints
```

No keymap or `default_config.yml` change is needed.

## Files to Touch

| File                                                         | Change                                                                                      |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/tools/report.py`                           | Generalize naming; status-aware title/error section; generic writer/recovery names          |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py` | Hint both success and failure visible rows; update marker width/counting/registration names |
| `src/sase/ace/tui/actions/hints/_processing.py`              | Use generic `write_tool_call_report()` and neutral notification text                        |
| `src/sase/ace/tui/modals/help_modal/agents_bindings.py`      | Change `v` help text to status-neutral wording                                              |
| `tests/ace/tui/tools/test_report.py`                         | Update helper names; add success report coverage; preserve failure coverage                 |
| `tests/ace/tui/widgets/test_agent_slow_tools.py`             | Update old success-unhinted expectation; add success+failure hint/alignment assertions      |
| `tests/ace/tui/actions/test_view_files_image.py`             | Update import/monkeypatch helper names; optionally assert a success spec materializes       |

## Test Plan

- Report helper tests:
  - success report title uses `✔` / “succeeded” and includes metadata, input JSON, recorded stdout/output previews,
    transcript/provenance, and no empty `## Error` section when no error exists;
  - failure report still renders `✘` / “failed”, error details, recorded output, truncation notes, and provenance;
  - path stability still works with missing `tool_use_id`;
  - writer still overwrites and prunes under tmp `SASE_HOME`;
  - transcript recovery tests pass under the generic helper name.
- Slow-tool rendering tests:
  - visible success and failure rows both receive sequential markers from the shared counter;
  - report specs are stored for both statuses and preserve source label / agent name;
  - running and did-not-complete rows remain unhinted while staying column-aligned with hinted rows;
  - `hint_state=None` normal output remains unchanged.
- View-input tests:
  - generic report writer is called/materialized before pager/editor/clipboard routing;
  - report write failure still drops only that generated report path and notifies.
- Focused verification before the full gate:

```bash
pytest tests/ace/tui/tools/test_report.py \
  tests/ace/tui/widgets/test_agent_slow_tools.py \
  tests/ace/tui/actions/test_view_files_image.py
```

- Because this repo requires it after file changes in the primary repo:

```bash
just install
just check
```

## Risks and Guardrails

- Do not add any disk I/O, transcript scans, JSON parsing, or subprocess work to the hint render path. Successful rows
  may be much more common than failures, so the row render must remain metadata-only.
- Keep the eligibility deliberately narrow to completed `success` and `failure` rows. Extending to interrupted or
  incomplete rows would be a separate UX decision because those reports may need different wording.
- Avoid runtime-specific branches. The report should stay based on normalized `ToolCallEntry` fields.
- Do not touch memory files, generated provider instruction shims, keymap config, or Rust core code for this change.
