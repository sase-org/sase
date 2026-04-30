# SDD Directory Consolidation + Legends & Myths

**Goal.** Consolidate `specs/`, `plans/`, `research/` under a single `sdd/` parent, and introduce two new
higher-altitude artifact types: `sdd/legends/` (epics-of-epics) and `sdd/myths/` (epics-of-legends). This document
surveys prior art, surfaces the design decisions that block a clean implementation, and ends with a recommended path
forward.

---

## 1. Current state (as of 2026-04-30)

```
{project_root}/
  specs/{YYYYMM}/*.md      # 489 files in 202604 alone — agent-expanded prompts
  plans/{YYYYMM}/*.md      # 570 files in 202604 — formatted plans (some with `bead_id`, `status: done`)
  research/{YYYYMM}/*.md   #  30 files in 202604 — hand-authored or research-agent investigations
  sase_plan_*.md           # ~140 loose work-in-progress plans at root, pre-`sase plan` persistence
  .sase_beads/             # Bead DB (when version_controlled: true)
  .sase/sdd/               # Local-mode SDD storage (when version_controlled: false)
```

Relevant code:

- `src/sase/sdd/files.py` — `get_sdd_dir`, `write_sdd_files`, `find_sdd_file`, `commit_sdd_files`. The root layout
  contract is hard-coded as `sdd_dir / "specs" / yyyymm` and `sdd_dir / "plans" / yyyymm`.
- `src/sase/axe/run_agent_exec_plan.py:46-47` — `find_sdd_file(base, "specs", fname)` / `("plans", ...)`.
- `src/sase/default_config.yml:280-341` — xprompts use `@plans/**/{{file_base}}.md` and `@specs/**/{{file_base}}.md`
  literally.
- `docs/sdd.md` — documents the two storage modes.
- `.gitignore:63-71` — references `plans/202604/perf_artifacts/...` paths.

Notable observations:

- **Research is NOT currently part of SDD.** It is just a directory convention; nothing in `src/` writes to it. Folding
  it under `sdd/` is a pure documentation/convention move (no code path touches it today).
- `find_sdd_file` already implements a flat-vs-`YYYYMM` fallback. We can extend this same affordance for the
  `sdd/`-prefixed move.
- The "epic" tier already exists in code — it lives in **beads** (Plan + Phase types), not in the filesystem. A plan
  file with `bead_id` and an associated bead epic with phases is the closest current analogue to a "legend." There is
  no third hierarchy level.
- `sase bead work <epic_id>` is the current mechanism for orchestrating multi-phase work. There is no equivalent
  multi-epic orchestrator, which is exactly the gap "legends" would fill.

---

## 2. Prior art

### 2.1 Spec-Driven Development frameworks

| System            | Top-of-tree            | Levels                                                                  | Notes                                                                                                                                                |
| ----------------- | ---------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GitHub Spec Kit** | `specs/{NNN-feat}/`  | `spec.md` → `plan.md` → `tasks.md` → `research.md` (per-feature folder) | One folder per feature, all artifacts co-located. Numeric ordering, not date-ordered. Sister files include `research.md`, `data-model.md`, `quickstart.md`. |
| **AWS Kiro**      | `.kiro/specs/{feat}/`  | `requirements.md` → `design.md` → `tasks.md`                            | Hidden top-level dir, one folder per feature.                                                                                                        |
| **OpenSpec**      | `openspec/`            | `specs/`, `changes/`, `proposals/`                                      | Sibling top-level dirs (like sase today), but namespaced under `openspec/`.                                                                          |
| **agent-os**      | `.agent-os/`           | `product/{mission,roadmap,decisions}.md`, `specs/{feat}/`, `standards/` | Strategic docs (`mission`, `roadmap`) sit alongside per-feature specs — direct precedent for legends/myths.                                          |
| **BMAD-METHOD**   | `bmad/`                | `briefs/` → `prds/` → `architecture/` → `epics/` → `stories/`           | Five tiers from product strategy down to per-story tasks.                                                                                            |
| **ADRs**          | `docs/adr/`            | flat, numeric, immutable                                                | The decisions, not the work. Often co-exists with the above.                                                                                         |

