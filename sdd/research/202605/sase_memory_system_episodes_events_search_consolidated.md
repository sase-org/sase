---
create_time: 2026-05-31
status: research
title: "Consolidated critique of SASE memory episodes, event memory, and `sase memory search`"
source_transcripts:
  - ~/.sase/chats/202605/sase-ace_run-260531_143950.md
  - ~/.sase/chats/202605/sase-ace_run-260531_143951.md
consolidates:
  - sdd/research/202605/memory_system_episodes_events_search_critique.md
  - sdd/research/202605/sase_memory_system_critique_episodes_events_search.md
verified_against_checkout: true
---

# Consolidated Critique: SASE Memory Episodes, Event Memory, And Search

## Research Question

Critique SASE's memory system, especially episode memory, the plans around event memory
(`memory/events/` in the prompt), and the proposed `sase memory search` command. End with a
recommended set of code and planning changes.

## Method

I read both completed-agent chat transcripts first, identified their created research notes,
then read both notes. I rechecked the load-bearing claims against the current checkout rather
than assuming the notes were current.

Verified code and project material included:

- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
- `src/sase/memory/episodes/components.py`
- `src/sase/memory/episodes/source_refs.py`
- `src/sase/memory/episodes/builder.py`
- `src/sase/memory/episodes/storage.py`
- `src/sase/memory/episodes/importance.py`
- `src/sase/memory/episodes/prompt_recall.py`
- `src/sase/core/episode_facade.py`
- `docs/memory.md`
- `docs/episodes.md`
- `sdd/tales/202605/revert_dynamic_memory.md`
- prior May 2026 research on `sase memory search`, `sdd/events/`, and episode v2

## Verified Current State

SASE currently has three mature memory surfaces:

- `memory/short/*.md`: loaded launch instructions via `@memory/...` references.
- `memory/long/*.md`: curated reference memory readable only through audited
  `sase memory read`.
- the proposal/review ledger behind `sase memory write` and `sase memory review`.

That trust model is sound: agents can discover and propose, but canonical long memory still
requires review.

Dynamic memory was removed in commit `e8c2f14bb feat: remove dynamic memory runtime`.
Keyword-triggered long-memory matching, `.sase/memory/long-*.md` cache generation, the
`### DYNAMIC MEMORY` prompt section, and late prompt rewriting were all removed. Opt-in
episodic prompt recall was preserved separately through `SASE_MEMORY_EPISODES_RECALL`.

Episode v2 has largely shipped. The current checkout has connected-component planning,
`build --split`, no-lesson v2 component storage, member/alias indexes, importance scoring,
`auto`, `status`, `doctor`, `export`, `recall`, documentation, and ACE explorer support.
Older critiques that describe episode v2 as mostly unbuilt are stale.

`sase memory search` is not implemented. The parser exposes only
`{episodes,init,list,log,read,review,write}`, and `memory_handler.py` has no `search`
dispatch branch. Running `sase memory search --help` fails as an invalid subcommand.

Neither `sdd/events/` nor `memory/events/` exists in this checkout. Existing
`sdd/beads/events/` files are operational bead state, not curated project memory.

## Terminology Finding: "memory/events" Is Ambiguous

The prompt says `memory/events/`, but the plans mix at least three concepts:

| Name | Meaning | Current state |
| --- | --- | --- |
| `sdd/beads/events/` | operational bead event ledger | exists; not memory |
| `sdd/events/YYYYMM/*.md` | proposed reviewed project-memory event cards | absent |
| `src/sase/memory/events.py` plus a generated index | implementation/parser/search support | absent |

Use `sdd/events/` for curated, repo-committed event cards. Do not add canonical
`memory/events/` unless the product intentionally creates a third loaded/reference memory
tier. A `memory/events/` directory would blur authority, interact badly with AGENTS memory
rules, and make historical evidence look like always-loaded or directly readable memory.

## Critique

### 1. The Memory Trust Model Is Right, But Discovery Is Missing

Removing dynamic memory was the right safety move. It stopped hidden keyword-triggered
prompt injection and left explicit, auditable reads as the main path into long memory.

The gap is now discovery. `sase memory list` answers "what is visible?" and
`sase memory read` reads a known long-memory file, but agents still need to already know
which file matters. Episode recall searches private episode evidence only. There is no
cross-tier finder that answers "what project memory is relevant to this question?"

`sase memory search` should fill that middle layer as a finder, not as dynamic memory 2.0.
It should return paths, labels, evidence, and follow-up commands. It should not silently
inject bodies into prompts or bypass the audited `read` path.

### 2. Episode V2 Has One Critical Live Defect: Path-Dependent IDs

