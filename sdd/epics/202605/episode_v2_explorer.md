---
create_time: 2026-05-28 17:16:13
bead_id: sase-48
tier: epic
status: done
prompt: sdd/prompts/202605/episode_v2_explorer.md
---

# Plan: Memory Episode V2, Connected Components, And Episode Explorer

## Context

SASE already has a structured episode MVP, but the current implementation still reflects the first concept: a build
command collects one draft, builds one episode, renders one `lesson.md`, stores one index row, and recalls stored lesson
text. That was a useful MVP, but it is the wrong foundation for future `sdd/events/`.

The newer research in `sdd/research/202605/memory_episode_connected_components_and_events.md` changes the model:

- private episodes are deterministic connected components over agent/chat lineage;
- curated events are rare, reviewed repo artifacts under `sdd/events/YYYYMM/<event_id>/lesson.md`;
- date windows select seed records only, and never define episode boundaries;
- strong lineage edges define component membership;
- weak topic edges such as ChangeSpec, bead, same family, and touched paths stay as metadata;
- private episodes should not own `lesson.md`; durable lessons belong to curated events later.

The user-facing gap is bigger than the architecture gap. Today a user can run `list`, `show`, `verify`, and `recall`,
but there is no strong way to answer:

- What episodes exist for this week/day/time range?
- Which ones matter most, and why?
- Which chats, agents, retries, workflow steps, artifacts, ChangeSpecs, and beads are inside this episode?
- Is this an actual connected work episode, or a bag of topic-nearby work?
- What should an agent consume as compact evidence without treating the episode as active instructions?

This plan rewrites episodes to be rock solid before any event work starts. It deliberately does not implement SASE
events, event promotion, dreamer proposals, or `sdd/events/` writes.

## Current State Reviewed

Primary repo:

- `src/sase/memory/cli_episodes.py` dispatches `build`, `list`, `show`, `verify`, and `recall`. `build` currently calls
  `collect_episode_draft`, `build_episode`, `render_lesson_markdown`, and `write_project_episode` exactly once.
- `src/sase/memory/episodes/_collector_seed.py` project scans seed all matching records into one collector queue.
- `src/sase/memory/episodes/_collector_record.py` records many useful edges, but also queues ChangeSpec, bead, and
  agent-family related records as transitive membership.
- `src/sase/memory/episodes/_collector_graph.py` bounds project-scan transitive expansion by date; the desired v2
  behavior is the opposite for strong lineage edges: date filters seed only, then strong connected work can expand
  beyond the window.
- `src/sase/memory/episodes/builder.py` derives `EpisodeLessonWire` records and uses
  `generate_episode_id(project, root_source_id, sources)`, so adding a later connected fork changes the source set and
  therefore the ID.
- `src/sase/memory/episodes/storage.py` always writes `episode.json`, `lesson.md`, and `sources.jsonl`, and index rows
  point to `lesson_path`.
- `src/sase/memory/episodes/recall.py` searches rendered lesson text plus lesson records.
- `docs/episodes.md` documents the v1 lesson-centered model.

Core repo:

- `../sase-core/crates/sase_core/src/episode/wire.rs` owns the shared v1 wire schema. It includes `lessons` on
  `EpisodeWire` and `lesson_path` on `EpisodeStorageIndexRowWire`.
- `../sase-core/crates/sase_core/src/episode/mod.rs` owns canonical JSON, source IDs, content-set episode IDs, and
  source verification.
- `../sase-core/crates/sase_core_py/src/lib.rs` exposes the episode helpers to Python.

Existing implementation should be treated as v1 compatibility, not deleted or rewritten in place.

## Product Contract

### Episode Definition

A v2 episode is a private, project-scoped, deterministic connected component of work evidence. It is built from raw
agent artifacts, chat transcripts, workflow step markers, retry/parent/fork lineage, and source refs. It is evidence,
not instruction.

Strong edges define episode membership:

