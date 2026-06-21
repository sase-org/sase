---
create_time: 2026-06-21 11:10:45
status: done
prompt: sdd/prompts/202606/fix_linked_repo_bundle_serialization.md
---
# Fix: `LinkedRepoMetadata is not JSON serializable` on agent kill

## Problem

Killing (or dismissing) an agent in the `sase ace` TUI fails with a notification like:

```
Error: Kill cleanup failed for sase: Object of type LinkedRepoMetadata is not JSON serializable
```

The kill appears to "work" optimistically in the UI, but the background cleanup task that persists the dismissed-agent
bundle raises, so the agent's bundle is never written to disk and the user sees a recurring error. This reproduces for
any agent that was launched while linked repositories are configured — which is the normal case in this repo
(`sase-core`, `sase-github`, `sase-telegram`, `sase-nvim` are all linked).

## Root cause (verified)

The dismissed-agent **bundle serializer** does not know how to serialize the `Agent.linked_repos` field.

- `Agent.linked_repos` is typed `tuple[LinkedRepoMetadata, ...]` (`src/sase/ace/tui/models/agent.py`). It is populated
  during metadata enrichment from `agent_meta.json["linked_repos"]` via `parse_linked_repos`
  (`src/sase/ace/tui/models/_loaders/_meta_enrichment_common.py`). `LinkedRepoMetadata` is a frozen dataclass (`name`,
  `workspace_dir`, `workspace_strategy`).

- `to_bundle_dict(agent)` (`src/sase/ace/tui/models/agent_bundle.py`) walks every dataclass field and only special-cases
  `AgentType`, `datetime`, lists-of-`datetime`, and `dict`. A `tuple` of `LinkedRepoMetadata` passes through
  **unconverted**, so the produced bundle dict contains raw `LinkedRepoMetadata` instances.

- The kill/dismiss persistence path calls `save_dismissed_bundle(agent)` → `save_dismissed_bundle_python(...)` →
  `write_json_file_atomic(...)` → `json.dump(data, ...)` (`src/sase/ace/dismissed_agents_bundles.py`). `json.dump`
  cannot serialize a `LinkedRepoMetadata`, so it raises
  `TypeError: Object of type LinkedRepoMetadata is not JSON serializable`.

- The exception bubbles up into the tracked cleanup worker, which formats it as
  `f"Kill cleanup failed for {agent.display_name}: {exc}"` (`src/sase/ace/tui/actions/agents/_kill_tasks.py`,
  single-kill path; the bulk path produces the analogous `"Bulk kill cleanup failed: ..."`).

Reproduced directly: building an `Agent` with one `LinkedRepoMetadata` and calling `json.dumps(agent.to_bundle_dict())`
raises the exact reported error.

### All trigger paths

Every code path that persists a bundle goes through `to_bundle_dict` and is therefore affected:

1. `_persist_workflow_kill` (kill kind `"workflow"`) → `save_dismissed_bundle(agent)`.
2. `persist_dismiss_side_effects` / `_save_dismissed_bundles_for` (the dismiss flow).
3. `persist_cleanup_side_effect_intents` `bundle_save_candidates` (the Rust cleanup-plan intent path).

### Secondary latent bug (same class, found while diagnosing)

`to_bundle_dict` skips the load-time-only `list[Agent]` fields `followup_agents`, `runtime_children`, and
`attempt_history`, but it does **not** skip `retry_chain_siblings`, which is also a load-time-populated `list[Agent]`.
It is normally empty at save time, so it is masked today — and even when populated it sorts _after_ `linked_repos` in
dataclass field order, so `linked_repos` raises first. Confirmed by reproduction: with `retry_chain_siblings` populated,
the bundle raises `Object of type Agent is not JSON serializable`.

Consequence: fixing only `linked_repos` would expose this as the _next_ failure when a retry-chain **root** agent is
killed. The fix must close both holes together so we don't trade one serialization crash for another.

### Why this is a Python-only fix (Rust boundary check)

