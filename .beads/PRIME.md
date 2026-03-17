# Beads Workflow Context

> **Context Recovery**: Run `.venv/bin/sase bead prime` after compaction, clear, or new session Hooks auto-call this in
> Claude Code when .beads/ detected

> **Important**: Always use `.venv/bin/sase bead` instead of `bd` directly.

# Session Close Protocol

Before wrapping up, run `.venv/bin/sase bead sync` to ensure beads data is flushed to JSONL.

**Do NOT commit or push code changes.** The stop hook handles commit prompting — it runs quality checks and then asks
you to use the `/commit` skill if there are uncommitted changes.

## Core Rules

- **Default**: Use beads for ALL task tracking (`.venv/bin/sase bead create`, `.venv/bin/sase bead ready`,
  `.venv/bin/sase bead close`)
- **Prohibited**: Do NOT use TodoWrite, TaskCreate, or markdown files for task tracking
- **Workflow**: Create beads issue BEFORE writing code, mark in_progress when starting
- Persistence you don't need beats lost context
- Git workflow: hooks auto-sync, run `.venv/bin/sase bead sync` at session end
- Session management: check `.venv/bin/sase bead ready` for available work

## Essential Commands

### Finding Work

- `.venv/bin/sase bead ready` - Show issues ready to work (no blockers)
- `.venv/bin/sase bead list --status=open` - All open issues
- `.venv/bin/sase bead list --status=in_progress` - Your active work
- `.venv/bin/sase bead show <id>` - Detailed issue view with dependencies

### Creating & Updating

- `.venv/bin/sase bead create --title="..." --type=task|bug|feature --priority=2` - New issue
  - Priority: 0-4 or P0-P4 (0=critical, 2=medium, 4=backlog). NOT "high"/"medium"/"low"
- `.venv/bin/sase bead update <id> --status=in_progress` - Claim work
- `.venv/bin/sase bead update <id> --assignee=username` - Assign to someone
- `.venv/bin/sase bead update <id> --title/--description/--notes/--design` - Update fields inline
- `.venv/bin/sase bead close <id>` - Mark complete
- `.venv/bin/sase bead close <id1> <id2> ...` - Close multiple issues at once (more efficient)
- `.venv/bin/sase bead close <id> --reason="explanation"` - Close with reason
- **Tip**: When creating multiple issues/tasks/epics, use parallel subagents for efficiency
- **WARNING**: Do NOT use `.venv/bin/sase bead edit` - it opens $EDITOR (vim/nano) which blocks agents

### Dependencies & Blocking

- `.venv/bin/sase bead dep add <issue> <depends-on>` - Add dependency (issue depends on depends-on)
- `.venv/bin/sase bead blocked` - Show all blocked issues
- `.venv/bin/sase bead show <id>` - See what's blocking/blocked by this issue

### Sync & Collaboration

- `.venv/bin/sase bead sync` - Sync with git remote (run at session end)
- `.venv/bin/sase bead sync --status` - Check sync status without syncing

### Project Health

- `.venv/bin/sase bead stats` - Project statistics (open/closed/blocked counts)
- `.venv/bin/sase bead doctor` - Check for issues (sync problems, missing hooks)

## Common Workflows

**Starting work:**

```bash
.venv/bin/sase bead ready           # Find available work
.venv/bin/sase bead show <id>       # Review issue details
.venv/bin/sase bead update <id> --status=in_progress  # Claim it
```

**Completing work:**

```bash
.venv/bin/sase bead close <id1> <id2> ...    # Close all completed issues at once
.venv/bin/sase bead sync                     # Push to remote
```

**Creating dependent work:**

```bash
# Run .venv/bin/sase bead create commands in parallel (use subagents for many items)
.venv/bin/sase bead create --title="Implement feature X" --type=feature
.venv/bin/sase bead create --title="Write tests for X" --type=task
.venv/bin/sase bead dep add beads-yyy beads-xxx  # Tests depend on Feature (Feature blocks tests)
```
