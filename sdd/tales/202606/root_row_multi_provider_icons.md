---
create_time: 2026-06-10 10:23:49
status: done
prompt: sdd/prompts/202606/root_row_multi_provider_icons.md
---
# Show All Child LLM Provider Icons on Root Agent Rows

## Problem

On the `sase ace` Agents tab, a root agent/workflow entry whose child agent entries ran on different LLM providers shows
only one provider emoji — the one stored on the root row itself. Example: the `51.f1` family root renders only `🎭` even
though its planner child ran on Claude (`🎭`) and its coder child ran on Codex (`🤖`).

Desired behavior: the root row shows **all distinct provider icons of the family**, ordered by first run (Claude icon
first in the example, since the Claude planner ran before the Codex coder). Single-provider families must render
byte-identically to today (one icon).

## Current behavior

- `format_agent_option()` (`src/sase/ace/tui/widgets/_agent_list_render_agent.py:149-155`) appends exactly one badge:
  `provider_emoji_badge(agent.llm_provider)`, gated by `_should_render_provider_badge()` (skips non-agent workflow child
  rows such as bash/python steps).
- `provider_emoji_badge()` and the provider→emoji map live in `src/sase/ace/tui/provider_styles.py:82-132`.
- Root rows already carry their child agent entries in memory: `sort_and_reorder()` → `_attach_runtime_children()`
  (`src/sase/ace/tui/models/_agent_ordering.py:158-178`) attaches each parent's main agent steps plus follow-up agents
  (planner/feedback/coder/question rounds) to `Agent.runtime_children`. This runs before fold filtering
  (`src/sase/ace/tui/models/_fold_filter.py`), so even **collapsed** roots retain their children at render time — the
  render cache's `_runtime_signature()` already relies on this for runtime suffixes.
- The row render cache key (`agent_render_key()`, `src/sase/ace/tui/widgets/_agent_list_render_cache.py:97-154`)
  includes only the root's own `agent.llm_provider`, so a child arriving on a new provider would not invalidate a cached
  root row.

## Design

### Provider aggregation semantics

Add a small pure helper (proposed home: `src/sase/ace/tui/widgets/_agent_list_helpers.py`):

```
ordered_row_providers(agent) -> tuple[str, ...]
```

1. Collect candidate runs: the row's own agent, plus `runtime_children` recursively (cycle-guarded with a `seen` id set,
   mirroring `_runtime_signature()`'s traversal). Only entries with a non-empty normalized `llm_provider` contribute.
   (`runtime_children` already contains only agent-typed steps and follow-ups, never bash/python steps.)
2. Order by launch time (`run_start_time or start_time`, same as `_child_launch_time()` in
   `_agent_status_overrides.py`), with a stable sort so the root — which always launches first — leads on ties.
3. Deduplicate normalized provider names, keeping first occurrence.

This yields `("claude", "codex")` for the `51.f1` example. Rows without children degrade to a 0/1-element tuple equal to
today's behavior. Because the helper applies to every row, an intermediate family row that itself has child agent
entries (e.g. `foo.bar` with `foo.bar.1`) also aggregates its subtree — consistent with the glossary definition of a
root entry as "any entry that has child entries".

All supported runtimes are treated uniformly via the existing provider registry/emoji map; providers with no emoji
mapping are simply skipped (current behavior for unknown providers).

### Rendering

In `format_agent_option()`, replace the single-badge append with a loop over
`provider_emoji_badge(p) for p in ordered_row_providers(agent)`, appending each known badge as `f"{badge} "` in order.
The `_should_render_provider_badge()` gate is unchanged (non-agent workflow child rows still render no badge). A
single-provider row produces exactly the same string as today, so existing rows, tests, and PNG goldens that show one
icon are unaffected.

### Cache correctness

In `agent_render_key()`, replace the `agent.llm_provider` component with the full `ordered_row_providers(agent)` tuple
(it subsumes the root's own provider). This keeps the documented invariant that the key captures every input that
affects the rendered Option: a child appearing with a new provider now correctly invalidates the cached root row. The
`patch_row` path reuses the same cached formatter, so no extra wiring is needed.

### TUI performance notes (per `memory/long/tui_perf.md`)

- The aggregation is a pure in-memory walk over `runtime_children` (typically 0–8 entries) with no disk I/O, no new
  refresh paths, and no event-loop blocking. The render cache key already performs an equivalent recursive walk in
  `_runtime_signature()`, so per-row key cost stays the same order of magnitude.
- The cache key becomes strictly more specific (rule: too-broad keys serve stale rows); single-provider rows keep
  identical render output, so cache hit rates are unchanged for the common case.

### Rust core boundary

This is presentation-only aggregation over rows already loaded into the Python TUI model (icon choice, ordering, and
Rich text assembly). No domain behavior crosses to other frontends, so no `sase-core` changes are needed.

## File changes

1. `src/sase/ace/tui/widgets/_agent_list_helpers.py` — add `ordered_row_providers()` (pure helper described above).
2. `src/sase/ace/tui/widgets/_agent_list_render_agent.py` — render one badge per aggregated provider, in order.
3. `src/sase/ace/tui/widgets/_agent_list_render_cache.py` — fold the aggregated provider tuple into `agent_render_key()`
   in place of the bare `agent.llm_provider` field.

## Tests

1. Extend `TestAgentListProviderEmojiBadges` in `tests/ace/tui/widgets/test_agent_display_list_rendering.py`:
   - Root with a Claude planner child and a later Codex coder child renders `🎭 🤖 ` (in that order) before the name.
   - Ordering follows first-run time across three providers (e.g. `🎭 🤖 ♊`), not attachment order.
   - Duplicate providers render once (root Claude + Claude planner + Codex coder → exactly one `🎭`).
   - Children without a provider contribute no badge; a grandchild's provider (nested `runtime_children`) is included.
   - Workflow child rows and single-provider roots are unchanged (existing assertions keep passing).
2. Extend `tests/ace/tui/widgets/test_agent_render_cache.py`:
   - `agent_render_key()` changes when a child's provider changes and when a new provider-bearing child is attached to a
     previously rendered root.
3. Run `just test-visual`; no golden updates are expected because existing fixtures use single-provider families (only
   accept regenerated goldens if a fixture genuinely contains a multi-provider family).

## Known limitation (accepted)

When a root's own `llm_provider` is missing and was backfilled by `_copy_missing_display_metadata()`
(`src/sase/ace/tui/models/_agent_status_overrides.py:242-253`, which mirrors the _newest_ child), the backfilled
provider sorts at the root's launch time and may lead the icon order even though it ran later. All icons still appear;
the common case (root carries its own provider, matching its first run) orders correctly. Reordering the backfill source
is left out of scope to avoid changing the detail panel's `Model:` semantics.

## Non-goals

- Detail panel `Model:` line, banner rows, CLI (`sase output`) rendering, and saved-group revival modals keep their
  current single provider/model display.
- Retry-chain siblings (`retry_chain_siblings`) render as their own indented rows and are not folded into the root's
  icon list.

## Verification

- `just install && just check` (required for `src/` + `tests/` changes).
- Targeted runs:
  `pytest tests/ace/tui/widgets/test_agent_display_list_rendering.py tests/ace/tui/widgets/test_agent_render_cache.py`.
- Manual spot check: `sase ace` with a plan-chain family whose coder ran on a different provider — root row shows both
  icons in launch order, collapsed and expanded.
