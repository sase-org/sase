---
title: Work tracking CLI workflows
description: How CLI workflows connect beads, plans, goals, projects, and Patches.
---

# Work tracking CLI workflows

## Work Tracking And Planning

Flag and option details live in the generated [CLI command groups](../cli/index.md):

- [sase patch](../cli/patch.md), [sase bead](../cli/bead.md),
  [sase plan](../cli/plan.md), [sase goal](../cli/goal.md),
  [sase project](../cli/project.md)
- [sase init](../cli/init.md), [sase machine](../cli/machine.md),
  [sase memory](../cli/memory.md), [sase instructions](../cli/instructions.md),
  [sase repo](../cli/repo.md)

Workflows: [Patches](patches.md), [Beads](index.md), [SDD](index.md), [Goals](goals.md),
[Project lifecycle](project-spec.md), [Initialization](../agents/index.md),
[Remote dispatch](../integrations/remote-dispatch.md), [Memory](../memory/memory.md).

Patches are PR-sized review records. SDD stores durable prompt and planning artifacts.
Beads add git-portable dependency tracking and executable epics on top of those
artifacts.

Bead commands that take existing bead IDs — `show`, `update`, `open`, `close`, `rm`,
`note`, `+1`, `snooze`, `history`, `dep`, `ref`, `pages`, `epic-symbols`, and `work` —
resolve a full ID against the current project's store first and then route it to the
enabled project that owns it, so `sase bead close bob-cli-1e --note done` works from
another project. Shorthand suffixes stay local, mutating commands reject batches that
span more than one store before writing, and `sase bead create` places a child in the
store that owns a full parent ID. Commands without a bead selector (`list`, `search`,
`ready`, `blocked`, and `stats`) keep the current-project scope. See
[Bead ID Arguments](beads.md#bead-id-arguments).

`sase project` defaults to `sase project list`, and `sase project list` defaults to
enabled true projects. `sase project current` prints the current project derived from
the VCS macro MRU head — the project name in that project's accent color, its canonical
directory key, whether it came from a project ref or a Patch, and the MRU ref that
produced it. Launch an agent on a project (or on a Patch owned by that project), or run
`sase project set-current`, to change it — sase's TUI binds the same operation in the
Projects tab. When nothing resolves, the command explains that and exits 0. Use
`sase project list --state all --json` to inspect disabled projects and internal
`sibling` backing records, `sase project disable <project>` to hide a dormant project
from default launch views, and `sase project enable <project>` to make it launchable
again. Disabling refuses projects with live `RUNNING` claims or active artifact markers
unless `--force` is passed. Project arguments also accept the
[project tag](../macros/reference-syntax.md#project-tags) spelling, so
`sase project show +sase` works like `sase project show sase`. `sase project list` has a
`TAG` column and `sase project show` a `Tag:` line with each project's `+<name>`
spelling (`-` or omitted when the name does not fit tag syntax), colored by project
accent on a color terminal; their `--json` output adds `tag` (`null` when the name does
not fit tag syntax), `workflow_type`, and `accent` (`null` for disabled projects).
Legacy active/inactive values and the deprecated lifecycle command aliases remain
read-compatible. sase's TUI **Projects** tab (in the SASE Admin Center, opened with `#`)
provides the interactive counterpart, including marking multiple projects, editing a
ProjectSpec in `$EDITOR`, and deleting obsolete SASE project directories after
confirmation. There is no CLI delete subcommand; full project-directory deletion is only
available from sase's TUI Projects tab and removes state under `~/.sase/projects/`, not
workspace checkouts.

`sase project suggest [PROVIDER] [-a|--all] [-j|--json] [-o|--owner OWNER]... [-r|--refresh]`
ranks the repositories worth adding as projects, grouped as `RESUME`, `ON THIS MACHINE`,
`SUGGESTED`, `LINKED TO YOUR PROJECTS`, and `DISABLED PROJECTS`. Discovery is
cache-first per owner: it creates no repositories or project registrations, so agents
may call it freely. It may refresh local discovery caches, and specifying a provider
records that provider as the wizard preference. `-o` restricts discovery to the named
owners, `-r` bypasses the cached repository lists, and `-a` includes the hidden rows
(sidecars, forks, archived repositories, enabled projects, numbered clone copies, and
third-party local checkouts) that are otherwise only counted in the footer.

`sase project add REF [-a|--alias ALIAS]... [-c|--check] [-j|--json] [-m|--make-current] [-n|--name NAME] [-S|--no-setup | -s|--setup] [-Q|--request-path PATH] [-R|--result-path PATH] [-y|--yes]`
registers an existing repository. `--check` is read-only and emits one plan document
with `--json`; JSON apply streams plan, step, and result events as NDJSON. New projects
are enabled by default. Setup may write `sase/sase.yml`, commit the marker, and push the
default branch; agents can preview and register with automatic setup omitted, while
explicit `--setup` is human-only. Repeating the same command resumes an interrupted
operation. After successful setup, a TTY can hand off to `sase init -p KEY`; sidecar
creation there still requires its own confirmation.

`sase project create REF [-a|--alias ALIAS]... [-c|--check] [-d|--description TEXT] [-j|--json] [-m|--make-current] [-n|--name NAME] [-O|--option KEY=VALUE]... [-S|--no-setup | -s|--setup] [-Q|--request-path PATH] [-R|--result-path PATH] [-v|--visibility VISIBILITY] [-y|--yes]`
creates a repository (`gh:OWNER/NAME`, `OWNER/NAME`, or `git:NAME`) and registers it.
The apply argv uses a create-parseable ref (`git:NAME` for bare git). `--visibility` is
GitHub sugar and is only defaulted or emitted when the provider's creation form has a
visibility field; bare-git has none. Provider options are validated strictly before any
create subprocess. `--check` lists every provider option with its default, value, and
availability, and is available to agents. Apply refuses inside agents and monitors
(exit 2) unless it runs as an approved `/sase_gate` option or
`SASE_PROJECT_CREATE_BYPASS` holds a reason. Repeating the same command resumes an
interrupted create.

`-Q`/`--request-path` and `-R`/`--result-path` on `add` and `create` are integration
options for a durable proc: `-Q` reads an existing operation-request JSON file and
checks that its target and options match the command; `-R` writes the outcome of an
apply attempt as typed JSON, including blocked or failed attempts. `--check` writes no
result file. These companion files are unrelated to project sidecar repositories. When
the flags are omitted, SASE uses `$SASE_PROC_REQUEST_PATH` and `$SASE_PROC_RESULT_PATH`
if set; otherwise no request file is read or result file written. Ordinary interactive
commands do not need either flag.

`sase project alias list [PROJECT] [-j|--json]`, `add PROJECT ALIAS`,
`remove PROJECT ALIAS`, and `clear PROJECT` manage ProjectSpec aliases. sase's TUI
Projects sub-tab (in the SASE Admin Center, opened with `#`) also displays aliases,
includes them in filtering, and opens an alias editor with `A`. Alias refs are accepted
in launch-bound VCS workspace tags, but prompt history, agent metadata, and artifacts
use the canonical directory-key project name. ProjectSpecs may also carry `PROJECT_NAME`
as the primary user-facing name. For example, the GitHub provider can create
`PROJECT_NAME: foo` and then `PROJECT_NAME: foo_1` for distinct `owner/foo` repositories
while keeping stable canonical project records. Existing auto-aliased GitHub projects
remain valid and keep resolving through `PROJECT_ALIASES`.

Enabled-only true-project discovery is also the default for launch pickers, Patch
searches, project-local macro catalogs, broad mobile helper catalogs, and all-known bead
helper reads. Internal sibling backing records are hidden from those surfaces and
support configured linked repositories. Agents prepare one through `/sase_repo`; the
underlying audited open infers the host project and workspace from cwd. Agent-history
views that need older artifacts opt into all project states explicitly. An explicitly
typed known-project VCS ref is a launch-time exception: it re-enables a disabled project
before claiming a workspace. A checkout cwd or mobile `project` value is only
prompt-resolution context, not a workspace ref; without an explicit ref, a bare prompt
defaults to `#git:home`. Direct low-level claims against a disabled ProjectSpec remain
blocked until the project is enabled.

`sase plan` defaults to `sase plan list`. The dashboard has Proposed, Approved, and
Rejected sections; use repeatable `-s/--status` options to select sections, `-n/--limit`
to set each history section's size (`0` is unlimited), and `-t/--tier` to filter by
plan-file tier. Proposed rows are never limited and are the actionable rows; each leads
with the plan `name` in bold cyan (shortest unique form, with the dim `id_prefix` below
it), plus agent, project, provider/model, plan path, and response directory. A hint line
under the section shows the ready-to-paste approve/reject commands for the first name.
Pass the plan name to `sase plan approve <name>` or `sase plan reject <name>` (a
`<shard>/<name>` path, filesystem path, `plan:` ref, planner agent, or notification
ID/prefix works too; names TAB-complete). Proposed `--json` rows carry the same `name`
field. If the selector is omitted, exactly one pending proposal must exist. When
`--kind` is omitted, approval defaults to `tale`; epic-authored plans require an
explicit `--kind epic` or `--kind tale`. The Rejected section is inferred from archived
proposal files that are not represented by the proposed or approved state; it is a
history aid, not the selector source for new actions. The approval kind is the workflow
choice: `approve` runs the coder without asking the runner to commit an SDD plan, `tale`
commits the plan as an SDD tale and then runs the coder, `epic` commits the matching SDD
tier and launches the bead follow-up, and `commit` records the approved plan in SDD
without launching a coder. Use `-m/--model` to pick the follow-up agent's model. Use
`-p/--prompt` to add extra coder instructions for the `approve` and `tale` paths. A plan
with no live gate can be named by path, `plan:` reference, archive name, or unavailable
gate ID: it is approved directly and starts a `#coder` in the planner's agent session
when it can safely attach, otherwise as a standalone agent. The coder launch runs a
ladder: it relocates to a pool workspace when the planner's workspace is taken, falls
back to standalone when the agent session cannot be joined, and retries once on
transient claim errors. Only unlaunchable-machine errors (missing owner identity,
unknown project tag, hard-disabled provider, or an unspawnable process) fail the launch.
On failure the card prints `sase plan approve <local plan path>` to re-run every
fallback and record the receipt. `-n/--dry-run` renders that decision without changing
state, and `-P/--project` supplies project context for the direct route. Re-approving an
already-approved plan relaunches its coder when that coder failed, was killed, or never
launched, and refuses when the coder is still running or has finished. Tale and epic
approvals validate against their target schema before writing a response; a failure
prints the diagnostics and expected schema and leaves the proposal pending for retry.
Plans can also declare typed choices and toggles as Plan Decisions. Ordinary approval
accepts their effective defaults; pass `-D/--decide ID=VALUE` to approve with different
values, or use `sase gate answer` with `--set decision_<id>=<value>` to override them on
a pending gate. See [Plan Decisions](plan-format.md#plan-decisions) for the grammar,
memory-consent rules, and current interface limits.

`sase plan reject` writes the rejection response first, then uses the same durable
cleanup path as the TUI no-feedback rejection action when the matching planner row is
still discoverable. If cleanup cannot find or kill the row, the CLI reports that
separately after the plan has already been rejected.

`sase plan search [QUERY]` searches plans in the resolved SDD store (the `repo` source)
and the machine-local `~/.sase/plans/` archive. Omit the query to browse with metadata
filters. Compact and Markdown output group SDD-store matches above local matches; JSON
and full output keep ranked result order with SDD-store matches prioritized over
otherwise-similar local matches. Useful filters include `--kind`, `--status`,
`--source`, `--since`, `--until`, `--sort`, and `--format json|markdown` for
agent-friendly output.

`sase plan show [TARGET]` resolves any way a user can name a plan to exactly one plan
and renders it. In `-t auto` (the default), TARGET is tried against five rungs in order
and the first definitive match wins: `path` (an existing file, absolute or
cwd-relative), `ref` (a `plan:` reference, a legacy marker path, or a month-drifted
reference, Rust resolved), `proposal` (any pending-plan selector `approve`/`reject`
accept: name, `<shard>/<name>`, planner agent, or notification id/prefix), `name` (a
corpus slug or `<shard>/<slug>` lookup, with or without `.md`), and `bead` (a bead id
whose `design` field points at a plan). Pass `-t/--target` to force one rung with no
fallthrough. Omit TARGET to show the sole visible pending plan proposal, exactly as
`sase plan approve`/`reject` treat an omitted selector. Every ambiguity prints its
candidates as re-runnable `plan:` references and every miss prints close-match
suggestions; neither guesses. `-f/--format` selects `full` (the default
section-structured detail view, matching the PLAN lane in sase's TUI), `compact` (the
same row `sase plan search` prints), `json` (a schema-versioned envelope), or `raw` (the
plan file's exact text, for piping). A plan that fails validation still renders in full
with its diagnostics shown and exits `0`; only a missed, ambiguous, or unreadable target
exits `1`. `-w/--wrap` controls goal/phase/diagnostics prose wrapping, and `-c/--color`
matches `sase bead show`.

`sase plan validate PLAN_FILE` reads the required `tier: tale|epic` property and
validates exactly one path without requiring a project or agent context. With Plan
Decisions, agent-context validation also checks memory selectors and human-request and
corrected-claim quotes; outside an agent, quote verification is deferred to proposal. It
reports every schema problem in one run and prints the expected tier schema plus a
minimal valid example on failure. Use `-e/--explain` for tier-specific authoring
guidance, `-j/--json` for the stable machine-readable envelope, or `-q/--quiet` to
suppress the successful human summary. A plan that has decisions also prints the
Decision Sheet after the result, and, when the live `%auto` spelling covers the plan's
tier, `auto-approved: every decision takes its default`. When the spelling does not
cover the tier, sase prints `%auto:<mode>` does not cover `<tier>` plans; this plan
waits for review instead. In `--json` mode stdout stays one JSON document: the sheet,
the `%auto` note, and the outside-agent quote-verification note live inside the
`decisions` envelope while the same human text goes to stderr. See the
[validation output](plan-format.md#plan-frontmatter-schema-and-validation). The removed
`-t/--tier` option is now invalid command usage. A valid plan exits 0, a validation
failure exits 1, and invalid command usage exits 2.

<a id="sase-goal"></a> Moved to [Goals](goals.md#sase-goal).
