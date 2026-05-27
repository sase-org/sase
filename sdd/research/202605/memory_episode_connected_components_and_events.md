---
create_time: 2026-05-27
status: research
---

# Connected Episode Components And Event Lessons

## Question

How should SASE refine memory episodes so automatic episode creation splits work by connected chats, merges later forks
into the right existing episode, assigns deterministic importance, and feeds a background dreamer that can propose
curated `sdd/events/` records with `lesson.md` files?

## Short Answer

Use a two-layer model:

1. **Private episodes** are deterministic connected components over agent/chat lineage. They live under project state,
   are built automatically by a batch worker, have no `lesson.md`, and carry deterministic importance metadata.
2. **Curated events** are rare, reviewed, repo-safe SDD records under `sdd/events/YYYYMM/<event_id>/lesson.md`. A
   dreamer reviews a bounded segment of important episodes and proposes zero or one event. The event's `lesson.md` is
   the dreamer's pitch for the reusable lesson across multiple episodes.

The date range should never define an episode boundary. It should only select seed records for backfill or worker
catch-up. Once a seed is selected, SASE should expand through strong lineage edges even if the connected chat or retry
attempt falls outside the seed window.

The highest-value implementation is:

- add a deterministic component planner over artifact and chat nodes;
- use only strong chat/run lineage edges for episode membership;
- keep weak topic edges such as ChangeSpec, bead, and agent family as metadata, not join criteria;
- make episode IDs stable from the component root key, not from all source files;
- let the background worker update the same episode when a later fork/retry connects to it;
- move lesson generation to event promotion, not episode build.

## Context Reviewed

Named prior agent chats:

- `bjn.cdx`, transcript `~/.sase/chats/202605/sase-ace_run-260527_072503.md`, concluded that date-only
  `sase memory episodes build` currently creates one `project_scan` episode because the CLI collects one draft and
  builds one episode per invocation.
- `bjn.cld`, transcript `~/.sase/chats/202605/sase-ace_run-260527_072454.md`, independently reached the same
  conclusion and suggested adding connected-component partitioning between collection and `build_episode`.

Local implementation reviewed:

- `src/sase/memory/cli_episodes.py` builds exactly one draft, one episode, and one `lesson.md` per `build` call.
- `src/sase/memory/episodes/_collector_seed.py` seeds all project-scan records into one collector queue.
- `src/sase/memory/episodes/_collector_record.py` already records retry, parent, linked chat, ChangeSpec, bead, and
  family edges.
- `src/sase/memory/episodes/storage.py` hard-codes episode `lesson.md` as a projection.
- `src/sase/memory/episodes/recall.py` searches stored episode lessons.
- `src/sase/axe/run_agent_exec_finalize.py` writes chat history, `episode_trace.json`, and `done.json` at completion.
- `src/sase/axe/lumberjack.py` and `src/sase/axe/chop_runner.py` already provide scheduled batch script chops and
  agent chops.
- `sase-core/crates/sase_core/src/episode/wire.rs` owns the current shared `EpisodeWire` and index row schema, including
  episode `lessons` and index `lesson_path`.

Relevant prior research:

- `sdd/research/202605/structured_episodic_agent_chat_memory.md`
- `sdd/research/202605/dream_chop_agent_chat_distillation.md`
- `sdd/research/202605/sase_dreams_design.md`
- `sdd/research/202605/git_versioned_episodic_events.md`
- `sdd/research/202605/structured_episodic_events_for_memory_search.md`
- `docs/episodes.md`
- `docs/memory.md`

The events research is useful directionally but not authoritative for this design, especially where this note changes
the storage shape to put event lessons in `lesson.md` files.

## Current Problem

The current pipeline is singular:

```text
EpisodeSelector
  -> collect_episode_draft(...)
  -> build_episode(...)
  -> render_lesson_markdown(...)
  -> write_project_episode(...)
```

That shape causes four mismatches with the desired model.

