---
create_time: 2026-05-28
status: research
---

# Episode V2 Architecture Critique

## Question

What is the current state and trajectory of SASE memory episodes, using the `sase-48` epic bead as the breadcrumb, and
are there concerning architectural problems before the design grows into curated `sdd/events/`?

## Short Answer

The direction is broadly right: private episodes should be source-linked connected evidence under project state, while
reviewed `sdd/events/` should be rare, repo-safe, curated memory. The concerning part is not the destination; it is the
transition plan and current execution shape.

The system is now halfway between two models. Phase 1 of `sase-48` landed the v2 wire contract in `sase-core` and the
Python facade, but the active Python product surface still behaves like v1: one `build` command collects one draft,
builds one episode, derives lessons, writes `lesson.md`, and recalls from lesson text. At the same time, the epic has
phases 2 through 9 marked `in_progress` even though their bead dependencies are linear. That is the largest operational
risk: downstream agents can implement UI, worker, export, or event-adjacent behavior against contracts that are still
moving.

Do not start `sdd/events/` implementation from the current episode behavior. First prove connected-component splitting,
stable IDs, member/alias resolution, v2 no-lesson storage, and v2-native recall on a real corpus.

## Local Evidence Reviewed

- `sase bead show sase-48`: one closed child (`sase-48.1`) and eight in-progress children (`sase-48.2` through
  `sase-48.9`).
- `sdd/epics/202605/episode_v2_explorer.md`: the current nine-phase epic plan.
- `sdd/research/202605/memory_episode_connected_components_and_events.md`: connected components, automatic builder,
  dreamer, and event-promotion research.
- `sdd/research/202605/git_versioned_episodic_events.md`: curated event-card research and `sdd/events/` design.
- `docs/episodes.md` and `docs/memory.md`: current public episode semantics.
- `src/sase/memory/cli_episodes.py`, `src/sase/memory/episodes/*`, and the episode tests.
- `/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_12/crates/sase_core/src/episode/*`: current
  shared wire implementation.

## Current State

Phase 1 is real. The current heads reviewed were:

- main repo: `010721231 feat: add episode v2 Python wire compatibility (sase-48.1)`;
- core repo: `123f0a7 feat: add episode v2 wire contract (sase-48.1)`.

The Rust wire schema is now `EPISODE_WIRE_SCHEMA_VERSION = 2` and includes v2 fields such as `component_key`,
`component_root_kind`, `status`, `importance_score`, `importance_band`, `importance_factors`, `safety`, and
`weak_refs`. Python mirrors those dataclasses and has compatibility conversion for v1 records.

The product behavior is still v1-centered:

- `cli_episodes._handle_build` still runs `collect_episode_draft(...) -> build_episode(...) -> render_lesson_markdown(...)
  -> write_project_episode(...)` once per command.
- `storage.write_project_episode` always writes `episode.json`, `lesson.md`, and `sources.jsonl`.
- `EpisodeStorageIndexRowWire` still has `lesson_path` as a live field, plus `legacy_lesson_path`.
- `recall.recall_episode_rows` still reads lesson text and returns lesson cards.
- `parser_memory_episodes.py` exposes no `--split`, `--aggregate`, `auto`, `status`, `doctor`, inventory filters, graph
  view, agent evidence-pack view, or event export.
- There is no `src/sase/memory/episodes/components.py`, `importance.py`, `auto_build.py`, or `views.py` yet.
- There is no top-level `sdd/events/` directory in this checkout.

The collector already proves why v2 is needed. `_collector_record.py` queues related records through ChangeSpec, bead,
and agent-family edges, and `_collector_graph.py` currently bounds transitive expansion by date for project scans. That
was a reasonable v1 fix, but it is not the intended v2 model where date windows select seeds only and strong lineage
edges define membership.

## Trajectory Assessment

The planned destination in `sase-48` is coherent:

