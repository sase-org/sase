---
create_time: 2026-04-03 15:17:17
status: done
---

# Implementation Plan: Fix Enter key passthrough from Agents tab to jump-to-ChangeSpec action

## Problem Summary

Pressing `<enter>` on the Agents tab should invoke the app-level `jump_to_agent_changespec` action. In practice, nothing
happens in some environments. The expected behavior is to switch to the CLs tab, adjust query to `project:<name>` when
needed, and select the target ChangeSpec.

## Root Cause Hypothesis

`AgentList` relies on overriding `OptionList.BINDINGS` to remove the `enter -> select` binding. However, the runtime
bindings map still includes inherited `enter -> select`, so Enter is consumed by `OptionList` selection handling and
never reaches app-level keybindings.

## Proposed Changes

1. Harden `AgentList` so it always refuses local `select` handling, even if upstream/inherited bindings include it.
2. Keep existing list navigation keys intact (`j/k` behavior remains app-driven; arrow keys remain widget-local).
3. Add regression tests to validate Enter is not handled by `AgentList` and can reach app-level handlers.

## Verification Plan

1. Run targeted tests covering the new regression behavior.
2. Run full `just check` per repo instructions.

## Risks / Tradeoffs

- Disabling widget-level `select` in `AgentList` means Enter won't trigger list-local selection events via OptionList;
  this is intended because app-level Enter is the canonical behavior in the Agents tab.
- Ensure mouse-click selection behavior remains unchanged (driven by option highlight/selected messages).