1. A project scan is one bag. Date-bounded backfill with many unrelated chats produces one episode.
2. The collector adds useful graph edges, but no partitioning step consumes those edges to split disconnected work.
3. Episode identity is content/source based. Adding a later fork changes the source set, so a naive rebuild would create
   a different episode ID instead of merging.
4. Episodes currently own deterministic `lessons` and a `lesson.md`, but the desired model says lessons belong to
   curated events, not private episodes.

## Episode Boundary Semantics

Episode membership should be computed from connected components over a graph of artifact records and chats.

Use strong lineage edges for membership:

| Edge or signal | Include in component? | Reason |
| --- | --- | --- |
| `done.response_path`, `agent_meta.chat_path`, `episode_trace.chat_path` | Yes | Direct run-to-chat evidence. |
| `Linked Chats` section | Yes | Explicit transcript connection. |
| `#fork`, `#fork_by_chat`, `#resume`, `#resume_by_chat` | Yes | User or retry intentionally continued prior context. |
| `parent_timestamp`, `parent_agent_timestamp` | Yes | Follow-up or workflow lineage. |
| `retry_of_timestamp`, `retry_chain_root_timestamp`, `retried_as_timestamp` | Yes | Retry attempts are one work episode. |
| `prompt_step_*.json.response_path` and `workflow_step_agent` | Yes | Planner/question/coder steps are one connected workflow episode. |

Keep weak topic edges as metadata only:

| Edge or signal | Include in component? | Reason |
| --- | --- | --- |
| `agent_family` | No by default | Family names can group unrelated work over time. |
| ChangeSpec co-mention | No by default | A long-running CL can contain multiple unrelated episodes. |
| bead co-mention | No by default | Beads are workstream metadata, not proof of one chat thread. |
| same file path touched | No by default | Useful for search and importance, too broad for identity. |
| date range overlap | No | Date is a seed filter only, never a boundary. |

The important change from today: project scan should seed by time or watermark, then expand through strong edges without
using the seed date window as a transitive bound. Weak edges can still be rendered in `episode.json` after the component
is built, but they should not merge components.

## Component Planning Design

Add a planner before `collect_episode_draft` or as a new lower-level collector mode:

```text
scan_agent_artifacts(...)
  -> build_episode_component_plan(seeds, scan, chat_catalog)
  -> [EpisodeComponentPlan, ...]
  -> collect_episode_draft_for_component(plan)
  -> build_episode(...)
```

Recommended module split:

- `src/sase/memory/episodes/components.py`
  - union-find implementation;
  - seed selection;
  - strong-edge extraction;
  - component root-key derivation;
  - existing-episode merge detection.
- `src/sase/memory/episodes/importance.py`
  - deterministic scoring and factor explanation.
- `src/sase/memory/episodes/auto_build.py`
  - checkpointed worker logic for scheduled batch builds.
- `src/sase/scripts/sase_chop_memory_episodes.py`
  - AXE script chop entry point.
- `src/sase/memory/events/`
  - event proposal, event validation, and `sdd/events` promotion helpers.

Keep shared schemas and stable ID helpers in `sase-core` because CLI, TUI, mobile, and editor integrations will need
the same episode/event meanings.

### Component Plan Shape

Use a small in-memory DTO before touching wire schemas:

```json
{
  "schema_version": 1,
  "project": "sase",
  "component_key": "retry-root:20260526121000",
  "episode_id": "ep-...",
  "root_kind": "retry_root",
  "artifact_dirs": [".../20260526121000", ".../20260526122000"],
  "chat_paths": ["~/.sase/chats/202605/...md"],
  "strong_edges": [
    {"kind": "retry_of", "from": "20260526121000", "to": "20260526122000"}
  ],
  "merge_episode_ids": [],
  "seed_reason": "done_mtime_after_checkpoint"
}
```

The collector can then include all records/chats named by the plan and render the existing rich graph around them.

## Stable IDs And Merging

