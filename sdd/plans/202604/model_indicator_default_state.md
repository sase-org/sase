---
create_time: 2026-04-29 22:14:44
status: done
prompt: sdd/prompts/202604/model_indicator_default_state.md
---
# Plan: Always-Visible TUI Model Indicator

## Goal

Make the ACE TUI's model indicator always visible so users can see the provider/model that new agents will use, while
making an active temporary override unmistakable at a glance.

## Current State

The TUI already mounts `LLMOverrideIndicator` in the top bar next to the other global indicators. It currently renders
an empty `Text` when there is no active override, and a warm gold badge when `~/.sase/llm_override.json` contains an
active temporary override. The surrounding top bar is compact: tab bar on the left, then task/model/idle/notification
indicators on the right.

That structure is the right place for this information because the model choice affects all new launches across every
tab. The missing piece is a calm default state that remains visible without reading as a warning.

## Product Design

Use one compact top-bar pill with two clearly different states:

```text
 Model CODEX(gpt-5.5)
 Override CODEX(o3) 47m
```

Default state:

- Label: `Model`
- Content: effective configured/autodetected default provider/model for the large tier.
- Tone: subdued cyan/blue text on the normal top-bar surface, or a very low-contrast cyan badge if Rich styling needs a
  filled pill for legibility.
- Purpose: informational, stable, not alarming.

Override state:

- Label: `Override`
- Content: active override provider/model plus remaining duration (`47m`, `1h2m`, or `until cleared`).
- Tone: bold dark text on a warm amber/gold background, keeping the existing high-signal treatment but improving the
  wording so the state cannot be mistaken for the normal default.
- Purpose: high-signal safety cue that new agents will not use the ordinary default.

Long labels should still elide in the middle, preserving the provider prefix and model suffix. The indicator should stay
single-line and compact enough to coexist with task, idle, and notification badges on narrow terminals.

## Technical Approach

1. Update `src/sase/ace/tui/widgets/llm_override_indicator.py`.
   - Rename the user-facing concept from override-only to a model status indicator while keeping the class name unless a
     rename is cheap and low-risk.
   - Split rendering into explicit default and override paths.
   - Continue accepting an injected override in `_build_content()` so tests can exercise active states without disk IO.
   - Resolve the default provider/model only when no active override exists.

2. Resolve the true default carefully.
   - Do not call `resolve_effective_default_provider_model()` for the default-state display after an active override is
     detected, because that helper intentionally returns the override.
   - For the no-override path, it is fine to use `resolve_effective_default_provider_model()` because no override is
     active.
   - If resolution fails, render a compact fallback such as `Model unavailable` rather than breaking the top bar.

3. Preserve refresh behavior.
   - Keep the existing 30-second refresh interval for countdown freshness.
   - Keep the modal dismissal refresh path so set/clear results update immediately.
   - Include the resolved default state in render signatures only if needed; this widget is small enough that a direct
     update every 30 seconds is acceptable.

4. Adjust top-bar styling only if the new default pill needs spacing or alignment changes.
   - Keep the existing mount point in `AceApp.compose()`.
   - Avoid adding footer status: the footer is for conditional keybindings and AXE state.

5. Update tests.
   - Change the inactive test to assert the default model badge instead of empty output.
   - Add/adjust tests for default rendering, active override rendering, active until-cleared rendering, expired override
     fallback to default, label elision, and default-resolution failure fallback.
   - Preserve the mount test and the modal-dismiss refresh tests.

## Verification

Run focused tests first:

```bash
just install
pytest tests/test_llm_override_indicator.py tests/test_temporary_llm_override_phase5.py
```

Then run the repo-required validation:

```bash
just check
```
