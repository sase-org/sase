---
create_time: 2026-05-31
status: research
topic: SASE memory episodes, event memory, and `sase memory search`
---

# Critique: SASE Episodes, Event Memory, And `sase memory search`

## Research Question

Critique SASE's memory system with emphasis on:

- current `sase memory episodes` behavior;
- plans for a curated event-memory layer, called `sdd/events/` in most current plans but requested here as
  `memory/events/`;
- the future `sase memory search` command;
- concrete changes to current code and project direction.

## Current State Verified

The current code has a mature `sase memory` command group, but no top-level memory search command yet.
`src/sase/main/parser_memory.py` registers `init`, `list`, `episodes`, `read`, `write`, `review`, and `log`.
`src/sase/main/memory_handler.py` dispatches the same set. There is no `search` parser or dispatch branch.

The `episodes` surface has advanced past several earlier critiques. `src/sase/main/parser_memory_episodes.py` now
registers `build`, `auto`, `status`, `doctor`, `export`, `list`, `show`, `verify`, and `recall`. Split builds are
implemented via `src/sase/memory/episodes/components.py`, and automatic one-shot batch building exists through
`src/sase/memory/episodes/auto_build.py` and `src/sase/scripts/sase_chop_memory_episodes.py`.

Episode v2 storage mostly matches the newer direction. `src/sase/memory/episodes/storage.py` writes `episode.json` and
`sources.jsonl` for v2 component episodes, skips `lesson.md`, and removes stale `lesson.md` when rewriting a component
episode. Legacy aggregate episodes still keep `lesson.md` for compatibility. Member and alias indexes are present via
`src/sase/memory/episodes/identity.py`.

The biggest remaining episode issue is identity portability. `src/sase/memory/episodes/components.py` still derives
component roots from `normalize_source_path(...)`, and `normalize_source_path` resolves paths to absolute paths in
`src/sase/memory/episodes/source_refs.py`. Current component keys therefore include absolute artifact or chat paths:

```text
component/artifact/<project>/<timestamp>/<absolute-artifact-path>
component/chat/<absolute-chat-path>
```

That is acceptable for local evidence refs, but not for durable identity, cross-machine sync, or repo-portable event
citations.

There is no top-level `sdd/events/` or `memory/events/` directory in this checkout. The only checked-in events-like tree
is `sdd/beads/events/`, which is operational bead state and should not be confused with curated memory events. The repo's
root `memory/` currently contains only `short/` and `long/`.

The plans are inconsistent on the event-memory path and file shape:

- most recent consolidated search/event notes recommend one reviewed markdown card per event under
  `sdd/events/YYYYMM/*.md`;
- the connected-components note recommends `sdd/events/YYYYMM/<event_id>/lesson.md`;
- the user's wording here says `memory/events/`;
- code-module plans mention `src/sase/memory/events/`, which is an implementation namespace, not necessarily the storage
  path.

That inconsistency should be resolved before writing event code.

## What Is Working

The high-level memory ladder is sound:

```text
memory/short       always-loaded instructions
memory/long        audited, reviewed reference memory
episodes           private source-linked evidence about prior work
event cards        reviewed, repo-portable project history
memory write/review optional promotion into durable procedural/reference memory
```

The newer episode design correctly treats episodes as evidence, not instructions. This avoids turning generated
summaries into prompt authority. The split between private episodes and reviewed durable memory is the right safety
boundary.

The episode CLI is now useful independent of events. `list`, `show`, `recall`, `verify`, `export`, `auto`, `status`, and
`doctor` give a reasonable operational surface for private history. `export` returning `writes_events: false` is the
right handoff posture for future event review.

The memory proposal flow also has the right shape: `sase memory write` creates attributable proposals, and
`sase memory review` is the human gate before canonical `memory/long` changes.

## Critique

### 1. `sase memory search` Is The Missing Product Surface

`sase memory episodes recall` searches private stored episode evidence. `sase memory list` inventories loaded,
referenced, available, and missing memory files. Neither is the proposed cross-tier memory finder.