**Pattern that wins.** Every mature system namespaces its artifacts under a single hidden- or named-parent directory
(`.kiro/`, `.agent-os/`, `openspec/`, `bmad/`). sase is currently the outlier — `specs/`, `plans/`, `research/` collide
with normal source-tree names (`specs/` clashes with pytest's spec-style tests in some projects; `plans/` is generic
enough to collide with anything). **Moving to `sdd/` is a defensible alignment with prior art.**

**Pattern that doesn't fit sase.** Spec Kit / Kiro both group _by feature_ (one folder per work unit). sase groups _by
artifact kind then by month_, which is better for a single solo-driver workflow producing 500+ plans/month. Don't copy
the per-feature folder layout — your scale is wrong for it.

### 2.2 Hierarchical work-decomposition models

| Model         | Levels (high → low)                                  | Source                                                |
| ------------- | ---------------------------------------------------- | ----------------------------------------------------- |
| **SAFe**      | Theme → Strategic Initiative → Epic → Feature → Story → Task | Scaled Agile.                                  |
| **PMI**       | Portfolio → Program → Project → Work package         | Project-mgmt institute.                               |
| **Atlassian** | Initiative → Epic → Story → Subtask                  | Jira default.                                         |
| **C4**        | System Context → Container → Component → Code        | Architecture; structural not temporal but same idea.  |
| **GitHub**    | Roadmap → Milestone → Issue → Sub-issue              | What product teams actually use day-to-day.           |

Every one of these gives you **at least three tiers above the unit-of-work**. sase's bead model only has two
(Plan + Phase). Adding legends and myths brings sase to four tiers — Phase < Plan/Epic < Legend < Myth — which lines up
with SAFe's Story/Epic/Initiative/Theme.

### 2.3 The naming question

"Legend" and "myth" are evocative but **share roughly the same denotation in English**, and the ordering legend < myth
is not intuitive (some readers will reverse them). Alternatives worth considering:

| Naming        | Top-down hierarchy                          | Pro                                                                  | Con                                                            |
| ------------- | ------------------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------- |
| Plan / Legend / Myth     | plan ⊂ legend ⊂ myth              | Memorable, sase-flavored, phonetic.                                  | Synonymous in everyday usage; ordering not obvious.            |
| Plan / Saga / Odyssey    | plan ⊂ saga ⊂ odyssey             | Clear escalation (saga < odyssey is intuitive — odysseys are longer). Greek + Norse mixed flavor matches sase's literary names. | "Saga" already overloaded in distributed-systems land. |
| Plan / Epic / Initiative | plan ⊂ epic ⊂ initiative          | Industry-standard, zero learning curve.                              | Boring; "epic" already overloaded in sase as the bead-Plan tier. |
| Plan / Arc / Era         | plan ⊂ arc ⊂ era                  | Story-arc → era is intuitive temporal escalation.                    | "Era" too time-flavored; sase work isn't time-bounded.         |
| Plan / Campaign / Crusade | plan ⊂ campaign ⊂ crusade        | Military escalation reads cleanly.                                   | Aggressive vibe; crusade has historical baggage.               |

**Recommendation:** Stick with **legend** and **myth** if you like them — they're memorable and fit sase's existing
tone — but document the ordering explicitly somewhere durable (`docs/sdd.md` glossary), because two thirds of readers
will guess wrong on first contact. If you want unambiguous ordering at the cost of cuteness, **plan / saga / odyssey**
is the cleanest alternative.

---

## 3. Critical design decisions

These need to be answered before any code change. Each has a "default if you don't decide" so nothing blocks.

### D1. What does a legend / myth file actually contain?

Today, `plans/{YYYYMM}/{name}.md` has:

- `create_time` frontmatter
- optional `status: done`
- optional `bead_id: <epic_id>`
- markdown body

Legends and myths could be:

- **(A)** Pure index / coordination docs — frontmatter with a list of child epic IDs and a high-level narrative. No
  per-file phases.
- **(B)** Full plans in their own right — same shape as today's plans, just at a higher altitude. Their "phases" are
  references to other plans/legends.