The most serious current bug is still present. `_component_root()` in
`src/sase/memory/episodes/components.py` builds durable `component_key` values from
`normalize_source_path(...)`. That helper resolves paths with
`Path(path).expanduser().resolve(strict=False)`, so component keys include absolute local
paths such as home directories and ephemeral `sase_<N>` workspace roots.

Those keys feed directly into `generate_v2_episode_id(project, component_key)`. The same
logical work can therefore receive different v2 episode IDs on another machine, another
home directory, or another numbered workspace. That conflicts with SASE's normal
ephemeral-workspace model and undermines:

- multi-machine sync;
- restored project state;
- event cards that cite episode IDs;
- cross-workspace comparison;
- future search indexes that treat episode IDs as stable keys.

Absolute paths are acceptable inside source refs and member indexes for local verification.
They should not be the durable identity input.

### 3. Episodes Are Useful Evidence, But Should Not Gate Event Memory

Episodes provide real value: segmentation, source refs, drift checks, weak refs, recall,
importance hints, and private high-volume storage. They are appropriate for "what happened
in this prior run?" and for future event-candidate mining.

They are not required for the first event-memory layer. A reviewed event card should stand
alone after a fresh clone and inline enough context to be useful without a local
`~/.sase` episode store. It may cite an episode ID as optional provenance, but it should
also cite repo-safe evidence such as research files, plans, commits, bead IDs,
ChangeSpecs, and chat basenames/hashes.

The right flow is:

```text
raw chats/artifacts
  -> private episodes
  -> optional event proposal aid
  -> reviewed sdd/events event card
  -> optional memory/long proposal using the event as evidence
```

### 4. Event Format Must Be Frozen Before Code Lands

Prior notes propose incompatible shapes:

- `sdd/events/YYYYMM/evt_<YYYYMMDD>_<slug>_<6hex>.md`
- `sdd/events/YYYYMM/<YYYYMMDD>-<slug>.md`
- `sdd/events/YYYYMM/<event_id>/lesson.md`
- the prompt's ambiguous `memory/events/`

This is a contract, not a cosmetic choice. It affects parsing, validation, search results,
Git review, supersession, and user understanding.

Use one markdown file per event in v1:

```text
sdd/events/
  README.md
  202605/
    evt_20260531_memory_search_command_a1b2c3.md
```

`event_id` should equal the filename stem. The required frontmatter should include at
least `schema_version`, `event_id`, `title`, `summary`, `event_type`, `status`,
`occurred_at`, `created_at`, `project`, `trust`, `privacy`, `scope`, `sources`,
`keywords`, `supersedes`, `superseded_by`, and `safety.contains_untrusted_text`.

Avoid directory-per-event `lesson.md` in v1. V2 component episodes intentionally removed
`lesson.md`; reusing that filename for reviewed event memory would reintroduce a confusing
contract.

### 5. The Dreamer Is Security-Critical, Not Cleanup

The planned dreamer would mine chats/episodes and propose event cards. That is the only
step that turns untrusted transcript/tool text into repo-committed, future-searchable
memory. Treat it as the security boundary.

Before any automated promotion path exists, the project needs a validator/redactor that
checks:

- required frontmatter and unique `event_id`;
- repo-safe, non-absolute source references;
- privacy classification;
- redaction findings;
- prompt-injection-like content;
- `safety.contains_untrusted_text`;
- event status/supersession rules.

The dreamer should always write proposals, never canonical `sdd/events/` files or
`memory/long` entries.

### 6. Search Should Start As Direct Scan

The strongest search plan is a read-only direct scan over existing inventory, not a
database project. The corpus is small, `sdd/events/` is empty, and direct scan is easier
to verify.

V1 should search:

- loaded short memory as already-loaded instruction context;
- long memory as pointers only, with an exact audited `sase memory read ... --reason ...`
  follow-up command;
- future `sdd/events/YYYYMM/evt_*.md` cards as reviewed evidence.

Do not include private episodes by default. Episode recall already exists as
`sase memory episodes recall`; add `--tier episodes` or `--include-episodes` later only if
users need a single finder to bridge into private evidence.

Use a stable JSON envelope from the start so SQLite FTS5, `sase-core`, or another backend
can replace the engine later without changing callers:

```json
{
  "query": "generated skills",
  "searched": {"short": 5, "long": 2, "events": 0, "episodes": 0},
  "order": "priority",
  "results": [],
  "warnings": []
}
```

### 7. Episode Recall Needs Stronger Evidence Framing

`format_episode_recall_section()` currently starts with `### EPISODIC MEMORY` and emits
episode cards. Because recalled text can derive from chats, tool output, and other
untrusted material, the injected section should say explicitly that recalled episodes are
historical evidence, not instructions, and that cited sources should be inspected before a
claim is relied on. Surface safety warnings or a compact warning count when present.

### 8. Importance Scoring Needs Auditability

