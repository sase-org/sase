---
create_time: 2026-04-15 16:56:07
status: done
---

# Plan: Make TUI fold navigation instant by skipping redundant disk reloads

## Problem

Every fold expand/collapse (`l`/`h` key) triggers `_expand_fold()` → `_load_agents()` → `load_all_agents()`, which
re-reads **all agents from disk** (~3-5s per key press). Profiling shows:

- `load_all_agents`: 3.2s (reads every JSON marker file, parses all .gp project files)
- Post-load filtering/display in `_load_agents`: ~2s (retry state reads, dismissed agent logic, panel rebuild)
- Total per key press: **~5s**

**Key insight:** Fold toggle only changes _which agents are visible_ — the underlying agent data is unchanged. The
auto-refresh timer already calls `_load_agents()` every 8s, so data freshness is handled. Fold filtering
(`filter_agents_by_fold_state`) is a pure in-memory operation on the cached `_agents_with_children` list.

Secondary issue: `is_entry_ref_suffix` (display_helpers.py:61) uses `re.match()` with an uncompiled pattern, spending
0.163s on regex compilation during each full reload.

## Changes

### Phase 1: Add `_refilter_agents()` for fold-only refreshes

**`src/sase/ace/tui/actions/agents/_loading.py`** — Add `_refilter_agents()` method to `AgentLoadingMixin`:

A lightweight path that reuses `self._agents_with_children` (cached by the last `_load_agents()` call) and re-applies
only the post-load pipeline:

1. `filter_agents_by_fold_state(self._agents_with_children, self._fold_manager)`
2. Custom ordering (`apply_custom_order`)
3. Search filter
4. Status overrides
5. Panel index rebuild (`_build_panel_indices`)
6. Selection restoration
7. Tab bar count update
8. Display refresh

This is a subset of `_load_agents()` starting from line 358 (after fold filtering), skipping the expensive disk I/O
(`load_all_agents`), retry state reads, dismissed agent logic, auto-dismiss, and artifact cleanup. Must guard against
empty `_agents_with_children` (first load hasn't happened yet) — fall back to full `_load_agents()` in that case.

### Phase 2: Update fold actions to use `_refilter_agents()`

**`src/sase/ace/tui/actions/agents/_folding.py`** — Replace `self._load_agents()` calls with `self._refilter_agents()`
in:

- `_expand_fold()` (line 66)
- `_collapse_fold()` (line 96)
- `_expand_all_folds()` (line 122)
- `_collapse_all_folds()` (line 131)

### Phase 3: Pre-compile `is_entry_ref_suffix` regex

**`src/sase/ace/display_helpers.py`** — Pre-compile the regex at module level:

```python
_ENTRY_REF_RE = re.compile(r"^\d+[a-z]?$")
```

Then use `_ENTRY_REF_RE.match(suffix)` instead of `re.match(r"^\d+[a-z]?$", suffix)`.

## Risks / edge cases

- **Stale data after fold toggle**: Not a real risk — the 8s auto-refresh keeps data fresh. A fold toggle 1s after a
  full refresh shows data that's at most 1s old, identical to what the user was already seeing.
- **First load guard**: If `_refilter_agents()` is called before any `_load_agents()` has run (empty
  `_agents_with_children`), fall back to `_load_agents()`.
- **Hidden agent count**: `_refilter_agents()` must preserve the `_hidden_count` and `_has_always_visible` state from
  the last full load (these depend on the always-visible vs hideable categorization which doesn't change on fold
  toggle).
