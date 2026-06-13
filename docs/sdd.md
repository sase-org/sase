# Spec-Driven Development (SDD)

SDD is sase's system for persisting the intent behind agent work. When an agent submits a plan for approval, SDD can
capture both the expanded prompt snapshot and the approved planning artifact, creating a traceable chain from intent to
execution. In this guide, "plan-like artifact" means a tale, epic, or legend.

## Why SDD Exists

Agent plans are ephemeral by default -- they live in a single session's context window and vanish when the session ends.
SDD fixes this by writing prompt snapshots and plans to disk as first-class artifacts:

- **Prompts** record the full expanded prompt the agent received, so the "why" behind the work is preserved.
- **Tales** record ordinary approved implementation plans, so decomposition decisions are queryable after the fact.
- **Epics** record executable multi-phase plans that can be handed to `sase bead work`.
- **Legends** record higher-level coordination plans that can own linked epics.
- **Myths** record long-horizon narrative, strategy, and context that is broader than active roadmap plans.
- **Research** records exploratory findings, prior art, options, critiques, and recommendations that inform later work.
- **Beads** provide structured issue tracking that links SDD artifacts to execution via plan-like bead tiers and phase
  IDs in commit messages.

Together, these create an audit trail from prompt snapshots to planning artifacts and supporting context. Tales, epics,
and legends can link into the bead hierarchy and phase commits; myths and research notes preserve the longer-lived
context those plans depend on.

## Storage Modes

SDD supports two storage modes. For non-bare-git projects the mode is controlled by the `sdd.version_controlled` config
option. Projects resolved as the built-in `bare_git` VCS provider always use version-controlled SDD under `sdd/`, even
when the merged config leaves `sdd.version_controlled` false.

### Local Mode (default for non-bare-git projects: `sdd.version_controlled: false`)

Files are stored in a standalone git repo inside the primary workspace:

```
{primary_workspace}/.sase/sdd/
  .git/                     # Standalone git repo for SDD tracking
  .gitignore                # Ignores beads.db
  prompts/
    {YYYYMM}/
      {plan_name}.md        # Expanded prompt (xprompts resolved, directives stripped)
  tales/
    {YYYYMM}/
      {plan_name}.md        # Normal non-epic implementation plans
  epics/
    {YYYYMM}/
      {plan_name}.md        # Executable multi-phase epic plans
  legends/
    {YYYYMM}/
      {plan_name}.md        # Higher-level coordination plans
  myths/
    README.md               # Generated directory guide
  research/
    README.md
    {YYYYMM}/
      {note_name}.md        # Research notes and critiques
  beads/                    # Bead store (canonical events + compatibility mirrors)
    config.json
    events/
      manifest.json
      streams/
        <root-id>.jsonl
    issues.jsonl
    beads.db
```

SDD auto-commits prompt and planning-artifact files to this local repo after each planning phase. The standalone repo
keeps SDD history separate from the project's own git history.

### Version-Controlled Mode (`sdd.version_controlled: true`, or any bare-git project)

Files are stored at the project root and tracked in the project's own git repo:

```
{project_root}/
  sdd/
    prompts/
      {YYYYMM}/
        {plan_name}.md
    tales/
      {YYYYMM}/
        {plan_name}.md
    epics/
      {YYYYMM}/
        {plan_name}.md
    legends/
      {YYYYMM}/
        {plan_name}.md
    myths/
      README.md
    research/
      README.md
      {YYYYMM}/
        {note_name}.md
  sdd/beads/              # Bead store (canonical events + compatibility mirrors)
    config.json
    events/
      manifest.json
      streams/
        <root-id>.jsonl
    issues.jsonl
    beads.db
```

In this mode, SDD artifacts are committed alongside code changes via `sase commit`.

For built-in bare-git projects, SASE also creates or refreshes the generated SDD guide files automatically. New
`sase git init` projects include them in the initial commit; `sase git init --existing`, `#git` materialization, and
`sase workspace open` commit and push an `Initialize SDD` init commit when the generated files are missing or stale.
First SDD writes, plan archiving, and `sase bead init` also refresh the generated files before writing project-local SDD
content.

Research notes live under `sdd/research/` alongside the rest of the repository-local SDD corpus.

