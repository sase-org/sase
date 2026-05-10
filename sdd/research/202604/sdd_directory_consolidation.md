# SDD Directory Consolidation + Legends & Myths

**Goal.** Consolidate `specs/`, `plans/`, `sdd/research/` under a single `sdd/` parent, and introduce two new
higher-altitude artifact types: `sdd/legends/` (epics-of-epics) and `sdd/myths/` (epics-of-legends). This document
surveys prior art, surfaces the design decisions that block a clean implementation, and ends with a recommended path
forward.

---

## 1. Current state (as of 2026-04-30)

```
{project_root}/
  specs/{YYYYMM}/*.md      # 489 files in 202604 alone — agent-expanded prompts
  plans/{YYYYMM}/*.md      # 570 files in 202604 — formatted plans (some with `bead_id`, `status: done`)
  sdd/research/{YYYYMM}/*.md   #  30 files in 202604 — hand-authored or research-agent investigations
  sase_plan_*.md           # ~140 loose work-in-progress plans at root, pre-`sase plan` persistence
  sdd/beads/             # Bead DB (when version_controlled: true)
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
(`.kiro/`, `.agent-os/`, `openspec/`, `bmad/`). sase is currently the outlier — `specs/`, `plans/`, `sdd/research/` collide
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

### 2.2.1 Second-pass prior-art gaps

The first pass got the broad pattern right, but missed four details that matter for sase's design:

1. **"Spec" means different things in adjacent systems.** Kiro specs are living requirements/design/task artifacts
   (`requirements.md`, `design.md`, `tasks.md`) that track implementation progress
   ([Kiro specs docs](https://kiro.dev/docs/specs/)). OpenSpec treats `openspec/specs/` as "current deployed
   capabilities" and `openspec/changes/` as active deltas that later archive into truth
   ([OpenSpec directory structure](https://thedocs.io/openspec/concepts/directory-structure/)). sase's current
   `specs/` are prompt snapshots, not canonical product requirements. If the directory move keeps the name
   `sdd/specs/`, document this aggressively or rename the folder to `sdd/prompts/` before the new layout hardens.
2. **Task execution systems increasingly encode dependency waves in the artifact.** Spec Kit's `tasks.md` includes
   dependency management, parallel execution markers, and file path specifications
   ([Spec Kit README](https://github.com/github/spec-kit/blob/main/README.md)). sase already has this in beads via
   `sase bead work`, not in markdown. Keep the DAG in beads; let plan/legend/myth markdown explain intent and lineage.
3. **Modern issue trackers support arbitrary-depth hierarchy without a distinct type at every level.** GitHub
   sub-issues explicitly support multiple hierarchy levels
   ([GitHub Docs](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/browsing-sub-issues)).
   Atlassian's public guidance says stories roll into epics, epics into initiatives, and higher custom hierarchy should
   be adapted to the organization rather than treated as universal
   ([Atlassian](https://www.atlassian.com/agile/project-management/epics-stories-themes)). That supports a flexible
   `tier`/lineage model more than a rigid "every altitude is a different database type" model.
4. **Scaled planning separates strategic context from executable work.** Azure Boards' SAFe mapping puts portfolio
   epics, program features, and team stories/tasks at different planning levels, and suggests strategic themes/portfolio
   vision live in a wiki or shared documentation rather than as executable leaf work
   ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/devops/boards/plans/safe-configure-boards?tabs=agile-process&view=azure-devops#safe-concepts)).
   BMAD likewise distinguishes completed planning artifacts from durable project docs/context
   ([BMAD established projects](https://docs.bmad-method.org/how-to/established-projects/)). This argues for making
   legends/myths coordination artifacts first, not auto-executed jobs on day one.

**Implication:** `sdd/` should probably have two semantics, not one:

- **Trace artifacts:** immutable-ish run artifacts produced by SDD (`specs/`, `plans/`, maybe `sdd/research/`).
- **Coordination artifacts:** living strategic containers (`legends/`, `myths/`) that roll up child bead IDs and
  decisions.

Mixing those is okay if the docs call it out. Treating every file in `sdd/` as the same lifecycle object will create
confusion.

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

**Default if undecided:** (B). Legends and myths are just plan-like coordination docs with one more linkage field:
`children: [<plan_id>...]`. Reuse the bead system for tracking; represent the higher altitude with bead `tier` metadata
rather than inventing a parallel tracker.

### D2. Bead integration: new types or reuse Plan?

The bead schema currently has `plan` and `phase`. Two options:

- **(A) New types.** Add `legend` and `myth` to `IssueType`. Phase always has parent=plan; plan can have parent=legend;
  legend can have parent=myth. This requires schema migration in `src/sase/bead/` and the SQLite + JSONL stores.
- **(B) Reuse Plan with a `tier` field.** All container tiers are stored as `plan` issues; differentiate via a
  `tier: plan|legend|myth` enum on the issue. Phases remain `IssueType.PHASE`.

**Second-pass repo finding:** the current CLI/parser already accepts `plan(<file>,<parent_id>)`, and `BeadProject.create`
already generates hierarchical child IDs for any issue with a parent. The DB check also permits `issue_type='plan'` with
or without `parent_id`. In other words, the code already has a latent "plans can contain plans" model even though the
docs present plans as top-level epics.

**Revised default if undecided:** start with (B), but define `tier` only for plan-like issues:
`plan | legend | myth`. Keep `IssueType` as a behavioral enum:

- `phase` = executable leaf work item.
- `plan` = container/design-linked work item that may have children.

Then expose ergonomic CLI aliases (`sase bead list --tier=legend`, optionally `--type=legend` as sugar) instead of
forcing `legend` and `myth` into the low-level `IssueType` enum on day one. Promote to first-class `IssueType` values
only if the UI/CLI needs distinct workflows that cannot be expressed as "plan-like container with tier." This is less
disruptive because import/export, SQLite checks, sorting, `close`, `remove`, and workspace merge code already understand
plan-like parents.

**Caveat:** if you do reuse `IssueType.PLAN`, fix the places where "plan" currently means "epic ready for phase-agent
execution." `sase bead work` should accept only `tier=plan`, not `tier=legend|myth`, until higher-tier orchestration
exists. `sase bead ready` / `#bd/next` should also filter or label container tiers so agents don't accidentally claim a
myth or legend as leaf work.

