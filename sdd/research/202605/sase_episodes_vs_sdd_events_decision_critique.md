# SASE Episodes vs Committed SDD Events

Date: 2026-05-29

## Scope

This critique was prepared from source, tests, config, and non-Markdown data files only. I did not read existing research Markdown or other Markdown files. The goal is to decide whether SASE episodes are necessary if durable events and lessons are committed under `sdd/events/`.

## Short Answer

Episodes should not be required for committing events or lessons to `sdd/events/`.

The stronger design is:

- `sdd/events/` is the reviewed, portable, version-controlled record.
- Episodes are an optional local evidence/index layer that can discover candidate events, provide provenance, support recall, and help audit source drift.
- A committed event may link to an `episode_id`, but the event should stand on its own without requiring the episode store.

This keeps the valuable parts of episodes while avoiding turning a local transcript/artifact graph into the authoritative project memory format.

## What Episodes Currently Are

The implementation frames episodes as deterministic evidence records under `~/.sase/projects/<project>/episodes`, not as committed SDD artifacts. The CLI parser describes them as source-grounded records that do not modify memory files (`src/sase/main/parser_memory_episodes.py:17`). The actual project path resolver returns `~/.sase/projects/<project>/episodes` (`src/sase/memory/episodes/index.py:25`).

The core wire schema is broad. An episode contains source refs, nodes, edges, timeline events, lessons, weak refs, safety metadata, importance scoring, and index metadata (`src/sase/core/episode_wire.py:14`, `src/sase/core/episode_wire.py:44`, `src/sase/core/episode_wire.py:54`, `src/sase/core/episode_wire.py:90`). Storage writes `episode.json`, `sources.jsonl`, and sometimes `lesson.md` as deterministic projections (`src/sase/memory/episodes/storage.py:45`, `src/sase/memory/episodes/storage.py:71`).

The v2 path is especially important: when a draft is a connected component, the builder deliberately sets `lessons = []` and instead derives a factual summary plus importance metadata (`src/sase/memory/episodes/builder.py:44`). Storage also does not write `lesson.md` for v2 component episodes (`src/sase/memory/episodes/storage.py:334`). So episodes are no longer primarily a lesson artifact in the current design.

Episodes include a connected-component planner over agent artifacts, chats, retries, workflow steps, ChangeSpecs, beads, and referenced paths (`src/sase/memory/episodes/components.py:90`, `src/sase/memory/episodes/components.py:225`, `src/sase/memory/episodes/components.py:287`, `src/sase/memory/episodes/components.py:523`). The automatic builder scans completed agent records, builds components, writes episodes, and records local state and metrics (`src/sase/memory/episodes/_auto_build_runner.py:57`, `src/sase/memory/episodes/_auto_build_runner.py:86`, `src/sase/memory/episodes/_auto_build_runner.py:184`). Agent finalization writes `episode_trace.json` hints, but that trace is linkage metadata, not a committed event (`src/sase/axe/run_agent_helpers_artifacts.py:75`).

The export path is also revealing: it is explicitly read-only and returns `writes_events: False` (`src/sase/memory/episodes/export.py:39`). That is the right boundary.

## What SDD Events Would Be

The repository already has a git-versioned event pattern for beads: `sdd/beads/events/streams/*.jsonl` plus a manifest. The manifest says it was generated from `issues.jsonl`, and the current tree has many per-stream JSONL files. A sample bead event has `schema_version`, `event_id`, `timestamp`, `actor`, `operation`, `issue_id`, and `payload`. The bead sync code stages and commits bead state changes, including event streams, while excluding SQLite files (`src/sase/bead/sync.py:23`, `src/sase/bead/sync.py:41`, `src/sase/bead/sync.py:161`).

That pattern is useful evidence that committed event streams can work. But `sdd/events/` for lessons should not blindly reuse bead event semantics. Bead events are state mutation facts. Lesson/events are durable knowledge records: decisions, failures, recoveries, invariants, and observations that future agents should read.

## Critique of Making Episodes Necessary

### 1. It couples a portable memory format to a local cache

Committed `sdd/events/` files should be useful after clone, reviewable in code review, and stable in git history. Episodes live under `~/.sase/projects/<project>/episodes` and include absolute paths, local artifact directories, chat transcript paths, source hashes, and private/missing source warnings. That is valuable locally, but it is not a good required dependency for a repo-level memory record.

