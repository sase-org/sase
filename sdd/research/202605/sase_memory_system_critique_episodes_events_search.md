---
create_time: 2026-05-31
status: research
title: "Critique of SASE's memory system: episodes, the events layer, and `sase memory search`"
consolidates:
  - sdd/research/202605/sase_memory_search_consolidated.md
  - sdd/research/202605/sase_episodes_events_decision_consolidated.md
  - sdd/research/202605/episode_v2_events_consolidated_critique.md
  - sdd/research/202605/memory_episode_connected_components_and_events.md
  - sdd/research/202605/git_versioned_episodic_events.md
verified_against_checkout: true
---

# Critique: SASE Memory System — Episodes, `memory/events/`, and `sase memory search`

## Scope And Method

This note critiques SASE's memory system as it actually exists in this checkout, then
critiques the planned event-memory layer and the planned `sase memory search` command.
It ends with a prioritized set of recommended changes to current code and to the
project's plans.

Inputs: I read the live implementation (`src/sase/memory/**`,
`src/sase/main/parser_memory.py`, `src/sase/memory/episodes/**`,
`src/sase/core/episode_facade.py`), the shipped docs (`docs/memory.md`,
`docs/episodes.md`), the existing consolidated research (memory-search, episodes/events
decision, episode-v2 critique, connected-components note), and the just-landed
`sdd/tales/202605/revert_dynamic_memory.md`. I verified the load-bearing claims below
against the checkout rather than trusting the prior notes, several of which were
explicitly stale.

### Verified current state (2026-05-31)

- **Three durable surfaces exist and are mature**: Tier 1 short memory (`memory/short/*.md`,
  always loaded via `@`-refs), Tier 2 long memory (`memory/long/*.md`, audited reads),
  and the **proposals ledger** (`sase memory write`/`review`, append-only JSONL under
  project state). Reads are gated and attributed through `sase memory read`
  (`src/sase/memory/read_log.py`); only `long/*.md` is readable, short memory is refused.
- **Episodes v2 has largely landed.** Contrary to the older `episode_v2_events_consolidated_critique.md`,
  the checkout now has: connected-component planning (`components.py`), `--split` builds,
  importance scoring (`importance.py`), member/alias identity (`identity.py`, `storage.py`),
  no-lesson v2 storage, and 9 CLI subcommands (`build`, `auto`, `status`, `doctor`,
  `export`, `list`, `show`, `verify`, `recall`). Episodes live under
  `~/.sase/projects/<project>/episodes/` and are explicitly **evidence, not instructions**.
- **Dynamic memory was reverted *today*** (`sdd/tales/202605/revert_dynamic_memory.md`,
  status: done). Keyword-triggered auto-injection of long memory, the `.sase/memory/long-*.md`
  cache, the `### DYNAMIC MEMORY` prompt section, and the late-rewrite pass were all removed.
  Opt-in episodic recall (`SASE_MEMORY_EPISODES_RECALL`) was deliberately preserved and split
  into its own module. **This revert is the single most important signal for the events and
  search direction** — see "Cross-Cutting Themes."
- **The events layer does not exist yet.** `sdd/events/` is absent. `src/sase/memory/events.py`,
  `search.py`, and `cli_search.py` are absent. `sase memory search` is **not registered**
  (the only `search` tokens in `parser_memory.py` are example strings). `sdd/beads/events/`
  exists but is operational bead state, not curated project memory.

### Terminology warning: three different "events"

The user's phrase "`memory/events/`" actually spans **three distinct, easily-conflated
concepts** in the research corpus. Disambiguating them is itself a finding, because the
plans drift between them:

1. **`sdd/beads/events/`** — operational bead event log. Exists today. Not memory.
2. **`sdd/events/YYYYMM/*.md`** — proposed *curated, repo-committed* project-memory cards
   (decisions, incidents, gotchas, postmortems). The main subject of the events plans.
3. **`src/sase/memory/events/`** (a code module) + **`.sase/memory/events.sqlite`** (a
   generated index) — proposed *implementation* surfaces for parsing/validating/indexing
   the cards in (2).

Throughout this critique, "the events layer" = (2) backed by (3). The plans should adopt
this vocabulary explicitly so "events" stops meaning three things.

