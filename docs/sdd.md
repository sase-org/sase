# Spec-Driven Development (SDD)

SDD is sase's system for persisting the intent behind agent work. When an agent produces a plan, SDD captures both the
fully-expanded prompt (the **spec**) and the structured plan itself, creating a traceable chain from intent to
execution.

## Why SDD Exists

Agent plans are ephemeral by default -- they live in a single session's context window and vanish when the session ends.
SDD fixes this by writing specs and plans to disk as first-class artifacts:

- **Specs** record the full expanded prompt the agent received, so the "why" behind the work is preserved.
- **Plans** record the structured plan the agent produced, so decomposition decisions are queryable after the fact.
- **Epics** record executable multi-phase plans that can be handed to `sase bead work`.
- **Legends** record higher-level coordination plans that can own linked epics.
- **Beads** provide structured issue tracking that links SDD artifacts to execution via plan-like bead tiers and phase
  IDs in commit messages.

Together, these create an audit trail: spec --> plan, epic, or legend --> bead hierarchy --> phase beads --> commits.

## Storage Modes

SDD supports two storage modes controlled by the `sdd.version_controlled` config option.

### Local Mode (default: `sdd.version_controlled: false`)

Files are stored in a standalone git repo inside the primary workspace:

```
{primary_workspace}/.sase/sdd/
  .git/                     # Standalone git repo for SDD tracking
  .gitignore                # Ignores beads.db
  specs/
    {YYYYMM}/
      {plan_name}.md        # Expanded prompt (xprompts resolved, directives stripped)
  plans/
    {YYYYMM}/
      {plan_name}.md        # Normal non-epic implementation plans
  epics/
    {YYYYMM}/
      {plan_name}.md        # Executable multi-phase epic plans
  legends/
    {YYYYMM}/
      {plan_name}.md        # Higher-level coordination plans
  beads/                    # Bead database (SQLite + JSONL)
    beads.db
    issues.jsonl
    config.json
```

SDD auto-commits spec and plan files to this local repo after each planning phase. The standalone repo keeps SDD history
separate from the project's own git history.

### Version-Controlled Mode (`sdd.version_controlled: true`)

Files are stored at the project root and tracked in the project's own git repo:

```
{project_root}/
  sdd/
    specs/
      {YYYYMM}/
        {plan_name}.md
    plans/
      {YYYYMM}/
        {plan_name}.md
    epics/
      {YYYYMM}/
        {plan_name}.md
    legends/
      {YYYYMM}/
        {plan_name}.md
  .sase_beads/              # Bead database (git-tracked)
    beads.db
    issues.jsonl
    config.json
```

In this mode, SDD artifacts are committed alongside code changes via `sase commit`.

The `research/` directory remains top-level. It is not migrated under `sdd/` because research notes are exploratory
inputs, not generated SDD artifacts.

## How SDD Works

### Spec Generation

When an agent completes its planning phase, SDD generates a spec file by:

1. Expanding all `#xprompt` references in the original prompt
2. Stripping `%directives` (`%model`, `%name`, `%wait`, etc.)
3. Dry-expanding embedded workflow `prompt_part` content (renders templates without executing pre/post steps)

The result is a clean, self-contained document showing exactly what the agent was asked to do.

### Plan Persistence

The plan file produced by the agent is:

1. Annotated with a `create_time` frontmatter field
2. Written to the action-specific SDD directory, where `{YYYYMM}` is derived from the current date:
   - normal approval: `sdd/plans/{YYYYMM}/{plan_name}.md`
   - epic approval: `sdd/epics/{YYYYMM}/{plan_name}.md`
   - legend approval: `sdd/legends/{YYYYMM}/{plan_name}.md`

Specs and plans are organized into `YYYYMM` subdirectories (e.g., `202603/`) based on the creation date. This keeps the
directories manageable as the number of specs and plans grows over time. Both flat and `YYYYMM` layouts are supported
for backwards compatibility — SDD searches both when resolving files.

Plan files may also carry a `status` field (set to `done` when work completes) and a `bead_id` field linking to the bead
issue tracker.

After writing the plan, `sase plan` touches `~/.sase/.ace_refresh_pulse` so any running ACE TUI flips the agent into the
`PLANNING` status immediately rather than waiting for the next auto-refresh tick. The pulse file is consumed by the
inotify-based artifact watcher and is harmless when no TUI is open.

### Q&A Sections

If the agent asks clarifying questions during planning (via the `/sase_questions` skill), the Q&A exchange is appended
to the spec file. This preserves the full context of planning decisions.

## Bead Integration

SDD initializes the [bead issue tracker](beads.md) automatically when an epic agent spawns:

- **Local mode**: Beads are stored in `.sase/sdd/beads/`; `.sase/sdd/` is a standalone git repo and bead storage is
  initialized through SASE's built-in bead project bootstrap
- **VC mode**: Beads are stored in `.sase_beads/` at the project root

Plan-like beads carry a `tier` value:

- `plan` for ordinary non-epic implementation plans.
- `epic` for executable multi-phase plans.
- `legend` for higher-level coordination plans.

For larger efforts, epic files carry `bead_id` and `tier: epic` in their frontmatter. Each phase of the epic gets its
own bead whose ID appears in commit messages, creating a traceable chain from epic to phase to commit. Legend files
carry `legend_bead_id` and `tier: legend`; linked epics also include `legend_bead_id`. For smaller plans, commit
messages include a `PLAN=<path>` tag pointing back to the plan file.

Linked epics are created as ordinary plan beads with a legend parent:

```bash
sase bead create --title "<title>" --type plan(sdd/epics/202605/example.md,<legend_bead_id>) --tier epic
```

Legend beads are non-executable containers for now. `sase bead work <id>` accepts epic-tier plan beads, not legends.

When the plan approval flow launches an epic agent, SASE passes the epic-creation xprompt a plan reference that all
workspaces can resolve. In version-controlled mode this is the project-relative `sdd/epics/{YYYYMM}/{name}.md` path. In
local mode it is the primary-workspace-relative `.sase/sdd/epics/{YYYYMM}/{name}.md` path. If an older flat plan layout
is encountered, the resolver still checks both canonical and legacy flat/`YYYYMM` locations for backwards compatibility.

## Configuration

```yaml
sdd:
  version_controlled: false # default
```

| Option                   | Type | Default | Description                                                                       |
| ------------------------ | ---- | ------- | --------------------------------------------------------------------------------- |
| `sdd.version_controlled` | bool | `false` | Store beads in `.sase_beads/` (git-tracked) instead of `.sase/sdd/beads/` (local) |

See [`configuration.md`](configuration.md) for the full configuration reference.

## Multi-Workspace Behavior

SDD always writes to the **primary workspace** (workspace 1). When running in workspace `sase_3`, SDD resolves the
primary workspace directory by stripping the `_3` suffix. This ensures all workspaces share a single set of specs,
plans, and beads.
