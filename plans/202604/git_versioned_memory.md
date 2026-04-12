---
create_time: 2026-04-11 18:49:12
status: wip
---

# Plan: Git-Versioned Agent Memory System

## Problem

Sase agents are stateless across invocations. They can't accumulate project-specific knowledge (conventions, decisions,
pitfalls, feedback) that persists between sessions. This forces repeated context rediscovery and prevents agents from
improving their behavior over time.

## Solution

A dedicated git repository at `~/.sase/memory/` that stores structured memory files per-project, with a two-tier context
model (always-loaded `system/` files vs. on-demand files), a `sase memory` CLI for management, and xprompt-based
injection into agent prompts.

## Architecture

```
~/.sase/memory/                          # Git repository (auto-initialized)
├── .git/
├── global/                              # Cross-project memory
│   ├── system/                          # Always loaded into all prompts
│   │   └── user_preferences.md
│   └── conventions.md                   # Loaded on demand
└── projects/
    ├── sase/                            # Per-project memory
    │   ├── system/                      # Always loaded for this project
    │   │   ├── architecture.md          # Core architectural context
    │   │   └── conventions.md           # Project-specific conventions
    │   ├── decisions/                   # Loaded on demand
    │   │   └── 2026-04_plugin_api.md
    │   └── feedback/                    # Loaded on demand
    │       └── testing_approach.md
    └── webapp/
        └── system/
            └── ...
```

**Memory file format** (YAML frontmatter + markdown body, same as Claude auto-memory):

```markdown
---
name: Testing Approach
description: Prefer integration tests over mocks for DB-touching code
type: feedback
created: 2026-04-11
---

Integration tests must hit a real database, not mocks.

**Why:** Prior incident where mock/prod divergence masked a broken migration.

**How to apply:** Any test that exercises DB queries should use the test database fixture, not unittest.mock.
```

**Two-tier context model:**

- `system/` directories → contents always fully injected into agent prompts
- Everything else → available on-demand (agents can read files when the filetree suggests relevance)

## Phases

### Phase 1: Core Storage & CLI

Implement the `sase memory` subcommand with full CRUD operations and git auto-commit.

**New files:**

- `src/sase/memory/__init__.py` — Package init
- `src/sase/memory/repo.py` — Git repo management (init, commit, status)
- `src/sase/memory/store.py` — Memory file CRUD (add, list, show, rm, update)
- `src/sase/memory/models.py` — Data models (MemoryFile, MemoryType enum)
- `src/sase/main/parser_memory.py` — CLI parser for `sase memory` subcommand
- `src/sase/main/memory_handler.py` — CLI handler dispatching to store operations
- `tests/memory/` — Unit tests

**CLI interface:**

```bash
sase memory init                              # Initialize ~/.sase/memory/ as git repo
sase memory add -p <project> -t <type> <name> # Create memory (reads from stdin or opens $EDITOR)
sase memory add -p <project> -t <type> <name> -m "content"  # Inline content
sase memory show -p <project> <name>          # Display a memory file
sase memory list [-p <project>]               # List memories (all or per-project)
sase memory rm -p <project> <name>            # Remove a memory (with git commit)
sase memory tree [-p <project>]               # Show filetree of memory repo
```

**Key behaviors:**

- `sase memory init` creates `~/.sase/memory/` with `.git/`, `global/system/`, and a README
- All write operations (add, rm) auto-commit with descriptive messages
- Project name defaults to current project (detected from CWD or ChangeSpec context)
- Memory types: `architecture`, `convention`, `decision`, `feedback`, `reference`, `pitfall`
- Files in `system/` are placed there explicitly via `-s`/`--system` flag on add
- Graceful handling when memory repo doesn't exist yet (suggest `sase memory init`)

**Git repo module (`repo.py`) responsibilities:**

- `ensure_repo()` — init if not exists, return repo path
- `auto_commit(message)` — stage all changes in memory repo and commit
- `get_filetree(project)` — return directory tree as string for injection
- `get_system_contents(project)` — return concatenated contents of system/ files

### Phase 2: Prompt Injection

Make memory content available in agent prompts via the xprompt system.

**New/modified files:**

- `src/sase/xprompts/memory.md` — XPrompt part that expands to memory injection
- `src/sase/memory/inject.py` — Logic for assembling injectable memory content
- Modify prompt assembly to optionally auto-inject memory (config-driven)

**Injection mechanism:**

- A `#memory` xprompt that agents (or users) can include in prompts to inject memory
- Expands to: filetree overview + full contents of `system/` files (global + project)
- Optional: auto-injection via config (`memory.auto_inject: true` in sase.yml)

**Injection output format:**

