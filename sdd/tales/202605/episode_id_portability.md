---
create_time: 2026-05-31 15:25:56
status: done
prompt: sdd/prompts/202605/episode_id_portability.md
---
# Episode ID Portability Fix Plan

## Problem

Recent May 2026 episode/event research identifies a concrete identity defect in v2 memory episodes:

- `src/sase/memory/episodes/components.py` derives durable `component_key` values from `normalize_source_path(...)`.
- `normalize_source_path(...)` resolves to machine-absolute paths.
- `build_episode(...)` generates v2 episode IDs from `generate_v2_episode_id(project, component_key)`.

That means the same logical connected component can receive different episode IDs under different home directories,
workspace roots, restored project-state roots, or machines. Existing v2 pilot data may already contain these
path-dependent IDs. Absolute paths are still useful source evidence, but they should not feed durable episode identity.

## Current Code Shape

The current implementation already has useful pieces to build on:

- v2 split planning exists in `src/sase/memory/episodes/components.py`.
- v2 episode IDs are already root-key based, not full-source-set based, via
  `src/sase/core/episode_facade.py::generate_v2_episode_id`.
- storage already writes `members.jsonl` and `aliases.jsonl` and resolves aliases in CLI/read paths.
- storage preserves legacy episode directories and can alias older IDs during v1 migration or late bridges.

The missing contract is a path-independent `component_key` and a migration path for v2 episodes whose existing component
keys were derived from absolute paths.

## Goals

1. Make v2 component episode IDs stable across different `projects_root`, chat root, and workspace paths for the same
   logical agent/chat component.
2. Keep absolute filesystem paths in source refs, verification, graph nodes, and local evidence.
3. Preserve existing stored episodes and map old path-dependent IDs to the new canonical ID when a component is rebuilt.
4. Add regression tests that fail against the current absolute-path behavior.
5. Keep the change scoped to episode identity; do not implement the future `sdd/events` or `sase memory search` work.

## Non-Goals

- Do not rewrite or delete existing episode directories.
- Do not make private episode IDs the canonical identity for future repo-portable event cards.
- Do not move the entire component planner into Rust in this change.
- Do not change source-ref hashing or verification semantics.

## Design

### 1. Introduce Logical Component Keys

Update `_component_root(...)` in `components.py` so the durable `component_key` uses logical runtime identity rather
than absolute paths.

Recommended key families:

- artifact-rooted component: project, workflow directory, and compact root timestamp;
- retry-rooted component: project, workflow directory, and `retry_chain_root_timestamp` when present;
- workflow/root-agent component: project, workflow directory, and root timestamp from `episode_trace.root_timestamp`
  when present;
- chat-only component: project, chat basename, and a content hash when the transcript exists.

The exact string format should be deterministic, compact, and path-free. For example:

```text
component/artifact/<project>/<workflow>/<timestamp>
component/retry-root/<project>/<workflow>/<timestamp>
component/workflow-root/<project>/<workflow>/<timestamp>
component/chat/<project>/<chat-basename>/<sha256-prefix>
```

Absolute artifact/chat paths should remain in `EpisodeComponentPlan.artifact_dirs`, `EpisodeComponentPlan.chat_paths`,
source refs, graph metadata, and verification output.

### 2. Keep Internal Graph Keys Separate From Durable Identity

The planner may continue using absolute `_record_key(...)` and `_chat_key(...)` values internally for union-find and
local evidence lookup. Those keys are local graph addresses, not durable IDs.

To make that boundary explicit, add small helper names/tests that distinguish:

- local planner keys: absolute artifact/chat addresses used for graph traversal;
- durable component keys: path-independent identity input for `generate_v2_episode_id`;
- member keys: stored lookup keys used by alias/merge resolution.

### 3. Add Path-Independent Member Keys Without Dropping Legacy Ones

`episode_member_keys(...)` currently records absolute chat/artifact member keys plus `component:<component_key>`. Keep
those absolute member keys for local compatibility and old-row migration, but add logical member keys where the episode
has enough data:

- `component:<component_key>`;
- `artifact:<project>/<workflow>/<timestamp>` for sources/nodes under `projects/<project>/artifacts/<workflow>/<ts>`;
- `chat:<basename>/<sha256-prefix>` when a chat source has a SHA-256;
- existing absolute `artifact:<abs-path>` and `chat:<abs-path>` rows for compatibility.

This lets rebuilt episodes find prior local rows through old absolute keys while also making future member indexes less
root-sensitive.

### 4. Migrate Existing Path-Dependent V2 IDs Through Aliases

Change storage identity selection so an existing non-legacy v2 episode with an absolute-path-derived component key does
not permanently win over the new logical ID.

Add detection for old path-dependent component keys, such as:

- `component/artifact/<project>/<timestamp>/<absolute-path...>`;
- `component/chat/<absolute-path...>`.

When a new logical v2 episode shares members with an old path-dependent v2 episode:

- store the rebuilt episode under the new desired ID;
- add an alias row from the old episode ID to the new ID;
- preserve the old directory on disk;
- use a distinct reason such as `component_key_migration`.

Keep the existing behavior for true v1 legacy migration and late bridges.

### 5. Tests

Add focused tests before or alongside implementation:

- two equivalent artifact fixtures under different `projects_root` values produce the same `component_key`;
- those fixtures also produce the same v2 `episode_id`;
- chat-only components under different chat roots with the same transcript content do not include absolute paths in
  `component_key` and produce the same ID;
- persisted old path-dependent v2 episodes are aliased to the new canonical ID on rebuild;
- member rows include the new logical member keys and still include legacy absolute keys for compatibility;
- existing split-build CLI tests continue to pass and still omit `lesson.md` for v2 components.

Focused validation commands:

```bash
pytest tests/test_memory_episodes_components.py \
  tests/test_memory_episodes_storage.py \
  tests/test_memory_episodes_cli_build.py \
  tests/test_memory_episodes_e2e.py
```

After source changes, run the repo-required validation:

```bash
just install
just check
```

## Implementation Order

1. Add failing regression tests for path-independent component keys and old-v2 alias migration.
2. Refactor `components.py` to compute logical durable component keys while leaving local graph keys/path refs intact.
3. Extend `identity.py` member-key generation with logical keys while preserving absolute keys.
4. Update `storage.py` canonical-ID selection and alias reason handling for old path-dependent v2 component keys.
5. Update any brittle expected component-key strings in tests or docs if they assume the old absolute-path shape.
6. Run focused tests, then `just install && just check`.

## Risks And Mitigations

- Risk: changing component keys changes IDs for existing v2 component episodes. Mitigation: alias old path-dependent v2
  IDs to the new logical IDs and preserve old directories.

- Risk: using chat content hashes can change chat-only IDs if a transcript is edited. Mitigation: chat-only components
  are a fallback for legacy evidence. Artifact-rooted runtime identity should dominate whenever an artifact record
  exists.

- Risk: adding logical member keys could accidentally merge unrelated episodes. Mitigation: keep logical artifact keys
  scoped by project, workflow, and timestamp; keep chat keys hash-backed; add tests for unrelated same-date records
  remaining split.

- Risk: Rust/Python identity drift later. Mitigation: keep the immediate fix in the Python planner where component
  planning currently lives, but pin golden expectations around the path-free key strings and IDs. If another frontend
  starts building component plans, move the pure key helpers behind `sase-core` bindings.

## Expected Outcome

After this change, rebuilding the same logical v2 component under another workspace or machine root should produce the
same durable `component_key` and `episode_id`. Existing absolute-path-derived v2 IDs should remain resolvable through
aliases, while source refs continue to preserve absolute local evidence for verification.