Current episode IDs hash the root source and full source set. That is good for immutable snapshots, but bad for merge
semantics. If a new chat forks an existing run, the source set changes and the episode ID should not.

Recommended v2 identity:

```text
episode_id = ep_<hash(project, component_root_key)>
content_sha256 = hash(canonical episode.json)
```

Root-key priority:

1. `retry_chain_root_timestamp` when present.
2. plan/workflow root timestamp from `episode_trace.root_timestamp`.
3. oldest ancestor timestamp reached through `parent_timestamp` or `parent_agent_timestamp`.
4. resolved fork target's existing component key.
5. artifact timestamp for a standalone completed agent.
6. normalized chat basename/hash for chat-only legacy episodes.

Merging cases:

- **New fork of existing chat.** The planner resolves the fork target, finds its component key in the episode member
  index, and rewrites that same `episode_id` with the new chat/artifact included.
- **New retry child.** The child shares the retry root key, so it updates the existing episode.
- **Late-discovered bridge between two old episodes.** The planner finds multiple existing IDs in one component. Choose
  the canonical ID from the root-key priority, then write an alias/supersession row for the other IDs.

Add a member index:

```text
~/.sase/projects/<project>/episodes/
  index.jsonl
  members.jsonl       # artifact/chat/member key -> canonical episode_id
  aliases.jsonl       # old episode_id -> canonical episode_id, reason
  build_state.json
  index.lock
```

This avoids scanning every stored episode when a new artifact arrives. It also lets `show`, `verify`, and `recall`
resolve old IDs after merges.

## Automatic Episode Creation

Do not run episode generation inline in `finalize_loop`. The completion path already saves the chat and writes
`done.json`; adding graph scans or markdown rendering there risks exactly the performance regression the design wants
to avoid.

Use a scheduled script chop:

```yaml
axe:
  lumberjacks:
    memory:
      interval: 300
      chop_timeout: "10m"
      chops:
        - name: memory_episodes
          description: "Build private connected memory episodes from completed agents"
          run_every: "15m"
```

The script should:

1. Acquire the project episode lock.
2. Read `build_state.json` with `last_done_mtime_ns` and processed member keys.
3. Scan completed artifacts newer than the checkpoint, bounded by a max seed count.
4. Build component plans from those seeds, expanding through strong edges.
5. Upsert each canonical episode.
6. Update `members.jsonl`, `aliases.jsonl`, and `index.jsonl`.
7. Advance `build_state.json` only after successful writes.

Idle cycles should exit quickly after the scan. No LLM calls should happen in this worker.

The explicit CLI should support the same path for debugging:

```bash
sase memory episodes build --since 2026-05-19 --until 2026-05-20 --split
sase memory episodes build --since 2026-05-19 --until 2026-05-20 --aggregate
sase memory episodes auto --dry-run --limit 50 --json
```

Recommendation: make project scans split by default after a short compatibility period, and keep `--aggregate` for the
old one-bag behavior.

## Deterministic Importance

Importance should be deterministic and explainable. Do not use an LLM for the score.

Store both the total and the factors:

```json
{
  "importance_score": 72,
  "importance_band": "high",
  "importance_factors": [
    {"name": "retry_recovered", "weight": 18},
    {"name": "sdd_research_written", "weight": 14},
    {"name": "plan_and_feedback", "weight": 10},
    {"name": "verification_present", "weight": 6}
  ]
}
```

Suggested starting weights:

| Signal | Weight |
| --- | ---: |
| retry or failed attempt later succeeded | +18 |
| user explicitly asked for research, memory, lesson, postmortem, or design decision | +16 |
| wrote or modified `sdd/research`, `sdd/events`, `memory/`, `AGENTS.md`, or core architecture docs | +14 |
| touched shared/core code such as `sase-core`, memory schemas, config defaults, launch/finalization, or hooks | +12 |
| plan approval, user feedback, or question/answer loop present | +10 |
| non-empty `diff_path`, generated artifact, commit/PR/ChangeSpec evidence | +8 |
| verification command detected | +6 |
| multiple connected chats or workflow steps | +5 |
| completed with no artifact/noop | -12 |
| hidden recurring chop with no failure or diff | -14 |
| tiny transcript with no plan, diff, feedback, question, or SDD source | -10 |
| dream-generated episode unless explicitly allowed | -20 |