- runtime-written chat links: `done.response_path`, `agent_meta.chat_path`, `episode_trace.chat_path`;
- `## Linked Chats` transcript sections;
- `#fork`, `#fork_by_chat`, `#resume`, and `#resume_by_chat` when resolved to a real chat or runtime artifact;
- `parent_timestamp`, `parent_agent_timestamp`, retry parent/child/root fields;
- `prompt_step_*.json.response_path` and `workflow_step_agent` links;
- workflow root/child artifact links written by SASE runtime metadata.

Weak edges are metadata only:

- ChangeSpec co-mention;
- bead co-mention;
- agent family;
- same touched file path;
- same date window;
- shared user or model/provider.

### Event Readiness Boundary

Episodes should carry enough structured metadata for future event selection:

- stable `episode_id`;
- stable `component_key`;
- first/last event timestamps;
- importance score, band, and factors;
- source refs and verification state;
- weak metadata edges;
- safety flags for untrusted transcript text or redaction hits.

They must not write `sdd/events/`, must not write event proposals, and must not create or update `memory/short` or
`memory/long`.

### User Visibility Contract

The episode surface must make the time-period inventory and drill-down path excellent.

Required inventory answers:

- list episodes by `--since` and `--until`;
- group by day or week;
- filter by importance band, agent, ChangeSpec, bead, status, and query text;
- show time span, title, component size, source count, connected agent/chat counts, importance, status, and warnings;
- emit stable JSON for agents and external tools.

Required drill-down views:

- `overview`: compact human summary, status, importance factors, participants, warnings, and next useful commands;
- `timeline`: ordered events grouped by run/chat where possible, with evidence IDs;
- `graph`: deterministic visual component graph with strong edges emphasized and weak metadata available on request;
- `sources`: grouped source refs with existence/hash status and source labels;
- `agent`: bounded, prompt-safe evidence pack for future agents, explicitly marked as evidence and not instructions;
- `json`: canonical machine-readable episode.

The CLI can ship first, but ACE TUI support is not optional for this effort: users should be able to browse a time range
and drill into an episode without copying IDs between commands.

## Cross-Phase Rules

- Start every phase with `git status --short` in every repo touched.
- Use `sase workspace open -p sase-core 12` before reading or editing the matching `sase-core` workspace from this
  numbered workspace.
- Shared episode schema, canonical identity, and backend semantics belong in `../sase-core`.
- Python should call Rust helpers or thin adapters for shared semantics.
- Preserve v1 episodes. Do not rewrite old `episode.json` or delete old `lesson.md` files silently.
- Every new CLI option needs both a short and long option unless an existing collision is documented and unavoidable.
- New episode storage remains under `~/.sase/projects/<project>/episodes/`.
- No phase may create `sdd/events/` files, event proposals, or memory writes.
- If this repo changes, run `just install` before focused tests and `just check` unless the phase is documentation-only
  and covered by the repo exceptions.
- If `sase-core` changes, run the relevant Rust format, clippy, and test commands in that workspace.

## Phase 1: Episode V2 Wire Contract And Compatibility

Owner: one agent instance.

Write scope:

- `../sase-core/crates/sase_core/src/episode/*`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/episode_wire*.py`
- `src/sase/core/episode_facade.py`
- Rust/Python parity tests and Python wire tests.

Purpose: define the shared v2 contract before changing collection, storage, or UI.

Concrete work:

- Bump the episode wire schema to v2 while keeping v1 deserialization/read compatibility.
- Add v2 fields to `EpisodeWire`:
  - `component_key`;
  - `component_root_kind`;
  - `status` such as `active`, `superseded`, or `legacy`;
  - `importance_score`;
  - `importance_band`;
  - `importance_factors`;
  - `safety`;
  - `weak_refs` or equivalent structured metadata for ChangeSpecs, beads, families, and touched paths.
- Keep `lessons` parseable but deprecated. New v2 episodes should normally have an empty `lessons` list.
- Add or replace index-row fields:
  - `component_key`;
  - `status`;
  - `summary_excerpt`;
  - `first_event_at`;
  - `last_event_at`;
  - `importance_score`;
  - `importance_band`;
  - `root_agent_names`;
  - `chat_count`;
  - `agent_count`;
  - `source_count`;
  - `content_sha256`;
  - optional `legacy_lesson_path` for v1 rows only.
- Add Rust helper for stable v2 IDs:
  - `episode_id = hash(project, component_key)`;
  - keep the old content-set ID helper for v1 compatibility and tests.
- Add conversion helpers that can load v1 rows/episodes and expose compatibility defaults without mutating disk.
- Update PyO3 bindings and Python facades in lockstep.

Acceptance:

- Rust/Python parity tests prove the v2 fixture serializes identically.
- A v1 fixture with `lessons` and `lesson_path` still parses and verifies.
- A v2 fixture with no `lessons` parses, canonicalizes, and has a stable ID from `component_key`.
- No CLI behavior changes in this phase.

## Phase 2: Connected Component Planner

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/components.py` or equivalent new module;
- `src/sase/memory/episodes/_collector_*` only as needed to support component-scoped collection;
- component planner tests and collector tests.