- **(C)** A new schema entirely — `{tier: legend, children: [bead-001, bead-007], goal: ..., metrics: ..., decisions: [...]}`.

**Default if undecided:** (B). Legends and myths are just plans with one more linkage field: `children: [<plan_id>...]`.
Reuse the bead system for tracking; add a new bead type rather than inventing a parallel one.

### D2. Bead integration: new types or reuse Plan?

The bead schema currently has `plan` and `phase`. Two options:

- **(A) New types.** Add `legend` and `myth` to `IssueType`. Phase always has parent=plan; plan can have parent=legend;
  legend can have parent=myth. This requires schema migration in `src/sase/bead/` and the SQLite + JSONL stores.
- **(B) Reuse Plan with a `tier` field.** All four tiers are stored as `plan` issues; differentiate via a
  `tier: phase|plan|legend|myth` enum on the issue.

**Default if undecided:** (A). It's the right model and the schema cost is one-time. (B) saves churn now but every
query (`bead list --type=legend`) ends up filtering by both type and tier — worse ergonomics forever.

### D3. ID format for legends and myths

Today: `beads-001` (plan), `beads-001.2` (phase). For legends:

- **(A)** Same prefix, deeper nesting: `beads-001` (myth) > `beads-001.2` (legend) > `beads-001.2.5` (plan) > `beads-001.2.5.3` (phase).
- **(B)** Tier-prefixed counters: `MY-001` (myth), `LG-001` (legend), `beads-001` (plan), `beads-001.2` (phase).
- **(C)** Mixed: top-level numeric for myths/legends/plans, `.N` for phases only.

**Default if undecided:** (B). Tier prefixes make IDs self-describing in commit messages and grep results, and avoid
N-deep dotted IDs that get unreadable past 3 levels.

### D4. Filesystem layout under `sdd/`

```
sdd/
  myths/{YYYYMM}/*.md     # rare, ~1-5 ever
  legends/{YYYYMM}/*.md   # uncommon, ~10-50/year
  plans/{YYYYMM}/*.md     # current "plans" (570/month at peak)
  specs/{YYYYMM}/*.md     # current "specs"
  research/{YYYYMM}/*.md  # current "research"
```

**Open question.** Should myths and legends use `YYYYMM` partitioning at all? There will only ever be a handful. A flat
`sdd/myths/*.md` is more discoverable. **Default:** flat for `myths/` and `legends/`, `YYYYMM` retained for
`plans/specs/research/`. `find_sdd_file`'s flat-vs-YYYYMM fallback already handles both.

### D5. Where does `sdd/` live in version-controlled vs local mode?

- **VC mode (`version_controlled: true`):** `{project_root}/sdd/` — git-tracked alongside code.
- **Local mode (`version_controlled: false`):** `{primary_workspace}/.sase/sdd/` — already correct; the layout under
  `.sase/sdd/` simply gains the new tiers.

This is the cleanest part of the change: `get_sdd_dir()` already returns the parent; the new layout is purely _under_
that parent. No mode logic changes.

### D6. Is `research/` agent-generated or human-authored?

Today it's mixed. The current files are mostly hand-authored research (you producing investigations) plus a few
research-agent outputs. Folding it under `sdd/research/` is fine, but **it is not a spec-driven artifact** and
shoehorning it in implies it is.

**Options:**

- **(A)** Move it under `sdd/research/` anyway — it co-locates with adjacent artifacts and benefits from the same
  YYYYMM organization.
- **(B)** Leave it at top-level — research is upstream of the SDD pipeline (pre-spec), not part of it.
- **(C)** Rename — `sdd/notes/`, `sdd/investigations/`, or `sdd/priors/` to disambiguate from "researcher" agent
  outputs.

**Default if undecided:** (A). The user's stated intent is consolidation, and the research dir genuinely is part of the
"why" trail that leads to specs and plans.

### D7. Migration strategy for existing files

- **489 specs**, **570 plans**, **30 research**, plus **~140 loose `sase_plan_*.md`** at root. Total: ~1,200+ files.
- `git mv` preserves blame.
- Existing plan files have `bead_id` references that don't change. xprompt references like `@plans/**/{file}.md` _do_
  change.