The missing command should be the agent-facing retrieval API over short memory, long memory pointers, and curated event
cards. Without it, event cards have no first-class retrieval path, and agents will keep using ad hoc `rg` searches or
over-reading canonical long-memory files.

Search must preserve the audit boundary: it may find `memory/long` files, but full long-memory content should still go
through `sase memory read` and the `/sase_memory_read` skill. Search results for long memory should default to metadata,
matched fields, and an audited follow-up command, not body excerpts.

### 2. The Event Path Needs One Name

The current plans mostly say `sdd/events/`; this prompt says `memory/events/`. That is not cosmetic. It changes the
trust model:

- `memory/short` and `memory/long` are instruction/reference memory.
- events are historical evidence about project work.
- `sdd/` is already where SASE stores prompts, tales, epics, legends, beads, and research.

I recommend **not** adding top-level `memory/events/` for v1 event cards. Use `sdd/events/YYYYMM/*.md` for curated
repo-portable event cards, and reserve `~/.sase/projects/<project>/event_proposals/` or a rebuildable project-state
index for generated/private state.

If the project intentionally wants `memory/events/`, then all existing event research and future parser docs should be
renamed to that path before implementation. The worst outcome is supporting both `sdd/events/` and `memory/events/`
without a clear authority rule.

### 3. The Event File Shape Should Avoid `lesson.md`

Private v2 episodes just escaped the `lesson.md` contract. Reintroducing `lesson.md` under event directories will blur
the boundary again, especially because old aggregate episodes still have `lesson.md`.

One file per event is simpler:

```text
sdd/events/
  README.md
  202605/
    evt_20260531_memory_search_a1b2c3.md
```

Use YAML frontmatter plus a short markdown body. Directory-per-event should wait until v1 truly needs sibling artifacts
such as validation reports, redaction reports, or source manifests.

### 4. Episode IDs Should Not Become Portable Event Identity

Episode IDs and component keys are still local-evidence identifiers because component/member keys use absolute paths.
Events may cite episodes as optional evidence, but an event card must stand alone after a fresh clone. It should cite
repo-relative SDD paths, commits, bead IDs, ChangeSpecs, chat basenames or stable chat IDs, and only optionally a local
episode ID.

Before event promotion consumes episodes, component keys need a path-independent identity contract. Use logical keys:
project, workflow directory, timestamp, runtime-written retry/workflow/root IDs, and chat basename/content hash. Keep
absolute paths inside source refs only.

### 5. Direct Manual Events Should Precede Dreamer Automation

The dreamer/event-proposal plan is useful for backfills, but it is also the highest-risk path. It lets generated content
become future retrieval material. A bad event card is persistent memory poisoning, not just a bad note.

The safer sequence is:

1. define `sdd/events/README.md`;
2. add parser and validator;
3. add `sase memory search` over hand-authored event cards;
4. seed 3-5 high-value manual cards from existing research/tales;
5. measure whether agents can find and use them;
6. only then add episode-export-to-event-proposal automation.

### 6. The Rust-Core Boundary Will Matter Soon

Direct-scan Python is fine for a first CLI-only `sase memory search`, because the corpus is small and no event directory
exists yet. But the stable semantics should be designed as if they may move to `sase-core`:

- event frontmatter schema and validation;
- source-reference safety checks;
- search result JSON envelope;
- scoring fields and filters;
- component-key normalization.

The CLI can start in Python as a thin implementation, but avoid a command contract that would be painful to move behind
`sase_core_rs`.

### 7. Generated `AGENTS.md` Should Point To Search, Not List Events

`src/sase/amd/_memory.py` currently renders Tier 1 short memory and Tier 2 long memory. When event cards exist, it
should add a short event-memory discovery note, not enumerate all event cards. Event cards are meant to be searched on
demand; listing them in managed instructions creates prompt bloat and churn.