The directory examples above show the storage roots. Most frontmatter links include the root prefix when the root is
well-known: `sdd/...` in version-controlled mode and `.sase/sdd/...` in local mode.

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
2. Written to the action-specific SDD directory, where `{YYYYMM}` is derived from the current date. Version-controlled
   paths look like:
   - normal approval: `sdd/tales/{YYYYMM}/{plan_name}.md`
   - epic approval: `sdd/epics/{YYYYMM}/{plan_name}.md`
   - legend approval: `sdd/legends/{YYYYMM}/{plan_name}.md`

Prompt snapshots and plans are organized into `YYYYMM` subdirectories (for example, `202603/`) based on the creation
date. This keeps the directories manageable as the number of prompts and plans grows over time. Both flat and `YYYYMM`
layouts are supported for backwards compatibility — SDD also searches legacy `specs` and `plans` paths when resolving
files.

Planning artifacts may also carry a `status` field (set to `done` when work completes) and a `bead_id` field linking to
the bead issue tracker. Legend artifacts use `legend_bead_id` for the legend container bead and `epic_count` for the
number of proposed epics; epics linked under a legend also preserve that `legend_bead_id`.

When `sase plan propose` submits a plan for approval, it touches `~/.sase/.ace_refresh_pulse` so any running ACE TUI
flips the agent into the `PLAN` status immediately rather than waiting for the next auto-refresh tick. The pulse file is
consumed by the inotify-based artifact watcher and is harmless when no TUI is open.

Humans can approve the pending proposal from ACE or from the CLI. `sase plan` lists pending PlanApproval notifications,
recent approvals, and inferred rejected archived proposals. `sase plan approve <id-prefix> --kind tale|epic|legend`
writes the same approval response as the TUI and tells the runner to commit the promoted plan under the matching SDD
tier before launching the follow-up. `--kind approve` runs the coder without committing an SDD plan, while
`--kind commit` records the approved plan in SDD without launching a coder.

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
# sdd/prompts/202605/example.md
plan: sdd/tales/202605/example.md

# sdd/tales/202605/example.md
prompt: sdd/prompts/202605/example.md
```

`sase sdd validate` checks these bidirectional links for prompts, tales, epics, and legends. It treats unpaired
historical files as warnings by default and as errors with `--strict`. Myths and research notes are durable SDD context,
but they are not part of the prompt-plan link validator.

### Model Field

Plan files may carry an optional top-level `model:` field in YAML frontmatter to record the model the work should run
under. The value uses the same syntax `%model` accepts: a bare known model name (e.g. `opus`), a provider-qualified id
(e.g. `codex/gpt-5.5`), or a configured local alias (e.g. `#pro`).

```yaml
# sdd/tales/202605/example.md
prompt: sdd/prompts/202605/example.md
model: opus
```

