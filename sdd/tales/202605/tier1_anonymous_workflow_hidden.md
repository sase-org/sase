---
create_time: 2026-05-21 13:01:34
status: done
prompt: sdd/prompts/202605/tier1_anonymous_workflow_hidden.md
---
# Plan: Stop Treating `is_anonymous` Workflows as Hidden in the Tier 1 Index

## Problem

After the `sase-3t` epic switched the ACE Agents tab to a Tier 1 (artifact-index) load by default, the Agents tab shows
only a tiny subset of real agents on startup (in the user's case: **2 of 20**). Pressing `,y` triggers a Tier 2 full
source scan, after which all expected agents reappear. The whole point of the epic was to make Tier 1 the authoritative
visible-inbox load, so the workaround defeats the design.

## Root Cause

`crates/sase_core/src/agent_scan/index.rs` (`RecordSummary::from_record`, lines ~596-672) projects the SQL `hidden`
column for each indexed artifact as:

```rust
hidden: meta.hidden
    || done.hidden
    || workflow_state.hidden
    || workflow_state.is_anonymous,   // ← bug
```

`is_anonymous` is set whenever a workflow's `workflow_name` starts with `tmp_` (see
`src/sase/xprompt/workflow_runner.py:324`). It just means "auto-generated ephemeral workflow name" — it is **not** a
visibility signal. Such workflows typically carry `appears_as_agent: true` and `hidden: false` in `workflow_state.json`
and are exactly the rows the user wants in the Agents tab.

The Tier 1 visible-inbox queries (`active_where`, `completed_where`, `visible_where` at index.rs:493-541) all add
`WHERE hidden = 0`, so the indexer's overly-broad `hidden` predicate silently filters every anonymous-but-
appears-as-agent row out of the inbox. The Tier 2 path bypasses SQL entirely (it walks the filesystem and builds `Agent`
objects whose `.hidden` flag comes only from `done.hidden`), which is why `,y` resurrects the missing rows.

### Evidence from the live workstation

Querying `~/.sase/agent_artifact_index.sqlite` directly:

- 26 done rows for 2026-05-21 have `hidden=1`. The most recent include `@sase-3t.3` (`20260521100533`), `@awm`
  (`20260521091233`), `@awk` (`20260521085424`), `@awq-epic` (`20260521095806`) — exactly the missing agents from the
  BAD snapshot.
- Their `workflow_state.json` contents:
  `{workflow_name: 'tmp_260521_104058', is_anonymous: true,   appears_as_agent: true, hidden: false}`.
- Running `load_tiered_agents(full_history=False)` returns **690** agents; `full_history=True` returns **842**. The
  152-agent delta is exactly the set of `tmp_*` workflows.

## Scope

In scope:

- Fix the Rust indexer's `hidden` projection (sase-core).
- Migrate existing in-place indexes so users do not have to run `sase agents index gc`/`rebuild`.
- Regression tests at both layers.

Out of scope (explicitly preserved):

- `_loading_apply.py`, Phase-4 reconcile-pending arming, dismissed projection — these are correct and not the bug.
- `Agent.hidden` derivation in Python (`bool(done.hidden)`) is unchanged.
- Anonymous-workflow rendering decisions in the TUI (parent collapsing, etc.) remain in the display layer where they
  belong.

## Fix Design

### 1. Rust indexer — drop the `is_anonymous` disjunct

In `../sase-core/crates/sase_core/src/agent_scan/index.rs`, change the `hidden` field of `RecordSummary::from_record`
to:

```rust
hidden: meta.map(|m| m.hidden).unwrap_or(false)
    || done.map(|d| d.hidden).unwrap_or(false)
    || workflow_state.map(|w| w.hidden).unwrap_or(false),
```

Rationale: visibility in the inbox is governed by the explicit `hidden` field on the relevant marker file.
`is_anonymous` is a naming/grouping signal, not a visibility signal, and is already handled independently in the Python
display layer (`_agent_list_render_agent.py`, `_agent_list_helpers.py`, fold logic). `appears_as_agent` doesn't need to
be added to the predicate — its inverse case (anonymous workflow that should not appear as its own row) is already
covered by either `workflow_state.hidden` being set, or by Python display-side collapsing.

### 2. In-place migration for existing indexes

The fix alone only corrects newly-upserted rows. Every existing user's `agent_artifact_index.sqlite` already contains
thousands of rows with `hidden=1` from the old logic. They must be fixed without forcing a full
`sase agents index rebuild`.

Approach (smallest possible migration; reuse existing scaffolding):

- Bump `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` (currently `1`) to `2` in `agent_scan/index.rs`.
- In `open_index()`, after creating tables and writing the new version, detect the previously-stored version. If it was
  `< 2`, run a one-shot in-place migration:
  - For every row where `hidden = 1`, re-parse `record_json` (cheap; already stored), recompute the new `hidden` value
    via the new `RecordSummary::from_record` logic, and `UPDATE agent_artifacts SET hidden = ? WHERE artifact_dir = ?`
    when it changed.
  - Wrap in a single transaction.
  - On the user's workstation this touches ~2,271 rows once; expected runtime well under a second.