Purpose: make episode boundaries correct.

Concrete work:

- Add an `EpisodeComponentPlan` DTO with:
  - project;
  - `component_key`;
  - `component_root_kind`;
  - root timestamp/chat key;
  - artifact dirs;
  - chat paths;
  - strong edges;
  - weak refs;
  - seed reason;
  - existing episode IDs discovered through member/alias lookup when available.
- Build a union-find planner over scan records and chat catalog entries.
- Extract only strong lineage edges for union operations.
- Extract weak ChangeSpec, bead, family, and touched-path refs without using them to union components.
- Make date windows seed filters only:
  - a seed inside the window may pull strong ancestors/children outside the window;
  - unrelated records inside the same date range become separate component plans.
- Add collection from a component plan, so the existing rich graph collector can build one draft per component.
- Keep old aggregate collection available behind an explicit compatibility path for one release.

Acceptance:

- A date-bounded project scan with three unrelated chats yields three component plans.
- A seed inside the date range pulls an out-of-window retry/fork/parent through strong lineage.
- Two records sharing a ChangeSpec remain separate components.
- Two records sharing a bead remain separate components.
- Two records sharing an agent family remain separate components unless another strong edge connects them.
- Planner output is byte-stable across repeated runs.

## Phase 3: Stable Identity, Members, Aliases, And V1 Migration

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/storage.py`
- `src/sase/memory/episodes/index.py`
- new member/alias index helpers;
- `src/sase/memory/cli_episodes.py` for alias resolution only;
- focused tests.

Purpose: make episode IDs and merging robust before the UI depends on them.

Concrete work:

- Add storage files:
  - `members.jsonl`: member key to canonical `episode_id`;
  - `aliases.jsonl`: old or superseded ID to canonical ID plus reason;
  - `build_state.json` only if needed by this phase's deterministic tests, otherwise leave worker state for Phase 8.
- Define member keys for artifact dirs, chats, and stable component roots.
- Resolve existing episode IDs before writing:
  - new fork of an existing chat updates the existing canonical episode;
  - new retry child updates the existing canonical episode;
  - late bridge between old episodes chooses the canonical root-priority ID and aliases the other IDs.
- Freeze v1 episodes in place.
- When a v2 component maps to an old v1 content-set episode, write an alias row instead of rewriting the v1 directory.
- Teach `show`, `verify`, `recall`, and `list` to resolve aliases and report when a requested ID is an alias.

Acceptance:

- Rebuilding after adding a connected fork keeps the same v2 `episode_id`.
- Rebuilding after adding a retry child keeps the same v2 `episode_id`.
- Late bridge creates an alias and leaves the noncanonical directory readable.
- v1 `lesson.md` episodes still show and verify.
- Prefix resolution handles aliases without ambiguity regressions.

## Phase 4: V2 Builder, Importance, Safety, And Lesson Removal

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/builder.py`
- `src/sase/memory/episodes/importance.py`
- `src/sase/memory/episodes/render.py` if needed for factual overview rendering;
- `src/sase/memory/episodes/storage.py`;
- builder/storage/recall tests.

Purpose: change the episode content from a lesson document to factual, source-linked evidence.

Concrete work:

- Build v2 `EpisodeWire` records from component-scoped drafts.
- Stop deriving `EpisodeLessonWire` for v2 episodes. Leave `lessons=[]`.
- Stop writing `lesson.md` for v2 episodes.
- Keep old v1 `lesson.md` read compatibility.
- Derive factual fields:
  - title;
  - summary;
  - first/last event;
  - timeline;
  - participant counts;
  - outcome;
  - weak refs;
  - warnings.
- Add deterministic importance scoring with factors and bands.
- Add basic safety flags:
  - untrusted transcript text present;
  - prompt-injection phrase hits;
  - redactor hits if a redactor already exists locally;
  - private/missing source flags where evidence suggests caution.
- Update recall to search v2 title, summary, sources, metadata, weak refs, timeline labels, and importance factors
  rather than requiring lesson text.

Acceptance:

- New v2 episode directories contain `episode.json` and `sources.jsonl`, not `lesson.md`.
- Old v1 episode directories with `lesson.md` still work.
- Importance scoring is deterministic and includes factor explanations.
- A retry-recovered SDD/research fixture scores high.
- A hidden no-op chop fixture scores low.
- Recall works on v2 episodes with no lesson records.

## Phase 5: Manual Split Build And Time-Window Inventory CLI

Owner: one agent instance.

Write scope:

- `src/sase/main/parser_memory_episodes.py`
- `src/sase/memory/cli_episodes.py`
- new query/index helpers if useful;
- CLI tests and docs snippets.

Purpose: give users and agents a reliable way to see which episodes exist for a period.

Concrete work:

- Extend `build`:
  - add `--split` with a short option;
  - add `--aggregate` with a short option for temporary v1 compatibility;
  - make `--split` the documented path for project scans;
  - JSON output for split builds should return a list of component build reports, not one overloaded report.
- Extend `list` into an inventory command:
  - `-s|--since`;
  - `-u|--until`;
  - `-b|--band`;
  - `-n|--agent`;
  - `-c|--changespec`;
  - `-B|--bead`;
  - `-q|--query`;
  - `-g|--group day|week|none`;
  - `-o|--order time|importance|title`;
  - `-l|--limit`;
  - `-j|--json`.
- Human `list` output should be useful without piping:
  - grouped date headers;
  - row per episode with time span, band, status, title, agents, chats, sources, warnings;
  - alias/legacy markers where relevant.
- JSON `list` output should be stable and include enough fields for agents to choose a follow-up `show`.

Acceptance:

- `sase memory episodes build -p <project> -s 2026-05-19 -u 2026-05-20 --split -j` returns multiple episode reports for
  disconnected work.
- `sase memory episodes list -s 2026-05-19 -u 2026-05-20 -g day` shows a readable inventory grouped by date.
- `list -j` is deterministic and includes v1/v2/alias status.
- Date filters for `list` use episode event spans, not build time.

