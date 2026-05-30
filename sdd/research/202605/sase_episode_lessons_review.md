# SASE Episode Review: Lessons for Future Agents

**Date:** 2026-05-30
**Author:** research agent (sase_13 workspace)
**Scope:** All 83 stored SASE episodes for the `sase` project (`sase memory episodes list`),
their referenced chat transcripts (`~/.sase/chats/202605/`), SDD tales/plans
(`sdd/tales/202605/`, `sdd/prompts/202605/`), the chop xprompts (`xprompts/`), and the
episode-builder source (`src/sase/memory/episodes/`).

---

## 1. Method

Episodes are deterministic, source-linked **evidence records** — not instructions. They tie
prompts, chats, plans, retries, beads, ChangeSpecs, and outcomes into inspectable bundles
(`docs/episodes.md`). To mine lessons I:

1. Inventoried all episodes and bucketed them by type and importance.
2. Deep-read the ~13 substantive feature/research/tooling episodes via
   `sase memory episodes show <id> --format lesson|timeline`, then read their referenced
   chats and tales.
3. Read the four scheduled-chop xprompt definitions and the episode-builder source to
   ground claims about chop scheduling and the safety-warning system.
4. Verified load-bearing technical claims against current code/git history so recommendations
   reflect the present state, not transient mid-fix snapshots.

---

## 2. Episode Inventory

| Bucket | Count | Importance | Notes |
| --- | --- | --- | --- |
| Scheduled chops (`sase_recent_bug_audit-N`, `sase_recent_improvement_audit-N`, `sase_pylimit_split-N`, `sase_refresh_docs-N`) | ~70 | low | Hourly automated jobs; mostly no-ops. Repetitive but encode a reusable pattern. |
| TUI/UI feature work (bn7, bn8, boc, boj, boh) | 5 | medium | Real human-driven feature episodes. |
| Memory/episodes tooling + chop config (bod, boe, bof, bok) | 4 | low–medium | The episodes system testing itself; richest source of system gotchas. |
| Research swarm (`research_swarm.cdx/cld/final/image`) | ~5 | low | Multi-model fan-out → consolidation → infographic. |
| Undated "previous conversation" fragments | several | low | Low signal. |

**Signal concentration:** ~70 of 83 episodes are repetitive automation. The durable lessons
come almost entirely from the ~13 substantive episodes plus the *pattern* the chops embody.

---

## 3. Lessons by Theme

Each lesson is rated for **reusability** — would it help a future agent on a *different* task?
One-off implementation bugs (already captured in their tales) are excluded; only generalizable
findings are listed.

### Theme A — The Memory/Episodes System (highest value)

**A1. `project-scan` builds expand transitively and can be slow/hang on busy days.**
Default project-scan date filtering bounds the *seed* set, but transitive expansion through
ChangeSpec-related records historically ignored the same project/date window and pulled in
thousands of records (one day's build: 255 seed records → 5672 ChangeSpec-linked records;
multi-minute hangs). Explicit selectors (`--agent`, `--chat`, `--artifact-dir`) are the
bounded-but-rich path. *Evidence:* ep-6b9619e5 (bok), ep-4073e6ba (bod),
`sdd/tales/202605/memory_episodes_build_hang.md`. **Reusability: HIGH.**

**A2. Build progress now goes to stderr; stdout stays clean for `--json`.**
The slowest phase (project artifact scan) used to run silently, indistinguishable from a hang.
Human mode now prints phase spinners + counts to stderr; `--json` is silent; `--quiet`
suppresses. Landed in `d00a15653`. *Evidence:* ep-6b9619e5,
`sdd/tales/202605/episodes_build_progress.md`, tests
`test_memory_episodes_build_*_progress*`. **Reusability: HIGH** (don't reinvent; don't mistake
a slow human-mode build for a hang).

**A3. Safety warnings are additive metadata, not errors.**
`warnings=N safety flag(s)` on an episode does **not** mean the build failed — episodes with
warnings are still `active` and queryable. Flags come from `derive_safety()`
(`_builder_derivation.py`): `hidden-source` / `private-source` (workflow internals like
`workflow_state.json`, `prompt_step_*.json` marked hidden/private in their JSON), and
`missing-source` (deleted/unreachable files), plus prompt-injection phrase and credential-regex
scans of source text. *Evidence:* ep-dbf0db96, ep-4073e6ba, ep-a30208be (all `warnings=2`,
all `hidden-source`), `src/sase/memory/episodes/_builder_derivation.py`. **Reusability: HIGH**
(prevents future agents from treating routine `warnings=2` as breakage).