1. put shared schema and identity helpers in `sase-core`;
2. introduce a connected-component planner over strong lineage edges;
3. add member and alias indexes so stable IDs survive retries, forks, and late bridges;
4. remove episode-owned lessons for v2 and replace them with factual evidence, importance, safety, and drill-down views;
5. add inventory, TUI explorer, automatic builder, status/doctor, recall/export, and documentation;
6. leave `sdd/events/` writes out of the epic.

That ordering is correct on paper. The risky trajectory is that the bead state has phases 2 through 9 all assigned and
in progress while their dependencies are still unresolved. The phase boundaries are not cosmetic. Phase 5 inventory
depends on Phase 3 identity and Phase 4 index fields. Phase 7 TUI depends on Phase 6 view models. Phase 8 worker
depends on Phase 2 component planning and Phase 3 crash-safe merge semantics. Phase 9 recall/export depends on Phase 4
no-lesson records.

If those phases are actually running in parallel, expect contract churn, duplicated temporary abstractions, and merge
conflicts around CLI JSON shapes, index rows, and renderer defaults. If the in-progress statuses are only a tracking
artifact of the epic launcher, make that explicit in bead notes so future readers do not infer that all downstream
contracts are ready.

## Architectural Problems

### 1. V2 Wire Landed Before V2 Semantics

Adding schema fields first was the right boundary move, but it creates a deceptive "v2 exists" state. New episodes built
today can serialize with schema version 2 while still having empty `component_key`, content-set IDs, non-empty
`lessons`, and `lesson.md` as the main UI.

That is dangerous for downstream code because schema version alone no longer implies v2 behavior. Consumers need an
explicit semantic discriminator, probably `status`, `component_key`, and maybe a migration marker. Until Phase 4 lands,
"schema 2" means "v2-capable wire," not "v2 episode."

### 2. `lesson_path` Is Becoming A Zombie Contract

The plan says v2 private episodes should not write `lesson.md`, but the current storage/index/recall contract still
requires `lesson_path`. Phase 1 added `legacy_lesson_path` but did not remove `lesson_path`, which is understandable
for compatibility. The risk is that new code continues to depend on `lesson_path` because it remains convenient.

Recommendation: introduce an explicit v2 row shape or at least a strong invariant:

- v1/legacy rows may have `legacy_lesson_path`;
- v2 rows should have no required `lesson_path` value;
- recall and show must not fall back to rendering lessons for v2 rows;
- tests should fail if a v2 write creates `lesson.md`.

### 3. Strong And Weak Edges Are Still Entangled

The desired model is clear: strong lineage edges define membership, weak topic refs are metadata. The current collector
does not yet enforce that separation. It records and follows ChangeSpec, bead, and family links as transitive
membership. This is exactly the old "one topic bag" problem.

The component planner must be the gate before any UI or worker code. Without it, automatic building will produce a
large number of plausible but wrongly grouped episodes, and the dreamer/event layer will learn from polluted inputs.

### 4. Stable Identity Needs A Concrete Merge Policy Before UI

`stable_v2_episode_id(project, component_key)` exists in core, but member and alias indexes do not. Late bridges are
the hard case. If two previously stored components later become one connected component, the system needs a deterministic
canonical winner, alias rows for the losers, and read paths that resolve aliases without rewriting old directories.

Until that is implemented, the TUI should avoid actions that imply episode IDs are durable permalinks. The explorer can
be built after alias resolution exists, not before.

### 5. Automatic Build Has Shared-State Concurrency Risk

Episodes live under `~/.sase/projects/<project>/episodes/`, shared by many ephemeral `sase_<N>` workspaces. Storage
already uses a lock and atomic replace for episode writes and index rows, which is good. The future worker adds more
shared mutable files: `members.jsonl`, `aliases.jsonl`, `build_state.json`, metrics, and event proposals.

Do not treat the existing index lock as enough by default. The worker needs one transaction boundary that covers episode
upserts, member/alias writes, index updates, and checkpoint advancement. If checkpoint advancement can commit without
member/alias/index consistency, later runs will skip seeds while losing merge knowledge.

### 6. The Phase Plan Is Too Wide For One Epic Run