---

## Part 1 — Critique of Episodes

### What is solid and worth keeping

- **The boundary model is correct.** "Date selects seeds; strong runtime lineage defines
  membership; ChangeSpec/bead/family/touched-path/date are weak refs that never merge" is
  the right call and is implemented (`components.py` union-find + strong edges;
  `docs/episodes.md` build selectors). It avoids the classic failure of lumping a
  long-running ChangeSpec into one giant blob.
- **Evidence, not instructions.** Episodes never write `memory/short|long`; promotion only
  goes through the reviewed proposal path. This trust boundary is stated in docs and
  enforced in code. Good.
- **Determinism + provenance.** Content-addressed IDs, canonical JSON via `sase-core`,
  per-source SHA-256, and a non-mutating `verify` that reports drift are genuinely strong
  primitives.

### Problem 1 (critical): v2 episode IDs are still path-dependent

This is the most important live defect, flagged in two prior notes and **still unfixed**.
`_component_root` (`src/sase/memory/episodes/components.py:612-635`) builds component keys
from `normalize_source_path(...)`, which is
`Path(path).expanduser().resolve(strict=False)` (`source_refs.py:48-51`) — an **absolute
path** including the home dir and the ephemeral `sase_<N>` workspace root:

```
component/artifact/<project>/<timestamp>/<ABSOLUTE artifact path>
component/chat/<ABSOLUTE chat path>
```

That `component_key` is fed directly into `generate_v2_episode_id(project, component_key)`
(`episode_facade.py`). **Consequence:** two machines, two home dirs, or two ephemeral
workspaces compute *different* v2 episode IDs for the same logical work. Given SASE's whole
premise is ephemeral `sase_<N>` clones (`memory/short/sase.md`), this is not a corner case —
it is the normal case. IDs are not portable, and any future `sdd/events/` card that cites an
episode ID, or any cross-machine sync, inherits non-determinism.

It is acceptable for absolute paths to remain *source refs* (they verify local files). It is
not acceptable for them to be the durable *identity* input. This must be fixed before any
durable consumer (events cards, sync, TUI deep-links) depends on v2 IDs.

### Problem 2 (high): massive surface area for an optional, unproven subsystem

The episodes feature now spans ~50 modules: collector (6 `_collector_*`), builder
(4 `_builder_*`), auto-build state machine (9 `_auto_build_*` with locks/checkpoints/
metrics/doctor), storage+identity+index, recall (4 `_recall_*`), importance, components,
export, render, views, plus 9 CLI files and a TUI explorer. The
`episode_v2_phase9_pilot.md` pilot reported the stored inventory was still **one** legacy
aggregate episode while a dry-run split produced **27** componentized episodes with **no
lessons**. In other words: a large, sophisticated machine whose real-world output has barely
been exercised, and whose v2 episodes carry `lessons=[]` (the human-legible payload is
empty by design). The cost/benefit is currently inverted — heavy infrastructure, thin
demonstrated value. This argues for a *usage pilot before further investment*, not more
phases.

### Problem 3 (high): importance weights are hardcoded magic constants

`importance.py` encodes ~12 factors with fixed point values (retry_recovered=18,
design_or_memory_requested=16, durable_docs=14, … noop=-4, dream_generated=-10) and fixed
band cutoffs (80/60/40/20). They are not configurable via `default_config.yml` or env (the
only config references in the file are *detecting* config-file edits as a scoring signal,
not reading weights). Prior memory-search research already recommends configurable weights
plus `--explain`. Until ranking is auditable and tunable, "importance band" is an opaque
editorial judgment baked into code — exactly the kind of thing that erodes trust when a
high-importance episode looks trivial to the user.

### Problem 4 (medium): the unscored-vs-zero ambiguity

The v2 wire defaults `importance_score=0` / `importance_band="unknown"`. `unknown` is a good
sentinel; `0` is not (it collides with "scored and genuinely worthless"). Any future
search/list/worker that sorts on score must special-case `unknown`, or the schema should
carry an explicit `scored` flag / nullable score. This is cheap to fix now and expensive to
retrofit after consumers depend on score ordering.

### Problem 5 (medium): the `lesson.md` zombie contract

