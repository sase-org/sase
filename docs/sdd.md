# Spec-Driven Development (SDD)

SDD is sase's system for persisting the intent behind agent work. When an agent submits a plan for approval, SDD can
capture both the expanded prompt snapshot and the approved planning artifact, creating a traceable chain from intent to
execution. In this guide, "plan-like artifact" means a tale or epic.

## Why SDD Exists

Agent plans are ephemeral by default -- they live in a single session's context window and vanish when the session ends.
SDD fixes this by writing prompt snapshots and plans to disk as first-class artifacts:

- **Prompts** record the full expanded prompt the agent received, so the "why" behind the work is preserved.
- **Tales** record ordinary approved implementation plans, so decomposition decisions are queryable after the fact.
- **Epics** record executable multi-phase plans that can be handed to `sase bead work`.
- **Research** records exploratory findings, prior art, options, critiques, and recommendations that inform later work.
- **Beads** provide structured issue tracking that links SDD artifacts to execution via plan-like bead tiers and phase
  IDs in commit messages.

Together, these create an audit trail from prompt snapshots to planning artifacts and supporting context. Tales and
epics can link into the bead hierarchy and phase commits; research notes preserve the longer-lived context those plans
depend on.

## Provider-Owned Storage

The workspace provider selects an initial policy; a materialized store record supplies the concrete layout:

- `in_tree` stores artifacts under the checkout's `sdd/` directory and commits them with code changes.
- `local` is the fallback for providerless projects and stores artifacts at the primary workspace's `.sase/sdd/`.
- `separate_repo` stores artifacts in a workspace-local `.sase/sdd/` clone backed by a provider-materialized companion
  repo.
- `companion_repos` stores plans and beads in an auto-cloned `--plans` repo and research in a separate `--research`
  repo. Initialization prepares both in its current workspace; later workspaces clone research on demand. Monthly
  directories live directly at each companion root; legacy single-root projects are unchanged until initialization and
  migration are run.

Use `sase sdd path` to print the effective root, or `sase sdd path research --ensure` to materialize and print the
research root. Launched agents receive `SASE_SDD_DIR` and per-kind `SASE_SDD_*_DIR` variables, so prompts and hooks
should use those resolvers instead of assuming `sdd/` is relative to the checkout.

Project and user configuration cannot override this selection. See [SDD Storage](sdd_storage.md) for the provider
contract, companion-repo convention, setup guidance, and offline/push behavior.

For built-in bare-git projects, SASE creates or refreshes the generated SDD guide files automatically. First-use
`#git:<project>` initialization includes them in the initial commit; existing bare-repo registration, `#git`
materialization, and `sase workspace open` commit and push an `Initialize SDD` init commit when the generated files are
missing or stale. First SDD writes, plan archiving, and `sase bead init` also refresh the generated files before writing
project-local SDD content.

Research notes live under `research/{YYYYMM}/` inside the effective SDD root. A `#research` xprompt (defined in user or
project config -- the packaged default was removed) conventionally tells the agent to create a new markdown file in the
current month directory; `sase sdd` does not write research files automatically.

## How SDD Works

### Prompt Generation

When a submitted plan is accepted, SDD generates a prompt snapshot by:

1. Expanding all `#xprompt` references in the original prompt
2. Stripping `%directives` (`%model`, `%name`, `%wait`, etc.)
3. Dry-expanding embedded workflow `prompt_part` content (renders templates without executing pre/post steps)

The result is a clean, self-contained document showing exactly what the agent was asked to do.

### Artifact Persistence

The plan file produced by the agent is:

1. Annotated with a `create_time` frontmatter field
2. Given a required `tier: tale|epic` frontmatter value and written to `<plans-root>/{YYYYMM}/{plan_name}.md`, where
   `{YYYYMM}` is derived from the current date. Its prompt snapshot is written beside it at
   `<plans-root>/{YYYYMM}/prompts/{plan_name}.md`.

Prompt snapshots, plans, and research notes are organized into `YYYYMM` subdirectories (for example, `202603/`) based on
the creation date. Prompt snapshots are nested under each plan month at `<plans-root>/<YYYYMM>/prompts/`. This keeps
paired artifacts together while plan discovery remains limited to `<plans-root>/<YYYYMM>/*.md`. Resolve the plans root
with `sase sdd path plans` or `SASE_SDD_PLANS_DIR`; historical top-level `prompts/` and `specs/` aliases remain readable
during migration.

Planning artifacts may also carry a `status` field (set to `done` when work completes) and a `bead_id` field linking to
the bead issue tracker.

When `sase plan propose` submits a plan for approval, it touches `~/.sase/.ace_refresh_pulse` so any running ACE TUI
flips the agent into the `PLAN` status immediately rather than waiting for the next auto-refresh tick. The pulse file is
consumed by the inotify-based artifact watcher and is harmless when no TUI is open.

