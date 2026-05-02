---
create_time: 2026-04-30 10:55:11
status: done
prompt: sdd/prompts/202604/full_model_indicator.md
---
# Stop Truncating the Ace Model Indicator

## Context

The `sase ace` top bar model indicator is rendered by `LLMOverrideIndicator` in
`src/sase/ace/tui/widgets/llm_override_indicator.py` and mounted between the task indicator and idle/notification
indicators in `src/sase/ace/tui/app.py`.

The current default-state output is shaped as:

```text
 Model PROVIDER(model)
```

The snapshot shows `Model GEMINI(gemi...h-preview)`, which comes from the widget's `_elide_middle()` call with a 24-cell
cap. This is an intentional local truncation, not a provider or Textual layout side effect.

## Goal

Render the new top-bar model indicator without:

- middle-truncating the provider/model label;
- the `"Model "` prefix in the default model indicator.

The display should preserve the useful provider/model shape, for example:

```text
 GEMINI(gemini-3-flash-preview)
```

For a temporary override, keep the explicit override signal and duration because that state has different semantics:

```text
 Override CODEX(o3) 1h2m
```

## Implementation Plan

1. Remove default-model truncation from `LLMOverrideIndicator`.
   - Stop passing the default provider/model label through `_elide_middle()`.
   - Remove the `label_max_width` path from default rendering if it becomes default-only dead API.
   - Render default content as `" {label} "` instead of `" Model {label} "`.

2. Decide how to treat the temporary override path conservatively.
   - Keep the `"Override "` prefix, because it differentiates a temporary override from the normal effective default
     model and carries expiry context.
   - Remove local truncation there too unless existing layout constraints require it; the user's request says "this
     indicator" and the helper is shared by default and override rendering.

3. Simplify or remove `_LABEL_MAX_WIDTH` and `_elide_middle()` if no longer used.
   - Prefer deleting unused truncation code over keeping a misleading helper.
   - Update tests accordingly.

4. Update focused tests in `tests/test_llm_override_indicator.py`.
   - Default model renders as `" CODEX(gpt-5.5) "`.
   - Expired override and state-file cleanup fallback render without `"Model "`.
   - Long labels render fully, not elided.
   - Resolution failure fallback should be concise and prefix-free, likely `" unavailable "`.
   - Remove tests that only validate obsolete elision behavior.

5. Verify narrowly first, then run the repository check command.
   - Run `pytest tests/test_llm_override_indicator.py`.
   - Because this repo's memory says changed work should finish with `just check`, run `just install` first if needed,
     then `just check`.

## Risks and Notes

- A very long custom model can consume more of the top bar. That is the requested tradeoff for accuracy. Textual will
  still allocate the tab bar as `1fr` and the indicator widgets as `auto`; if the model is extremely long, top-bar
  crowding can still happen at small terminal widths.
- The fallback word `"unavailable"` is kept so failures remain visible without implying a concrete model.
