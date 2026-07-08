---
create_time: 2026-07-07 21:12:18
status: done
prompt: sdd/prompts/202607/configurable_slow_tool_threshold.md
---
# Configurable ACE Slow Tool-Call Threshold

## Goal

Make the threshold used by the "SLOW TOOL CALLS" section in the ACE Agents-tab metadata panel configurable from SASE
config, while preserving the current default behavior of 20 seconds.

## Current State

The slow-tool threshold is currently hard-coded as `SLOW_TOOL_CALL_THRESHOLD_MS = 20_000` in the ACE tool-call constants
module.

That constant is used in three visible paths:

- `select_slow_tool_calls(...)` filters which tool calls qualify for the metadata section.
- `append_slow_tool_calls_section(...)` renders the section summary label, currently `>=20s`.
- The Tools timeline formats and styles durations using the same threshold.

The metadata panel has normal-agent and workflow render paths. Both ultimately call
`append_slow_tool_calls_section(...)`, but through different wrappers, so both paths need to receive the configured
threshold.

The Agents-tab metadata render path can repaint repeatedly for pending tool calls. Per the TUI performance guidance, the
implementation should not read config files or rebuild merged config from the render/tick loop.

## Proposed Config Field

Add this field:

```yaml
ace:
  tool_calls:
    slow_threshold_seconds: 20
```

Rationale:

- It is under `ace` because this is ACE TUI presentation behavior.
- It is under `tool_calls` because the threshold defines the ACE tool-call "slow" concept, not just one row of metadata
  text.
- It uses seconds for user-facing config readability, while internal rendering continues using milliseconds.
- The default remains 20 seconds.

Schema behavior:

- Add `ace.tool_calls.slow_threshold_seconds` to `src/sase/config/sase.schema.json`.
- Use an integer with `minimum: 0` and `default: 20`.
- Add the default value to `src/sase/default_config.yml`.

Runtime behavior:

- Load and coerce the value once during ACE late state initialization, alongside other ACE settings.
- Store the derived millisecond value on the app, for example `_slow_tool_call_threshold_ms`.
- Invalid runtime values should fall back to 20 seconds defensively, even though the schema rejects invalid user config.
- Keep `SLOW_TOOL_CALL_THRESHOLD_MS` only as a default/fallback constant, or rename it to clarify that it is the
  default.

## Implementation Plan

1. Add a small parser/helper for the ACE slow-tool threshold.

   Suggested location: near the tool-call helpers, such as `src/sase/ace/tui/tools/slow.py` or a new adjacent config
   helper.

   The helper should:
   - Accept the merged `ace` config mapping or the `ace.tool_calls` submapping.
   - Return threshold milliseconds.
   - Preserve a default of 20,000 ms.
   - Clamp or reject negative/non-numeric values back to the default.

2. Load the threshold once during ACE startup.

   In the existing late state initialization path that already reads `load_merged_config()`, parse
   `ace.tool_calls.slow_threshold_seconds` and store the millisecond value on the app.

   Also initialize the app state default in the earlier state initialization path so tests and partially constructed app
   objects have a stable fallback.

3. Parameterize slow-call selection.

   Change `select_slow_tool_calls(...)` to accept a `threshold_ms` keyword argument with the current default.

   Replace the direct constant comparison with the passed threshold. This keeps the core selection logic testable and
   avoids hidden config reads.

4. Parameterize metadata section rendering.

   Change `append_slow_tool_calls_section(...)` to accept `threshold_ms`, defaulting to 20,000 ms.

   Use that value for both:
   - Selecting slow calls.
   - Rendering the summary label, so a config of 30 seconds displays `>=30s`.

5. Thread the configured value through all metadata render paths.

   Update:
   - `build_header_text(...)`
   - `AgentDisplayRenderMixin._update_display_impl(...)`
   - `AgentDisplayMixin.update_header_only(...)` if needed for signature compatibility, even though cheap headers omit
     slow calls.
   - Workflow rendering via `build_workflow_detail_renderable(...)` and `WorkflowDisplayMixin`.
   - The slow-tool tick refresh path, which should reuse cached tool-call data and the already-loaded app threshold.

   The widgets should read the stored app attribute, not merged config.

6. Keep the Tools timeline consistent.

   Because the timeline currently shares the same slow threshold constant for long-duration formatting and highlighting,
   parameterize `format_duration(...)` / `build_tools_timeline_text(...)` with the same threshold and pass the app value
   from `AgentToolsPanel`.

   This avoids the metadata panel saying one threshold while the full timeline styles a different threshold as slow.

7. Update schema/default tests and targeted TUI tests.

   Add coverage for:
   - `src/sase/default_config.yml` validating against the schema with the new field.
   - Parser defaults and invalid-value fallback.
   - `select_slow_tool_calls(..., threshold_ms=...)` filtering inclusively at the custom threshold.
   - `append_slow_tool_calls_section(..., threshold_ms=...)` rendering the custom summary label and using the custom
     filter.
   - `build_header_text(...)` or an adjacent prompt-panel test proving the configured threshold reaches the metadata
     panel.
   - Workflow render path if not covered by the same helper-level tests.
   - Tools timeline duration styling/formatting with a custom threshold.

8. Run verification.

   After implementation, run:

   ```bash
   just install
   just check
   ```

   If `just check` is too broad for the first iteration, run the targeted tests first:

   ```bash
   pytest tests/test_config_schema.py tests/ace/tui/tools/test_slow_selection.py tests/ace/tui/widgets/test_agent_slow_tools.py tests/ace/tui/widgets/test_prompt_panel_header.py tests/ace/tui/widgets/test_tools_panel_timeline.py
   ```

   Then still run `just check` before finishing, because repo instructions require it after code changes.

## Out of Scope

- Changing the existing slow-tool repaint cadence. The configurable threshold controls which calls qualify and how the
  threshold is displayed; the current cache-backed tick interval remains unchanged to avoid extra render churn.
- Adding live config reload after editing the value in the Config Center. The setting should follow the existing ACE
  startup config-loading behavior unless there is already a local refresh hook that can be reused without broadening
  scope.
- Moving this logic to the Rust core backend. This is ACE presentation behavior, and the shared Rust backend boundary
  does not require a cross-frontend API change for this setting.
