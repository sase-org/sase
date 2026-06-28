---
create_time: 2026-06-28 10:00:36
status: done
prompt: sdd/prompts/202606/model_above_xprompts.md
---
# Plan: Render `Model:` Above `Xprompts:` In Agent Detail Metadata

## Summary

Move the existing `Model:` metadata row in the ACE Agents-tab detail header so it renders immediately after the `Auto:`
row when auto-approval is enabled, and always before the `Xprompts:` section when xprompt metadata is present.

The target top-of-header ordering for agents that have all three fields is:

```text
Auto: ...
Model: ...
Xprompts: ...
```

For agents without auto-approval, the relevant ordering becomes:

```text
Model: ...
Xprompts: ...
```

This is a presentation-only TUI change. It should not change model label formatting, xprompt metadata loading, agent
state, backend behavior, or auto-approval semantics.

## Current State

`build_header_text()` currently renders metadata in this relevant sequence:

1. Identity and ChangeSpec/project/workspace/workflow rows.
2. `Auto:` via `_append_auto_approve_field()`.
3. `Xprompts:` via `append_agent_xprompts_section()` when the full, debounced summary is available.
4. `Model:` via `append_model_field()` when `should_render_agent_detail_model()` allows it.
5. `VCS:` and the remaining metadata rows.

The recent `Auto:` change intentionally made `Auto:` adjacent to `Xprompts:`. This follow-up should insert `Model:`
between them without weakening the performance guarantee that the cheap header path does not read xprompt artifacts.

## Implementation Approach

Update `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py` by relocating the existing model-rendering block
to sit after `_append_auto_approve_field(header_text, agent)` and before the `append_agent_xprompts_section(...)` call.

Keep the existing predicate and formatter:

- Continue using `should_render_agent_detail_model(agent)` so non-agent workflow children still omit `Model:`.
- Continue using `append_model_field(header_text, agent.model, agent.llm_provider, agent.reasoning_effort)` so provider
  colors, model formatting, and reasoning-effort suffixes stay unchanged.
- Do not add any new disk reads or summary work to the cheap path. `Model:` is agent-field-only and can safely render
  before the disk-backed xprompt section in both cheap and full renders.

Leave the xprompt section itself unchanged, including the existing `Xprompts:` label casing and the full-render-only
summary behavior.

## Test Plan

Add focused unit coverage in `tests/ace/tui/widgets/test_agent_display_name_model_metadata.py`:

- Add a case with `approve=True`, a renderable model, and a `DetailHeaderSummary` containing xprompt metadata. Assert
  the order is `Auto:` before `Model:` before `Xprompts:`.
- Add or adjust a case without auto-approval but with both model and xprompt metadata. Assert `Model:` renders before
  `Xprompts:`.
- Preserve existing assertions that non-agent workflow children omit `Model:`.
- Update the existing `test_auto_field_renders_before_xprompts` expectation because there will intentionally be a
  `Model:` row between `Auto:` and `Xprompts:` when the test agent has model metadata. If the test is meant to cover the
  no-model path, make that explicit by using an agent shape where `Model:` is omitted.

Update visual coverage in `tests/ace/tui/visual/test_ace_png_snapshots_agents_interactions.py`:

- Adjust the combined Auto + Xprompts visual fixture so it includes explicit provider/model metadata.
- Assert the exported SVG contains `Auto:`, `Model:`, and `Xprompts:` in that order.
- Regenerate the affected PNG golden(s) only for intentional metadata-order changes.

## Validation

Because this changes repository files, run the normal SASE validation path:

1. `just install`
2. Targeted metadata unit test(s) for agent detail ordering.
3. Targeted visual snapshot test in update mode if the golden changes, then rerun it without update mode.
4. `git diff --check`
5. `just check`

## Risks And Guardrails

- The main risk is accidentally moving model rendering onto the xprompt/full-summary code path. Keep model rendering
  independent of `summary` so cheap header updates continue to show model metadata without artifact reads.
- The second risk is over-updating visual goldens. Only update snapshots whose rendered metadata order actually changes.
- This change stays inside Python/TUI presentation code, so it does not cross the Rust core backend boundary.