V2 component episodes intentionally have no lessons and no `lesson.md`, but the legacy
aggregate path still writes `lesson.md`, index rows still carry `lesson_path`, and `show`
defaults to the lesson projection when present. This dual contract is fine for compatibility
but invites confusion — especially because the events plans propose *reusing the word
"lesson"* (and in one variant a `lesson.md` file) for curated repo cards. The same filename
meaning "private generated evidence" in one place and "reviewed repo memory" in another is a
trust-boundary trap. Terminology should be split deliberately.

### Smaller episode concerns (worth a cleanup pass, not blocking)

- Negative importance factors are clamped to 0 in the wire with the real value stashed in
  metadata — lossy round-trips.
- Source `exists` flags are computed at build time and not re-verified at recall time;
  recall can surface evidence pointing at deleted files.
- Component metadata is injected at collection time, not re-derived from the final graph, so
  a re-run could diverge.
- Chat root timestamps are parsed from filename stems with no validation.

---

## Part 2 — Critique of the Events-Memory Plans (`sdd/events/` + `src/sase/memory/events/`)

### The core decision is right

The consolidated decision note's conclusion is sound and should be locked in: **episodes are
NOT a prerequisite for `sdd/events/`.** A reviewed event card must stand alone after a fresh
clone, may *cite* an episode ID, but must not *require* the local episode store to be
intelligible. The push model (a finishing agent/user writes a card as work completes) needs
no episodes; only the pull model (a "dreamer" mining months of chats) does. Building
`sdd/events/` first as a standalone curated layer, with episodes as an optional
evidence/candidate feed, is the correct sequencing.

### Problem 6 (high): the event format is still undecided across notes

The research contains **three incompatible format proposals**:

| Source | Path shape | Identity |
| --- | --- | --- |
| `memory_search_consolidated` | `sdd/events/YYYYMM/evt_<YYYYMMDD>_<slug>_<6hex>.md` | `event_id` = filename stem |
| `episodes_events_decision` | `sdd/events/YYYYMM/<YYYYMMDD>-<slug>.md` | `evt_<date>_<slug>` |
| `connected_components_and_events` | `sdd/events/YYYYMM/<event_id>/lesson.md` (dir-per-event) | `event_id` |

The parser, validator, search index, Git-merge behavior, and the user's mental model all
hinge on this. This is not bikeshedding; it is a contract that must be frozen *before* any
code lands. **Recommendation: one reviewed markdown card per event** (file, not directory),
`evt_<YYYYMMDD>_<slug>_<6hex>.md`, `event_id` = filename stem. A single file is easier to
diff, link, supersede, and delete-for-secrets, and it avoids resurrecting the `lesson.md`
ambiguity from Problem 5. Use directory-per-event only if v1 genuinely needs sibling
artifacts (redaction/validation reports) — it does not.

### Problem 7 (high): the dreamer is the security-critical step and is being treated as cleanup

Across the notes, the LLM-driven "dreamer" that mines chats into proposed event cards is
consistently deferred to "later." But it is the *only* step that turns untrusted transcript
text (which may contain prompt-injection payloads) into repo-committed, searchable,
agent-consumed content. The validator/redactor/injection-scanner is therefore the
**security boundary of the entire feature** and must be an *early* phase of the events epic,
not a finishing touch after promotion already works. The plans correctly require
`safety.contains_untrusted_text`, `privacy: repo_safe`, repo-relative-only source refs, and
"never auto-inject event bodies as instructions" — those rules should be enforced by a
validator that exists before the first card is written, even hand-authored cards.

### Problem 8 (medium): SQLite/`memory/events.sqlite` is premature

`git_versioned_episodic_events.md` proposes a `.sase/memory/events.sqlite` FTS index. With
zero event cards today and a small corpus, a persistent index is premature complexity (and
must never be committed). The memory-search consolidation already reached the right answer:
**direct deterministic scan first**, behind a result model/JSON envelope stable enough to
swap in SQLite FTS5 (or a `sase-core` engine) later without changing the CLI contract. Hold
the index until corpus size or latency demands it.

---

## Part 3 — Critique of the `sase memory search` Plan

