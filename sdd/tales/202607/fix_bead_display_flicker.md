---
create_time: 2026-07-06 00:32:10
status: wip
prompt: sdd/prompts/202607/fix_bead_display_flicker.md
---
# Fix flickering `Bead:` field in the ace TUI agent metadata panel

## Problem

The `Bead:` field in the agent metadata panel on the Agents tab of `sase ace` keeps disappearing and re-appearing for
agents with a confirmed bead (e.g. `sase-5f`). Screenshot comparison (00:23:56 vs 00:24:05) shows the field vanish and
return within ~9 seconds. The same blink affects the ◆ bead badge on the agent's list row: the row shows `×6 sase-5f`
(no badge) in the capture where the `Bead:` line is missing and `×6 ◆ sase-5f` in the capture where it is present.

(The screenshots also differ in the AGENT XPROMPT section — `%model:@epic_lander` present in one capture only. That
content comes from `agent.get_raw_xprompt_content()`, which reads the raw xprompt from disk, so it reflects a genuine
on-disk change to the agent's composed follow-up xprompt at that moment. It is unrelated to this bug and is out of
scope.)

## Root cause

The bead display cache in `src/sase/ace/tui/models/agent_bead.py` treats TTL expiry as a hard cache miss and **discards
the previously confirmed value**:

- `_BeadDisplayCache.get()` pops an expired entry and returns `BEAD_DISPLAY_CACHE_MISS` (`_CACHE_TTL_SECONDS = 60.0`).
- Every render path interprets a miss as "unconfirmed — render nothing":
  - `build_header_text()` (`widgets/prompt_panel/_agent_display_header.py`) drops the `Bead:` line on the cheap path
    (direct cache read) and on the full path (via `summary.bead_display`).
  - `build_detail_header_summary()` (`_agent_display_header_summary.py`) bakes `bead_display=None` into the per-widget
    summary cache. That summary is considered stale after only 1 second (`DIFF_CACHE_TTL_SECONDS = 1.0`), so with the 2s
    auto-refresh it is rebuilt on essentially every tick — the first rebuild after TTL expiry captures `None` and the
    `Bead:` line disappears.
  - `agent_has_confirmed_bead()` flips to `False`, and since it is part of the row render cache key
    (`widgets/_agent_list_render_cache.py`), the agent row re-renders without the ◆ badge.
- The async re-resolve paths then repopulate the cache off-thread (`_start_agent_bead_display_resolve_from_context` in
  the prompt panel; `AgentBeadWarmupMixin` on the Agents tab) and the field/badge come back on a subsequent render. Note
  the re-render triggered directly by the bead-resolve worker (`_apply_agent_bead_display_worker_result`) still paints
  from the summary that was built during the miss window (`bead_display=None`), so the field stays missing for one extra
  cycle until the 1s summary staleness forces a rebuild.

Net effect: a 1–4 second blink of the `Bead:` field and ◆ badge every ~60 seconds, which under the 2s auto-refresh is
exactly the observed disappear/re-appear cycle.

The TTL exists so the TUI eventually picks up upstream bead changes (title/description edits, bead deletion). But expiry
semantically means "revalidate", not "forget" — the current implementation conflates the two.

## Fix: stale-while-revalidate for the bead display cache

Keep serving the last-known value after TTL expiry while flagging the entry for re-resolution; only change what renders
once a fresh lookup actually completes. All changes are presentation-layer TUI caching in this repo — bead display
_formatting_ stays in `sase.agent.bead_display`, and no domain behavior changes, so no `sase-core` (Rust) changes are
needed.

### 1. `src/sase/ace/tui/models/agent_bead.py`

- `_BeadDisplayCache.get()`: stop popping expired entries. An expired entry returns its stored value (stale) instead of
  `BEAD_DISPLAY_CACHE_MISS`; track freshness so callers can distinguish "needs revalidation" from "fresh".
  `BEAD_DISPLAY_CACHE_MISS` is returned only for keys never resolved (or evicted by the LRU bound, which continues to
  cap memory).
- `cached_bead_display(agent)`: returns the last-known value even when expired — renders keep showing the confirmed
  string during revalidation.
- `should_resolve_bead_display(agent)`: returns `True` for never-resolved **or expired** entries, so the existing async
  workers re-confirm on the same ~60s cadence as today (no extra bead-store load).
- `resolve_bead_display(agent)`: unchanged — `set()` overwrites the value and refreshes the TTL. A deleted bead
  transitions confirmed → `None` exactly once, after the fresh lookup completes, with no flicker.
- `warm_confirmed_bead_displays(candidates)`: report identities whose **confirmed state changed** in either direction
  (newly confirmed _or_ newly unconfirmed), by comparing the pre-resolve cached value with the fresh result. Today it
  only reports newly confirmed candidates; with stale values now rendering, a bead deleted upstream must also patch its
  row (`_apply_bead_warmup_results` already patches every identity in the results mapping, so only the producer side
  needs the change — verify docstrings/comments in `_loading_bead_warmup.py` stay accurate).

### 2. Consistency check on the prompt-panel resolve path

In `_apply_agent_bead_display_worker_result` (`widgets/prompt_panel/_agent_display_async.py`), the post-resolve
re-render reads the cached summary. With stale-while-revalidate the summary built during revalidation holds the old
(still-correct) string, so no blink occurs; the 1s summary staleness picks up any actual value change within a second.
If, while implementing, that one-second lag proves visible when a bead's text genuinely changes, drop the agent's cached
summary when the resolved display differs from `summary.bead_display` so the next paint rebuilds immediately. Keep this
minimal — it is an optimization, not the core fix.

## Tests

Follow the existing conventions in `tests/ace/tui/widgets/test_agent_display_bead_metadata.py`,
`tests/ace/tui/test_agents_bead_warmup.py`, and `tests/ace/tui/widgets/test_agent_list_bead_badges.py` (the
`_BeadDisplayCache` constructor already accepts `ttl_seconds`, and tests already manipulate `_BEAD_DISPLAY_CACHE`
directly, so expiry can be simulated without sleeping — e.g. by writing an entry with an already-passed deadline or a
tiny-TTL instance).

New coverage:

- Expired-but-previously-confirmed entry: `cached_bead_display` returns the stale string; cheap and full headers still
  render the `Bead:` line; the agent row still renders the ◆ badge; `should_resolve_bead_display` returns `True`.
- Re-resolve confirms the same value: display unchanged, entry fresh again.
- Re-resolve returns `None` (bead deleted upstream): headers and row stop rendering bead UI;
  `warm_confirmed_bead_displays` includes that identity so the row is patched.
- Existing cold/miss semantics unchanged: a never-resolved candidate still renders nothing and never touches bead
  storage from render paths.

## Verification

- `just install` then `just check`.
- Targeted:
  `pytest tests/ace/tui/widgets/test_agent_display_bead_metadata.py tests/ace/tui/test_agents_bead_warmup.py tests/ace/tui/widgets/test_agent_list_bead_badges.py tests/ace/tui/widgets/test_agent_display_bead_async.py tests/ace/tui/widgets/test_agent_render_key_core.py`.
- Manual spot-check: run `sase ace`, select an agent with a confirmed bead, and watch the metadata panel across a >60s
  window — the `Bead:` field and row ◆ badge should remain stable through cache revalidation.