Use bands:

- `critical`: `>= 80`
- `high`: `60..79`
- `medium`: `35..59`
- `low`: `< 35`

Do not bake recency into `importance_score`. Recency can be a scheduling tie-breaker or a "new since checkpoint"
filter, but importance should remain content-based so old high-value episodes are still high-value.

## Dreamer Contract

The dreamer should not process raw date windows. It should receive a bounded segment of already-built episodes selected
by deterministic score and optional topic clustering.

Input:

- compact episode summaries;
- episode IDs and source refs;
- importance scores/factors;
- existing event IDs and recent proposals to avoid duplicates;
- safety metadata such as hidden/chop/source provenance flags.

Output:

- exactly zero or one event proposal;
- no direct writes to `memory/short` or `memory/long`;
- no episode-level `lesson.md`;
- source-linked rationale for why the grouped episodes teach a durable lesson.

The "zero" case matters. Most episode batches should not become events.

Recommended event proposal shape in project state:

```text
~/.sase/projects/<project>/event_proposals/
  proposals.jsonl
  drafts/
    evt_20260527_memory_episode_components_a1b2c3/
      lesson.md
```

Promotion writes the reviewed event into the repo:

```text
sdd/events/
  202605/
    evt_20260527_memory_episode_components_a1b2c3/
      lesson.md
```

Use frontmatter in `lesson.md` as the v1 machine-readable event record:

```yaml
---
schema_version: 1
event_id: evt_20260527_memory_episode_components_a1b2c3
event_type: gotcha
status: active
created_at: 2026-05-27T00:00:00-04:00
project: sase
episode_ids:
  - ep-...
aggregate_importance_score: 84
keywords:
  - memory episodes
  - connected components
  - dreamer
sources:
  research:
    - sdd/research/202605/memory_episode_connected_components_and_events.md
  episodes:
    - ep-...
trust: reviewed
privacy: repo_safe
supersedes: []
---
```

The body should be the pitch:

```markdown
# Split Memory Episodes By Connected Chats

## Lesson

...

## Evidence

...

## Why These Episodes Belong Together

...

## What Not To Infer

...
```

This keeps the user's requested `lesson.md` name while preserving the prior research's safety boundary: dreamers
propose, humans or explicit review promote.

## Episode Storage Changes

New episodes should not write `lesson.md`.

Recommended v2 private episode directory:

```text
~/.sase/projects/<project>/episodes/
  <episode_id>/
    episode.json
    sources.jsonl
```

Optional, if human readability is needed:

```text
    summary.md       # factual summary/timeline only, not a lesson
```

Schema implications:

- `EpisodeWire.lessons` should become deprecated and empty for new v2 episodes.
- `EpisodeStorageIndexRowWire.lesson_path` should be replaced by `summary_path`, `importance_score`,
  `importance_band`, `component_key`, and `status`.
- `EpisodeBuildReportWire.lesson_count` should be deprecated or replaced by `source_count`, `event_candidate_count`,
  and `importance_score`.
- `sase memory episodes recall` should search episode title, summary, source labels, metadata, and importance factors,
  not `lesson.md`.
- `sase memory episodes show` should default to summary/timeline. Old v1 episode `lesson.md` files should still render
  for compatibility.

Because these are wire changes, update `sase-core` first, then Python bindings/callers/tests.

## Search And Event Relationship

The final memory ladder should be:

```text
raw chats/artifacts
  -> private connected episodes
  -> dreamer event proposals
  -> reviewed sdd/events/YYYYMM/<event_id>/lesson.md
  -> optional memory/long proposal using the event as evidence
```

Events are still evidence, not instructions. If an event reveals a durable rule, use the existing `sase memory write`
and `sase memory review` path to create or update `memory/long`.