The `sase_memory_search_consolidated.md` design is the strongest document in the corpus and
is largely ready to implement. It correctly frames search as a **read-only finder** across
Tier 1/2/3 that **does not change trust boundaries**: Tier 2 results show pointers + the
exact audited `sase memory read` follow-up command (never body excerpts), and Tier 3 results
are labeled evidence, not authority. The result-model/JSON-envelope discipline is good. My
critiques are narrower:

### Problem 9 (medium): `search` partially overlaps `recall`, `list`, and `episodes recall` — the boundaries need one canonical statement

The memory surface is accreting verbs: `list` (launch-context inventory), `read` (audited
reader), `write`/`review` (promotion), `episodes recall` (private episode evidence search),
`episodes list` (episode inventory), and now `search` (cross-tier finder). A new user cannot
infer when to use `search` vs `episodes recall` vs `list`. The plan acknowledges this in
prose but the product needs a single authoritative "which command when" table in
`docs/memory.md` *shipped with* the search command, or the surface will feel like five
half-overlapping finders.

### Problem 10 (low/medium): the option surface is large for a v1

The proposed `search` has ~14 options (`-t/-l/-L/-f/-K/-e/-S/-s/-u/-o/-A/-x/-j` + query).
That is a lot for a finder whose Tier 3 corpus is empty. Ship a smaller v1 (`query`,
`-t/--tier`, `-l/--limit`, `-j/--json`, `-o/--order`) and add event-specific filters
(`-e/-S/-s/-u`) *with* the events layer that gives them meaning. Note the repo convention
(`memory/short/gotchas.md`) requires both short and long forms for every option — the plan
honors this, keep it.

### What's right and should be preserved as-is

- Direct scan over `build_memory_inventory(...)`; no DB in v1.
- Tier 2 never prints body; always emits the `read_command`.
- Default `priority` grouping (tier = trust prior) with optional `-o relevance` flat list.
- Empty results exit 0 with searched counts.
- Generated `AGENTS.md` gets a short "Searching Memory" discovery pointer, and Tier 3 is
  rendered only when cards exist — **never enumerate event cards** in `AGENTS.md` (prompt
  bloat). This is consistent with the dynamic-memory revert lesson below.

---

## Cross-Cutting Themes

### Theme A: The dynamic-memory revert is the lodestar

Today's revert removed exactly the pattern the events/search work could accidentally
recreate: **automatic, keyword-triggered injection of stored memory into prompts as
quasi-instructions.** The team tried it and pulled it out, keeping only *opt-in* episodic
recall. The lesson is explicit and should govern the events layer: event cards are
**searched, cited, and read on demand — never auto-injected as authority.** Both the events
plan ("never auto-inject event bodies") and the search plan (Tier 3 = evidence, pointers
only) already align with this. Make it a written, enforced invariant so the next iteration
doesn't reintroduce auto-injection under a new name.

### Theme B: Complexity budget

Episodes (~50 modules) + a new events epic (parser, validator, redactor, promotion, search,
optional dreamer, optional SQLite) + a 14-option search command is a large amount of
machinery for memory features whose demonstrated end-to-end usage is still a 27-episode
dry run and zero event cards. The healthiest next step is **a thin vertical slice that a
human actually uses**, not another horizontal phase.

### Theme C: Rust-core boundary

Per `memory/short/rust_core_backend_boundary.md`, behavior that multiple frontends must
match belongs in `sase-core`. Phase 1 correctly put episode wire/ID helpers there; the
component planner stayed in Python. The *stable semantics* — component-key normalization,
canonical winner selection, and (future) event frontmatter validation/scoring — are exactly
"must match across CLI/TUI/mobile/web." At minimum, pin cross-language golden fixtures for
component keys and v2 IDs before persistent writes; ideally move the pure identity
normalizer into `sase-core` when fixing Problem 1.

---

## Recommended Changes

### A. Current code (do these first; they prevent expensive retrofits)

1. **Fix path-dependent v2 episode identity (Problem 1, critical).** Derive `component_key`
   from stable logical members — project name, workflow/run dir name, timestamp,
   runtime-written retry/workflow/root identifiers, chat *basename* or content hash — not
   `normalize_source_path(...)` absolutes. Keep absolute paths only as source refs. Add
   tests proving: component keys are independent of `projects_root`/home; the same fixture
   under two temp roots yields the same `component_key` and v2 ID; chat-only components don't
   use absolute chat paths as roots. Put the normalizer in `sase-core` or pin golden
   fixtures (Theme C).
