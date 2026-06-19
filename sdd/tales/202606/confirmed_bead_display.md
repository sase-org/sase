---
create_time: 2026-06-19 10:10:49
status: done
prompt: sdd/prompts/202606/confirmed_bead_display.md
---
# Confirmed Bead Display in `sase ace` Agents Tab

## Problem

The Agents tab currently treats a bead-shaped agent name as enough evidence to render bead UI:

- Agent-list rows append the bead glyph when `derive_agent_bead_id(agent)` returns an id-like value.
- The metadata panel renders `Bead:` from the same inferred id on cheap/cold paths, and the enriched async lookup falls
  back to the id when no bead is found.

That makes the UI show bead metadata for ordinary agents whose names happen to look like bead ids, or for stale
bead-work agent names whose matching bead no longer exists. The desired contract is stricter: show the bead glyph and
`Bead:` only when the TUI has confirmed that the inferred bead id exists in the appropriate bead store for that agent
context.

## Definition of Certainty

An agent has confirmed bead metadata only when:

1. `derive_agent_bead_id_from_name(agent.agent_name)` produces a candidate id, preserving the existing normalization
   behavior for dismissed-prefix names and `.land` names.
2. A bead lookup for that candidate id returns a concrete `Issue` from the agent-context lookup order already used by
   the TUI: `agent.workspace_dir`, then `agent.project_file` project, then the current configured read view / known
   project stores.

If lookup returns no issue, raises, or has not run yet, the TUI is not certain. In that state it must omit both the row
glyph and the metadata `Bead:` field.

## Design

1. Split "candidate id" from "confirmed bead display".

   Keep the existing candidate derivation helper. Add a strict display path for the TUI, for example:
   - `format_agent_bead_display_for_name(..., require_existing=True)`, or
   - a small TUI wrapper that calls a shared lookup helper and formats only when an `Issue` is returned.

   The default non-TUI behavior should remain unchanged unless explicitly requested later, because completion
   notifications currently depend on the fallback id behavior.

2. Make the TUI bead cache express three states.

   Reuse the existing TTL/LRU cache in `src/sase/ace/tui/models/agent_bead.py`, but treat values as:
   - cache miss: candidate has not been checked yet
   - `None`: checked and not confirmed
   - `str`: checked, bead exists, display string is ready

   A confirmed issue with no description/title should cache the bead id string. That keeps `None` reserved for "do not
   render".

3. Change metadata rendering to render only confirmed values.

   In `build_header_text()` and `build_detail_header_summary()`:
   - Do not call the non-strict fallback formatter for cheap/cold rendering.
   - On cache miss, render no `Bead:` row and let the existing async worker resolve the candidate off the Textual event
     loop.
   - On cached `None`, render no `Bead:` row and avoid rescheduling until the TTL expires.
   - On cached `str`, render `Bead: <display>`.

   This means a selected row may initially show no `Bead:` field, then gain one after the worker confirms existence.
   Missing beads stay silent.

4. Change row rendering to use confirmed cache state only.

   Replace the current `derive_agent_bead_id(agent)` row-glyph check with a helper such as
   `agent_has_confirmed_bead(agent)`. It should be an O(1) cache read only. Row formatting must never touch bead
   storage.

   Update `agent_render_key()` to include the confirmed bead render signature instead of the candidate id, so cached
   rows invalidate when a background confirmation result changes visible output.

5. Warm the confirmation cache without blocking list refresh or navigation.

   The row renderer can only use cached certainty, so add a coalesced, background confirmation warmup for visible
   Agents-tab rows:
   - After an Agents refresh applies and the list has painted, collect unique uncached bead candidates from the
     currently visible agents.
   - Run confirmation in a worker thread, never on the Textual event loop.
   - Deduplicate by `(bead_id, project_name, workspace_dir)` before resolving.
   - Prefer a batch/store-scoped resolver so one bead store is opened/read once per warmup instead of once per
     candidate. If the first implementation uses the existing single-candidate lookup, keep the worker post-paint,
     coalesced, and bounded to visible rows only.
   - On completion, re-read the current Agents tab/selection state, then patch affected rows with the existing selective
     row update path when possible. Fall back to the existing display refresh only if row patching cannot represent the
     change safely.

   This preserves first-paint and j/k responsiveness: no new synchronous disk work in handlers, row rendering, or header
   building.