Later, `sase memory search` should index:

- `memory/long`;
- reviewed `sdd/events/**/lesson.md`;
- private episodes only when explicitly requested or in agent-mode with provenance labels.

## Implementation Plan

Phase 1: component planning.

- Add `EpisodeComponentPlan` and union-find over strong lineage edges.
- Add tests proving date windows are seed filters only.
- Add tests proving ChangeSpec, bead, and agent family do not merge unrelated chats.
- Add `--split` and `--aggregate` project-scan modes.

Phase 2: stable IDs and merge index.

- Move episode ID generation to root-key identity in `sase-core`.
- Add `members.jsonl` and `aliases.jsonl`.
- Teach `show`, `verify`, and `recall` to resolve aliases.
- Test new fork and retry child updating an existing episode ID.

Phase 3: automatic worker.

- Add `sase_chop_memory_episodes` script and entry point.
- Add default memory lumberjack config, probably disabled or conservative at first if cost/IO is a concern.
- Add `build_state.json` checkpointing.
- Make idle cycles cheap and bounded.

Phase 4: remove episode lessons.

- Bump episode wire schema.
- Stop writing `lesson.md` for v2 episodes.
- Keep read compatibility for v1 `lesson.md`.
- Rewrite docs and tests around summaries, sources, timelines, and importance.

Phase 5: dreamer and events.

- Add deterministic episode segment selection by score.
- Add a dreamer xprompt/agent contract that returns zero or one event proposal.
- Store proposals under project state.
- Add event promotion to `sdd/events/YYYYMM/<event_id>/lesson.md`.
- Add validation for frontmatter, source refs, privacy, and prompt-injection warnings.

## Test Surface

Minimum tests before relying on this automatically:

- date-bounded project scan with three disconnected chats emits three episodes;
- component seeded inside a date window pulls an out-of-window retry/fork ancestor;
- two unrelated chats on the same ChangeSpec remain separate;
- two unrelated chats in the same agent family remain separate;
- `#fork_by_chat` to an existing episode rewrites the existing ID, not a new ID;
- late bridge between two existing episodes creates an alias;
- automatic worker exits without writes when no new done markers exist;
- automatic worker advances checkpoint only after episode/index writes succeed;
- importance score and factors are byte-stable across runs;
- hidden no-op chop scores low;
- retry recovery plus SDD research scores high;
- new v2 episodes do not write `lesson.md`;
- old v1 episodes with `lesson.md` still show and verify;
- dreamer proposal can return zero events;
- dreamer proposal for multiple high-signal episodes writes only an event proposal, not `memory/long`;
- promoted event lands under `sdd/events/YYYYMM/<event_id>/lesson.md`.

## Open Decisions

- Should the default project-scan CLI behavior switch to split immediately, or require `--split` for one release?
  Recommendation: add `--split` first, then make split the default after docs and tests land.
- Should automatic episode creation be enabled by default? Recommendation: ship the worker enabled only for manual
  `sase axe chop run memory_episodes` or a config opt-in, then enable by default after the idle-cycle cost is measured.
- Should event proposals reuse the existing memory proposal ledger? Recommendation: reuse validation and review
  concepts, but keep a separate event proposal type because the promotion target is `sdd/events`, not `memory/long`.
- Should `summary.md` exist for episodes? Recommendation: skip it in v1 unless `show` output becomes painful. JSON,
  timeline, and sources are enough for private records.

## Recommendation

Implement the connected-component planner first. It is the architectural hinge: automatic builds, merge semantics,
deterministic importance, and dreamer segmentation all depend on having stable, date-independent episode components.

Do not start with the dreamer. Without component splitting and stable merge IDs, the dreamer would be reviewing the same
overlarge project-scan bags that caused the original confusion.

Do not keep episode `lesson.md` as the human-facing value proposition. Private episodes should be source-linked
evidence with importance. Curated events should carry the lesson pitch.