2. **Disambiguate the unscored/zero importance representation (Problem 4).** Add an explicit
   `scored` flag or make score nullable; forbid score-ordering when band is `unknown`.
3. **Externalize importance weights + add `--explain` (Problem 3).** Move the factor weights
   and band cutoffs into `default_config.yml`; surface score components in `show`/`recall`
   output behind `-x/--explain`.
4. **Quarantine the `lesson.md` zombie contract (Problem 5).** Add a regression test that
   *fails* if a v2 component episode ever writes `lesson.md`; document `lesson.md` as
   legacy-only; do not reuse "lesson"/`lesson.md` terminology for the events layer.
5. **Cleanup pass** for the smaller episode issues (lossy negative-factor clamping, recall
   re-verification of `exists`, filename-stem timestamp validation) — non-blocking.

### B. Plans / future direction

6. **Adopt the three-term vocabulary** (`sdd/beads/events/` = operational; `sdd/events/` =
   curated repo memory; `src/sase/memory/events/` + index = implementation). Stop writing
   "memory/events" ambiguously.
7. **Freeze the event card format before any code:** one markdown file per event,
   `sdd/events/YYYYMM/evt_<YYYYMMDD>_<slug>_<6hex>.md`, `event_id` = stem, required
   frontmatter (schema_version, event_id, title, summary, event_type, status, trust,
   privacy, scope, sources≥1, safety). Write `sdd/events/README.md` first.
8. **Sequence the events epic security-first (Problem 7):** spec + validator/redactor/
   injection-scanner → hand-authored pilot cards → `sase memory search` retrieval →
   episode-`export`-fed proposal inbox → (only later, gated) the dreamer. The dreamer is the
   one LLM step and must never write `sdd/events/` directly; it produces reviewable proposals.
9. **Keep episodes optional for events.** Cards cite episode IDs at most; they never require
   the local episode store. (Depends on Recommendation 1 making those IDs portable.)
10. **Ship `sase memory search` as a thin v1:** direct scan over `build_memory_inventory`,
    no SQLite (Problem 8), small option set (Problem 10), Tier 2 pointers-only with
    `read_command`, stable JSON envelope. Ship it *with* a canonical "which memory command
    when" table in `docs/memory.md` (Problem 9). Add event-specific filters only when
    `sdd/events/` exists.
11. **Run a usage pilot before more episode phases (Problem 2):** split a real May 2026 date
    window, inspect component quality and the importance histogram, hand-author 5–10 event
    cards from existing `sdd/research`/`sdd/tales`, and confirm a human finds the loop
    useful. Let that decide whether episodes have earned the role of event-candidate
    substrate.
12. **Codify the no-auto-injection invariant (Theme A)** in docs and a test: stored
    memory/events are searched, cited, and read on demand — never injected into prompts as
    instructions. This is the durable lesson of today's dynamic-memory revert.

## Bottom Line

The architecture is pointed the right way: deterministic private episodes as evidence,
audited Tier 2 reads, reviewed promotion, and (planned) a curated `sdd/events/` layer found
through a read-only `sase memory search`. The risks are not in the destination but in the
transition and the complexity budget:

- **One concrete bug to fix now:** v2 episode IDs are machine/workspace-dependent because
  `component_key` embeds absolute paths — fatal for portability and any durable consumer.
- **One decision to freeze:** the event card format (pick single-file-per-event).
- **One sequencing rule:** build the events validator/redactor security boundary *first*,
  the dreamer *last*.
- **One discipline to keep:** search and events are finders and evidence, never
  auto-injected authority — the exact line today's dynamic-memory revert just drew.

Fix identity before durable writes, freeze the event format before promotion machinery, and
prove the loop with a small human-used pilot before funding more episode phases. If those
gates hold, `sdd/events/` + `sase memory search` become genuinely useful curated memory. If
they don't, the system risks turning noisy generated summaries into repo-backed false
confidence.