6. Keep invalidation simple and conservative.

   The existing TTL cache bounds stale confirmations. Existing filesystem watches already notice `sdd/beads` changes and
   trigger Agents refreshes. The warmup should respect the TTL and avoid repeatedly resolving known-missing candidates
   during rapid refreshes.

## Implementation Steps

1. Add strict bead-display support in the shared bead display helper or in the TUI wrapper, preserving current default
   behavior for non-TUI callers.
2. Update `src/sase/ace/tui/models/agent_bead.py` with explicit confirmed helper functions:
   - candidate id derivation remains cheap
   - cache reads expose miss / missing / confirmed
   - resolver stores `None` for missing and a display string for existing
3. Update prompt-panel metadata rendering to remove all candidate-id fallback rendering from cheap, cold, and
   full-summary paths.
4. Update agent-list row rendering and render-cache keys to depend only on confirmed cache state.
5. Add the post-refresh background warmup and selective patching path for visible Agents-tab rows, following the
   existing async refresh/coalescing patterns and avoiding any event-loop blocking.
6. Keep help text unchanged unless the glyph semantics description needs a wording tweak from "bead-linked" to
   "confirmed bead".

## Tests

Add or update focused tests:

- Missing bead lookup caches `None`; cheap and full metadata headers omit `Bead:`.
- Cold metadata headers do not touch bead storage and omit `Bead:`.
- Confirmed phase, top-level epic, `.land`, and dismissed-prefix agents still render `Bead:` with id/description/title
  as appropriate.
- Confirmed issue with no description/title renders just the id.
- Agent-list rows omit the bead glyph for cold or missing candidates and show it only for cached confirmed candidates.
- Agent row render keys change when confirmed bead state changes, and do not change merely because an unconfirmed
  candidate id exists.
- The async prompt-panel worker re-renders on confirmed success, stays silent on missing results, and does not
  reschedule missing lookups until TTL expiry.
- The list warmup worker deduplicates candidates, does not run during row formatting, and patches only rows whose
  confirmed state changed.
- Existing non-TUI notification tests continue passing, proving default shared helper behavior was not changed
  accidentally.

Run targeted validation:

```bash
pytest tests/ace/tui/widgets/test_agent_display_bead_metadata.py \
  tests/ace/tui/widgets/test_agent_display_bead_async.py \
  tests/ace/tui/widgets/test_agent_display_list_rendering.py \
  tests/ace/tui/widgets/test_agent_render_cache.py \
  tests/test_agent_bead_display.py \
  tests/test_run_agent_runner_notifications.py
```

If the implementation touches the post-refresh pipeline, also run the relevant refresh/list tests:

```bash
pytest tests/ace/tui/test_agents_refresh_coalescing.py \
  tests/ace/tui/test_agent_display_defer_detail.py \
  tests/ace/tui/widgets/test_agent_list_runtime_patching.py
```

For performance confidence, use the existing TUI perf tools after targeted tests pass:

```bash
pytest -s -m slow tests/ace/tui/bench_tui_jk.py
```

The performance acceptance criteria are:

- no bead lookup from row rendering, cheap header rendering, key handlers, or Textual event handlers
- list first paint is not delayed by bead confirmation
- j/k p95 remains within the existing target
- background warmup is coalesced and bounded to visible uncached candidates

## Risks and Mitigations

- Existing confirmed bead agents may briefly render without the glyph/field on first paint while confirmation warms.
  This is preferable to false positives; the background warmup restores the glyph/field only after certainty exists.
- If bead stores are temporarily unreadable, the TUI will omit bead UI until the cache expires or a refresh succeeds.
  That matches the "not certain, do not show" requirement.
- Batch lookup is the main performance-sensitive part. Keep the initial implementation small, measured, and off-thread;
  only optimize further if benchmarks or traces show measurable overhead.