### D3. ID format for legends and myths

Today: `beads-001` (plan), `beads-001.2` (phase). For legends:

- **(A)** Same prefix, deeper nesting: `beads-001` (myth) > `beads-001.2` (legend) > `beads-001.2.5` (plan) > `beads-001.2.5.3` (phase).
- **(B)** Tier-prefixed counters: `MY-001` (myth), `LG-001` (legend), `beads-001` (plan), `beads-001.2` (phase).
- **(C)** Mixed: top-level numeric for myths/legends/plans, `.N` for phases only.

**Original default:** (B). Tier prefixes make IDs self-describing in commit messages and grep results, and avoid
N-deep dotted IDs that get unreadable past 3 levels.

**Second-pass adjustment:** option (B) is the cleanest human-facing shape, but it is not the low-churn implementation.
The current generator has one global prefix in `config.json`; child IDs are always `<parent_id>.<N>`. Supporting `MY-`
and `LG-` counters would require either per-tier counters or a more general ID allocator. If the goal is to land legends
quickly, keep the existing IDs internally and add a required `slug`/`display_id` frontmatter field for files:

```yaml
---
tier: legend
bead_id: beads-001.2
slug: rust-backend-migration
children:
  - beads-001.2.1
---
```

The CLI can print `legend rust-backend-migration (beads-001.2)` without making the storage layer handle multiple
counter namespaces immediately. Revisit prefixed IDs only after the hierarchy is stable.

### D4. Filesystem layout under `sdd/`

