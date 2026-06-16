---
create_time: 2026-06-16 08:28:07
status: done
prompt: sdd/prompts/202606/hide_terminalized_abandoned_agents.md
---
# Plan: Stop terminalized "abandoned" agents from reappearing on the Agents tab

## Problem

After yesterday's (2026-06-15) startup-perf work, the Agents tab shows agents that the user dismissed/abandoned long
ago. The reproducible symptom: the `#chop` dynamic agent panel surfaces ~197 stale chop rows that the user "knows" were
gone, and re-dismissing them from the TUI does not stick.

### Confirmed root cause

Commit `c029ba2da` ("perf: reduce ACE startup active index work") added startup index maintenance
`terminalize_stale_active_agent_artifact_index_rows` (in the sibling Rust core `sase-core`), wired in via
`_run_active_tier_maintenance` in `src/sase/core/agent_artifact_index_lifecycle.py`. Its goal was a perf win: drain
stale, no-marker rows out of the bounded (now `active_limit=1000`) Tier-1 active query.

To drain a row out of the active tier it writes an **index-only synthetic `done` record** (`outcome="abandoned"`,
`finished_at=now`, `has_done_marker=1`) into `agent_artifacts`. This regresses behavior in two ways:

1. **Abandoned agents become visible.** These artifacts have only `agent_meta.json` on disk — no
   `done.json`/`running.json`/`workflow_state.json`. Before the change, no loader picked them up (a fresh source scan of
   such a directory returns **0 agents**), so they were correctly invisible. The synthetic `done` marker now makes
   `load_done_agents_from_snapshot` load them as visible `DONE` rows, and `finished_at=now` floats them to the front of
   the recent-completed inbox.

2. **Their identity is corrupted to `unknown`.** `RecordSummary::from_record` derives `cl_name` only from the
   `done`/`running`/`workflow_state` markers, never from `agent_meta`. So `terminalized_abandoned_record` falls back to
   `cl_name="unknown"`, even though `agent_meta.json` carries the real `cl_name` (e.g. `"sase"`). The reappeared rows
   therefore load as `(run, "unknown", <timestamp>)`, which matches **neither** their saved chop tag
   (`(workflow, "sase", <timestamp>)`) **nor** any dismissed-agent entry. That is why they fall into the `(untagged)`
   panel and why dismissing "does not work" — the identity the user dismisses under never lines up with the identity the
   index keeps re-minting on each startup pass.

### Evidence / blast radius

- Tier-1 (index) load returns 197 chop-tagged rows, all `(run, "unknown", <ts>)`, all `DONE`; none are present in
  `dismissed_agents.json` (verified: 0 exact-identity and 0 suffix matches). Full-history source scan does not return
  these rows at all.
- The on-disk artifact for an affected row (`.../artifacts/ace-run/<ts>/`) contains only `agent_meta.json`
  (`cl_name="sase"`, `chop_lumberjack`/`chop_run_id` fields) — no `done.json`.
- The live index currently holds **14,283** rows with a synthetic `done.outcome="abandoned"`, all with
  `cl_name="unknown"`, of which **12,668** are `hidden=0` (visible). The 197 chop rows are simply the most recent and
  prominent slice.

This is an artifact-index projection bug, not a TUI rendering bug.

## Approach

The fix belongs in `sase-core` (artifact-index visibility is shared backend behavior per the core/backend boundary).
Work happens in the `sase-core` workspace matching this repo's workspace number.

### 1. Hide terminalized abandoned rows from normal visibility (core)

- In `terminalized_abandoned_record`, mark the synthetic abandoned record `hidden = true` so it is excluded from every
  `include_hidden = false` query (active, recent-completed, visible, full-history). This still satisfies the original
  perf goal (the row leaves the bounded active tier) while keeping abandoned, marker-less agents off the Agents tab —
  restoring the pre-2026-06-15 behavior where they were invisible.
- As correctness hygiene (so the row is still sensible when inspected via `include_hidden = true`), preserve the real
  identity: add `agent_meta.cl_name` to the `cl_name` resolution chain in `RecordSummary::from_record` so the
  terminalized record keeps `cl_name="sase"` instead of `"unknown"`.

### 2. Heal the already-corrupted index in place (core)

The 12,668 existing visible abandoned rows already have `hidden=0` and `has_done_marker=1`, so the existing terminalize
candidate query (which requires `has_done_marker=0`) will never revisit them. Add a lightweight repair pass, run from
the same startup maintenance entry point, that flips existing synthetic-abandoned rows (`done.outcome="abandoned"`,
`hidden=0`) to `hidden=1`. Launching the patched TUI then self-heals the user's index with no manual state edits and no
`dismissed_agents.json` changes.

### 3. Regression coverage (core)

- Update the terminalization test so abandoned rows are absent from normal active/recent/full-history queries.
- Add coverage that `include_hidden = true` can still inspect abandoned terminalized rows and that they retain the real
  `cl_name`.
- Add coverage for the in-place repair path (pre-existing `hidden=0` abandoned row becomes hidden).

### 4. Build, verify, and prove the fix

- `just install` in this Python repo so `.venv` / TUI use the patched `sase_core_rs`.
- Re-run the loader diagnostic: Tier-1 `visible chop after the dismissed filter` must be `0`.
- Run the targeted Rust tests for the changed index behavior and the targeted Python loader/index-projection tests, then
  `just check` (file changes were made).
- Launch `sase ace --tmux`, capture the pane, and confirm the abandoned `#chop` rows no longer appear on the Agents tab
  (the user's required verification).

## Scope / non-goals

- Do not modify memory files or user state files (`dismissed_agents.json`, `agent_tags.json`, the live index by hand).
  Healing happens through normal index lifecycle/query code.
- No change to the dismissed-agent matching design or the Python dismissed filter — the agents simply should not be
  surfaced by terminalization in the first place.
- The `active_limit=1000` bound and the rest of the perf commit are kept; only the visibility/identity side effect of
  terminalization is corrected.

## Risks

- Overloading the `hidden` flag for "abandoned" is acceptable (it already aggregates several "do not show by default"
  reasons), but the repair pass must scope strictly to synthetic-abandoned rows so it cannot hide legitimately completed
  agents.
- Verify the repair pass is cheap at the user's scale (~14k candidate rows) so it does not regress startup time it was
  meant to improve.
