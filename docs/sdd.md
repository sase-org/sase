# Spec-Driven Development (SDD)

SDD is sase's system for persisting the intent behind agent work. When an agent produces a plan, SDD captures both the
fully-expanded prompt (the **spec**) and the structured plan itself, creating a traceable chain from intent to
execution.

## Why SDD Exists

Agent plans are ephemeral by default -- they live in a single session's context window and vanish when the session ends.
SDD fixes this by writing specs and plans to disk as first-class artifacts:

- **Specs** record the full expanded prompt the agent received, so the "why" behind the work is preserved.
- **Plans** record the structured plan the agent produced, so decomposition decisions are queryable after the fact.
- **Beads** provide structured issue tracking that links plans to execution via epic and phase IDs in commit messages.

Together, these create an audit trail: spec --> plan --> bead epic --> phase beads --> commits.

## Storage Modes

SDD supports two storage modes controlled by the `sdd.version_controlled` config option.

### Local Mode (default: `sdd.version_controlled: false`)

Files are stored in a standalone git repo inside the primary workspace:

```
{primary_workspace}/.sase/sdd/
  .git/                     # Standalone git repo for SDD tracking
  .gitignore                # Ignores beads.db
  specs/
    {plan_name}.md          # Expanded prompt (xprompts resolved, directives stripped)
  plans/
    {plan_name}.md          # Formatted plan with create_time frontmatter
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
  .sase_beads/              # Bead database (git-tracked)
    beads.db
    issues.jsonl
    config.json
  specs/
    {plan_name}.md
  plans/
    {plan_name}.md
```

In this mode, specs and plans are committed alongside code changes via `sase commit`.

## How SDD Works

### Spec Generation

When an agent completes its planning phase, SDD generates a spec file by:

1. Expanding all `#xprompt` references in the original prompt
2. Stripping `%directives` (`%model`, `%name`, `%wait`, etc.)
3. Dry-expanding embedded workflow `prompt_part` content (renders templates without executing pre/post steps)

The result is a clean, self-contained document showing exactly what the agent was asked to do.

### Plan Persistence

The plan file produced by the agent is:

1. Formatted with prettier for consistent markdown
2. Annotated with a `create_time` frontmatter field
3. Written to `plans/{plan_name}.md`

Plan files may also carry a `status` field (set to `done` when work completes) and a `bead_id` field linking to the bead
issue tracker.

### Q&A Sections

If the agent asks clarifying questions during planning (via the `/sase_questions` skill), the Q&A exchange is appended
to the spec file. This preserves the full context of planning decisions.

## Bead Integration

SDD initializes the [bead issue tracker](beads.md) automatically when an epic agent spawns:

- **Local mode**: Beads are stored in `.sase/sdd/beads/` and initialized via `git init` + `bd init`
- **VC mode**: Beads are stored in `.sase_beads/` at the project root

For larger efforts, plan files carry a `bead_id` in their frontmatter that links to an epic in the bead tracker. Each
phase of the epic gets its own bead whose ID appears in commit messages, creating a traceable chain from epic to phase
to commit. For smaller plans, commit messages include a `PLAN=<path>` tag pointing back to the plan file.

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
