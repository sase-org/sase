---
create_time: 2026-04-29 13:40:57
status: done
prompt: sdd/prompts/202604/tui_backend_indicator.md
---
# TUI Backend Indicator Plan

## Goal

Make the ace TUI visibly show which `sase.core` backend mode it is running under, so a user can tell at a glance whether
the TUI is on the default Python path, the opt-in Rust path, or dual-run comparison mode.

## Current State

- Backend selection is centralized in `src/sase/core/backend.py`.
- `SASE_CORE_BACKEND` accepts `python` or `rust`, defaulting to Python.
- `SASE_CORE_BACKEND=rust` is a hybrid per-operation mode: Rust-backed facade operations use `sase_core_rs`, while
  intentionally unported facade operations fall back to Python.
- `SASE_CORE_DUAL_RUN=1` runs both implementations for Rust-backed operations but returns Python results, so the UI
  should represent it as a dual/comparison mode rather than simply "Rust".
- The ace TUI has a persistent one-line top bar in `src/sase/ace/tui/app.py` with `TabBar`, `TaskIndicator`,
  `InactiveIndicator`, and `NotificationIndicator`.
- The footer status area already carries AXE/background-command state and is updated frequently; overloading it with
  core backend state would make two unrelated statuses compete.

## Proposed User Experience

Add a compact persistent badge to the top bar, near the other global indicators:

- Default: `backend: Python`
- Rust mode: `backend: Rust`
- Dual-run enabled: `backend: Python+Rust dual`

This keeps the signal visible on every tab without changing list/detail layouts. The text should be plain enough to be
unambiguous, and styled as a small badge so it reads as environment/runtime state rather than an action.

## Implementation Plan

1. Add a small backend-display helper in `src/sase/core/backend.py`.
   - Keep backend semantics centralized next to `get_active_backend()` and `is_dual_run_enabled()`.
   - Return a display object or simple label/style tuple that distinguishes Python, Rust, and dual-run modes.
   - Avoid probing Rust availability in the steady-state display path unless needed; the selected backend env var and
     dual-run env var are the source of truth for the requested TUI mode.

2. Add a `BackendIndicator` widget under `src/sase/ace/tui/widgets/`.
   - Build a `rich.text.Text` badge from the helper.
   - Keep it static after construction because backend env vars should not change during a running TUI session.
   - Export it through `src/sase/ace/tui/widgets/__init__.py`.

3. Mount the widget in `AceApp.compose()`.
   - Place it in `#top-bar` after `TaskIndicator` and before idle/notification indicators, or adjacent to the right-side
     global indicators.
   - This makes the backend visible across ChangeSpecs, Agents, and AXE views without touching per-tab content.

4. Add CSS in `src/sase/ace/tui/styles.tcss`.
   - Give `#backend-indicator` `width: auto` and `content-align: right middle`, matching the existing top-bar indicator
     widgets.
   - Do not alter global layout dimensions beyond the single top-bar cell allocation.

5. Add focused tests.
   - Unit-test the backend display helper for default Python, explicit Rust, and dual-run mode.
   - Unit-test the widget text so it renders the expected words for relevant env combinations.
   - If existing app composition tests make this cheap, add a smoke assertion that `#backend-indicator` is mounted.

6. Verify.
   - Run the focused tests first: likely `pytest tests/test_core_backend.py tests/ace/tui/widgets/...`.
   - Because this repo requires it after file changes, run `just install` if needed and then `just check` before the
     final response.

## Risks and Tradeoffs

- A single "Rust" label can be misleading because Rust mode is per-operation and not all facade APIs are ported. The
  label should communicate the selected core backend mode, not guarantee every TUI operation is Rust.
- Dual-run is especially easy to misrepresent: both implementations may execute, but Python results are returned. The
  proposed `Python+Rust dual` wording makes that behavior visible without adding a long explanatory sentence to the UI.
- The top bar is finite width. The badge is intentionally short, and if later width pressure becomes a problem it can be
  shortened to `core: Py`, `core: Rust`, and `core: dual`.
