---
create_time: 2026-05-29
tier: research
status: consolidated
topic: Whether SASE episodes should be required for committed sdd/events lessons
---

# Critique: Are SASE Episodes Necessary for `sdd/events/`?

## Scope and Verification

This consolidates the two May 29, 2026 research drafts on episodes versus committed SDD events. I read the two provided
agent transcripts, then only the two research files they identified. I did not read any other `sdd/research/` Markdown
files.

I rechecked the core implementation claims against source:

- `sase memory episodes` describes episodes as deterministic evidence records under
  `~/.sase/projects/<project>/episodes`, not committed repo artifacts, and says they do not modify short or long memory
  (`src/sase/main/parser_memory_episodes.py`).
- Episode source references store path, existence, size, and SHA-256 metadata, not the source content itself
  (`src/sase/core/episode_wire.py`, `src/sase/memory/episodes/source_refs.py`).
- Verification recomputes source state without mutating the episode, so it detects drift or disappearance but does not
  preserve deleted evidence (`src/sase/memory/episodes/verify.py`).
- V2 component episodes intentionally set `lessons = []`, and storage does not write `lesson.md` for v2 component
  episodes (`src/sase/memory/episodes/builder.py`, `src/sase/memory/episodes/storage.py`).
- Episode export is explicitly read-only and includes `writes_events: false`
  (`src/sase/memory/episodes/export.py`).
- The current tree has `sdd/beads/events/`, but no top-level `sdd/events/` directory yet.

## Short Answer

Do not make SASE episodes necessary for committing events or lessons to `sdd/events/`.

The cleaner boundary is:

- `sdd/events/` is the authoritative, reviewed, portable, git-versioned project memory layer.
- Episodes are an optional local evidence/index layer for discovery, lineage reconstruction, recall, and source-drift
  audit.
- A committed event may reference episode IDs, but it must stand alone after clone without requiring the local episode
  store.

This is a critique of making episodes a prerequisite for events, not a claim that episodes have no value.

## The Important Distinction

There are two separate decisions:

1. Should SASE have episodes at all?
2. Must `sdd/events/` depend on episodes?

The answer can reasonably be "maybe" for the first and "no" for the second. Episodes have independent uses: opt-in
prompt recall reads the episode index and formats recalled episode cards for prompt augmentation
(`src/sase/memory/dynamic.py`), and the episode planner can stitch together chats, artifacts, retries, workflow steps,
ChangeSpecs, and beads. Those may justify episodes on their own. They still should not become the required format or
gate for durable lessons.

## What Each Layer Should Own

| Layer | Storage | Writer | Role |
| --- | --- | --- | --- |
| Raw artifacts and chats | Agent artifact dirs and chat transcripts | Runtime | Noisy source material |
| Episodes | `~/.sase/projects/<project>/episodes` | Machine | Local evidence graph, index, recall, drift checks |
| Events | `sdd/events/YYYYMM/...` | Human or reviewed agent | Durable lesson, decision, invariant, or incident record |

Episodes are evidence packaging. Events are editorial judgment. The valuable event is not "a graph exists"; it is "this
lesson is important enough to commit, review, and carry forward."

## Strongest Case For Episodes

Episodes solve real problems that are hard to solve by hand:

- **Lineage reconstruction.** Work can be spread across parent agents, retries, forks, linked chats, workflow children,
  ChangeSpecs, beads, and touched files. A connected-component planner can recover context that an author might miss.
- **Candidate discovery.** If you want to mine a week of agent activity for notable lessons, an indexed inventory and
  importance bands are useful triage aids.
- **Recall.** Stored episodes can support prompt augmentation with compact evidence cards, which is a separate consumer
  from committed events.
- **Audit.** Source hashes, missing-source flags, safety metadata, and `verify` help detect when an event's evidence
  trail has changed.
- **Deduplication.** Component identity, member indexes, and aliases can reduce repeated candidate events for the same
  work.

That strongest case says episodes are useful as staging and audit infrastructure. It does not prove they are necessary
for committing reviewed lessons.

## Case Against Making Episodes Required

### 1. Events Need Durability; Episodes Mostly Store References

