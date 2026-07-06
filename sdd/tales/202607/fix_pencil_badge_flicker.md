---
create_time: 2026-07-06 04:06:39
status: wip
prompt: sdd/prompts/202607/fix_pencil_badge_flicker.md
---
# Fix flickering ✏️ file-change pencil badge for running agents in the ace TUI

## Problem

The ✏️ file-change pencil badge on Agents-tab rows keeps disappearing and re-appearing for _running_ agents (observed on
the `sase-5g.2` and `sase-5g.7` agents). The blink repeats every few seconds while the agent runs. This is the same
class of bug as the recently fixed `Bead:` field flicker (stale-while-revalidate, commit `47a7d5dad`), but in a
different state path: the bead fix was a TTL cache that forgot values on expiry; the pencil bug is per-object row state
that is forgotten on every agents reload.

## Root cause

The row pencil is computed by `agent_file_change_hint()` in `src/sase/ace/tui/widgets/_agent_list_render_cache.py` with
this precedence:

1. Redirected root Plan rows (`diff_badge_uses_live_hint()` in `src/sase/ace/tui/widgets/file_panel/_diff.py`):
   `bool(agent.live_file_change_hint)` only.
2. Otherwise: `agent.diff_has_real_edits` (classified from the persisted `diff_path`), then
   `agent.live_file_change_hint`, then `bool(agent.diff_path)`.

A running agent has no persisted `diff_path` yet, so its pencil comes entirely from `Agent.live_file_change_hint` — an
in-memory field (`compare=False`, default `None`) that only the deferred, coalesced background scan in
`src/sase/ace/tui/actions/agents/_loading_live_hints.py` (`AgentLiveHintMixin`) ever sets, by running per-agent VCS
probes off-thread _after_ a load applies.

The flicker cycle:

1. **Every agents reload discards the hint.** Both the broad reload (`_load_agents_async`) and the artifact-delta reload
   (`_load_agent_artifact_delta_async` in `_loading_disk.py`) build fresh `Agent` objects from disk and replace
   `self._agents_with_children` / `self._agents` wholesale in `_apply_loaded_agents_prepared_inner`
   (`src/sase/ace/tui/actions/agents/_loading_apply.py`). No loader pass sets `live_file_change_hint`
   (`classify_diff_badges` explicitly leaves it alone) and no carry-over from the previous objects exists anywhere, so
   every fresh object starts at `None`.
2. **Running agents trigger reloads constantly.** They write artifacts continuously, so the file watcher keeps marking
   the agents surface dirty and `_on_auto_refresh` reloads at up to one per `AGENTS_LOAD_MIN_INTERVAL_SECONDS` (5 s),
   plus the 60 s full sanity refresh. The agents observed flickering are exactly the running ones whose artifact dirs
   keep changing.
3. **Running rows repaint every second**, because `_runtime_signature` folds quantized `now` into `agent_render_key` for
   runtime-ticking rows. So the first tick after an apply paints from the fresh object: hint `None` →
   `agent_file_change_hint` falls through to `bool(diff_path)` = `False` (or `bool(None)` on the redirected-plan path) →
   pencil disappears. (Idle/terminal rows don't tick and the incremental display diff ignores the `compare=False` hint
   field, so their previously rendered row survives — which is why only running agents blink.)
4. **The deferred scan brings it back.** `_apply_loaded_agents_prepared_inner` ends with
   `_schedule_live_hint_refresh(source="apply")`; when the off-thread VCS probe batch completes,
   `_apply_live_hint_results` patches the hint `None → True` and the pencil re-appears.
5. Repeat on every reload → a sub-second-to-seconds blink roughly every 5 s on running rows.

Rows with a persisted `diff_path` don't flicker because `classify_diff_badges` re-derives `diff_has_real_edits`
synchronously in every loader pass from stable on-disk data.

Secondary instability: `_apply_live_hint_results` overwrites a known `True` with `None` when a probe transiently fails
(`classify_live_file_change_hint` fails closed to `None` on any exception; `get_agent_diff` returns `None` on provider
errors/timeouts, which `live_agent_file_change_hint` maps to `False`). A transient git error (e.g. lock contention or a
timeout while the running agent itself does VCS work) blinks the pencil off for one scan cycle.

