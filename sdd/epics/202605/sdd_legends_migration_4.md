---
create_time: 2026-05-01 20:17:10
bead_id: sase-1x
status: done
prompt: sdd/prompts/202605/sdd_legends_migration_4.md
---
# SDD Directory Migration and Legend Support Plan

## Context

The prior research note is `sdd/research/202604/sdd_directory_consolidation.md`. Its key recommendations still hold:
namespace SDD artifacts under a single `sdd/` directory, keep legacy lookup during the migration, and model higher
altitude containers as plan-like beads rather than introducing a separate low-level issue type immediately.

This plan intentionally diverges from that research in three places because of the current request:

- Do not migrate `sdd/research/`; it remains a top-level directory.
- Add `sdd/epics/` and move existing epic plan files there instead of leaving them in `sdd/tales/`.
- Use `--type plan(<plan_file>,<legend_bead_id>)` for epic beads linked to legends. Do not add or document
  `--type epic(...)`.

## Target Model

The canonical version-controlled SDD layout becomes:

```text
sdd/
  specs/{YYYYMM}/*.md      # expanded prompt snapshots
  plans/{YYYYMM}/*.md      # normal non-epic implementation plans
  epics/{YYYYMM}/*.md      # executable multi-phase epic plans
  legends/{YYYYMM}/*.md    # higher-level coordination plans
```

Local non-version-controlled mode keeps the same shape under `.sase/sdd/`.

Beads keep the existing behavioral issue types:

- `phase`: executable child work item
- `plan`: container/design-linked work item

Plan-like beads gain a `tier` field with values `plan`, `epic`, and `legend`. This lets SASE distinguish normal plans,
epics, and legends without disrupting the existing `plan(<file>,<parent>)` create syntax or the existing hierarchical ID
allocator. Phases should not carry a tier other than the implicit `phase` behavior.

Legend creation is a new plan-approval action. It creates a plan-type bead with `tier=legend`, links it to the saved
`sdd/legends/{YYYYMM}/...` file, and writes `legend_bead_id` plus `tier: legend` frontmatter into that file. It does not
launch `sase bead work`.

Epic creation remains the executable multi-phase path. If an epic is linked to a legend, the epic bead is created with:

```bash
sase bead create --title "<title>" --type plan(<epic_plan_file>,<legend_bead_id>)
```

The epic bead should get `tier=epic`, and the epic plan file should get `bead_id`, `tier: epic`, and, when applicable,
`legend_bead_id` frontmatter. Existing unlinked epics continue to use `--type plan(<epic_plan_file>)`.

## Phase 1: SDD Path Infrastructure and Mechanical Migration

Owner: one agent in `sase_100`.

Scope:

- Update SDD path helpers so version-controlled mode writes under `{workspace}/sdd`, while local mode continues to use
  `{primary_workspace}/.sase/sdd`.
- Extend SDD file resolution to search canonical and legacy locations for `specs`, `plans`, `epics`, and `legends`.
  Canonical search should prefer `sdd/<kind>/{name}` and `sdd/<kind>/*/{name}`, then legacy `<kind>/{name}` and
  `<kind>/*/{name}` for compatibility.
- Add a plan-kind parameter to SDD plan writing so future normal, epic, and legend actions can write to `plans/`,
  `epics/`, or `legends/` respectively while specs always write to `specs/`.
- `git mv specs sdd/specs`.
- Split current `plans/`:
  - Move existing epic plan files to `sdd/epics/`.
  - Move existing non-epic plan files to `sdd/tales/`.
  - Classify epic plan files as the union of files with `bead_id` frontmatter and version-controlled bead `design` paths
    that point at plan beads. Keep a migration manifest or script output in the phase notes so the classification is
    auditable.
- Do not move `sdd/research/`.
- Update `.gitignore`, built-in xprompts, docs, tests, and live examples that should use canonical paths.

Important implementation details:

- `_build_epic_plan_ref()` must return `sdd/epics/{YYYYMM}/{name}.md` in version-controlled mode for epic actions.
- Normal coder handoff should use `sdd/tales/...` for approved non-epic plans.
- Legacy path resolution is a compatibility feature only; new writes must not create root `plans/` or `specs/`.

Validation:

- Focused tests for SDD path writing/resolution and epic plan refs.
- `rg` guard showing no live config/xprompt code writes new root `plans/` or `specs/`.
- `just install && just check` in `sase_100`.

## Phase 2: Bead Tier Metadata in Rust Core and Python

Owner: one agent across `sase_100` and `../sase-core`.

Scope:

- Add a `tier` field to bead issue records in `../sase-core` and the Python `Issue` model.
- Define valid tiers as `plan`, `epic`, `legend`, with default migration behavior:
  - Existing `issue_type=phase` records have no plan-like tier behavior.
  - Existing top-level and parented `issue_type=plan` records default to `tier=epic` when they have phase children,
    `tier=legend` only if explicitly set, and `tier=plan` otherwise. If defaulting by child inspection is too invasive
    for the wire layer, default stored missing tiers to `epic` for existing plan beads and let Phase 3/4 adjust newly
    created normal plans explicitly.
- Update JSONL import/export, SQLite compatibility schema/migrations, Rust store validation, Python wire conversion, and
  golden fixtures.
- Add CLI support for tier filtering/display:
  - `sase bead list --tier epic`
  - `sase bead list --tier legend`
  - `sase bead show <id>` displays tier and parent lineage.
- Ensure `sase bead ready` and `#bd/next` avoid surfacing non-executable plan-like containers accidentally. The safest
  behavior is to show ready phases only by default, or at minimum exclude `tier=legend`.
- Ensure `sase bead work <id>` only accepts `tier=epic` plan beads until legend orchestration exists.

Validation:

- Rust bead unit tests and Python facade tests for missing-tier migration, JSONL round trip, list/show filtering, ready
  filtering, and `bead work` rejection for legends.
- `cargo test --workspace` in `../sase-core`.
- `just install && just check` in `sase_100`.

## Phase 3: Core SASE Plan Approval Actions for Epics and Legends

Owner: one agent in `sase_100`.

Scope:

- Add a `legend` plan approval action alongside `approve`, `epic`, `reject`, and feedback actions.
- Update `PlanApprovalModal` with a Legend option and keybinding. Keep the UI compact and update hints/status text.
- Update notification modal response writing so `legend` is persisted to `plan_response.json`.
- Update `handle_plan_approval()` and `handle_plan_marker()` to understand `legend`.
- Save plans based on action:
  - `approve`/run: `sdd/tales/{YYYYMM}/...`
  - `epic`: `sdd/epics/{YYYYMM}/...`
  - `legend`: `sdd/legends/{YYYYMM}/...`
- Add a built-in `bd/new_legend` xprompt that creates a plan-type bead with `tier=legend`, links it to the legend file,
  writes `legend_bead_id` and `tier: legend` frontmatter, commits the bead/file metadata, and stops.
- Update `bd/new_epic` so it:
  - accepts an optional `legend_bead_id`;
  - creates linked epics with `--type plan(<plan_file>,<legend_bead_id>)`;
  - sets `tier=epic`;
  - writes `bead_id`, `tier: epic`, and optional `legend_bead_id` frontmatter;
  - continues to run `sase bead work <epic_id> --yes` only for epic beads.
- Decide how the optional legend parent is supplied for epic creation. The low-churn path is to read `legend_bead_id`
  from the epic plan frontmatter when present and otherwise create an unlinked epic.

Validation:

- Plan approval unit tests for `legend`, including response JSON, saved path kind, prompt construction, and
  auto-dismiss.
- Epic creation tests for linked and unlinked epics, confirming the linked command form is
  `--type plan(<plan_file>,<legend_bead_id>)`.
- `just install && just check` in `sase_100`.

## Phase 4: Telegram and Google Chat Plan Approval Support

Owner: one agent across `../sase-telegram` and `../retired chat plugin`.

Scope:

- Add a Legend option to Telegram plan approval formatting.
- Add a Legend option to Google Chat plan approval formatting.
- Update inbound handlers so the Legend button/reply writes `{"action": "legend"}` to `plan_response.json`.
- Update confirmation strings, pending-action tests, formatting snapshots, README/docs, and integration tests.
- Keep the existing Epic option; it now means executable epic creation under `sdd/epics/`.

Validation:

- `just check` in `../sase-telegram`.
- `just check` in `../retired chat plugin`.
- Manual smoke instructions in phase notes: trigger a plan approval, choose Legend externally, confirm SASE launches the
  legend-creation follow-up rather than the epic-creation follow-up.

## Phase 5: Documentation, Skills, and Cross-Repo Cleanup

Owner: one agent in `sase_100`, with read-only scans of plugin/chezmoi repos unless stale references require edits.

Scope:

- Update `docs/sdd.md`, `docs/beads.md`, README, `docs/xprompt.md`, and any current workflow docs to explain:
  - `sdd/specs`, `sdd/tales`, `sdd/epics`, and `sdd/legends`;
  - research remains top-level;
  - plan-like bead tiers;
  - linked epic command form using `--type plan(<plan_file>,<legend_bead_id>)`;
  - `sase bead work` supports epics only for now.
- Update bundled skills/xprompt docs that show `plans/...` examples.
- Scan sibling repos and chezmoi config for stale live references to root `plans/` or `specs/`; update only live
  behavior/docs. Historical references inside old research or plan files can remain.
- Add a lightweight doctor/check if feasible, or at least a focused test/utility that verifies no new SDD writes target
  legacy roots and bead `design` paths in the current repo resolve through canonical or legacy lookup.

Validation:

- `rg` scans across `sase_100`, `../sase-telegram`, `../retired chat plugin`, `../retired Mercurial plugin`, `../sase-github`, `../sase-nvim`,
  `~/.local/share/chezmoi/home/dot_config/sase`, and `~/.config/sase`.
- `just install && just check` in `sase_100`.
- `just check` in any plugin repo changed during this phase.

## Phase 6: End-to-End Verification and Migration Hardening

Owner: one final integration agent.

Scope:

- Rebase or merge outputs from the prior phases and resolve any path/tier mismatches.
- Run end-to-end local flows:
  - normal approve writes `sdd/tales/...`;
  - epic approve writes `sdd/epics/...`, creates `tier=epic`, and launches/prints `sase bead work`;
  - legend approve writes `sdd/legends/...`, creates `tier=legend`, and does not launch phase agents;
  - an epic plan with `legend_bead_id` creates its epic bead using `--type plan(<plan_file>,<legend_bead_id>)`;
  - legacy `plans/...` and `specs/...` lookups still resolve existing historical references.
- Verify no `sdd/research/` files moved and no new code assumes research lives under `sdd/`.
- Run final cross-repo checks:
  - `cargo test --workspace` in `../sase-core`;
  - `just install && just check` in `sase_100`;
  - `just check` in modified plugin repos.

Exit criteria:

- New SDD writes use only `sdd/` or `.sase/sdd/`.
- Existing epic plan files are in `sdd/epics/`; normal plans are in `sdd/tales/`; prompts are in `sdd/prompts/`.
- Plan approval has a working Legend action in the TUI, Telegram, and Google Chat.
- Linked epic creation uses the requested `--type plan(<plan_file>,<legend_bead_id>)` syntax.
- `sase bead work` remains epic-only and does not try to orchestrate legends.