- `.gitignore` rules referencing `plans/202604/perf_artifacts/...` need updating.

**Options:**

- **(A) Big-bang move.** One commit: `git mv specs sdd/specs && git mv plans sdd/plans && git mv research sdd/research`.
  Update `find_sdd_file` to keep accepting both `{root}/specs/` and `{root}/sdd/specs/` so any archived ChangeSpec or
  external link still resolves.
- **(B) Incremental.** Only new files land under `sdd/`. `find_sdd_file` already does flat-vs-YYYYMM; extend it to also
  fall back to `{root}/{kind}` (legacy) when `{root}/sdd/{kind}` doesn't have the file.
- **(C) Symlink at root.** `specs -> sdd/specs`, `plans -> sdd/plans`, `research -> sdd/research`. Zero-cost backwards
  compat for tooling that hard-codes the old paths, but symlinks in git are flaky on Windows and confuse some editors.

**Default:** (A) + the legacy fallback in (B) as a safety net for any uncommitted external references (other clones,
docs, archived prompts). Big-bang is fine when you're the only operator and you can land it in a quiet hour.

### D8. xprompt and config updates

Concrete grep hits that must change in lockstep with the directory move:

- `src/sase/default_config.yml:280-341` — `@specs/**`, `@plans/**` references in `bd/finish`, `bd/new_epic`, and
  related xprompts.
- `src/sase/sdd/files.py:139-141` — `sdd_dir / "specs" / yyyymm` hard-coded paths.
- `src/sase/axe/run_agent_exec_plan.py:46-47` — `find_sdd_file(base, "specs", ...)`.
- `.gitignore:63,70-71` — `plans/202604/perf_artifacts/...` rules.
- `docs/sdd.md` — entire layout section.
- `docs/beads.md:5,48` — references to "Plan (epic)" tier need to gain "Legend" and "Myth" rows.

The xprompt globs are the most fragile because they're fuzzy-matched. After the move, `@plans/**/foo.md` won't match
`sdd/plans/202604/foo.md` unless the agent's `@`-resolver supports walking up. Two fixes: (i) change the xprompts to
`@sdd/plans/**`, (ii) keep the legacy `plans/` symlink during a deprecation window.

### D9. Auto-orchestration for legends

`sase bead work <epic_id>` schedules phases of one epic. The natural extension is `sase bead work <legend_id>` →
schedules epics, where each epic itself runs `sase bead work` on its phases. This implies:

- A legend's "Kahn-wave schedule" is over its child epics, not phases.
- An epic launched from a legend runs to completion (all phases land + epic lands) before the next epic starts, _or_
  parallelizes by dependency graph just like phases do today.
- Failure handling: if epic B fails halfway, does the legend halt? Roll back the legend's `is_ready_to_work` flag?

**Default if undecided:** Out of scope for the directory-restructure. Land the directory + bead-tier work first; add
`sase bead work` legend support as a follow-up only after you have at least two real legends to test against.

### D10. Discoverability across tiers

Given a phase, can an agent find its plan, legend, and myth? Today: phase → plan via parent bead. After the change:
phase → plan → legend → myth via repeated parent lookup.

**Recommendation:** Add a `lineage` field (computed, not stored) to `sase bead show` output:
`beads-007.3 (phase) ← beads-007 (plan) ← LG-002 (legend) ← MY-001 (myth)`. Same data, cheaper to read.

---

## 4. Risks and gotchas

1. **Workspace primary-resolution.** `get_primary_workspace_dir` strips `_N` suffixes. Nothing about the new layout
   changes this, but make sure the migration commits go to the primary workspace and ephemeral `sase_<N>` workspaces
   don't accidentally write to old paths after they pull (they will, until they re-`just install`).
2. **ChangeSpec COMMITS drawer references.** Active `.gp` files in `~/.sase/projects/` may contain
   `| <NAME>: plans/202604/foo.md` lines. After `git mv`, these go stale unless rewritten. Cheap to grep and `sed`, but
   easy to forget.
3. **Local-mode SDD git history.** `.sase/sdd/.git` is a separate repo. The `git mv` happens inside it, not the project
   repo. Don't conflate.
