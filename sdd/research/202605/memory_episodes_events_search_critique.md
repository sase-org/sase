---
create_time: 2026-05-31
updated: 2026-05-31
status: research
topic: SASE memory episodes, event memory, and `sase memory search`
---

# Critique: SASE Episodes, Event Memory, And `sase memory search`

> Revision note (2026-05-31): expanded after a second code-grounded pass. New
> material: the opt-in episode-recall prompt-injection path (§8), hardcoded
> importance scoring and its Rust-core boundary risk (§9), the already-persisted
> identity defect and migration gap (§4, expanded), in-code evidence that
> `sdd/events/` is already the de facto canonical path (§2, expanded), the
> absence of any committed bead/epic for this work, and the research-note
> fragmentation problem (§10). Earlier sections verified against current code.

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

Two current-state facts the earlier draft omitted matter to the critique below:

- **Episodes already have a prompt-injection path.** `src/sase/axe/run_agent_runner_setup.py:181` calls
  `apply_episode_recall_memory(...)`, which (when `SASE_MEMORY_EPISODES_RECALL` is set) calls
  `generate_episode_recall_prompt` and appends a `### EPISODIC MEMORY` block to the agent's prompt
  (`src/sase/memory/episodes/prompt_recall.py:84`). It is opt-in and capped (`SASE_MEMORY_EPISODES_RECALL_LIMIT`,
  default 3), and it writes `episode_recall.json` for audit. So "episodes are evidence, not instructions" is the
  *design intent*, but a recall path that puts generated episode text into the prompt already exists.
- **Importance is scored entirely in code.** `src/sase/memory/episodes/importance.py` computes a deterministic
  0–100 score from ~12 hardcoded factors (e.g. `retry_recovered` +18, `design_or_memory_requested` +16,
  `dream_generated` −20) with hardcoded bands (`critical` ≥80, `high` ≥60, `medium` ≥35). Each factor carries a
  label and `evidence_ids`, so the *output* is explainable, but the *weights and thresholds* are magic constants with
  no config surface.

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

The newer episode design *intends* to treat episodes as evidence, not instructions, and the split between private
episodes and reviewed durable memory is the right safety boundary. But that boundary is not yet fully enforced: the
opt-in recall path (§8) does inject generated episode text into prompts, so the "not prompt authority" property holds
only while `SASE_MEMORY_EPISODES_RECALL` is unset. Treat that as a design goal still in progress, not a settled
guarantee.

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

The code already votes for `sdd/events/`. The importance scorer's `durable_knowledge_docs` factor
(`src/sase/memory/episodes/importance.py:156`) explicitly rewards touching `sdd/events/` alongside `sdd/research/`,
`memory/`, and `AGENTS.md`. So an episode that edits an `sdd/events/` card is *already* scored as durable-knowledge
work, even though the directory does not exist yet. Choosing `memory/events/` instead would orphan that scoring rule
and the cross-frontend research. This is concrete evidence to settle the name as `sdd/events/` rather than relitigate
it.

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

This is not a greenfield fix. The `_component_root()` helper in `src/sase/memory/episodes/components.py` builds keys
like `component/artifact/{project}/{timestamp}/{artifact_key}` where `artifact_key = normalize_source_path(...)`, and
`normalize_source_path` (`src/sase/memory/episodes/source_refs.py:48`) returns `Path(path).expanduser().resolve()` — a
machine-absolute path. The episode v2 phase-9 pilot already stored components built this way, so broken IDs exist on
disk now. The fix therefore needs a migration story, not just a code change: when the key derivation changes, existing
episode IDs change, and any stored `alias`/`member` index, recall artifact, or future event citation that points at the
old ID must be re-pointed or alias-mapped. Recommend: (a) add the path-independent derivation, (b) record the old key as
an alias on rewrite so existing references still resolve, and (c) add golden-fixture tests proving identical inputs
under two different home/workspace roots produce identical `component_key` and `episode_id`.

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

### 8. Episode Recall Already Injects Into Prompts Without A Trust Label

The earlier draft treated "episodes are evidence, not instructions" as already true. It is not, on the recall path.
When `SASE_MEMORY_EPISODES_RECALL` is set, `format_episode_recall_section` emits a bare `### EPISODIC MEMORY` block of
episode lessons/cards directly into the agent prompt (`src/sase/memory/episodes/prompt_recall.py:84`). The block carries
`[evidence: ...]` source citations, which is good, but it has **no framing** telling the agent this is recalled past
work to be verified rather than an authoritative instruction. A heading like `### EPISODIC MEMORY` reads as authority.

This matters more once events and search exist, because the same generated content becomes promotable. Two concrete
risks:

- `dream_generated` episodes score −20 in importance but are **not excluded** from recall. A low-importance,
  machine-authored episode can still be injected if it lexically matches the query.
- There is no trust/altitude label distinguishing recalled episode text from short-memory instructions in the prompt.

