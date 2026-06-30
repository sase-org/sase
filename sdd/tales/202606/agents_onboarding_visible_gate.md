---
create_time: 2026-06-30 06:01:59
status: done
prompt: sdd/prompts/202606/agents_onboarding_visible_gate.md
---
# Fix: Agents-tab onboarding not shown when the visible list is empty

## Problem

The Agents tab is supposed to show a first-run onboarding panel ("Welcome to sase ace") when there are no agents. In
practice the panel sometimes does **not** appear: the user sees an empty agents list (e.g. an `(untagged) · 0` panel)
and a right-hand pane reading **"No agent selected"** instead of the onboarding guide.

This is a real defect in current code (the onboarding feature is present and shipped) — not a stale build and not a
grouping/tab-specific quirk.

## Root cause

The onboarding visibility gate lives in `src/sase/ace/tui/actions/agents/_display_detail.py`:

```python
def _should_show_agents_onboarding(self) -> bool:
    if not getattr(self, "_agents_first_load_done", False):
        return False
    if (getattr(self, "_agent_search_query", "") or "").strip():
        return False
    return not bool(getattr(self, "_agents_with_children", []))   # <-- wrong list
```

It decides "the tab is empty" by checking `_agents_with_children`, which is the **unfiltered** agent list. That list
intentionally retains rows that the user never sees, in particular **fold-collapsed workflow rows** and **"hidden-only"
workflow parents** (a workflow whose children are all hidden steps). The fold filter in
`src/sase/ace/tui/models/_fold_filter.py` removes such a parent (and its hidden children) from the **visible** list
`_agents`, but they remain in `_agents_with_children`.

Result: whenever the only agents present are folded away / hidden-only, the visible list `_agents` is empty (the user
sees nothing) but `_agents_with_children` is non-empty, so `_should_show_agents_onboarding()` returns `False`, the
onboarding panel stays hidden, and the empty detail pane ("No agent selected") is shown instead.

### Reproduction (confirmed)

Loading a single workflow parent whose only child is a hidden step yields:

- visible `_agents` length = **0** (empty list, matches the screenshot's `(untagged) · 0`)
- `_agents_with_children` length = **2**
- `_should_show_agents_onboarding()` = **False** → onboarding hidden, "No agent selected" shown

This exactly matches the reported screenshot.

### Why existing tests missed it

All current onboarding tests in `tests/ace/tui/test_agents_onboarding.py` and
`tests/ace/tui/visual/test_ace_png_snapshots_agents_onboarding.py`:

- only ever set up either a truly-empty load or visible agents, so visible vs. unfiltered never diverge;
- reach the Agents tab by switching from the default `changespecs` tab, while the real application starts directly on
  the Agents tab;
- use the default `STANDARD` grouping only.

The predicate unit-test harness `_PredicateApp` only sets `_agents_with_children`, encoding the buggy assumption
directly.

## Fix

Gate onboarding on the **visible** agent list — what the user actually sees — instead of the unfiltered list.

In `_should_show_agents_onboarding()`, change the final condition to test the visible `_agents` list (the post-fold,
post-query list assigned in `src/sase/ace/tui/actions/agents/_loading_finalize.py`). The `_agents_first_load_done` guard
and the active-search-query guard stay unchanged, so:

- truly empty (fresh) → both lists empty → onboarding shows (unchanged);
- only folded / hidden-only rows exist → visible empty → onboarding shows (the fix);
- any visible agent rows exist, including grouped/collapsed-banner states where rows still occupy `_agents` → onboarding
  stays hidden (unchanged);
- active agent search query → onboarding stays hidden regardless (unchanged).

This is a presentation-only Textual state decision (which pane to display); it does not cross the Rust core backend
boundary, so no `sase-core` / binding changes are required.

## Test changes

1. Update the `_PredicateApp` harness in `tests/ace/tui/test_agents_onboarding.py` to drive the new condition (provide a
   visible-agents list), and update the predicate unit tests so "hides when agents exist" asserts against the visible
   list.

2. Add a regression test that loads a hidden-only workflow parent (visible list empty, `_agents_with_children`
   non-empty) and asserts the onboarding panel **is** shown and the detail pane is hidden — i.e. the previously-failing
   case now passes.

3. Close the coverage gaps surfaced during diagnosis:
   - an onboarding test that starts directly on the Agents tab (matching the real app default) with an empty load;
   - a non-empty → empty transition test (last visible agent disappears) asserting onboarding re-appears.

4. Keep the existing "hidden when agents exist" and "hides after first agent arrives" integration tests green.

## Verification

- Run the onboarding unit + integration tests and the dedicated PNG snapshot suite for the empty Agents tab.
- Run `just check` (after `just install`) for lint/type/static gates. Note the pre-existing, environment-only failures
  already documented in memory (the `default_effort` llm_provider failures, the `sase validate` freshness gate, and
  sandbox SIGTERM kills of the full test run) are not caused by this change; rely on targeted pytest subsets plus the
  static gates.

## Out of scope

- Changing whether hidden-only workflow parents should themselves be surfaced in the visible list is a separate concern;
  this change only ensures the onboarding empty-state correctly reflects the visible list.