The most compelling reason for a persistent intermediate layer would be evidence preservation before raw artifacts are
pruned. Current episodes do not provide that guarantee. They store source references and hashes, not inlined source
content. If a transcript disappears, `verify` can tell you it disappeared, but the episode does not recover the text.

For a git-committed lesson, the durable record should inline the key evidence or quote/summarize enough context in the
event itself. Optional source paths and episode IDs are useful provenance, but they cannot be the only evidence.

### 2. V2 Episodes Are Not Lesson-First

The current v2 path builds component evidence packages with summaries and importance metadata. It deliberately leaves
`lessons` empty and skips `lesson.md` storage for component episodes. That is a good design if episodes are an evidence
index. It is the wrong dependency if the desired output is a committed lesson under `sdd/events/`.

### 3. The Event Curation Path Is Cold

Materialized caches pay for themselves when the query path is frequent or latency-sensitive. Event creation should be
rare and reviewed. If lessons are usually obvious during the work, requiring an episode first adds ceremony before the
main act: writing the event.

This point has one caveat: if episode recall becomes a high-value everyday prompt feature, that can justify the episode
store independently. It still does not make the store a prerequisite for events.

### 4. Importance Scoring Can Sort, Not Decide

A deterministic score is useful for candidate ordering. It is not the same as correctness. The decision "this should be
project memory" is editorial and review-driven. If `sdd/events/` requires an episode only to get a score, the workflow
will confuse a triage heuristic with the actual judgment.

### 5. Required Episodes Would Blur Privacy and Portability Boundaries

Episodes naturally know about local artifact paths, chat transcript paths, untrusted transcript text, private or missing
sources, prompt-injection hits, and redaction hits. That is exactly why they should be a pre-commit review aid. The
committed event should contain only sanitized, portable information that is safe and useful in the repository.

### 6. The Intermediate Layer Can Become the Product

The episode surface is broad: build, auto-build, status, doctor, export, list, show, verify, recall, indexes, aliases,
metrics, locks, and TUI affordances. That may be justified for local memory and recall. But if `sdd/events/` is still
undefined, the risk is that the intermediate evidence system absorbs attention while the durable reviewed memory format
remains missing.

## Recommended Architecture

Build `sdd/events/` first as the authoritative reviewed memory stream. Keep episodes optional.

Use Markdown with frontmatter for lesson and decision records unless machine replay becomes more important than human
review. A minimal event could look like:

```yaml
schema_version: 1
event_id: 20260529-sase-episodes-events-boundary
timestamp: 2026-05-29T00:00:00-04:00
kind: decision
status: reviewed
confidence: medium
episode_ids: []
source_paths: []
privacy: public-repo-safe
```

The body should answer:

- What happened or what was learned?
- Why does it matter?
- What should future agents do differently?
- What evidence supports the lesson?

If an episode exists, add `episode_ids` and source paths. If no episode exists, commit the event anyway. The event must
carry the critical evidence itself.

## Decision Rule

Use episodes when:

- You are mining old work.
- You need transitive agent/chat/retry/workflow context.
- You want source hashes, source-drift checks, or duplicate-component detection.
- You want prompt recall over prior work.

Skip episodes when:

- The lesson is clear in the moment.
- The event is being authored directly during or immediately after the work.
- The record must be portable across clones.
- The source material includes private or local-only evidence that should not shape the committed artifact.
- The extra step would make the event less likely to be written.

## Open Questions That Actually Decide Future Investment

- What is the retention policy for raw agent artifacts and chats? If they are pruned, the event writer needs a way to
  inline or snapshot key evidence, not merely keep hashes.
- How often will someone triage a week or month of agent work for lessons? Frequent triage favors episode inventory;
  in-the-moment lesson writing favors direct events.
- How valuable is opt-in episodic prompt recall in practice? That can justify episodes independently of `sdd/events/`.

## Recommendation

Proceed with `sdd/events/` without making episodes required. Treat episodes as a helpful local evidence cache and recall
system that can suggest events, reconstruct provenance, and audit source drift. The committed event should be the durable
reviewed unit of memory, with optional episode references rather than an episode dependency.