```
sdd/
  myths/{YYYYMM}/*.md     # rare, ~1-5 ever
  legends/{YYYYMM}/*.md   # uncommon, ~10-50/year
  plans/{YYYYMM}/*.md     # current "plans" (570/month at peak)
  specs/{YYYYMM}/*.md     # current "specs"
  sdd/research/{YYYYMM}/*.md  # current "research"
```

**Open question.** Should myths and legends use `YYYYMM` partitioning at all? There will only ever be a handful. A flat
`sdd/myths/*.md` is more discoverable. **Default:** flat for `myths/` and `legends/`, `YYYYMM` retained for
`plans/specs/sdd/research/`. `find_sdd_file`'s flat-vs-YYYYMM fallback already handles both.

### D5. Where does `sdd/` live in version-controlled vs local mode?

- **VC mode (`version_controlled: true`):** `{project_root}/sdd/` — git-tracked alongside code.
- **Local mode (`version_controlled: false`):** `{primary_workspace}/.sase/sdd/` — already correct; the layout under
  `.sase/sdd/` simply gains the new tiers.

This is mostly mechanical, but it does require one mode-specific change: in VC mode `get_sdd_dir()` currently returns
the project root, and should return `{project_root}/sdd` after the move. In local mode it already returns
`{primary_workspace}/.sase/sdd`, which is already the desired parent.

### D6. Is `sdd/research/` agent-generated or human-authored?

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

- **(A) Big-bang move.** One commit: `git mv specs sdd/specs && git mv plans sdd/tales && git mv research sdd/research`.
  Update `find_sdd_file` to keep accepting both `{root}/specs/` and `{root}/sdd/specs/` so any archived ChangeSpec or
  external link still resolves.
- **(B) Incremental.** Only new files land under `sdd/`. `find_sdd_file` already does flat-vs-YYYYMM; extend it to also
  fall back to `{root}/{kind}` (legacy) when `{root}/sdd/{kind}` doesn't have the file.
- **(C) Symlink at root.** `specs -> sdd/specs`, `plans -> sdd/tales`, `research -> sdd/research`. Zero-cost backwards
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
`sdd/tales/202604/foo.md` unless the agent's `@`-resolver supports walking up. Two fixes: (i) change the xprompts to
`@sdd/tales/**`, (ii) keep the legacy `plans/` symlink during a deprecation window.

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
`beads-007.3 (phase) ← beads-007 (plan) ← rust-backend (legend, beads-002) ← platform-sdd (myth, beads-001)`.
Same data, cheaper to read.

### D11. Are higher tiers living documents or immutable run artifacts?

Current specs/plans are created as part of a run and then mostly age into audit history. Legends and myths will almost
certainly need edits over weeks/months as priorities, dependencies, and child plans change.

**Default if undecided:** make legends/myths living coordination docs. Their `updated_time` and `children` can change;
their child plans remain the lower-level execution/audit trail. This matches GitHub/Jira hierarchy behavior and avoids
turning every strategic correction into a brand-new myth file.

### D12. Should status roll up or be written by hand?

A myth/legend can be "done" because all descendants are closed, because the strategic goal was abandoned, or because a
replacement container superseded it. Those are different meanings.

**Default if undecided:** compute rollup status for normal display and reserve explicit frontmatter for exceptional
states:

- `computed_status`: derived from child beads (`open`, `in_progress`, `blocked`, `done`).
- `status`: optional human override (`archived`, `superseded`, `cancelled`).

Do not make agents manually maintain `status: done` on myths/legends as a primary source of truth.

### D13. What validates the hierarchy?

The new layout creates references that can drift: child bead IDs, plan file paths, `bead_id` frontmatter, and moved
`@plans/**`/`@specs/**` references.

**Default if undecided:** add `sase sdd doctor` or extend `sase bead doctor` with SDD checks:

- every `sdd/tales/**.md` with `bead_id` points to an existing bead;
- every legend/myth `children` entry exists and has the expected tier;
- every bead `design` path exists after path normalization;
- no new files are written to legacy root `plans/`, `specs/`, or `sdd/research/`;
- xprompts in merged config do not reference legacy `@plans/**` or `@specs/**`.