- The migration is idempotent (running against an already-v2 index is a no-op).
- If `record_json` is missing or malformed for a row, leave `hidden` untouched — the next
  `upsert_agent_artifact_index_row` for that artifact will repair it.

Why this and not a Python-side migration: the indexer is the source of truth for the `hidden` semantics; embedding the
migration next to the projection keeps the two in lock-step and respects the Rust-core boundary memory.

### 3. Regression tests

**Rust** (`agent_scan/index.rs` test module):

- `anonymous_appears_as_agent_workflow_is_not_hidden`: insert a record with `workflow_state.is_anonymous = true`,
  `workflow_state.appears_as_agent = true`, `workflow_state.hidden = false`, `has_done_marker = 1`. Query the visible
  inbox (`include_active = true`, `include_recent_completed = true`, `include_hidden = false`). Assert the row is
  returned.
- `explicit_workflow_state_hidden_is_still_filtered`: same row but with `workflow_state.hidden = true`. Assert the row
  is **not** returned. This proves we only narrowed the predicate, not removed it.
- `migration_recomputes_hidden_for_v1_indexes`: build an index manually with `schema_version = 1` and rows that have
  `hidden = 1` but record_json showing only `is_anonymous = true` (no explicit hidden). Re-open via `open_index`. Assert
  those rows now have `hidden = 0`, and rows with explicit `hidden = 1` in record_json are untouched.

**Python** (`tests/`, integrated with the existing index test harness):

- `test_tier1_loads_anonymous_appears_as_agent_workflow`: build a fixture artifact tree containing a `tmp_*` workflow
  with `appears_as_agent: true, hidden: false`, index it, call `load_tiered_agents(full_history=False)`, assert the
  agent appears in the result and `load_state.complete_visible_inbox` is `True`.
- Parity check: assert the set of agent identities is identical between `full_history=False` and `full_history=True` for
  a fixture that contains anonymous tmp_ workflows. (This is the regression-prevention assertion that generalizes the
  current bug.)

### 4. End-to-end verification

After the Rust fix lands and bindings are rebuilt (`just install` from this repo, which re-installs `sase_core_rs` from
`../sase-core`):

1. Start `sase ace --tmux` on the user's actual workstation index (do not manually rebuild it — the in-place migration
   must do the work).
2. Capture the tmux pane.
3. Assert every agent visible in the user-supplied GOOD snapshot appears without any `,y` press:
   - Untagged: `@aww`, `@awr`, `@awq`, `@awl`, `@awk`, `@awj.r1`, `@awj`, `@aw1`.
   - `#research`: `@awm`, `@awm.r1`, `@awm.r1.r1`.
   - `#sase-3t`: `@sase-3t`, `@sase-3t.8`, `@sase-3t.6`, `@sase-3t.5`, `@sase-3t.4`, `@sase-3t.3`, `@sase-3t.7`,
     `@sase-3t.2`, `@sase-3t.1`.
4. Confirm the header still reads tier=`tier1`, source=`artifact_index`, `complete_visible_inbox=True`, and no Tier 2
   reconcile is auto-scheduled (`_agents_history_reconcile_pending` stays `False`).
5. Run `just check` for lint/type/test gates.

## Cross-Repo Dependency

This requires coordinated changes in `../sase-core`:

- `crates/sase_core/src/agent_scan/index.rs` — projection fix + migration + schema version bump + Rust tests.
- No Python wire-shape changes are required; the `WorkflowStateWire` already carries `is_anonymous` and
  `appears_as_agent` so nothing has to cross the FFI boundary differently.

After the sase-core PR lands and is published, this repo's `just install` picks up the new `sase_core_rs` build and the
Python-side tests can be written against it.

## Risks

- **Reintroducing rows that were intentionally hidden via `is_anonymous`**: Mitigated by the explicit
  `workflow_state.hidden` test — anything that genuinely wants to be hidden must set `hidden: true`, which is the
  contract every other producer already honors.
- **Migration runtime on huge indexes**: the migration only touches rows where `hidden = 1`. The largest observed local
  index has ~2,271 such rows; even an order of magnitude larger is well under a second of UPDATE work under WAL. If we
  observe pathological cases, gate the migration behind a background task and surface a `repair_recommended` hint via
  the existing Phase-7 diagnostics path.
- **Stale record_json**: a small number of indexed rows could have outdated `record_json` predating later schema fields.
  The migration tolerates parse failures by leaving `hidden` untouched; the next normal upsert repairs the row.

## Out-of-Scope Follow-Ups (not part of this fix)

- A separate pass to audit whether other Tier 1 SQL predicates (e.g. the dismissed visibility filter) make assumptions
  equivalent to "anonymous == hidden". Initial scan shows they do not, but this is worth a deliberate review once the
  immediate regression is closed.
- Surfacing schema-version mismatches through `sase agents index status --json` as called out in epic Phase 7. Useful
  operator UX but not required to fix the reported bug.