4. **Beads ID renumbering.** If you adopt option D3-(B) (`MY-`, `LG-` prefixes), don't try to rewrite existing
   `beads-NNN` plan IDs. Just start the new tiers fresh. Cross-tier references go by ID, not by tier name.
5. **Tooling that scans `plans/`.** Anything outside `src/sase/` (skills, mentor scripts, sase-google plugin,
   sase-nvim, chezmoi dotfiles) might hard-code `plans/` or `specs/`. Run `rg -F 'plans/' lib/ public_api_methods.txt`
   and across the plugin repos before flipping the switch.
6. **`.sase_plan_*.md` at project root.** These are pre-persistence WIP files written by the `sase_plan` skill. They
   should _not_ move; they're orthogonal to SDD storage. Just confirm no proposed change touches them.

---

## 5. Recommended solution

**Phase 1 — Directory consolidation (mechanical, ~half-day).**

1. Create `sdd/` at project root in version-controlled mode (or under `.sase/sdd/` in local mode — already correct).
2. `git mv specs sdd/specs && git mv plans sdd/plans && git mv research sdd/research`. One commit.
3. Update `src/sase/sdd/files.py` to write under `sdd_dir / "sdd"` segment when `version_controlled=True` (no change
   for local mode — `sdd_dir` already points at `.sase/sdd/`, so the new tiers are simply created beneath it).
   Concretely: have `get_sdd_dir()` return `Path(workspace_dir) / "sdd"` in VC mode.
4. Extend `find_sdd_file` with a third fallback: `base / "sdd" / kind / name` (new), `base / kind / name` (flat
   legacy), `base / kind / */name` (YYYYMM legacy). Keep all three for one release cycle.
5. Update `default_config.yml` xprompts: `@plans/**` → `@sdd/plans/**`, same for specs.
6. Update `.gitignore` perf-artifacts paths.
7. Update `docs/sdd.md` layout section.

**Phase 2 — Add legend tier (one well-scoped change, ~1-2 days).**

8. Decide naming (D-2.3) — recommend keeping `legend` if you commit to documenting the ordering.
9. Add `legend` to `IssueType` in beads (D2-A). Schema migration via JSONL re-export. Plans gain optional
   `parent_legend_id` (or, if you adopt D2-A fully, `parent_id` on plans referring to legend bead).
10. Add `sdd/legends/` directory; legend file format = same shape as plan with optional `children: [<bead_id>...]`
    frontmatter (D1-B).
11. Add `sase bead create --type=legend(<name>)` and `sase bead show` lineage display.
12. Defer `sase bead work <legend_id>` orchestration (D9) to phase 4.

**Phase 3 — Add myth tier (smaller, ~half-day after phase 2).**

13. Same shape as legend, one tier up. Almost certainly only 1-3 myths exist at any time; flat layout under
    `sdd/myths/` (D4).

**Phase 4 — Orchestration (only when justified).**

14. `sase bead work <legend_id>` and `<myth_id>` — schedules child epics/legends with the same Kahn-wave model. Don't
    build this until you have at least one real multi-epic legend in flight.

**Phase 5 — Cleanup (deprecation cycle, ~3 months later).**

15. Drop the legacy `find_sdd_file` fallbacks. Remove the legacy `plans/`, `specs/`, `research/` symlinks if you went
    with D7-C.

**What I'd skip.** Don't touch:

- `sase_plan_*.md` at project root (orthogonal — these are pre-persistence WIP files).
- The bead Phase tier (no reason to rename or restructure).
- The local-mode storage path (`.sase/sdd/` is already correct; new tiers nest under it for free).

**What I'd flag for further thought.**

- D2 (new bead types vs `tier` field) is the highest-stakes irreversible decision in this whole project. If you punt
  with `tier`, switching later requires a JSONL rewrite. Take an extra day to commit to the model.
- D3 (ID format). Once you ship `LG-001`, you can't go back without renumbering. The defaults above (`LG-`, `MY-`
  prefixes) bias toward grep-ability; pick deliberately.
- The naming. Legend/myth is fine but please pin down the ordering in `docs/sdd.md` and the bead glossary on day one.