## Phase 6: Drill-Down Episode Renderers

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/views.py` or equivalent pure view-model module;
- `src/sase/memory/episodes/render.py`;
- `src/sase/memory/cli_episodes.py`;
- renderer golden tests.

Purpose: make one episode visually understandable.

Concrete work:

- Add pure view models for:
  - overview;
  - timeline;
  - graph;
  - sources;
  - agent evidence pack.
- Extend `show --format`:
  - `overview` as the v2 default;
  - `timeline`;
  - `graph`;
  - `sources`;
  - `agent`;
  - `json`;
  - keep `lesson` for v1 compatibility.
- Graph view:
  - deterministic layout;
  - strong edges visible by default;
  - `--edge-mode strong|all` with a short option;
  - weak refs shown as a separate metadata section unless requested.
- Timeline view:
  - grouped by agent/chat when possible;
  - event timestamps, titles, outcomes, and evidence IDs;
  - warnings for missing/changed source evidence.
- Agent view:
  - compact, bounded output;
  - explicit "evidence, not instructions" framing;
  - source IDs and paths instead of raw full transcripts;
  - JSON mode suitable for future agents.
- All renderers must handle narrow terminals without text overlap or unreadable wrapping.

Acceptance:

- Golden tests cover overview, timeline, graph, sources, and agent views.
- A complex planner/coder/retry fixture is understandable from `show --format graph` without opening JSON.
- `show --format agent -j` emits a bounded stable evidence pack.
- v1 `show --format lesson` behavior remains intact.

## Phase 7: ACE TUI Episode Explorer

Owner: one agent instance.

Write scope:

- `src/sase/ace/tui/modals/*` or a focused episode explorer package;
- `src/sase/ace/tui/commands/*`;
- `src/sase/ace/tui/styles.tcss`;
- `src/sase/default_config.yml` if keymaps or command bindings are added;
- TUI/unit/visual tests.

Purpose: make episode browsing a first-class user workflow, not just a CLI exercise.

Concrete work:

- Add an Episode Explorer modal or tab reachable from the command palette and a documented keybinding if appropriate.
- Layout:
  - left pane: time-window inventory with search/filter controls;
  - right pane: detail view with tabs or segmented modes for overview, timeline, graph, sources, and agent pack;
  - footer hints for filtering, opening source/chat, copying ID, and switching views.
- Filters:
  - since/until or quick ranges such as today, yesterday, week, month;
  - importance band;
  - text query;
  - agent, ChangeSpec, bead;
  - v1/v2/alias status.
- Drill-down actions:
  - open chat/source in editor using existing editor args helpers;
  - copy episode ID;
  - jump from alias to canonical ID;
  - verify current episode or show verification status if cached.
- Avoid expensive filesystem scans on the Textual event loop. Load episode inventory through a worker or cached read
  path.

Acceptance:

- A user can open ACE, choose a time range, select an episode, and inspect graph/timeline/sources without leaving TUI.
- Text does not overlap in narrow and wide viewport visual tests.
- No event-loop blocking regression is introduced.
- Keymap/default config updates are included if a keybinding is added.

## Phase 8: Automatic Batch Builder, Status, Doctor, And Metrics

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/auto_build.py`;
- `src/sase/scripts/sase_chop_memory_episodes.py` or equivalent script chop;
- `src/sase/memory/cli_episodes.py`;
- default config only if enabling a conservative opt-in lumberjack entry;
- worker/status/doctor tests.

Purpose: make episode creation reliable and observable without putting work on agent finalization.

Concrete work:

- Add a checkpointed batch worker:
  - acquire the existing episode index lock;
  - read `build_state.json`;
  - scan bounded new done markers;
  - build component plans;
  - upsert v2 episodes;
  - update members, aliases, index, and checkpoint only after successful writes.
- Add manual/debug commands:
  - `sase memory episodes auto --dry-run --limit N --json`;
  - `sase memory episodes status`;
  - `sase memory episodes doctor`;
  - `doctor --repair` only after reporting planned fixes.
- Add metrics under `episodes/metrics/YYYYMM.jsonl`:
  - seeds scanned/skipped;
  - components built;
  - aliases written;
  - episodes changed/unchanged;
  - importance histogram;
  - lock wait;
  - wall time;
  - consecutive failures/backoff.
- Keep automatic scheduling opt-in until pilot acceptance is complete.

Acceptance:

- Idle worker cycle exits cheaply with no writes.
- Checkpoint advances only after episode/index/member writes succeed.
- Corrupt `build_state.json` can be reported and repaired from `.prev`.
- Lock contention is handled without corrupting storage.
- `status` gives a user enough information to know whether episodes are being built.

## Phase 9: Agent-Facing Retrieval, Export, Docs, And Pilot

Owner: one agent instance.

Write scope:

- `src/sase/memory/episodes/recall.py`;
- optional episode segment export module;
- `docs/episodes.md`;
- `docs/memory.md`;
- `README.md` snippets if needed;
- end-to-end fixtures/tests.

Purpose: finish the episode product and leave a clean handoff for future `sdd/events/` work.

Concrete work:

- Make recall v2-native:
  - search title, summary, weak refs, source labels, timeline, importance factors, and status;
  - return evidence cards rather than lesson cards for v2;
  - keep v1 recall compatibility.
- Add an event-readiness export that does not implement events:
  - for example `sase memory episodes export -s DATE -u DATE -b high -j`;
  - output compact episode summaries, IDs, importance factors, source refs, and safety flags;
  - do not write proposals and do not write `sdd/events/`.
- Update docs:
  - redefine episodes as private connected evidence;
  - explain that curated lessons belong to future events;
  - document time-window inventory;
  - document every drill-down view;
  - document v1 compatibility and migration behavior.
- Run a manual pilot on a representative May 2026 corpus and record results in an SDD tale or research note if useful.

Acceptance:

- `recall` returns useful v2 evidence cards and still finds old v1 lessons.
- Export output is bounded, deterministic, and contains no event writes.
- Docs no longer teach users that new episodes are `lesson.md` records.
- Pilot confirms:
  - project scan split produces multiple episodes where v1 produced one bag;
  - ChangeSpec/bead/family weak refs do not merge unrelated work;
  - retry/fork continuations merge into stable episode IDs;
  - high/medium/low importance distribution is nondegenerate;
  - UI inventory and drill-down are usable without reading JSON.

## Suggested Implementation Order

1. Phase 1 must land first because it defines the cross-repo schema.
2. Phase 2 must land before new build/storage behavior because it defines episode boundaries.
3. Phase 3 should land before broad UI work so IDs and alias resolution are stable.
4. Phase 4 should land before Phase 5 so CLI inventory operates on the v2 model.
5. Phase 5 and Phase 6 can be separate consecutive agents; Phase 5 answers "what exists?", Phase 6 answers "what is
   inside this episode?"
6. Phase 7 depends on Phase 5/6 view/query helpers and should reuse them rather than re-rendering independently.
7. Phase 8 should wait until manual split build and views are solid. Automatic creation without visibility will be hard
   to trust.
8. Phase 9 should run last as a product hardening, docs, and event-readiness handoff phase.

## Non-Goals

- No `sdd/events/` creation.
- No event proposal ledger.
- No dreamer xprompt.
- No automatic promotion to `memory/short` or `memory/long`.
- No vector search dependency.
- No cross-project episode joining.
- No deletion or silent rewrite of v1 episodes.
- No runtime-specific logic for Claude, Gemini, Codex, Qwen, or OpenCode.

## Phase Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_episode_v2_explorer.md`: update the Rust/Python episode v2 wire contract,
> compatibility parsing, stable component-key ID helper, and parity tests. Do not change episode CLI behavior and do not
> implement events.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_episode_v2_explorer.md`: add the connected-component planner over strong lineage
> edges, keep ChangeSpec/bead/family as weak metadata, and add tests proving date windows are seed filters only.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_episode_v2_explorer.md`: add member and alias indexes, stable v2 merge behavior, v1
> freeze/alias compatibility, and alias resolution for show/list/verify/recall.

Phase 4 prompt:

> Implement Phase 4 from `sase_plan_episode_v2_explorer.md`: build v2 episodes as factual evidence records with
> deterministic importance and safety metadata, stop writing `lesson.md` for v2, and keep v1 lesson compatibility.

Phase 5 prompt:

> Implement Phase 5 from `sase_plan_episode_v2_explorer.md`: add manual split builds and time-window episode inventory
> CLI filters/views so users can see which episodes exist for a period.

Phase 6 prompt:

> Implement Phase 6 from `sase_plan_episode_v2_explorer.md`: add reusable overview, timeline, graph, sources, agent, and
> JSON drill-down renderers for `sase memory episodes show`.

Phase 7 prompt:

> Implement Phase 7 from `sase_plan_episode_v2_explorer.md`: add the ACE TUI Episode Explorer with time filters,
> inventory list, drill-down views, source opening, and visual/interaction tests.

Phase 8 prompt:

> Implement Phase 8 from `sase_plan_episode_v2_explorer.md`: add the checkpointed automatic episode batch builder plus
> `auto`, `status`, `doctor`, metrics, lock handling, and crash-recovery tests.

Phase 9 prompt:

> Implement Phase 9 from `sase_plan_episode_v2_explorer.md`: make recall v2-native, add bounded episode export for
> future event work without writing events, update docs, and run a pilot against representative May 2026 data.