Per `memory/rust_core_backend_boundary.md` I checked the sibling Rust core. The Rust entry point
`save_dismissed_bundle_json(bundles_root, bundle: &JsonValue)` (and its pyo3 wrapper) accept an **already-built JSON
value** and persist it as opaque text; Rust never constructs the `linked_repos` field. The defect is entirely in the
Python TUI-model → JSON conversion (presentation-layer persistence of the `Agent` Textual model). No Rust
wire/API/binding change is required, and there is no cross-frontend behavior to keep in parity here.

## Fix design

All changes are in **`src/sase/ace/tui/models/agent_bundle.py`** plus tests.

### 1. Serialize `linked_repos` in `to_bundle_dict`

Convert the tuple of `LinkedRepoMetadata` into a JSON-native list of dicts (the dataclass is flat, so
`dataclasses.asdict` per element is sufficient and mirrors the shape `parse_linked_repos` already reads):
`[{"name": ..., "workspace_dir": ..., "workspace_strategy": ...}, ...]`. An empty tuple serializes to `[]`.

### 2. Skip `retry_chain_siblings` in `to_bundle_dict`

Add `retry_chain_siblings` to the existing skip set alongside `followup_agents` / `runtime_children` /
`attempt_history`. It is a load-time-only relationship field and must never be embedded in a bundle.

### 3. Reconstruct `linked_repos` in `from_bundle_dict`

When loading a bundle, convert the list-of-dicts back into `tuple[LinkedRepoMetadata, ...]` so the field's runtime type
is preserved for consumers (e.g. `_eligible_linked_repos`, `src/sase/ace/tui/widgets/file_panel/_linked_deltas.py`).
Reuse the existing, already-hardened `parse_linked_repos` helper (lazy/function-level import to avoid any import-cycle
risk, matching the file's existing lazy-import style). Old bundles that predate this fix simply have no `linked_repos`
key and load as the empty-tuple default — backward compatible.

### Optional hardening (recommended, low cost)

Add a regression guard so any _future_ non-JSON-serializable field is caught by the test suite rather than in
production: a test that builds a broadly-populated `Agent` and asserts `json.dumps(agent.to_bundle_dict())` does not
raise. (This same guard would have caught both bugs above.)

## Test plan

Add to `tests/test_agent_model_bundle.py` (matches the existing round-trip test style there):

1. **`linked_repos` round-trips**: an `Agent` with one or more `LinkedRepoMetadata` → `to_bundle_dict` produces a list
   of plain dicts → `json.dumps` succeeds → `from_bundle_dict` restores `linked_repos` as a
   `tuple[LinkedRepoMetadata, ...]` with equal values.
2. **Empty `linked_repos`** stays an empty tuple through the round-trip (default-path regression).
3. **`retry_chain_siblings` is never serialized**: populate it with a child `Agent`, assert the field is absent from the
   bundle dict and `json.dumps(bundle)` succeeds.
4. **JSON-serializable guard**: broadly-populated `Agent` (including `linked_repos`) → `json.dumps(to_bundle_dict(...))`
   does not raise.

Consider one integration-level assertion that exercises the actual kill/dismiss persistence (e.g. extend a test under
`tests/test_dismissed_bundle_persistence.py` or `tests/test_agent_dismiss_persistence.py`) so a linked-repo agent can be
dismissed and its bundle written + reloaded end-to-end, guarding the real `save_dismissed_bundle` path and not just the
serializer in isolation.

## Out of scope / non-goals

- No changes to `LinkedRepoMetadata`, linked-repo resolution, or metadata enrichment.
- No Rust (`sase-core`) changes (see boundary check above).
- No CLI/skill/config changes (no new subcommands or options), so no CLI-rules or generated-skill sync needed.

## Risks & verification

- **Risk**: a downstream consumer expects `linked_repos` to be a `tuple` rather than a `list` after revive. Mitigated by
  step 3 (reconstruct to a tuple) and the round-trip test.
- **Verification**: `just check` (lint + mypy + tests). The new tests fail before the fix and pass after. Optionally
  smoke-test by dismissing/killing a linked-repo agent in `sase ace` and confirming no "Kill cleanup failed"
  notification and a bundle file is written.
