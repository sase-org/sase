---
create_time: 2026-06-23 12:46:32
status: done
prompt: sdd/prompts/202606/linked_repo_deltas_rust_scan_fix.md
---
# Plan: Fix missing linked-repo file entries in the Agents-tab "Deltas:" panel

## Problem / Product context

On the **Agents** tab of the `sase ace` TUI, the agent metadata panel header has a **"Deltas:"** section. For the
primary workspace it lists changed files; the recently-added "linked repo deltas" feature was supposed to _also_ list
changed files in each configured linked repository (e.g. `sase-core`, `sase-github`) the agent touched.

The feature was landed in commit `a47a4ca5c "feat(tui): show linked repo deltas for agents"` (plus a follow-up
`4097b4338 "fix: serialize linked repo bundle metadata"`), but **no linked-repo file entries ever appear** in the panel.

## Root cause (confirmed)

The feature was implemented end-to-end on the **Python consumer side**, but the **Rust core producer** that builds the
agent-metadata projection consumed by the TUI was never updated.

Data flow for an active agent's linked-repo deltas:

1. Agent launch writes `agent_meta.json` containing a `linked_repos` array (`workspace_dir/.../agent_meta.json`; written
   by `run_agent_runner_setup.py` / `run_agent_directives.py`).
2. The Agents-tab loader (`src/sase/ace/tui/models/agent_loader.py`) reads agents through the **Rust core scan / SQLite
   artifact-index path** — `query_agent_artifact_index(...)` with a `scan_agent_artifacts(...)` fallback. Both call the
   Rust binding `sase_core_rs` (`src/sase/core/agent_scan_facade.py`).
3. The Rust binding returns a JSON-shaped dict; Python rehydrates it via `agent_scan_wire_from_dict(...)` →
   `AgentMetaWire(**agent_meta)` (`src/sase/core/agent_scan_wire_conversion.py`).
4. `enrich_agent_from_meta_wire(...)` sets `agent.linked_repos = parse_linked_repos(meta.linked_repos)`.
5. The header builder calls `get_cached_linked_delta_groups(agent)` which calls `_eligible_linked_repos(agent)` over
   `agent.linked_repos`; a background worker (`compute_linked_delta_groups`) shells out per linked repo and renders
   groups under "Deltas:".

**The break is at step 3's producer.** In the Rust core repo `sase-core` (linked repo; open with
`sase workspace open -p sase-core -r "<reason>" <workspace_num>`):

- `crates/sase_core/src/agent_scan/wire.rs` — the `AgentMetaWire` struct has **no `linked_repos` field** (it goes
  straight from `workspace_dir` to `approve`).
- `crates/sase_core/src/agent_scan/scanner.rs` — `agent_meta_from_object(...)` projects each field explicitly from the
  parsed `agent_meta.json` object and **never reads `linked_repos`**.

Consequently the dict handed back to Python never contains a `linked_repos` key, so `AgentMetaWire(**agent_meta)` falls
back to its default `[]`, `parse_linked_repos([])` returns `()`, and `agent.linked_repos` is **always empty** on the
scan/index/wire path the live TUI uses. `_eligible_linked_repos` then returns `()`, so no linked groups are ever
rendered.

**Why tests didn't catch it:** the commit's tests only exercise (a) the Python _filesystem_ enrichment path
(`enrich_agent_from_meta`, which reads `agent_meta.json` directly and _does_ populate `linked_repos`), and (b) a
pure-Python wire _round-trip_ (`tests/test_core_agent_scan_wire.py::test_agent_meta_output_variables_round_trip` feeds a
dict that already contains `linked_repos`). Neither test drives the real Rust **producer**, which is the only place the
field is dropped.

### Secondary concern — stale SQLite index rows

The persistent artifact index stores each record as a full `record_json` blob
(`crates/sase_core/src/agent_scan/index.rs`, serialized via `serde_json::to_string` of `AgentArtifactRecordWire`). Even
after the producer is fixed, **rows already in the index keep stale JSON without `linked_repos`** until re-upserted.
Notes:

- Only **active** agents surface linked deltas — `_status_allows_linked_deltas` excludes `Done`/`Failed` — so stale
  _completed_ rows are harmless.
- `open_index` (the read path) only does `CREATE TABLE IF NOT EXISTS`; there is currently **no
  rebuild-on-schema-mismatch**, so a stored-version change alone will not refresh existing rows.
- `upsert_record` always rewrites `record_json` (no signature short-circuit), but for a live agent
  `update_agent_artifact_index_for_marker_mutation` is only invoked on certain marker changes, so refresh timing is not
  guaranteed.

## Proposed fix

### A. Rust core producer — the actual bug fix (`sase-core` linked repo)

1. **`crates/sase_core/src/agent_scan/wire.rs`** — add a `linked_repos` field to `AgentMetaWire`, placed after
   `workspace_dir` to mirror the Python `AgentMetaWire` field order:
   `#[serde(default)] pub linked_repos: Vec<serde_json::Map<String, serde_json::Value>>`. Add the
   `serde_json::{Map, Value}` import if not already present in this module. The struct already derives
   `Serialize, Deserialize` with per-field `#[serde(default)]`, so this is purely additive and wire-compatible.