Epic plan files can additionally annotate individual phases with their own `model:` lines so different phases can be
worked by different models. The `bd/new_epic` xprompt forwards the top-level `model:` field to `sase bead create`'s
`-m/--model` flag on the epic plan bead (so the land agent inherits it) and forwards each phase's `model:` annotation to
that phase bead's `-m/--model` flag. The `bd/new_legend` xprompt forwards only the top-level `model:` to the legend plan
bead (the legend's land-legend agent inherits it); legend plans propose epics rather than phases, so per-phase model
assignment happens later when each epic is split via `bd/new_epic`. When the field is absent, `--model` is omitted and
the bead falls back to the launcher default.

## CLI

The `sase sdd` command group manages generated SDD documentation and frontmatter links:

With no subcommand, `sase sdd` defaults to `sase sdd list` with default options. Use the explicit `sase sdd list` form
when passing list flags such as `--kind` or `--json`.

| Command                 | Purpose                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------- |
| `sase sdd init`         | Enable `sdd.version_controlled`, then refresh `sdd/README.md`, tier READMEs, and the directory map      |
| `sase init sdd`         | Alias for `sase sdd init`; accepts the same `-p/--path` option                                          |
| `sase sdd list`         | List SDD markdown files; `-k/--kind` filters to `prompts`, `tales`, `epics`, `legends`, or `all`        |
| `sase sdd links`        | Print each prompt/artifact frontmatter link and whether its reverse link is intact                      |
| `sase sdd validate`     | Validate frontmatter links; `-j/--json`, `-q/--quiet`, `--strict`, and `-W/--show-warnings` tune output |
| `sase sdd repair-links` | Infer unambiguous prompt/artifact pairs; add `-w/--write` to update files                               |

Each subcommand accepts `-p/--path`, which may point at an SDD root or a project root. Validation treats unpaired or
ambiguous historical files as warnings by default and promotes them to errors with `--strict`; parse errors, missing
targets, wrong link kinds, and broken reverse links are errors unless explicitly allowlisted for legacy migration.

`sase sdd validate` hides warning-severity issues from its text output by default — the summary line still reports the
warning count and appends `(use --show-warnings to display)` so they remain discoverable without scrolling through noise
on the happy path. Pass `-W/--show-warnings` to print each warning, or `--strict` to promote warnings to errors before
filtering. JSON mode (`-j/--json`) and exit codes are unaffected by `-W`.

The `sase sdd init` command enables version-controlled SDD in the project-local `sase.yml`, then refreshes
`sdd/README.md`, the directory map asset, and generated `README.md` files in `tales/`, `epics/`, `legends/`, `myths/`,
and `research/`. Keep conceptual details here in `docs/sdd.md`; use `sase sdd init` to opt into project-local SDD and
refresh generated project guides. The generated guides are safe to overwrite, so do not put hand-maintained conceptual
prose in those README files.

Bare-git projects normally do not need a manual `sase sdd init`: SASE runs the same generated-file refresh during
repository setup, workspace materialization, and the first version-controlled SDD write. The explicit command remains
useful for manual refreshes and `--check` drift audits.

## Bead Integration

SDD initializes the [bead issue tracker](beads.md) automatically when an epic agent spawns:

- **Local mode**: Beads are stored in `.sase/sdd/beads/`; `.sase/sdd/` is a standalone git repo and bead storage is
  initialized through SASE's built-in bead project bootstrap
- **VC mode**: Beads are stored in `sdd/beads/` at the project root

Plan-like beads carry a `tier` value:

- `plan` for ordinary non-epic implementation plans.
- `epic` for executable multi-phase plans.
- `legend` for higher-level coordination plans.

For larger efforts, epic files carry `bead_id` and `tier: epic` in their frontmatter. Each phase of the epic gets its
own bead whose ID appears in commit messages, creating a traceable chain from epic to phase to commit. Legend files
carry `legend_bead_id`, `tier: legend`, and `epic_count`; linked epics also include `legend_bead_id`. For smaller plans,
commit messages include a `PLAN=<path>` tag pointing back to the plan file.

Linked epics are created as ordinary plan beads with a legend parent:

```bash
sase bead create --title "<title>" --type plan(sdd/epics/202605/example.md,<legend_bead_id>) --tier epic
```

Legend beads are executable kickoff points for their proposed epics. `sase bead work <legend_bead_id>` launches one
epic-planning agent per stored `epic_count`; it does not create phase beads directly.

When the plan approval flow launches an epic agent, SASE passes the epic-creation xprompt a plan reference that all
workspaces can resolve. In version-controlled mode this is the project-relative `sdd/epics/{YYYYMM}/{name}.md` path. In
local mode it is the primary-workspace-relative `.sase/sdd/epics/{YYYYMM}/{name}.md` path. If an older flat plan layout
is encountered, the resolver still checks both canonical and legacy flat/`YYYYMM` locations for backwards compatibility.

## Configuration

```yaml
sdd:
  version_controlled: false # default
```

| Option                   | Type | Default | Description                                                                                                                                |
| ------------------------ | ---- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `sdd.version_controlled` | bool | `false` | For non-bare-git projects, store SDD artifacts and beads under `sdd/` in the project repo instead of `.sase/sdd/` in the primary workspace |

See [`configuration.md`](configuration.md) for the full configuration reference.

## Multi-Workspace Behavior

SDD artifact placement follows the configured SDD mode and project workflow. In version-controlled mode, bead commands
read and write the current checkout's `sdd/beads/` store; they do not merge bead records from numbered sibling
workspaces. Coordinate bead state between checkouts through the normal VCS sync path.
