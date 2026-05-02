---
create_time: 2026-04-30 17:30:12
status: done
prompt: sdd/prompts/202604/agents_enter_misjump.md
---
# Diagnose and Fix Agents-tab Enter Misjump

## Problem

The `<enter>` keymap on the `sase ace` Agents tab sometimes lands on the wrong ChangeSpec in the CLs tab. The keymap
calls `action_jump_to_agent_changespec()`, resolves the selected agent's target ChangeSpec name, then delegates to
`navigate_to_changespec_tab()`.

Investigation points to a recent fuzzy matching change for suffix-renamed ChangeSpecs. `navigate_to_changespec_tab()`
currently selects the first row where `changespec_names_match(cs.name, target)` returns true. That helper intentionally
matches `foo_1` with `foo` so jumps still work after a WIP/Draft suffix is stripped. However, if both `foo` and a
sibling such as `foo_1` are present in the current filtered CL list, the first fuzzy match can be the wrong row even
when an exact match exists later.

## Root Cause

The navigation lookup has no match priority. It treats exact identity and suffix-compatible fallback identity as equal.
This makes list ordering decide which ChangeSpec is selected, which is wrong for direct Agents-tab navigation where the
agent already carries a concrete `cl_name`.

## Plan

1. Add a small lookup helper near `navigate_to_changespec_tab()` that selects ChangeSpecs in priority order:
   - exact name match first;
   - suffix-compatible fallback via `changespec_names_match()` only if no exact match exists.
2. Use that helper in both lookup passes inside `navigate_to_changespec_tab()`:
   - the initial current-query search;
   - the post-query-change project search.
3. Preserve the existing fuzzy fallback for suffix-strip rename compatibility.
4. Add focused tests covering:
   - exact target wins over earlier suffixed sibling;
   - fuzzy fallback still works when only the suffix-compatible row exists;
   - the same exact-first behavior applies after the query is changed to `project:<project>`.
5. Run targeted tests for the jump helper and matching behavior, then run `just install` if needed and `just check`
   before finishing because this repo requires it after edits.