2. **`crates/sase_core/src/agent_scan/scanner.rs`** — add a small `coerce_object_list` helper (alongside the existing
   `coerce_object` / `coerce_str_list` helpers) returning `Vec<Map<String, Value>>` from a JSON array, keeping only
   object items and dropping non-objects. This mirrors the leniency of Python's `parse_linked_repos`. Then add
   `linked_repos: coerce_object_list(data.get("linked_repos"))` to `agent_meta_from_object(...)`.

3. **Rust tests** — extend `crates/sase_core/tests/agent_scan_parity.rs` (mirroring the existing
   `running_record_carries_string_output_variables` test): write an `agent_meta.json` containing a `linked_repos` array
   and assert it survives both (a) `scan_agent_artifacts(...)` and (b) an index `rebuild_agent_artifact_index(...)` →
   `query_agent_artifact_index(...)` round-trip (the re-hydrated record's `agent_meta.linked_repos` carries the
   entries).

### B. Refresh existing index rows for active agents

Goal: existing active-agent rows pick up `linked_repos` without the user manually rebuilding.

1. Bump the artifact-index schema version `4 → 5`:
   - Rust: `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` in `crates/sase_core/src/agent_scan/index.rs` (add the corresponding
     `prior_version < 5` arm in `open_index_for_rebuild`'s migration chain; no new column is needed — the refresh comes
     from re-serializing `record_json` during a full rebuild).
   - Python: `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` in `src/sase/core/agent_scan_wire.py`, and update the assertion in
     `tests/test_core_agent_scan_wire.py::test_schema_version_pinned` (`4 → 5`).
   - Note: the _wire_ schema version (`AGENT_SCAN_WIRE_SCHEMA_VERSION`, currently `1`) does **not** need bumping —
     additive wire fields are backward-compatible (the same convention used when `output_variables` was added).

2. Add a one-time **rebuild-on-stale-version** trigger so the bump actually refreshes rows. Hook it into the existing
   startup index-maintenance pass (the thread that already runs `sync_dismissed_agent_artifact_index_report` from
   `src/sase/ace/tui/actions/startup.py`, or the lifecycle helper in `src/sase/core/agent_artifact_index_lifecycle.py`):
   read the stored index schema version (via `agent_artifact_index_status` / `read_agent_artifact_index_meta`) and, when
   it is older than `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION`, run `rebuild_agent_artifact_index(...)` before the normal
   sync. This stays off the first-paint path (already threaded) and runs at most once per version change.

3. Immediate operator workaround (document in the change / commit message): `sase agent index rebuild` forces the
   refresh now.

### C. Python consumer — confirm, don't duplicate

- `src/sase/ace/tui/models/agent.py` (`LinkedRepoMetadata`, `Agent.linked_repos`),
  `_meta_enrichment_common.parse_linked_repos`, `enrich_agent_from_meta_wire`, the `AgentMetaWire.linked_repos` field,
  and the render path (`_agent_deltas`, `deltas_builder`, `_linked_deltas`) are already correct and need **no change**.
- Add a Python regression test that drives the **real scan→enrich path** (not just the round-trip): create a fixture
  project with an `agent_meta.json` containing `linked_repos`, run `scan_agent_artifacts(...)` (real Rust binding) or
  `rebuild`+`query`, enrich an `Agent`, and assert `agent.linked_repos` is populated. This is the test that would have
  caught the producer gap.

## Boundary note (per `memory/rust_core_backend_boundary.md`)

The agent-scan projection is shared core backend behavior, so the fix correctly belongs in the Rust core (`sase-core`);
the Python side is presentation/consumer glue and is already in place. When implementing, edit `sase-core` via
`sase workspace open -p sase-core -r "<reason>" <workspace_num>` and use the path it prints.

## Verification

1. **sase repo:** `just install` then `just check` (lint + mypy + tests, including the new Python regression test).
2. **sase-core repo:** `cargo test` (new parity/scanner/index tests pass; existing parity tests unaffected).
3. **Manual end-to-end:** launch an agent against a project with a configured linked repo that has local edits, open
   `sase ace`, select the agent on the Agents tab, and confirm linked-repo file entries now render under "Deltas:"
   (grouped per linked repo). Confirm completed agents still show no linked deltas (expected), and that the panel still
   renders primary-workspace deltas and file hints as before.

## Files to change

**sase-core (linked repo):**

- `crates/sase_core/src/agent_scan/wire.rs` — add `linked_repos` to `AgentMetaWire`.
- `crates/sase_core/src/agent_scan/scanner.rs` — add `coerce_object_list` + project `linked_repos`.
- `crates/sase_core/src/agent_scan/index.rs` — bump `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` 4→5 (+ migration arm).
- `crates/sase_core/tests/agent_scan_parity.rs` — new test(s).

**sase repo:**

- `src/sase/core/agent_scan_wire.py` — bump `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` 4→5.
- `tests/test_core_agent_scan_wire.py` — update pinned version; (optionally) extend coverage.
- Startup/lifecycle (`src/sase/ace/tui/actions/startup.py` and/or `src/sase/core/agent_artifact_index_lifecycle.py`) —
  rebuild-on-stale-version trigger.
- New Python regression test driving the real scan→enrich path.

## Out of scope

- Redesigning the linked-repo diff computation/caching (`_linked_deltas.py`) — it works once `agent.linked_repos` is
  populated.
- Changing linked-repo resolution/config (`src/sase/linked_repos.py`).
- The primary-workspace delta rendering and file-hint behavior (unchanged).