This should run as part of the migration PR and become a cheap preflight after the move.

### D14. Should directory names describe artifact kind or lifecycle state?

OpenSpec's most useful distinction is not "spec vs plan"; it is "truth vs active change." sase today has no canonical
truth directory; `specs/` are the input prompt record.

**Default if undecided:** keep the user's proposed `sdd/{specs,plans,research,legends,myths}` layout for now, but add a
small glossary to `docs/sdd.md`:

- `specs`: expanded prompt snapshots, not product truth.
- `plans`: approved implementation plans.
- `research`: upstream investigations and design rationale.
- `legends`/`myths`: living coordination containers.

If you want to break compatibility now, the more honest rename is `sdd/prompts/` instead of `sdd/specs/`, but that is a
larger migration than the user asked for.

### D15. How should agents reference moved files?

The migration affects three reference surfaces, not just filesystem paths:

- markdown links in docs/research;
- xprompt `@file` globs;
- bead `design` fields and ChangeSpec `PLAN:` drawers.

**Default if undecided:** choose one canonical project-relative display path in VC mode (`sdd/tales/YYYYMM/foo.md`) and
one primary-workspace-relative path in local mode (`.sase/sdd/tales/YYYYMM/foo.md`). Store those exact strings in new
bead `design` fields after the migration. For old beads, support legacy lookup but do not rewrite historical JSONL unless
you also have a `sase sdd migrate --rewrite-bead-designs` command with a dry run.

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
5. **Tooling that scans `plans/`.** Anything outside `src/sase/` (skills, mentor scripts, retired Mercurial plugin plugin,
   sase-nvim, chezmoi dotfiles) might hard-code `plans/` or `specs/`. Run `rg -F 'plans/' lib/ <legacy-public-api-list>`
   and across the plugin repos before flipping the switch.
6. **`.sase_plan_*.md` at project root.** These are pre-persistence WIP files written by the `sase_plan` skill. They
   should _not_ move; they're orthogonal to SDD storage. Just confirm no proposed change touches them.
7. **Plan-ref builder and tests.** `_build_epic_plan_ref` currently returns `plans/YYYYMM/foo.md` in VC mode and
   `.sase/sdd/tales/YYYYMM/foo.md` in local mode. Updating `get_sdd_dir()` is not enough; the plan-ref builder and
   tests in `tests/test_axe_run_agent_exec_plan.py` need to move in lockstep or new epic agents will still receive
   legacy paths.
8. **Existing parented-plan behavior.** `sase bead create --type plan(<file>,<parent>)` is already accepted even though
   docs describe a two-tier hierarchy. A migration that adds legend/myth without deciding what existing parented plans
   mean will leave ambiguous data in `issues.jsonl`.
9. **Ready list pollution.** `ready_issues()` currently returns all open issues with no active blockers; it does not
   filter to phases. Once legends/myths exist, `sase bead ready` and `#bd/next` can surface strategic containers unless
   they gain tier/type filtering.
10. **Second-pass external scan.** Known sibling repos mostly do not hard-code SDD paths. Hits found on 2026-04-30:
    `sase-telegram/tests/test_bead_format.py` expects `../sase/plans/202604/...`, and
    `sase-telegram/src/sase_telegram/formatting.py` documents `sdd/research/*.md`. No hits were found in `sase-github`,
    `retired Mercurial plugin`, `sase-nvim`, `~/.local/share/chezmoi/home/dot_config/sase`, or `~/.config/sase` for the scanned
    path patterns. Still rerun the scan in the final migration CL because these repos move independently.
11. **Docs outside SDD docs.** `README.md`, `docs/configuration.md`, `docs/beads.md`, `docs/xprompt.md`,
    `docs/change_spec.md`, and `docs/rust_backend.md` all contain user-facing `plans/`/`specs/`/`sdd/research/` examples.
    Some are historical references and should remain; others are live guidance and must move.