Recommend: prefix the recall block with an explicit non-authority preamble ("Recalled evidence from past runs — verify
before relying on it; not an instruction"), and add an importance/`dream_generated` floor (or a `--include-generated`
opt-in) before episodes are eligible for prompt recall. Reuse the same trust labeling for `sase memory search` Tier 3
results so episodes and event cards present identically.

### 9. Importance Scoring Is Hardcoded And Will Cross The Rust-Core Boundary

`src/sase/memory/episodes/importance.py` is pure Python with ~12 hardcoded factor weights and hardcoded bands. It is
the de facto ranking authority for "what work mattered," and event promotion plus `sase memory search` Tier 3 ordering
will almost certainly want to reuse it. That makes importance **shared backend semantics** under
`memory/short/rust_core_backend_boundary.md`: a web app, mobile client, or editor integration ranking the same
episodes/events would need byte-identical scores to match the TUI.

Two consequences the earlier draft missed:

- Tuning a weight today is a code change with no config or `--explain`-at-the-CLI surface. The factor list is
  explainable internally (each factor has a label and evidence), but there is no user-facing way to see or adjust why
  an episode scored 62 vs 48.
- If importance later moves to `sase-core` (as the boundary memo implies it should once a second frontend needs it),
  the current magic constants become a wire-compatibility contract. Freezing them now, undocumented, risks a painful
  parity migration.

Recommend: before importance feeds event promotion or search ranking, (a) document the factor table and bands in one
place, (b) expose an `--explain` view that surfaces the existing factor breakdown, and (c) design the score envelope as
if it will move behind `sase_core_rs`, even if the v1 implementation stays in Python.

### 10. This Is All Research — There Is No Committed Plan, And The Notes Are Fragmenting

A critique of the *project direction* has to note that there is currently **no committed plan** for events or search:
no bead in `sdd/beads/` mentions `sase memory search`, `sdd/events`, or event cards, and the episode-v2 epic that
delivered the current surface is closed with no follow-on epic. Everything analyzed here lives in `sdd/research/`.

Meanwhile the research itself is fragmenting. At least three near-duplicate critiques carry the 2026-05-31 date alone —
this file, `memory_system_episodes_events_search_critique.md`, and
`sase_memory_system_critique_episodes_events_search.md` — on top of several consolidated notes
(`sase_memory_search_consolidated.md`, `sase_episodes_events_decision_consolidated.md`,
`episode_v2_events_consolidated_critique.md`). They broadly agree (single-file cards under `sdd/events/`, fix identity
first, direct-scan search, defer the dreamer), but parallel critiques that restate the same conclusions are now the
main source of drift risk.

Recommend: stop spawning parallel critiques and convert the consensus into one committed artifact — a short tale/epic
under `sdd/` with an ordered bead list (fix identity → freeze event format + README → ship search over hand-authored
cards → pilot → defer dreamer). Mark the superseded research notes as consolidated-into that artifact so future agents
read the decision, not five overlapping critiques.

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

10. Label and gate the episode-recall prompt block.

    In `src/sase/memory/episodes/prompt_recall.py`, prefix the `### EPISODIC MEMORY` block with an explicit
    non-authority preamble, and add an importance floor (and/or a `dream_generated` exclusion) so low-value or
    machine-authored episodes are not injected by default. Reuse the same trust label for `sase memory search` Tier 3
    results.

11. Make importance auditable and boundary-ready.

    Document the factor table and bands from `src/sase/memory/episodes/importance.py` in one place, add an `--explain`
    view over the existing per-factor breakdown, and design the score envelope so it can move behind `sase_core_rs`
    without changing the CLI contract. Treat importance as shared backend semantics, not TUI glue.

12. Document command boundaries.

    `sase memory list`, `sase memory episodes recall`, and a future `sase memory search` have overlapping scope. Add a
    short "which command when" table (inventory vs private-episode recall vs cross-tier discovery) to the memory docs so
    agents and users do not conflate them.

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
   `sase_core_rs`. Importance scoring (§9) is the most likely shared-semantics candidate — design it to move even if it
   ships in Python first.

7. Convert the consensus into one committed plan and stop spawning parallel critiques.

   The research has converged (see §10). Land a single tale/epic under `sdd/` with an ordered bead list — fix episode
   identity (with migration/alias) → freeze event format and write `sdd/events/README.md` → ship `sase memory search`
   over hand-authored cards → run the manual pilot → only then consider the dreamer. Mark the overlapping 2026-05-31
   critiques and consolidated notes as superseded by that plan so future agents read one decision, not five restatements.

8. Settle the recall trust model alongside events.

   Before event cards become promotable, decide and document the trust posture for any generated memory that reaches a
   prompt: episode recall (§8) and search Tier 3 must share one non-authority label, one importance/generated-content
   floor, and one "verify before relying" framing. Do not let events inherit an unframed `### EPISODIC MEMORY`-style
   injection.