`importance.py` hardcodes factor weights and band cutoffs. The score is useful for sorting
and future candidate selection, but hardcoded editorial weights will be hard to trust once
they influence search or dreamer batches.

Move weights and band cutoffs into config, add an explain view, and disambiguate "unknown
importance" from a real score of zero. Today v2 wire defaults combine
`importance_score=0` with `importance_band="unknown"`, which invites accidental bad
ordering unless every consumer special-cases `unknown`.

## Recommended Changes

### Current Code

1. **Fix v2 episode identity before building durable consumers on episode IDs.**
   Derive `component_key` from stable logical members rather than absolute paths: project,
   workflow/run identifiers, timestamps, retry-chain root, existing fork target component
   key, chat basename plus content hash, or similar. Keep absolute paths only in source
   refs/member indexes. Add tests proving the same fixture under two temp roots produces
   the same component key and v2 ID. Per the Rust-core boundary, put the pure normalizer in
   `sase-core` or pin cross-language golden fixtures.

2. **Add migration/alias handling for already-written absolute-key v2 episodes.** Provide
   a `doctor --repair` or rebuild path that recomputes logical keys, writes canonical IDs,
   preserves old directories, adds aliases from old IDs, and rebuilds `index.jsonl`.

3. **Implement `sase memory search` as a direct-scan v1.** Add
   `src/sase/memory/search.py`, `src/sase/memory/cli_search.py`, parser/handler branches,
   and tests for parser help, JSON envelope, no Tier 2 body leakage, ranking, warnings,
   and read-command output. Keep the v1 option surface small: query, `-t|--tier`,
   `-l|--limit`, `-o|--order`, and `-j|--json`.

4. **Add event-card parsing and validation before promotion automation.** Use
   `sdd/events/YYYYMM/evt_*.md`; warn on invalid cards without failing the whole search.
   Do not create `memory/events/` as a canonical memory tier.

5. **Strengthen opt-in episode recall formatting.** Add evidence/not-instruction framing
   and include safety warning visibility.

6. **Make importance ranking auditable.** Add a nullable score or explicit `scored` flag,
   configurable weights/bands, and an explain surface for importance factors.

7. **Quarantine the legacy `lesson.md` contract.** Add a regression test that v2 component
   episodes never write `lesson.md`; document the file as legacy-only; do not reuse
   `lesson.md` for event cards.

### Plans And Future Direction

1. **Retire ambiguous "memory/events" language.** Document the three meanings explicitly:
   `sdd/beads/events/` is operational state, `sdd/events/` is curated project memory, and
   `src/sase/memory/events.py`/generated indexes are implementation details.

2. **Freeze the event-card contract before code.** One markdown file per reviewed event:
   `sdd/events/YYYYMM/evt_<YYYYMMDD>_<slug>_<6hex>.md`, with `event_id` equal to the stem.
   Write `sdd/events/README.md` first.

3. **Sequence the events epic security-first.** Spec and validator/redactor first, then
   hand-authored pilot cards, then `sase memory search` over those cards, then proposal
   plumbing, and only later a gated dreamer.

4. **Keep episodes optional for events.** Direct event authoring should be allowed from
   plans, research, commits, beads, ChangeSpecs, and chat basenames. Episodes are optional
   evidence and candidate-generation substrate.

5. **Do not add SQLite/FTS or embeddings in v1.** Add a rebuildable index under project
   state only when corpus size or latency proves direct scan inadequate. Never commit the
   index.

6. **Ship docs with the search command.** `docs/memory.md` needs a canonical "which
   command when" table covering `list`, `search`, `read`, `episodes recall`, `write`, and
   `review`. Generated AGENTS guidance should mention search as discovery, but must not
   enumerate event cards.

7. **Run a small human-used pilot before more episode phases.** Seed 5 to 10 hand-authored
   event cards from existing May 2026 research/tales and test realistic queries such as
   "dynamic memory removed", "episode component identity absolute paths", "rust core
   backend boundary", and "memory write review gate". Tune metadata and ranking before
   adding dreamer automation.

8. **Codify the no-auto-injection invariant.** Memory and event records are searched,
   cited, and read on demand. They are never auto-injected as instruction authority. This
   is the durable lesson of the dynamic-memory revert.

## Bottom Line

The architecture is pointed in the right direction: private deterministic episodes as
evidence, audited long-memory reads, reviewed promotion, and a planned curated event layer
found through explicit search.

The immediate risks are concrete and fixable:

- v2 episode IDs are not portable because component keys embed absolute paths;
- the event-card path/schema is not frozen;
- `sase memory search` is still missing after dynamic memory was removed;
- dreamer/event automation could turn untrusted transcript text into repo memory unless
  validation comes first.

Fix episode identity, ship a small explicit search command, define `sdd/events/` as
reviewed evidence rather than a new loaded memory tier, and prove the loop with manual
cards before funding more automation.
