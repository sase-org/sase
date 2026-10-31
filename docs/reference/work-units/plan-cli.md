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
| `sase plan propose PLAN_FILE`        | Submit an agent-authored Markdown plan for approval                                                               |
| `sase bead work TARGET [TARGET ...]` | Validate, archive, link, and launch epic plans or bead targets in order; `-n/--dry-run` previews without mutation |

`sase plan propose` runs inside a SASE agent. With `staged_handoffs` enabled, it saves
the proposal and returns `Staged`; the approval gate is published after host completion.
The root agent finishes through `/sase_final`. With the flag off, the command ends the
turn through the immediate handoff path. See
[Handoff completion](../agents/agent-sessions.md#handoff-completion).

The link subcommands accept `-p/--path`, which may point at an SDD root or a project
root. Bare `sase plan links` defaults to `sase plan links list`. Validation does not
check that a plan has a paired prompt file or that a `PROMPT` bullet's target exists —
prompts live in the agents-sidecar archive and are validated separately by
`sase agent prompts validate`. `sase plan links validate` only checks a plan's own
metadata and `PROMPT` bullet: frontmatter parses, `tier` is valid, the header block
parses in its canonical form (`header-invalid` otherwise), `PARENT` resolves to a real
plan file, and the `PROMPT` bullet (when present) uses the correct link kind and
canonical placement; these are all errors unless explicitly allowlisted for existing
data.

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
local or separate-repo stores. In a split `--plans` repository, it is
`<YYYYMM>/<name>.md`. Agents can also build paths from the kind-specific root, for
example `$SASE_SDD_PLANS_DIR/{YYYYMM}/{name}.md`.

## Related

- [Plans](plans.md)
- [Plan format](plan-format.md)
- [Starting bead work](bead-work.md)

## SDD repository and plan commands

SDD initialization/path resolution lives under `sase repo`; artifact browsing and
prompt/plan link maintenance live under `sase plan`. Link commands accept `-p/--path`,
which may point at an SDD root or a project root. Bare `sase plan links` defaults to its
`list` child.

<a id="cli-options-30"></a> Moved to [sase plan](../cli/plan.md#sase-plan-links).

## `sase plan`

With no subcommand, `sase plan` defaults to the `sase plan list` dashboard.

<a id="cli-options-46"></a> Moved to [sase plan](plan-cli.md#sase-plan).

<a id="command-behavior-30"></a> Moved to
[Plan commands](plan-cli.md#command-behavior-30).

## Command behavior {#command-behavior-30}

`sase plan list` prints a Rich dashboard by default and emits a stable JSON projection
with `summary`, `proposed`, `approved`, and `rejected` keys when `-j/--json` is set.
Repeat `-s/--status` with `approved`, `proposed`, or `rejected` to render or serialize
only those sections; unrequested JSON section keys are omitted, while summary counts
continue to describe the full collected view. `-n/--limit` controls the maximum rows in
each Approved and Rejected history section (default `10`, with `0` meaning unlimited).
Proposed rows are always shown in full, leading with the plan `name` (shortest unique
form, dim `id_prefix` below) and a ready-to-paste approve/reject hint line. `-t/--tier`
composes with both filters. Proposed `--json` rows carry the same `name` field alongside
`id_prefix`. The JSON summary includes `status_filter`, `tier_filter`, and a non-default
`limit` when applicable, plus `approved_scan_truncated` if a finite artifact scan may
have omitted older approvals.

Use the Proposed row's plan name as the selector for `sase plan approve` or
`sase plan reject` (the row's `id_prefix` still works); omitting the selector is valid
only when exactly one pending proposal exists. The Rejected rows are inferred from
archived proposal files that are not represented by current proposed or approved state,
so they are useful for history but are not actionable selectors. Omitting `--kind`
defaults to `tale`; an epic-authored plan requires an explicit `--kind epic` or
`--kind tale`. A gateless epic must be launched with `sase bead work <plan-file>`; the
direct approval route does not launch epics. Tale/epic targets are validated before the
proposal is consumed. Approval kind `approve` runs the coder without asking the runner
to commit an SDD plan, `tale` commits the plan as an SDD tale and then runs the coder,
`epic` commits the matching SDD tier and launches the bead follow-up, and `commit`
records the approved plan in SDD without launching a coder. The `-m/--model` flag
applies to the follow-up agent; `-p/--prompt` adds extra coder instructions only for the
`approve` and `tale` paths. Use `-w/--wait` with comma-separated agent names and
`bead=<id>` entries to hold the approved coder or launched epic phases until those
dependencies finish. `sase plan reject` writes the rejection response first, then
attempts the same durable cleanup path as TUI no-feedback rejection when the matching
planner row is still discoverable.

`sase plan search [query]` scans plans in the resolved SDD store (the `repo` source) and
the machine-local `~/.sase/plans/` archive. The query is a literal case-insensitive
substring; omit it to browse and filter. `--format` accepts `compact`, `full`, `json`,
or `markdown`; `--kind` is repeatable and filters SDD-store artifacts to a plan tier
(`tale` or `epic`), `prompt`, or a configured document-sidecar role such as `research`
(an unknown kind is a usage error that lists the valid ones); `--status` is repeatable
and filters frontmatter status to `wip` or `done`; `--source` selects `all`, `repo`, or
`local`; `--sort` selects `relevance`, `recent`, or `title` (defaulting to relevance
with a query and recent without one); `--since`/`--until` accept `YYYY-MM-DD`,
`YYYY-MM`, `YYYYMM`, or relative durations such as `14d`; and `--limit` defaults to
`20`, with `0` printing all matches.

`sase plan validate <plan_file>` infers the validation schema from the authored `tier`;
it no longer accepts `-t/--tier`. `--explain` prints tier-specific authoring guidance
before human results or adds it to the JSON envelope, while `--quiet` suppresses only
the successful human summary. See
[Plan Frontmatter Schema and Validation](plan-format.md#plan-frontmatter-schema-and-validation)
for diagnostics and exit codes.