**A4. Episodes are evidence, not instructions — route reusable rules through `sase memory write`.**
Episodes never write `memory/short` or `memory/long`. A reusable rule found in an episode must
be proposed with `sase memory write` and approved via `sase memory review`. *Evidence:*
`docs/episodes.md`. **Reusability: HIGH** (defines the correct promotion path — including for
this very document's recommendations).

**A5. Identity-collapse caveat for research-swarm clusters.**
The episode identity layer can collapse multiple related components (e.g.
`research_swarm.final`/`image`) into one canonical episode and keep only the last-written source
set, so a few chats can go unreferenced (one bulk build: 112 of 117 day chats stored). Verify
passes regardless. *Evidence:* ep-6b9619e5, ep-a30208be. **Reusability: MEDIUM** (matters when
auditing coverage or debugging "missing" chats).

**A6. Bulk/day builds need a chat-coverage pass.**
Artifact-scan builds miss standalone chats (workflow wrappers, failed/temp runs) that have no
artifacts. Complete coverage requires seeding missing chats separately *after* the scan, folding
into existing canonical episodes rather than creating duplicates. *Evidence:* ep-6b9619e5.
**Reusability: MEDIUM.**

### Theme B — Scheduled Chops & Multi-Agent Orchestration

**B1. Chop scheduling: `interval` vs `chop_timeout` vs `run_every`.**
Lumberjacks (`default_config.yml: axe.lumberjacks`) have an `interval` (wake frequency, seconds)
and `chop_timeout`; a per-chop `run_every` ("15m" → 900s) throttles an individual chop
independently of the wake interval. Both must align for a desired cadence (e.g. `interval: 300`
+ `run_every: "15m"`). *Evidence:* ep-9d2fdcb7 (boe), ep-c1d2a252 (bof),
`sdd/tales/202605/memory_episodes_chop_1.md`, `src/sase/default_config.yml:223-263`.
**Reusability: HIGH.**

**B2. Config deep-merge: dicts merge recursively, lists replace wholesale.**
SASE loads defaults then deep-merges user YAML. Adding a *new* key under `axe.lumberjacks` is
safe (preserves default lumberjacks); appending to an existing lumberjack's `chops` *list* would
replace the default chops entirely. Add a new lumberjack instead of editing a default's list.
*Evidence:* ep-9d2fdcb7, ep-c1d2a252, `memory_episodes_chop_1.md`. **Reusability: HIGH**
(applies to any config edit, reinforces existing `gotchas.md` "Default Keymap Config" note).

**B3. Marker-based lazy-audit pattern (count → launch → update marker, atomically).**
The four audit chops persist a marker (SHA + timestamp) in `~/.sase/projects/<project>/`, count
commits since it, launch an agent only past a threshold (~200 commits; 100 for docs), and update
the marker **only if** the launch succeeded. Falls back to timestamps when the SHA is GC'd;
forces an audit on first run / corrupted marker. *Evidence:* `xprompts/audit_recent_bugs.yml`,
`audit_recent_improvements.yml`, `pylimit_split.yml`, `refresh_docs.yml`; ~70 episodes.
**Reusability: HIGH** (template for any periodic, batched, idempotent automation).

**B4. Audit prompts enforce narrow scope to avoid churn.**
The audit prompts explicitly reject style-only edits, speculative refactors, broad rewrites,
renames, and preference changes — which is why most audit episodes are no-ops. *Evidence:* audit
xprompts; consistent `noop` outcomes. **Reusability: MEDIUM.**

**B5. Research-swarm = multi-model fan-out → consolidation → fork-to-image, with cleanup.**
`research_swarm.md` fans out independent research across `codex/gpt-5.5` and `claude/opus`
(`%g:research`), a `%wait`-gated `final` agent reads both transcripts and merges them
(explicitly **deleting** the two intermediate `sdd/research/` files to prevent bloat), then an
`image` agent `%fork`s the final to generate an infographic. *Evidence:* `xprompts/research_swarm.md`,
ep-a30208be / ep-35bff7da. **Reusability: MEDIUM–HIGH** (reusable shape for research/design tasks
needing model diversity + a visual artifact).

### Theme C — TUI / Presentation Engineering

**C1. Separate display formatting from stored data and CLI contracts.**
Recurring across episodes: relative-path display falls back to `source_path` then absolute
(bn7); tag-label capitalization (`done`→`Done`) is applied at render time while stored tags and
CLI contracts stay unchanged (bn8). Never mutate stored values for cosmetic display. *Evidence:*
ep-c2f1302a, ep-dbf0db96. **Reusability: HIGH.**

**C2. In-memory status overrides must be reconciled against fresh source-of-truth on reload.**
A stale `QUESTION` override survived after children moved to `RUNNING`; the fix added a shared
reconciliation helper used by both sync and worker finalize paths. *Evidence:* ep-c70b902c (boj).
**Reusability: MEDIUM.**

**C3. Stale-tokens for precomputed state must encode identity AND value.**
A token keyed only on which row had an override let an old `QUESTION` clear a newer `PLAN` on the
same row; including the override *value* forced recomputation. *Evidence:* ep-c70b902c.
**Reusability: MEDIUM** (general caching/precompute correctness pattern).

**C4. Test Rich/Textual markup safety for footer/hint strings.**
A `[/]: tags` footer hint is parsed as Rich markup and can break rendering; `[]: tags` was chosen
with an explicit markup-safety regression test. Also: keep modal-local binding hints in sync with
the bindings via a focused test so shortcuts don't become invisible. *Evidence:* ep-decdbb32 (boc).
**Reusability: MEDIUM** (recurring TUI gotcha).

---

## 4. Recommendation: What to Promote to `memory/long/`

> Per Lesson A4 and `AGENTS.md`, memory files must not be modified without user approval, and
> reusable rules should be promoted via `sase memory write` / `sase memory review`. The below is
> a **proposal** for the user to approve — no memory files were changed.

### Primary (recommended) — two new tier-3 reference files

**1. `memory/long/memory_episodes_system.md`** — *How the episodes/memory system behaves and its
gotchas.* Fold in **A1–A6**: build selectors and the project-scan transitive-expansion cost;
stderr-progress vs clean `--json`; the safety-warning model (`hidden`/`private`/`missing` +
injection/credential scans) being **additive, not fatal**; episodes-are-evidence + the
`sase memory write`/`review` promotion path; the identity-collapse and chat-coverage caveats for
bulk builds. This is the single highest-value addition — it directly prevents future agents from
misreading `warnings=2`, mistaking slow builds for hangs, and choosing the wrong build selector.
It matches the existing tier-3 reference style (cf. `generated_skills.md`).

**2. `memory/long/axe_chops_and_swarms.md`** — *Scheduling automation and multi-agent
orchestration.* Fold in **B1–B5**: the `interval`/`chop_timeout`/`run_every` model; the
dict-merge/list-replace config rule (add a new lumberjack, never append to a default's `chops`);
the marker-based atomic lazy-audit pattern and its narrow-scope discipline; and the research-swarm
fan-out/consolidate/fork-to-image shape with intermediate cleanup. High reuse for anyone adding a
scheduled job or a multi-agent workflow.

Then register both under the "Long-Term Memory Files" list in `AGENTS.md` (with one-line
descriptions) so the tier-3 index stays accurate.

### Secondary (optional) — small `memory/short/gotchas.md` additions

These are short, always-loaded conventions rather than deep reference, so they fit tier-1 better
than tier-3 if promoted at all:

- **C1** — Separate display formatting from stored data / CLI contracts (one line).
- **C4** — Avoid raw `[`/`]` in Rich/Textual hint strings; test markup safety (one line).

### Do **not** promote

- One-off implementation bugs already captured in their tales (timeline grouping `views.py:452`,
  graph edge noise, retry self-loops, component-key absolute paths, `verify --json` aggregates).
  These were point fixes, not durable rules — they live correctly in
  `sdd/tales/202605/` and the git history.
- **C2/C3** (override reconciliation, identity+value stale-tokens): real but narrow; leave as
  tale-level knowledge unless the override system keeps generating regressions, in which case
  promote C2+C3 together into the TUI gotchas.

### Suggested next action

Approve files (1) and (2), then run `sase memory write` for each proposed rule and
`sase memory review` to land them, updating the `AGENTS.md` tier-3 index in the same change.

---

## 5. Source Index

- Episodes: `sase memory episodes list`; details via `sase memory episodes show <id> --format lesson|timeline`.
- Feature: ep-c2f1302a (bn7), ep-dbf0db96 (bn8), ep-decdbb32 (boc), ep-c70b902c (boj), ep-d62e0c01 (boh).
- Tooling: ep-4073e6ba (bod), ep-9d2fdcb7 (boe), ep-c1d2a252 (bof), ep-6b9619e5 (bok).
- Research swarm: ep-a30208be (final), ep-35bff7da (cld), cdx/cld variants.
- Code: `src/sase/memory/episodes/_builder_derivation.py` (safety), `src/sase/default_config.yml:223-263` (lumberjacks).
- Tales: `sdd/tales/202605/memory_episodes_build_hang.md`, `episodes_build_progress.md`, `memory_episodes_chop_1.md`.
- xprompts: `xprompts/audit_recent_bugs.yml`, `audit_recent_improvements.yml`, `pylimit_split.yml`, `refresh_docs.yml`, `research_swarm.md`.
- Docs: `docs/episodes.md`.