The `sase-48` epic is effectively a product rewrite: schema, planner, migration, storage, importance, safety, CLI,
renderers, TUI, background worker, status, doctor, metrics, recall, export, docs, and pilot. The plan is well-written,
but it is too broad to let downstream phases run on assumptions.

Recommendation: split the execution gates, even if the bead remains one epic:

- Gate A: component planner plus tests, no storage changes.
- Gate B: stable identity, members, aliases, v1 compatibility.
- Gate C: v2 no-lesson write/read/recall semantics.
- Gate D: inventory and drill-down CLI.
- Gate E: TUI and automatic builder.
- Gate F: pilot and docs.

Each gate should close only after focused tests and a small manual corpus check.

## `sdd/events/` Assessment

The high-level `sdd/events/` plan is worth keeping. The strongest version is still:

```text
raw chats/artifacts
  -> private connected episodes in ~/.sase/projects/<project>/episodes/
  -> project-local event proposals
  -> reviewed sdd/events/YYYYMM/... files
  -> optional memory/long proposal using the event as evidence
```

This preserves the trust boundary. Episodes are generated evidence. Events are reviewed project history. Long memory is
instructional only after the existing memory review flow.

The concerns are mostly format and timing:

1. `sdd/events/` does not exist yet, which is good. Keep it out of `sase-48` until the episode pilot is clean.
2. The two research notes disagree on storage shape:
   - `git_versioned_episodic_events.md` recommends one markdown file per event:
     `sdd/events/YYYYMM/<YYYYMMDD>-<slug>-<short-hash>.md`.
   - `memory_episode_connected_components_and_events.md` recommends a directory with `lesson.md`:
     `sdd/events/YYYYMM/<event_id>/lesson.md`.
3. `lesson.md` is understandable, but it risks recreating the same terminology problem v2 episodes are escaping.
   Events should be evidence cards with "what happened," "why it matters," "future retrieval guidance," and "what not
   to infer." They should not sound like active instructions unless they have been promoted into `memory/long`.
4. If events are directory-per-event, the extra directory should buy something concrete: attachments, generated
   validation reports, source manifests, or redaction reports. If v1 only needs one reviewed markdown card, the
   one-file format is simpler, easier to diff, and easier to index.
5. The event parser, frontmatter validator, and search/index semantics belong in `sase-core`, not only Python, because
   CLI, TUI, editor, mobile, and future web surfaces must agree.
6. `sase memory search` is not implemented yet. `sdd/events/` without search is just another SDD archive. Implement
   search and provenance labels before expecting agents to benefit from events.

Recommended decision before implementation: choose one v1 event path contract and write `sdd/events/README.md` before
adding promotion commands. My preference is one file per event for v1:

```text
sdd/events/
  README.md
  202605/
    20260528-episode-v2-architecture-critique-a1b2c3.md
```

Use directory-per-event only if the first implementation will actually store sibling files beside `lesson.md`.

## Recommended Next Moves

1. Freeze downstream `sase-48` phases until Phase 2 has a tested `EpisodeComponentPlan` and a split project-scan path.
2. Add tests that prove ChangeSpec, bead, family, same path, and same date do not merge unrelated components.
3. Add tests that prove a seed inside a date window can pull strong retry/fork/workflow lineage outside the window.
4. Do not let schema version be the only v1/v2 discriminator. Add explicit semantic compatibility tests for schema-2
   records with and without `component_key`.
5. Land member/alias indexes before TUI IDs or automatic worker checkpoints become user-visible.
6. Remove v2 `lesson.md` writes before recall/export/TUI work. Otherwise every later surface will accidentally keep the
   old artifact alive.
7. Run a pilot over the May 2026 corpus before enabling any background worker by default.
8. Defer `sdd/events/` implementation until after the pilot. When it starts, begin with README, validator, search
   index, and proposal/review flow. Do not start with a dreamer that writes repo files.

## Bottom Line

The architectural idea is sound, but the system needs stricter sequencing. The connected-component planner is the hinge.
If it is correct, `sdd/events/` can become a useful curated memory layer. If it is wrong or bypassed, events will launder
noisy generated summaries into reviewed repo history and make future agents more confident for the wrong reasons.