The existing long-memory warning should broaden only when event cards exist: agents should not modify memory files or
event cards without user approval.

## Recommended Changes

### Code Changes

1. Add `sase memory search` as a read-only direct-scan v1.

   Implement `src/sase/memory/search.py` for document collection, tokenization, scoring, filtering, and JSON result
   models. Implement `src/sase/memory/cli_search.py` for human and JSON output. Wire it through
   `src/sase/main/parser_memory.py` and `src/sase/main/memory_handler.py`.

2. Search tiers should be explicit.

   Default to all available tiers:

   - Tier 1: loaded `memory/short/*.md`;
   - Tier 2: visible `memory/long/*.md` pointers, with `read_command`;
   - Tier 3: curated event cards once the event directory exists.

   Do not print Tier 2 body excerpts by default.

3. Add event parsing and validation before event promotion.

   Add `src/sase/memory/events.py` or `src/sase/memory/events/` with a strict v1 schema for one-file markdown cards.
   Validate required fields, duplicate `event_id`, filename/id equality, `privacy: repo_safe`, safe source refs, status,
   event type, and suspicious instruction-like copied text.

4. Use `sdd/events/YYYYMM/*.md` as the v1 event-card path.

   Do not implement `memory/events/` unless the project first decides to rename all event-memory plans to that path.
   Do not support both paths in v1.

5. Add `sdd/events/README.md` before code that writes cards.

   Document path, frontmatter, body sections, privacy, source refs, supersession, retraction, and the rule that events
   are evidence rather than instructions.

6. Fix episode component identity.

   Stop using absolute normalized source paths in durable `component_key` values. Add tests proving identical fixtures
   under two different temp/project roots produce the same `component_key` and `episode_id`. Keep absolute paths only in
   source refs and verification data.

7. Keep private v2 episodes lesson-free.

   Preserve legacy aggregate `lesson.md` compatibility, but add tests that split v2 component episodes do not write
   `lesson.md`, and ensure recall/search stays v2-native over title, summary, events, source refs, weak refs, safety,
   and importance factors.

8. Update AMD-managed instructions only after search/event cards exist.

   Add a compact "Searching Memory" block and an event-memory note only when event cards are present. Do not enumerate
   every event card in `AGENTS.md`.

9. Defer SQLite/FTS and embeddings.

   Direct scan is enough for v1. If latency or corpus size becomes a real problem, add a rebuildable project-state index
   such as `~/.sase/projects/<project>/memory_search.sqlite`. Do not check in indexes or embeddings.

### Plan And Future-Direction Changes

1. Rename the event-memory target consistently in all SDD plans.

   Preferred wording: "curated project memory events under `sdd/events/`." Avoid `memory/events/` unless the project
   deliberately chooses to colocate event cards with `memory/short` and `memory/long`.

2. Collapse the two event file-shape proposals into one.

   Adopt one markdown file per event for v1. Reject `sdd/events/YYYYMM/<event_id>/lesson.md` until there is a concrete
   need for per-event sibling artifacts.

3. Treat episodes as optional evidence, not an event prerequisite.

   Manual event cards should be allowed to cite SDD research, tales, commits, beads, ChangeSpecs, and chat IDs directly.
   Episodes become valuable for backfill, debugging, and proposal generation, but they should not be required to record
   a known decision or incident.

4. Make `sase memory search` the event retrieval gate.

   Do not build dreamer promotion or event write automation until search can find hand-authored cards with useful
   precision and clear trust labels.

5. Keep promotion gates separate.

   Event cards are reviewed evidence. Durable instructions still go through `sase memory write` and
   `sase memory review`. A future event proposal workflow should write to project-state proposals first and only land
   in `sdd/events/` after explicit review.

6. Move shared semantics to `sase-core` when a second frontend needs them.

   The first Python direct-scan implementation is acceptable. Once ACE, mobile, editor integrations, or sibling repos
   need the same event/search behavior, promote validation, result schemas, scoring, and path normalization behind
   `sase_core_rs`.
