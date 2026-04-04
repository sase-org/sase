---
create_time: 2026-04-04 10:22:16
status: wip
---

# Plan: Agents Tab Title — Replace Dismissable Count with Pinned Count

## Problem

The Agents tab title currently shows `Agents (x1)` where `x` is the dismiss keybind and `1` is the count of dismissable
(done) agents. The user wants it to show `Agents (+1)` where `1` is the count of pinned agents. This better reflects the
user's mental model: the tab badge should highlight what they've explicitly saved/pinned, not what's waiting to be
dismissed.

## Current Behavior

In `tab_bar.py:223-236`, the Agents tab suffix is built from:

- `main_count` = `self._agents_manual_count` (running non-workflow agents)
- `key_counts` = `[(dismiss_key, self._agents_done_count)]` + optional hidden count

The `done_count` is computed in `_loading.py:407-411` as agents with status in `DISMISSABLE_STATUSES` that are not
workflow children. This feeds into `tab_bar.update_agents_count()`.

## Proposed Changes

### 1. Compute pinned count in `_loading.py` and pass it to the tab bar

In `_loading.py:387-420`, after computing `manual_running`, `hidden_running`, and `done_visible`, also compute the
pinned count (non-workflow-child agents whose identity is in `self._pinned_agents` and status is in
`DISMISSABLE_STATUSES`). Pass this as a new `pinned_count` parameter to `tab_bar.update_agents_count()`.

**Files:** `src/sase/ace/tui/actions/agents/_loading.py`

### 2. Update `TabBar.update_agents_count()` to accept and store `pinned_count`

Replace the `done_count` parameter with `pinned_count` (or add alongside and remove `done_count` if it's no longer
needed). Store it as `self._agents_pinned_count`.

**Files:** `src/sase/ace/tui/widgets/tab_bar.py`

### 3. Update `_build_content()` to render `+N` instead of `xN`

In `tab_bar.py:223-236`, change the Agents tab `key_counts` from `[(dismiss_key, self._agents_done_count)]` to
`[("+", self._agents_pinned_count)]`. The `+` is a literal string, not a keybind — it acts as a static indicator.

**Files:** `src/sase/ace/tui/widgets/tab_bar.py`

### 4. Update tests

Search for tests that assert on the Agents tab title format (e.g., `(x1)` or `done_count`) and update them to reflect
the new `(+N)` format and `pinned_count` parameter.