### 2. It imports too much raw provenance into the decision path

Episodes preserve source refs, graph structure, safety flags, prompt-injection hits, redaction hits, weak refs, and derived importance. That is useful for audit and recall. It is too much machinery for the common case: "we learned a lesson; commit the lesson." A committed lesson needs a concise claim, context, evidence links, and review status. It does not need a full transcript graph.

### 3. V2 episodes are not lesson-first

If the goal is "events/lessons in `sdd/events/`", episodes do not directly provide the desired final artifact. V2 component episodes intentionally have no lesson records. They are factual evidence packages with summaries and importance bands. That makes them a good source of candidate material, not the canonical durable lesson.

### 4. The complexity is justified only for discovery and audit

Episodes have selectors, split versus aggregate builds, indexes, locks, member rows, aliases, automatic checkpoints, metrics, doctor repair, show/list/export/verify/recall commands, and connected-component planning. That complexity pays off when reconstructing work from messy agent artifacts. It is overbuilt if every event is authored intentionally at the moment the lesson is learned.

### 5. Privacy and review boundaries are cleaner without required episodes

Episodes know about untrusted transcript text, prompt-injection phrases, redaction patterns, private sources, hidden sources, and missing source files. Those are exactly the reasons to keep episodes as a review aid before committing anything. The committed event should contain only reviewed, sanitized, durable information.

### 6. Required episodes would slow down the mental model

The user-facing question should be simple: "Should this lesson become project memory?" If yes, write `sdd/events/YYYYMM/...`. Requiring a prior episode adds another noun and workflow step. That can discourage use of the committed event system.

## What Episodes Are Good For

Episodes still have real value:

- Backfilling lessons from old chats and agent artifacts.
- Finding hidden relationships across parent agents, retries, linked chats, workflow steps, ChangeSpecs, and beads.
- Producing candidate event summaries sorted by importance.
- Verifying source drift after a lesson was derived.
- Giving future agents a compact evidence pack when the committed event references `episode_id`.
- Avoiding duplicate candidate events through component/member identity and aliases.

Those are optional capabilities. They are not prerequisites for a committed event.

## Recommended Architecture

Create `sdd/events/` as the authoritative reviewed memory stream. Keep episodes as an optional evidence cache.

Suggested committed event shape:

```yaml
schema_version: 1
event_id: 20260529-sase-episodes-events-decision
timestamp: 2026-05-29T00:00:00-04:00
kind: decision
status: reviewed
confidence: medium
episode_ids: []
bead_ids: []
changespec_names: []
source_paths:
  - src/sase/memory/episodes/export.py
privacy: public-repo-safe
```

Then the body should answer:

- What happened or what was learned?
- Why does it matter?
- What should future agents do differently?
- What evidence supports it?

This can be Markdown with frontmatter if humans are the primary consumers, or JSONL if machine append/replay is the priority. For lessons and design decisions, Markdown with frontmatter is a better default because review quality matters more than replay speed.

## Workflow Recommendation

1. Let agents commit curated events/lessons directly to `sdd/events/YYYYMM/`.
2. Add optional `episode_ids` and evidence paths when an episode exists.
3. Keep `sase memory episodes export` read-only. It can feed an event-review command later, but it should not silently write committed events.
4. Add a separate review step for converting episode summaries into events.
5. Do not commit raw `episode.json`, `sources.jsonl`, or `lesson.md` from the local episode store into `sdd/events/`.

## Decision Rule

Use episodes when:

- You are mining old work.
- You need transitive agent/chat/retry context.
- You want source hashes or source drift verification.
- You need deterministic recall over raw evidence.
- You suspect duplicate or split work needs component identity.

Skip episodes when:

- The lesson is already clear.
- The event is being authored during the work.
- The record must be portable across clones.
- The source material includes private transcripts or local-only paths.
- The extra workflow step would prevent the event from being written.

## Recommendation

Do not make SASE episodes necessary for `sdd/events/`.

Keep episodes as a useful local staging and audit system. Build `sdd/events/` as the durable, reviewed, version-controlled memory layer. The best long-term posture is "episodes can suggest events; humans or agents commit reviewed events." That gives SASE the provenance benefits without making local evidence graphs the canonical memory format.
