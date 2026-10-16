---
title: Plan commands
description: The SASE CLI commands and bead integration for saved plans.
---

# Plan commands

This page describes how SASE commands and beads work with saved plans.

## CLI

SDD's durable operations live primarily on the repo and plan command groups; executable
epic handoff uses the bead command group:

| Command                              | Purpose                                                                                                           |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `sase repo init`                     | Initialize configured sidecars, generated guides, config, and the repository ignore rule                          |
| `sase init repo`                     | Alias for `sase repo init`                                                                                        |
| `sase repo path REPO`                | Print a primary or sidecar path; `-e/--ensure` materializes the selected sidecar                                  |
| `sase plan links [list]`             | Print each prompt/plan artifact link and whether its reverse link is intact                                       |
| `sase plan links refresh`            | Preview header-block reconciliation; `-w/--write` applies, `-P/--plan REF` scopes, `-j/--json` reports            |
| `sase plan links repair`             | Preview canonical link migration; add `-w/--write` to update unambiguous pairs                                    |
| `sase plan links validate`           | Validate links; `-j/--json`, `-q/--quiet`, and `-W/--show-warnings` tune output                                   |
| `sase plan search`                   | Search or browse tale, epic, prompt, and document-sidecar (for example research) artifacts                        |
| `sase plan show [TARGET]`            | Resolve any plan reference form and render it; `-f/--format` picks full/compact/json/raw                          |
| `sase plan validate`                 | Validate by authored tier; `-e/--explain`, `-j/--json`, and `-q/--quiet` tune output                              |
| `sase bead work TARGET [TARGET ...]` | Validate, archive, link, and launch epic plans or bead targets in order; `-n/--dry-run` previews without mutation |

The link subcommands accept `-p/--path`, which may point at an SDD root or a project
root. Bare `sase plan links` defaults to `sase plan links list`. Validation no longer
checks that a plan has a paired prompt file or that a `PROMPT` bullet's target exists —
prompts live in the agents-sidecar archive and are validated separately by
`sase agent prompts validate`. `sase plan links validate` only checks a plan's own
metadata and `PROMPT` bullet: frontmatter parses, `tier` is valid, the header block
parses in its canonical form (`header-invalid` otherwise), `PARENT` resolves to a real
plan file, and the `PROMPT` bullet (when present) uses the correct link kind and
canonical placement; these are all errors unless explicitly allowlisted for legacy data.

The `PARENT` check is scoped to what the current workspace owns. Plans are published to
the store asynchronously, so a phase plan can land before the epic plan its `PARENT`
points at, and every workspace holding that snapshot would otherwise fail on a file none
of its agents wrote or can produce. An unresolvable `PARENT` is therefore a
`parent-missing-target` error only when the plans checkout reports local changes to the
referencing plan — the case the current agent can actually fix — and a
`parent-unpublished` warning when that plan is already published and merely waiting on
its parent to land. A plan tree that is not a usable git checkout stays strict, and
`sase plan links repair` reports both codes so the condition is never silent.

`sase plan links validate` hides warning-severity issues from its text output by default
— the summary line still reports the warning count and appends
`(use --show-warnings to display)` so they remain discoverable without scrolling through
noise on the happy path. Pass `-W/--show-warnings` to print each warning. JSON mode
(`-j/--json`) and exit codes are unaffected by `-W`.

For a repository whose own `sase/sase.yml` sets `is_sase_managed: true`, the
`sase repo init` command materializes the provider-selected store. On GitHub it finds or
creates every enabled configured sidecar, deriving `<owner>/<repo>--<role>` for unpinned
roles such as plans and research and honoring explicit repository pins. It writes each
repository's deterministic README and infographic asset, pushes generated drift, and
only then records the split store. Provider errors fail setup instead of falling back to
local storage. Missing or false markers make the command and `--check` successful no-ops
before provider work; invalid local configuration fails safely. `sase init repo` exposes
the same flow and the same `-c/--check`, `-d/--diff`, and `-C/--no-commit` flags; both
act on the repository containing the current directory.

Before explicit initialization creates a missing GitHub sidecar, it asks a default-no
question naming the role, repository, visibility, and host. Only `y` or `yes` approves.
Blank input, any other answer, EOF, interruption, and non-interactive stdin cancel with
a nonzero exit before repository or local-state mutations. An existing remote sidecar
connects without this creation prompt. `--check` remains offline and non-interactive,
and neither bare `sase init --yes` nor its generic initializer approval authorizes
repository creation.

Keep conceptual details here in `docs/reference/work-units/plans.md`; generated guides
are safe to overwrite, so do not put hand-maintained conceptual prose in those README
files. Reserved roles and the shipped `research` presentation preset pair their
generated README with an illustrated directory map, while other document sidecars
receive only their deterministic description-based README.

Bare-git projects normally do not need a manual `sase repo init`: SASE runs the same
generated-file refresh during repository setup, workspace materialization, and the first
in-tree SDD write. The explicit command remains useful for manual refreshes and
`--check` drift audits.

## Bead Integration

`sase bead work <plan-file>` initializes the [bead issue tracker](beads.md)
automatically when its resolved store does not have one yet:

- **In-tree mode**: Beads are stored in `sdd/beads/` at the project root.
- **Local mode**: Beads are stored in `.sase/sdd/beads/`; `.sase/sdd/` is a standalone
  git repo.
- **Separate-repo mode**: Beads are stored in `.sase/sdd/beads/` inside the sidecar
  checkout.
- **Split sidecar mode**: Schema-3 projects store beads at the root of the active
  workspace's `--beads` repository, materialized on demand. Schema-2 projects retain
  `beads/` in the `--plans` clone.

Plan-like beads carry a `tier` value:

- `plan` for ordinary non-epic implementation plans.
- `epic` for executable multi-phase plans.

Standalone task beads live in the same store and carry no tier or parent. Their creation
and launch paths are plan-free: agents use `/sase_new_task` first, then use
`sase bead create --type 'task(bug)' --title "Follow up" --size small -w "Independent follow-up that does not belong on the current epic" -f location=src/foo.py -f repro='fails on retry'`
only for an independent follow-up. See the
[standalone task workflow](bead-triage.md#standalone-task-workflow) for ready-state
triage and one-worker launch behavior. The generic bead update command currently accepts
design metadata on a task, but task launch does not consume it as an SDD plan.

For larger efforts, epic files carry `bead_id` and `tier: epic` in their frontmatter.
The command validates the epic, archives it into the resolved plans store, creates the
epic and phase beads, wires the authored dependencies, commits the `bead_id` link, and
launches the shared bead-work schedule. Each phase bead's ID is written as a structured
`SASE_BEAD=<id>` commit footer, creating a traceable chain from epic to phase to commit
and its generated bead page. A stale `bead_id` whose bead is missing is reported with a
remedy instead of silently creating a second epic.

For smaller plans, commit messages include a `SASE_PLAN=<path>` tag pointing back to the
plan file. The path is relative to the repository that owns the plan:
`sdd/plans/<YYYYMM>/<name>.md` for in-tree storage and `plans/<YYYYMM>/<name>.md` for
local or legacy separate-repo stores. In a split `--plans` repository, it is
`<YYYYMM>/<name>.md`. Agents can also build paths from the kind-specific root, for
example `$SASE_SDD_PLANS_DIR/{YYYYMM}/{name}.md`.

## Related

- [Plans](plans.md)
- [Plan format](plan-format.md)
- [Starting bead work](bead-work.md)
