# Beads Workflow Context

> **Context Recovery**: Run `sase_bd prime` after compaction, clear, or new session Hooks auto-call this in Claude Code
> when .beads/ detected

> **Important**: Always use `sase_bd` (at `tools/sase_bd`) instead of `bd` directly.

# Session Close Protocol

Before wrapping up, run `sase_bd sync` to ensure beads data is flushed to JSONL.

**Do NOT commit or push code changes.** The stop hook handles commit prompting — it runs quality checks and then asks
you to use the `/commit` skill if there are uncommitted changes.

## Core Rules

- **Default**: Use beads for ALL task tracking (`sase_bd create`, `sase_bd ready`, `sase_bd close`)
- **Prohibited**: Do NOT use TodoWrite, TaskCreate, or markdown files for task tracking
- **Workflow**: Create beads issue BEFORE writing code, mark in_progress when starting
- Persistence you don't need beats lost context
- Git workflow: hooks auto-sync, run `sase_bd sync` at session end
- Session management: check `sase_bd ready` for available work

## Essential Commands

### Finding Work

- `sase_bd ready` - Show issues ready to work (no blockers)
- `sase_bd list --status=open` - All open issues
- `sase_bd list --status=in_progress` - Your active work
- `sase_bd show <id>` - Detailed issue view with dependencies

### Creating & Updating

- `sase_bd create --title="..." --type=task|bug|feature --priority=2` - New issue
  - Priority: 0-4 or P0-P4 (0=critical, 2=medium, 4=backlog). NOT "high"/"medium"/"low"
- `sase_bd update <id> --status=in_progress` - Claim work
- `sase_bd update <id> --assignee=username` - Assign to someone
- `sase_bd update <id> --title/--description/--notes/--design` - Update fields inline
- `sase_bd close <id>` - Mark complete
- `sase_bd close <id1> <id2> ...` - Close multiple issues at once (more efficient)
- `sase_bd close <id> --reason="explanation"` - Close with reason
- **Tip**: When creating multiple issues/tasks/epics, use parallel subagents for efficiency
- **WARNING**: Do NOT use `sase_bd edit` - it opens $EDITOR (vim/nano) which blocks agents

### Dependencies & Blocking

- `sase_bd dep add <issue> <depends-on>` - Add dependency (issue depends on depends-on)
- `sase_bd blocked` - Show all blocked issues
- `sase_bd show <id>` - See what's blocking/blocked by this issue

### Sync & Collaboration

- `sase_bd sync` - Sync with git remote (run at session end)
- `sase_bd sync --status` - Check sync status without syncing

### Project Health

- `sase_bd stats` - Project statistics (open/closed/blocked counts)
- `sase_bd doctor` - Check for issues (sync problems, missing hooks)

## Common Workflows

**Starting work:**

```bash
sase_bd ready           # Find available work
sase_bd show <id>       # Review issue details
sase_bd update <id> --status=in_progress  # Claim it
```

**Completing work:**

```bash
sase_bd close <id1> <id2> ...    # Close all completed issues at once
sase_bd sync                     # Push to remote
```

**Creating dependent work:**

```bash
# Run sase_bd create commands in parallel (use subagents for many items)
sase_bd create --title="Implement feature X" --type=feature
sase_bd create --title="Write tests for X" --type=task
sase_bd dep add beads-yyy beads-xxx  # Tests depend on Feature (Feature blocks tests)
```
