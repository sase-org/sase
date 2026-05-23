---
create_time: 2026-05-23 15:40:22
status: done
prompt: sdd/prompts/202605/agent_sibling_root_inclusion.md
---
# Plan: Include Bare Root Agents In Agent Sibling Families

## Context

The `sase-40` epic added Agents-tab sibling navigation for names shaped like `foo.<name>`. Its original design
explicitly excluded the bare `foo` row from `foo.*` sibling families. The current short-term glossary now defines an
Agent Family as including `foo`, `foo.bar`, `foo.baz`, and deeper descendants such as `foo.bar.1`. The code path that
still enforces the old rule is `src/sase/ace/tui/models/agent_siblings.py::agent_sibling_family()`: it returns `None`
for dotless names, and both the cached sibling index and `~` navigation use that helper as their source of truth.

The desired change is therefore not a new navigation feature. It is a semantics update to the existing visible sibling
index: when considering siblings for `foo.bar`, include visible agents named exactly `foo` as members of the same
family, in addition to the already-supported `foo.<name>` rows.

## Target Behavior

- `foo.bar`, `foo.baz`, `foo.review.pass1`, and `foo` all share the same sibling family key: `foo`.
- Matching remains case-insensitive for the family key while preserving the original display names in rows and modal
  choices.
- The relationship is symmetric: selecting bare `foo` can jump to visible `foo.<name>` siblings, and selecting
  `foo.<name>` can jump to visible bare `foo`.
- A dotless singleton such as `foo` with no other visible `foo` family member still has zero visible siblings, so no
  footer binding or info-panel sibling badge appears.
- Duplicate visible bare `foo` rows should be treated as siblings of each other because they are distinct visible rows
  with the same explicit family identity. This follows the "agent family" model and avoids adding a special case that
  only applies to dotless names.
- Empty or malformed names remain excluded: no `Agent.agent_name`, `.bar`, and `foo.` should not produce a sibling
  family.
- Keep all existing visibility constraints from `sase-40`: only rendered Agents-tab rows count, so query/filter state,
  tag panels, grouped panel mode, folded groups, dismissed/killed state, and STARTING-row suppression continue to decide
  which siblings are visible.
- Continue using `Agent.agent_name` as the only source of truth. Do not infer sibling families from `display_name`,
  `cl_name`, tags, or plan-chain metadata in this change.

## Implementation Approach

1. Update `agent_sibling_family()` in `src/sase/ace/tui/models/agent_siblings.py`.
   - Return `name.casefold()` for non-empty dotless names.
   - Keep returning the case-folded first segment for dotted names with non-empty first and remaining segments.
   - Keep rejecting `None`, `""`, `.bar`, and `foo.`.
   - Update the docstring so callers understand that the helper now returns a family key for both the bare root and
     dotted descendants.

2. Let `AgentSiblingIndex.from_visible_rows()` absorb the behavior through the helper.
   - Its current family bucketing already handles "all rows with the same family key, excluding the current row".
   - No separate scan or special root handling should be needed.
   - Preserve render-order output exactly as the visible-row walk yields it.

3. Update the modal family label to avoid implying that only `foo.*` rows are included.
   - `AgentSiblingMixin._agent_sibling_family_label()` currently returns `foo.*`.
   - Change it to a root-inclusive label such as `foo family` or `foo / foo.*`.
   - Prefer the smallest UI change that still makes a modal containing bare `foo` unsurprising.

4. Avoid changing the hot path.
   - `_selected_agent_sibling_count()` and `AgentSiblingMixin._agent_sibling_index()` should keep using the cached
     index.
   - `~` navigation can continue to use `agent_sibling_family(selected) is None` as its early rejection. After the
     helper changes, bare `foo` will pass that check, then no-op naturally when `siblings_for()` is empty.
   - Do not add selected-row sibling state to row render cache keys.

## Test Plan

Update and extend the focused sibling tests rather than broadening unrelated UI coverage:

- `tests/ace/tui/models/test_agent_siblings.py`
  - Change the family helper expectations so `foo` maps to `foo`.
  - Keep rejection coverage for `None`, `.bar`, and `foo.`.
  - Add or update an index test proving `foo.bar` sees bare `foo`, and bare `foo` sees `foo.bar` / `foo.baz`.
  - Preserve tests for case-insensitive matching, STARTING-row exclusion, collapsed groups, and cross-panel render
    order.

- `tests/ace/tui/test_agent_sibling_navigation.py`
  - Add a direct-jump test from `foo.bar` to bare `foo` when that is the only sibling.
  - Add the symmetric direct-jump test from bare `foo` to `foo.bar`.
  - Add or adjust the multiple-sibling modal test so a bare `foo` choice appears in render order.
  - Keep no-op behavior for unrelated families and artifact-viewer guard behavior unchanged.

- `tests/ace/tui/test_agent_sibling_index_cache.py`
  - Add a root-inclusive cache/index case if the model tests do not cover the app-level visible-row walk enough.
  - Ensure repeated sibling-count reads still perform one visible-row walk.

- Visual/modal coverage
  - If the modal title label changes, update `tests/ace/tui/modals/test_agent_sibling_modal.py` and the existing PNG
    snapshot expectations after inspecting the rendered output.
  - No new visual snapshot is required unless the title or root row materially changes the existing modal fixture.

## Verification

After implementation, run:

```bash
just install
just test tests/ace/tui/models/test_agent_siblings.py tests/ace/tui/test_agent_sibling_navigation.py tests/ace/tui/test_agent_sibling_index_cache.py tests/ace/tui/modals/test_agent_sibling_modal.py
just check
```

If a visual snapshot changes because of the modal title, inspect the actual/expected/diff artifacts under
`.pytest_cache/sase-visual/` before accepting any new golden.

## Risks And Constraints

- The main behavior risk is unintentionally surfacing `~` for duplicate bare-name rows. This plan accepts that as the
  coherent family semantics; a dotless singleton still remains invisible to sibling UI because it has no peers.
- The performance risk is low because the change lives in the existing cached family key calculation and does not add a
  per-selection scan.
- The Rust core boundary does not need to change. This remains presentation-layer behavior tied to the Agents tab's
  current visible rows.
- No SASE memory files should be modified.