---

## 5. Recommended solution

**Phase 1 — Directory consolidation (mechanical, ~half-day).**

1. Create `sdd/` at project root in version-controlled mode (or under `.sase/sdd/` in local mode — already correct).
2. `git mv specs sdd/specs && git mv plans sdd/tales && git mv research sdd/research`. One commit.
3. Update `src/sase/sdd/files.py` to write under `sdd_dir / "sdd"` segment when `version_controlled=True` (no change
   for local mode — `sdd_dir` already points at `.sase/sdd/`, so the new tiers are simply created beneath it).
   Concretely: have `get_sdd_dir()` return `Path(workspace_dir) / "sdd"` in VC mode.
4. Extend `find_sdd_file` to search both canonical and legacy roots: `base/sdd/{kind}/{name}`,
   `base/sdd/{kind}/*/{name}`, `base/{kind}/{name}`, and `base/{kind}/*/{name}`. Keep legacy lookup for one release
   cycle.
5. Update `default_config.yml` xprompts: `@plans/**` → `@sdd/tales/**`, same for specs.
6. Update `.gitignore` perf-artifacts paths.
7. Update `docs/sdd.md` layout section.

**Phase 2 — Add legend tier (one well-scoped change, ~1-2 days).**

8. Decide naming (D-2.3) — recommend keeping `legend` if you commit to documenting the ordering.
9. Do **not** add `legend` to `IssueType` in the first implementation. Add `tier` metadata for plan-like beads
   (`plan`, `legend`, `myth`) and keep `IssueType.PLAN` as the shared container behavior. This matches the existing
   `plan(<file>,<parent>)` support and avoids a wider JSONL/SQLite enum migration before the workflow semantics are
   proven.
10. Add `sdd/legends/` directory; legend file format = same shape as plan with optional `children: [<bead_id>...]`
    frontmatter (D1-B).
11. Add ergonomic CLI surface: `sase bead create --tier=legend --design sdd/legends/<slug>.md` or equivalent sugar;
    `sase bead show` should display computed lineage and tier.
12. Defer `sase bead work <legend_id>` orchestration (D9) to phase 4.

**Phase 3 — Add myth tier (smaller, ~half-day after phase 2).**

13. Same shape as legend, one tier up. Almost certainly only 1-3 myths exist at any time; flat layout under
    `sdd/myths/` (D4).

**Phase 4 — Orchestration (only when justified).**

14. `sase bead work <legend_id>` and `<myth_id>` — schedules child epics/legends with the same Kahn-wave model. Don't
    build this until you have at least one real multi-epic legend in flight.

**Phase 5 — Cleanup (deprecation cycle, ~3 months later).**

15. Add or run `sase sdd doctor` to prove no live config/xprompts/bead design fields still point at legacy paths.
16. Drop the legacy `find_sdd_file` fallbacks. Remove the legacy `plans/`, `specs/`, `sdd/research/` symlinks if you went
    with D7-C.

**What I'd skip.** Don't touch:

- `sase_plan_*.md` at project root (orthogonal — these are pre-persistence WIP files).
- The bead Phase tier (no reason to rename or restructure).
- The local-mode storage path (`.sase/sdd/` is already correct; new tiers nest under it for free).

**What I'd flag for further thought.**

- D2 (new bead types vs `tier` field) is the highest-stakes irreversible decision in this whole project. If you punt
  with first-class `IssueType` values, switching back requires a JSONL rewrite. The second-pass repo inspection now
  biases toward `IssueType.PLAN` + `tier` because parented plan beads already exist in the implementation.
- D3 (ID format). Once you ship `LG-001`, you can't go back without renumbering. The low-churn default is existing bead
  IDs plus a human-readable `slug`; prefixed IDs can wait.
- The naming. Legend/myth is fine but please pin down the ordering in `docs/sdd.md` and the bead glossary on day one.