```markdown
## Agent Memory

### Filetree
```

global/ system/ user_preferences.md conventions.md projects/sase/ system/ architecture.md conventions.md decisions/
2026-04_plugin_api.md feedback/ testing_approach.md

```

### System Context (Always Loaded)

#### global/system/user_preferences.md
[full file contents]

#### projects/sase/system/architecture.md
[full file contents]

#### projects/sase/system/conventions.md
[full file contents]
```

**Config additions** (sase.yml `memory:` section):

```yaml
memory:
  auto_inject: false # Whether to inject memory into all prompts automatically
  max_system_tokens: 4000 # Approximate token budget for system/ injection
  repo_path: ~/.sase/memory # Override default repo location
```

### Phase 3: Bootstrap & Initialization

Provide a `sase memory bootstrap` command that seeds initial memory by exploring the codebase.

**New/modified files:**

- `src/sase/memory/bootstrap.py` — Bootstrap logic
- `src/sase/xprompts/memory_bootstrap.yml` — Workflow xprompt for agent-driven bootstrap

**Approach:**

- `sase memory bootstrap [-p <project>]` kicks off an agent run that:
  1. Reads project structure (key files, README, config)
  2. Optionally reviews recent chat history (`~/.sase/chats/`) for recurring patterns
  3. Distills findings into memory files (architecture, conventions, pitfalls)
  4. Commits all generated memories in one batch
- Can use the `#memory_bootstrap` xprompt workflow to drive the agent
- Targets 5-15 initial memory files for a typical project

### Phase 4: Maintenance Operations

Implement reflection (post-run distillation) and defragmentation (periodic reorganization).

**New/modified files:**

- `src/sase/memory/reflect.py` — Post-run reflection logic
- `src/sase/memory/defrag.py` — Memory reorganization logic
- `src/sase/xprompts/memory_reflect.yml` — Reflection workflow
- `src/sase/xprompts/memory_defrag.yml` — Defrag workflow

**Reflection:**

- A post-run hook or explicit `sase memory reflect` command
- Reviews the most recent chat session and extracts learnings
- Adds new memories or updates existing ones
- Avoids duplicating what's already stored

**Defragmentation:**

- `sase memory defrag [-p <project>]` reorganizes memory:
  - Splits large files (> ~50 lines) into focused topics
  - Merges near-duplicate or overlapping memories
  - Removes stale/outdated entries
  - Reorganizes directory structure for clarity
  - Targets 15-25 focused files per project
- Can be run as a lumberjack (periodic axe task)

### Phase 5: Sync & Sharing

Enable cross-machine sync and optional team sharing via git remotes.

**New/modified files:**

- `src/sase/memory/sync.py` — Remote sync operations
- Modify `repo.py` to support remote configuration

**CLI additions:**

```bash
sase memory sync                    # Push/pull from configured remote
sase memory remote add <url>        # Configure remote for memory repo
sase memory remote rm               # Remove remote
```

**Behaviors:**

- `sync` does pull --rebase then push (handles simple conflicts)
- Remote URL stored in memory repo's git config (not sase.yml — portable)
- Merge conflicts surface clearly with instructions for manual resolution
- Optional: team sharing via shared remote (different team members' memories coexist in branches or subdirs)

## Design Decisions

1. **Dedicated repo over in-repo**: Avoids polluting project repos, works for read-only/external projects, enables
   cross-project memory.

2. **Filetree as navigation**: The directory tree itself is the index — no separate MEMORY.md index file needed.
   Directory and file names are the primary discovery mechanism.

3. **Two-tier context (system/ vs. rest)**: Explicit control over what's always loaded vs. on-demand. Prevents context
   bloat while ensuring critical context is always present.

4. **Auto-commit on writes**: Every mutation is a git commit. The repo's sole purpose is memory, so commit noise is
   actually useful history.

5. **XPrompt-based injection**: Leverages existing sase infrastructure rather than inventing a new injection mechanism.
   Agents/users use `#memory` in prompts to pull in context.

6. **Project detection from CWD**: The `-p` flag defaults to the current project name, making the common case
   effortless.

## Risks & Mitigations

| Risk                         | Mitigation                                                                        |
| ---------------------------- | --------------------------------------------------------------------------------- |
| Memory grows unbounded       | Defrag phase keeps count manageable; token budget caps injection size             |
| Stale memory misleads agents | Reflection updates; defrag removes outdated entries; git history enables rollback |
| Bootstrap hallucinates       | Human review step; generated memories are committed (visible in diff)             |
| Concurrent writes conflict   | Each agent instance writes distinct files; git merge handles the rest             |
| Token budget exceeded        | `max_system_tokens` config caps injection; filetree stays small regardless        |