Humans can approve the pending proposal from ACE or from the CLI. `sase plan` lists pending PlanApproval notifications,
recent approvals, and inferred rejected archived proposals. `sase plan approve <id-prefix> --kind tale|epic` writes the
same approval response as the TUI and tells the runner to commit the promoted plan under the matching SDD tier before
launching the follow-up. `--kind approve` runs the coder without committing an SDD plan, while `--kind commit` records
the approved plan in SDD without launching a coder. `sase plan reject <id-prefix>` writes the same no-feedback rejection
response as the TUI, then attempts to dismiss and user-kill the matching planner row when it can be found.

To recall prior plans, `sase plan search [QUERY]` searches plans in the resolved SDD store (the `repo` source, surfaced
first) and the machine-local `~/.sase/plans/` archive by content. The query is optional — omit it to browse and filter
with `--kind`, `--status`, `--source`, and `--since`/`--until` date bounds. Results are ranked (relevance with a query,
recency without) and render as colored `compact`/`full` output or as agent-friendly `json`/`markdown` via `--format`.

### Q&A Sections

If the agent asks clarifying questions during planning (via the `/sase_questions` skill), the Q&A exchange is appended
to the prompt snapshot so the full context of planning decisions is preserved.

Multi-round Q&A is rendered as a single merged `### Questions and Answers` section with monotonic `Q1..QN` numbering
across all rounds (a second round of questions continues at the next free number rather than restarting at `Q1`). The
section is wrapped in exactly one `%xprompts_enabled` pair regardless of round count, and follow-up writes strip any
prior Q&A block (including legacy duplicate blocks from older runs) before re-emitting the merged section. When a round
carries a global note the "last non-empty wins" rule applies — a later round's note replaces the earlier one, but an
empty later note preserves the earlier value.

### Frontmatter Links

Prompt snapshots and plan-like artifacts link to each other through YAML frontmatter:

```yaml
# plans/202605/prompts/example.md
plan: plans/202605/example.md

# plans/202605/example.md
prompt: plans/202605/prompts/example.md
tier: tale
```

The example shows the in-tree/local/legacy single-root link form. In a split `--plans` repository, the same links omit
the leading `plans/` component (`202605/example.md` and `202605/prompts/example.md`) because monthly directories live at
the repository root.

`sase sdd validate` checks these bidirectional links for prompts, tales, and epics. It treats unpaired historical files
as warnings by default and as errors with `--strict`. Research notes are durable SDD context, but they are not part of
the prompt-plan link validator.

### Model Field

Plan files may carry an optional top-level `model:` field in YAML frontmatter to record the model the work should run
under. The value uses the same syntax `%model` accepts: a bare known model name (e.g. `opus`), a provider-qualified id
(e.g. `codex/gpt-5.6-sol`), or a configured local alias (e.g. `#pro`).

```yaml
# plans/202605/example.md
prompt: plans/202605/prompts/example.md
tier: tale
model: opus
```

Epic plan files can additionally annotate individual phases with their own `model:` lines so different phases can be
worked by different models. The `bd/new_epic` xprompt forwards the top-level `model:` field to `sase bead create`'s
`-m/--model` flag on the epic plan bead (so the land agent inherits it) and forwards each phase's `model:` annotation to
that phase bead's `-m/--model` flag. When the field is absent, `--model` is omitted and the bead falls back to the
launcher default.

## CLI

The `sase sdd` command group manages generated SDD documentation and frontmatter links:

With no subcommand, `sase sdd` defaults to `sase sdd list` with default options. Use the explicit `sase sdd list` form
when passing list flags such as `--kind` or `--json`.

| Command                 | Purpose                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------- |
| `sase sdd init`         | Create/connect effective SDD storage, then refresh generated guide files                                |
| `sase init sdd`         | Compatibility alias for the provider-owned `sase sdd init` flow                                         |
| `sase sdd links`        | Print each prompt/artifact frontmatter link and whether its reverse link is intact                      |
| `sase sdd list`         | List SDD markdown files; `tales`/`epics` are tier filters over `plans/`                                 |
| `sase sdd migrate`      | Preview or apply migration from a legacy clone into initialized split companions                        |
| `sase sdd path`         | Print the effective root or kind root; `-e/--ensure` materializes its backing companion                 |
| `sase sdd repair-links` | Infer unambiguous prompt/artifact pairs; add `-w/--write` to update files                               |
| `sase sdd validate`     | Validate frontmatter links; `-j/--json`, `-q/--quiet`, `--strict`, and `-W/--show-warnings` tune output |

The file-oriented subcommands accept `-p/--path`, which may point at an SDD root or a project root. `sase sdd path`
instead resolves the current workspace and accepts an optional kind such as `research`; `--ensure` synchronizes that
kind's companion. Validation treats unpaired or ambiguous historical files as warnings by default and promotes them to
errors with `--strict`; parse errors, missing targets, wrong link kinds, and broken reverse links are errors unless
explicitly allowlisted for legacy migration.

`sase sdd validate` hides warning-severity issues from its text output by default — the summary line still reports the
warning count and appends `(use --show-warnings to display)` so they remain discoverable without scrolling through noise
on the happy path. Pass `-W/--show-warnings` to print each warning, or `--strict` to promote warnings to errors before
filtering. JSON mode (`-j/--json`) and exit codes are unaffected by `-W`.