Reload semantically means "revalidate", not "forget" — same conflation the bead fix addressed.

## Fix: carry live hints across reloads (stale-while-revalidate)

All changes are presentation-layer TUI row state in this repo. Badge classification and diff semantics are unchanged, so
no `sase-core` (Rust) changes are needed (litmus test: this is Textual row-rendering state, not domain behavior).

### 1. Carry-over on apply — `src/sase/ace/tui/actions/agents/_loading_apply.py` + `_loading_live_hints.py`

Add a small helper in `_loading_live_hints.py` (e.g. `carry_over_live_hints(previous_agents, current_agents)`) so
live-hint semantics stay in one module, and call it from `_apply_loaded_agents_prepared_inner`:

- Before `self._agents_with_children` / `self._agents` are reassigned, snapshot an identity → `live_file_change_hint`
  map from the previous objects (both lists, mirroring how `_apply_live_hint_results` matches current objects).
- After reassignment, copy the previous hint onto each fresh agent (visible and unfiltered lists) whose
  `live_file_change_hint is None` **and** which still qualifies for a live hint — the same filter
  `_live_hint_candidates` uses: resolved diff source (`resolve_agent_diff_source`) has no `diff_path` and its status
  bucket is non-terminal. A row that gained a persisted diff or went terminal must not retain a stale pencil; badge
  precedence for those rows comes from persisted data anyway.
- The deferred scan already scheduled at the end of the apply revalidates every candidate and patches genuine changes,
  so a workspace that really went clean transitions `True → False` exactly once, with no flicker.
- Cost: one dict build + attribute copies per apply, all in-memory on the UI thread — negligible next to the existing
  finalize work, and no new refresh paths (per the TUI perf rules).

### 2. Revalidation keeps the last known value on "no signal" — `_loading_live_hints.py`

In `_apply_live_hint_results`, when the fresh result for an identity is `None` (probe-level "signal doesn't apply" or a
transient probe failure) and the current hint is a boolean, keep the boolean instead of overwriting. `None` means "no
fresh signal", not "signal is off": whenever the signal genuinely stopped applying (persisted `diff_path` appeared,
agent went terminal), render precedence stops reading the live hint entirely, so keeping the stale boolean cannot
override authoritative data — it only prevents transient probe failures from blinking the row. A fresh `False` (probe
ran, tree is clean) still overwrites and removes the pencil.

## Tests

Follow the existing conventions in `tests/ace/tui/test_agents_live_hint_refresh.py` (the `_FakeApp(AgentLiveHintMixin)`
harness with fabricated `Agent` objects) and `tests/ace/tui/widgets/test_agent_list_file_change_pencil.py`.

New coverage:

- Carry-over copies a previous `True`/`False` hint onto a fresh same-identity agent whose hint is `None`, across both
  the visible and unfiltered lists; `agent_file_change_hint` / `agent_render_key` keep the pencil variant stable across
  the simulated reload.
- Carry-over skips: fresh row whose resolved diff source now has a persisted `diff_path`; fresh row with a terminal
  status bucket; identities with no previous hint (stay `None`); fresh rows that already have a non-`None` hint
  (loader/merge value wins).
- Redirected root Plan row: carry-over still applies (the hint lives on the row agent, matching `_live_hint_candidates`
  scope).
- `_apply_live_hint_results`: result `None` with current boolean hint → no patch, hint retained; result `False` with
  current `True` → patched exactly once; existing `None → True` behavior unchanged.
- Apply-path integration: applying a prepared load whose fresh agents share identities with previous hinted agents
  leaves the pencil render key unchanged (no `True → False → True` flip), and still schedules the deferred scan.

## Verification

- `just install` then `just check`.
- Targeted:
  `pytest tests/ace/tui/test_agents_live_hint_refresh.py tests/ace/tui/widgets/test_agent_list_file_change_pencil.py tests/ace/tui/widgets/test_agent_render_key_badges.py tests/ace/tui/test_agent_display_diff.py tests/test_agent_loader_live_file_change_hint.py`.
- Manual spot-check: run `sase ace` while at least one agent is running and watch its row across several artifact-driven
  refreshes (>60 s to include a full sanity reload) — the ✏️ pencil should stay stable through reloads and only change
  when the workspace's real edit state changes.
