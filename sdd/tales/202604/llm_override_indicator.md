---
create_time: 2026-04-29 18:59:52
status: done
prompt: sdd/prompts/202604/llm_override_indicator.md
---
# Plan: Active LLM Override Indicator

## Goal

Make an active temporary LLM provider/model override immediately visible in the ACE TUI, without making the interface
noisy when no override is active.

## Product Design

The best placement is the existing top bar, next to the backend/task/idle/notification indicators. The override is
global TUI state that affects every new agent launch, so it should be visible on every tab and not tied to the currently
selected row. I will add a compact pill that appears only while an override is active:

```text
 LLM: codex/o3 47m
```

Visual treatment:

- Active override: dark text on warm magenta/gold accent, distinct from AXE green/red and notification gold/orange.
- No override: empty content, preserving the uncluttered top bar.
- No-expiry override: render `until cleared` instead of a countdown.
- Long provider/model labels: elide the middle of the label so the top bar remains stable on narrow terminals.
- Expired or malformed state: rely on `get_active_temporary_override()` cleanup and render nothing.

This should feel like a high-signal safety badge: visible enough to prevent accidental launches on the wrong model, but
compact enough that ACE still reads as a work surface rather than a warning banner.

## Technical Approach

1. Add a new `LLMOverrideIndicator` widget under `src/sase/ace/tui/widgets/`.
   - It will read `get_active_temporary_override()`.
   - It will format provider/model via `format_provider_model_label()`.
   - It will compute remaining time from `expires_at`.
   - It will expose `refresh()` and pure helpers for testable rendering.

2. Mount it in `AceApp.compose()` in the top bar.
   - Place it after `BackendIndicator` and before idle/notifications, so model state sits with other global system
     state.
   - Add TCSS sizing similar to other top-bar indicators.
   - Export it from `widgets/__init__.py`.

3. Keep it fresh.
   - On mount, refresh once and set a low-cost interval while the app is running.
   - The interval can tick every 30 seconds; the displayed minutes do not need second-level precision.
   - After the temporary override modal dismisses with `set` or `cleared`, refresh the indicator immediately so feedback
     is instant.

4. Preserve footer behavior.
   - Keep the existing leader-mode `temporary model` binding.
   - Do not overload the keybinding footer with persistent status; the footer is already optimized for contextual
     actions and AXE state.

5. Tests.
   - Unit-test the indicator render states: inactive, active with expiry, active until cleared, expired cleanup, and
     long-label elision.
   - Add an ACE page mount test confirming the widget exists in the top bar.
   - Add a modal-dismiss callback test or narrow integration test proving set/clear results trigger an immediate
     refresh.

## Verification

Run focused tests first:

```bash
just install
pytest tests/test_llm_override_indicator.py tests/test_temporary_llm_override_phase5.py
```

Then run the repo-required validation after edits:

```bash
just check
```