For a repository whose own `sase.yml` sets `is_sase_managed: true`, the `sase sdd init` command materializes the
provider-selected store. On GitHub it finds or creates public `<owner>/<repo>--plans` and `<owner>/<repo>--research`
companions, writes each repository's deterministic README and infographic asset, pushes both, and only then records the
split store. Provider errors fail setup instead of falling back to local storage. Missing or false markers make the
command and `--check` successful no-ops before provider work; invalid local configuration fails safely. `sase init sdd`
exposes the same flow and check/path flags, and `--path` checks the target repository's marker.

Before explicit initialization creates a missing GitHub companion, it asks a default-no question naming the public
`--plans` or `--research` repository and host. Only `y` or `yes` approves. Blank input, any other answer, EOF,
interruption, and non-interactive stdin cancel with a nonzero exit before repository or local-state mutations. An
existing remote companion connects without this creation prompt. `--check` remains offline and non-interactive, and
neither bare `sase init --yes` nor its generic initializer approval authorizes repository creation.

For an existing legacy store, run initialization before migration: `sase sdd init` creates or adopts both companions and
records the split layout; it does not import legacy content. Then `sase sdd migrate --check --diff` previews the import.
Applying `sase sdd migrate` copies monthly plan and research directories and durable bead files, excludes `beads.db*`,
rewrites legacy plan-link prefixes, pushes both companions, and retires the selected local legacy source tree. README
files, assets, non-month directories, and other files are not copied; after local retirement they are recoverable only
from an existing Git remote/history or a backup.

Keep conceptual details here in `docs/sdd.md`; generated guides are safe to overwrite, so do not put hand-maintained
conceptual prose in those README files.

Bare-git projects normally do not need a manual `sase sdd init`: SASE runs the same generated-file refresh during
repository setup, workspace materialization, and the first in-tree SDD write. The explicit command remains useful for
manual refreshes and `--check` drift audits.

## Bead Integration

SDD initializes the [bead issue tracker](beads.md) automatically when an epic agent spawns:

- **In-tree mode**: Beads are stored in `sdd/beads/` at the project root.
- **Local mode**: Beads are stored in `.sase/sdd/beads/`; `.sase/sdd/` is a standalone git repo.
- **Separate-repo mode**: Beads are stored in `.sase/sdd/beads/` inside the companion checkout.
- **Split companion mode**: Beads are stored at `beads/` in the active workspace's auto-cloned `--plans` repository.

Plan-like beads carry a `tier` value:

- `plan` for ordinary non-epic implementation plans.
- `epic` for executable multi-phase plans.

For larger efforts, epic files carry `bead_id` and `tier: epic` in their frontmatter. Each phase of the epic gets its
own bead whose ID appears in commit messages, creating a traceable chain from epic to phase to commit. For smaller
plans, commit messages include a `SASE_PLAN=<path>` tag pointing back to the plan file. The path is relative to the
repository that owns the plan: `sdd/plans/<YYYYMM>/<name>.md` for in-tree storage and `plans/<YYYYMM>/<name>.md` for
local or legacy separate-repo stores. In a split `--plans` repository, it is `<YYYYMM>/<name>.md`.

When the plan approval flow launches an epic agent, SASE passes the epic-creation xprompt a plan reference that all
workspaces can resolve. Agents can also build paths from the kind-specific root, for example
`$SASE_SDD_PLANS_DIR/{YYYYMM}/{name}.md`.

## Configuration

```yaml
sdd:
  repo:
    name: "" # optional companion repo override for providers that support it
  push_after_commit: async
```

| Option                  | Type        | Default | Description                                                                                                                                                                                                                             |
| ----------------------- | ----------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sdd.repo.name`         | string      | `""`    | Optional companion repo override for providers that support `separate_repo`; accepts `name` or `owner/name`. For GitHub, empty checks only `<owner>/<repo>--sdd`; set `sdd.repo.name` to use another repo such as `sdd` or `owner/sdd`. |
| `sdd.push_after_commit` | bool/string | `async` | Companion-repository push behavior after SDD commits: `async`, `true`, or `false`.                                                                                                                                                      |

Storage selection is not configurable. The workspace provider owns it. Retired `sdd.storage` and
`sdd.version_controlled` keys are ignored and reported by `sase doctor` for cleanup.

See [`configuration.md`](configuration.md) for the full configuration reference and [SDD Storage](sdd_storage.md) for
mode behavior.

## Multi-Workspace Behavior

SDD artifact placement follows provider policy. With `in_tree`, bead commands use the current checkout's `sdd/beads/`
store. With `separate_repo`, commands first require a usable provider companion and then use the active workspace's
`.sase/sdd/` clone. With `companion_repos`, each workspace auto-clones `--plans` under `sase/repos/` for plans and
beads. Initialization also prepares `--research` in its current workspace; other workspaces clone it when explicitly
ensured. Providerless local storage uses the primary workspace. Numbered sibling stores are not merged; coordinate
shared state through the normal VCS sync path. Prefer `sase sdd path <kind>` or the `SASE_SDD_*_DIR` variables over
hard-coded relative paths.
