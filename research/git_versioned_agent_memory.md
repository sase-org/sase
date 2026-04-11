# Git-Versioned Agent Memory System: Research & Recommendation

## Goal

Design a project-specific agent memory system for sase that:

1. Enables agents to accumulate knowledge across sessions (cross-invocation persistence)
2. Stores memory per-project so that context is scoped to the work being done
3. Uses git for versioning so that memory has history, can be shared, and can be rolled back
4. Integrates naturally with sase's existing infrastructure (xprompts, config layers, workflows)

## Current State

Sase currently has **no cross-invocation memory** for agents. Each agent run is stateless beyond what it can derive
from:

- The codebase itself (files, git history)
- ChangeSpec state (`~/.sase/projects/{project}/{project}.gp`)
- Chat history files (`~/.sase/chats/`) which are conversation logs, not distilled knowledge
- Runtime-specific memory (e.g., Claude Code's `~/.claude/` auto-memory, which is per-runtime and not portable)

The mentor redesign research already identified this gap: "Each mentor run is stateless; no learning from prior runs on
the same CL or codebase." The Reflexion paper (Shinn et al.) showed that episodic memory across attempts significantly
improves agent performance.

### Relevant Existing Patterns

| System             | Storage                             | Versioned?       | Scope         | Cross-run?          |
| ------------------ | ----------------------------------- | ---------------- | ------------- | ------------------- |
| ChangeSpec         | `~/.sase/projects/`                 | No (plain files) | Per-project   | Yes                 |
| Chat history       | `~/.sase/chats/`                    | No               | Per-session   | No (read-only logs) |
| Workflow state     | `artifacts_dir/workflow_state.json` | No               | Per-execution | No                  |
| Marker files       | `~/.sase/projects/{project}/`       | No               | Per-project   | Yes (manual)        |
| Claude auto-memory | `~/.claude/projects/`               | No               | Per-runtime   | Yes                 |
| SDD specs/plans    | `specs/` or `~/.sase/sdd/`          | Optional         | Per-project   | N/A                 |

## Requirements

1. **Project-scoped**: Memory must be keyed to a specific project
2. **Git-versioned**: Changes to memory should be tracked with full history
3. **Agent-writable**: Agents must be able to create/update memories during runs
4. **Prompt-injectable**: Memory content must be easily included in agent prompts
5. **Curate-able**: Humans (and agents) must be able to prune, edit, and reorganize memories
6. **Runtime-agnostic**: Must work across Claude, Gemini, Codex (not tied to one runtime's memory format)
7. **Shareable**: Team members should be able to benefit from shared memory (optional)

## Design Alternatives

### Alternative 1: In-Repo Memory Directory

Store memory as markdown files in a `.sase/memory/` directory within the project repository itself.

```
my-project/
├── .sase/
│   └── memory/
│       ├── MEMORY.md           # Index file
│       ├── architecture.md     # How the system is structured
│       ├── conventions.md      # Project conventions agents should follow
│       ├── decisions.md        # Key decisions and their rationale
│       └── pitfalls.md         # Known gotchas and workarounds
└── src/
    └── ...
```

Memory files committed alongside code, appearing in PRs and code review.

**Pros:**

- Simplest possible approach -- just files in git
- Memory is code-reviewed alongside the code it describes
- Automatically shared with anyone who clones the repo
- No additional infrastructure or tooling required
- Natural for "project conventions" type memory (like CLAUDE.md but richer)
- Git blame shows who added each memory and when

**Cons:**

- Pollutes the project repo with agent-specific files
- Memory changes create noise in diffs/PRs (every agent run that learns something creates a commit)
- Not suitable for per-user or per-agent memory (only shared/project-level)
- Doesn't handle ephemeral or personal observations well
- Requires the project repo to accept sase-specific files (not always possible for external repos)
- Conflicts with existing patterns like CLAUDE.md, AGENTS.md which already serve a similar role

### Alternative 2: Dedicated Memory Git Repository

Create a separate git repository at `~/.sase/memory/` (or per-project at `~/.sase/projects/{project}/memory/`) that
stores all agent memories.

```
~/.sase/memory/
├── .git/
├── projects/
│   ├── sase/
│   │   ├── MEMORY.md
│   │   ├── architecture.md
│   │   ├── feedback_testing.md
│   │   └── decisions/
│   │       └── 2026-04_plugin_api_v2.md
│   ├── webapp/
│   │   ├── MEMORY.md
│   │   └── ...
│   └── ...
└── global/
    ├── MEMORY.md
    └── user_preferences.md
```

A single git repo holds all project memories, organized by project name.

**Pros:**

- Clean separation from project code -- no pollution of project repos
- Single repo makes backup/sync trivial (push to a remote)
- Supports both project-scoped and global/cross-project memory
- Full git history for all memory changes
- Can be shared across machines via git remote
- Can evolve independently of the project's git history
- Works even for projects where you can't commit to the repo (external, read-only)

**Cons:**

- Additional git repo to manage (commits, pushes, potential conflicts)
- Not automatically shared with team (requires explicit remote setup)
- Memory is disconnected from the code it describes (no co-location)
- Need tooling to auto-commit (otherwise memory accumulates as dirty state)
- Risk of unbounded growth without pruning discipline
- Slightly more complex to bootstrap (need to `git init` on first use)

### Alternative 3: Git Branch-Based Memory

Store memory on a dedicated orphan branch (e.g., `sase/memory`) within the project repo.

```
# On branch: sase/memory (orphan, no shared history with main)
memory/
├── MEMORY.md
├── architecture.md
├── feedback/
│   ├── testing_approach.md
│   └── pr_style.md
└── decisions/
    └── 2026-04_migration_strategy.md
```

The memory branch never gets merged into main -- it exists in parallel.

**Pros:**

- Lives in the project repo but doesn't pollute main branch history
- Shared automatically when the repo is cloned/fetched
- Full git versioning with isolated history
- Can be pushed/pulled like any branch
- No extra repos to manage

**Cons:**

- Orphan branches are a lesser-known git pattern -- confusing for contributors
- CI/CD systems may try to build or lint the memory branch
- `git clone` fetches it by default (adds overhead)
- Awkward to read/write (requires branch switching or worktree)
- Risk of accidental deletion during branch cleanup
- Harder to include memory content in agent prompts (need to `git show` from another branch)
- Doesn't support cross-project memory

### Alternative 4: Git Notes

Use `git notes` to attach memory metadata to commits in the project repo.

```bash
# Attach a memory note to the current HEAD
git notes --ref=sase/memory add -m "Architecture: the auth module was redesigned in this commit..."

# Read memory notes
git notes --ref=sase/memory show HEAD
git log --notes=sase/memory
```

**Pros:**

- Native git feature, no extra repos or branches
- Memory is attached to specific commits (temporal anchoring)
- Notes can be pushed/fetched via refspecs
- Lightweight -- no file tree management

**Cons:**

- Notes are per-commit, not per-project -- awkward for persistent knowledge
- No file-based organization (just blobs of text on commits)
- Not portable across repos
- Tooling support is poor (most git UIs ignore notes)
- Hard to curate or reorganize
- Can't represent structured memory (categories, types, relationships)
- Rebase/squash destroys note associations
- Not suitable for "always-on" context (would need to aggregate all notes for prompt injection)

### Alternative 5: Hybrid Local + Git Sync

Memory accumulates as local files at `~/.sase/projects/{project}/memory/`, with periodic git-based sync for sharing and
versioning.

```
~/.sase/projects/sase/
├── sase.gp                    # ChangeSpecs (existing)
├── memory/
│   ├── MEMORY.md              # Index
│   ├── architecture.md        # Distilled knowledge
│   ├── feedback.md            # Agent behavior guidance
│   └── .git/                  # Local git repo for versioning
└── memory_staging/
    └── raw_observations.jsonl  # Unprocessed agent observations
```

Two-phase approach:

1. **Accumulate**: Agents append raw observations to a staging area (fast, no git overhead)
2. **Distill**: A periodic workflow (or manual step) processes raw observations into curated memory files and commits to
   the local git repo
3. **Sync**: Optional push to a remote for sharing/backup

**Pros:**

- Separates fast writes (agent observations) from expensive operations (git commits)
- Distillation step ensures memory quality (not just raw dumps)
- Can be automated via axe lumberjacks (periodic distillation runs)
- Git versioning without per-observation commit overhead
- Staging area handles the "agents write a lot of noise" problem
- Natural integration with existing `~/.sase/projects/` structure
- Per-project git repos allow different sharing strategies per project

**Cons:**

- Most complex to implement (two-phase pipeline)
- Distillation adds latency between observation and usable memory
- Raw observations need TTL/cleanup to prevent unbounded growth
- More moving parts to debug when things go wrong
- Need to handle the case where distillation agent hallucinates or corrupts memory

### Alternative 6: Memory as ChangeSpec Extension

Extend the existing ChangeSpec system to include memory sections, keeping memory co-located with the work it relates to.

```
# In ~/.sase/projects/sase/sase.gp
---
NAME: fix_auth_race_condition
STATUS: WIP
COMMITS:
  abc123: Fix race condition in token refresh
MEMORY:
  - The auth module uses a dual-lock pattern (file lock + advisory lock)
  - Token refresh must complete within 30s or the session expires
  - Previous attempt to fix this (CL/xyz) was reverted due to deadlock
---
```

**Pros:**

- Leverages existing ChangeSpec infrastructure (parsing, locking, archival)
- Memory is naturally scoped to a unit of work
- Archived when the ChangeSpec is archived (automatic lifecycle)
- No new storage locations or repos to manage

**Cons:**

- ChangeSpec-scoped memory dies when the CL is submitted (lost with archival)
- No place for project-wide or long-lived memory
- Overloads the ChangeSpec format (already has many sections)
- Not git-versioned (ChangeSpec files are plain files at `~/.sase/`)
- Doesn't support cross-CL knowledge transfer
- Fundamentally wrong abstraction level for persistent memory

## Comparison Matrix

| Criterion                | In-Repo | Dedicated Repo | Branch  | Git Notes | Hybrid | CS Extension |
| ------------------------ | ------- | -------------- | ------- | --------- | ------ | ------------ |
| Project-scoped           | Yes     | Yes            | Yes     | Partial   | Yes    | CL-scoped    |
| Git-versioned            | Yes     | Yes            | Yes     | Yes       | Yes    | No           |
| Agent-writable           | Easy    | Easy           | Hard    | Medium    | Easy   | Easy         |
| Prompt-injectable        | Easy    | Easy           | Hard    | Hard      | Easy   | Easy         |
| Curate-able              | Easy    | Easy           | Medium  | Hard      | Easy   | Medium       |
| Runtime-agnostic         | Yes     | Yes            | Yes     | Yes       | Yes    | Yes          |
| Shareable                | Auto    | Manual         | Auto    | Manual    | Manual | No           |
| No repo pollution        | No      | Yes            | Partial | Yes       | Yes    | Yes          |
| Cross-project            | No      | Yes            | No      | No        | Yes    | No           |
| Low complexity           | High    | Medium         | Medium  | Medium    | Low    | High         |
| Works for external repos | No      | Yes            | No      | Yes       | Yes    | Yes          |

## Prior Art

### Claude Code Auto-Memory

Claude Code's built-in memory system (at `~/.claude/projects/`) provides a useful reference:

- **Index file** (`MEMORY.md`) with one-line pointers to individual memory files
- **Typed memories** (user, feedback, project, reference) with YAML frontmatter
- **Automatically loaded** -- MEMORY.md is always in context, individual files loaded on demand
- **File-per-memory** -- enables targeted updates without rewriting everything
- **Not git-versioned** -- no history, no sharing, no rollback

This works well for a single user on a single machine but doesn't scale to team sharing or provide the audit trail that
git versioning enables.

### Letta Context Repositories

Letta's [Context Repositories](https://www.letta.com/blog/context-repositories) represent a mature implementation of
git-backed agent memory that validates many of our design goals and introduces several patterns worth adopting.

**Core idea**: Agents store context as files in a local git repository, using their full terminal and coding
capabilities (including scripts and subagents) to manage memory -- not just read/write individual files.

**Key design patterns**:

1. **Filesystem-first**: Files are "simple, universal primitives that both humans and agents can work with using
   familiar tools." Agents chain standard Unix tools (`grep`, `find`, bash scripts) for complex memory queries rather
   than relying on specialized memory APIs.

2. **Progressive disclosure via filetree**: The directory tree is always included in the system prompt, with folder
   hierarchy and filenames acting as "navigational signals." Agents decide what to read deeper based on the tree
   structure. Frontmatter descriptions on each file control what gets pinned to context.

3. **`system/` always-loaded directory**: Files in a `system/` directory are always fully loaded into the system prompt.
   Other files are available but only loaded on demand. This creates an explicit two-tier context model.

4. **Git worktrees for concurrency**: "Multiple subagents can process and write to memory concurrently, then merge their
   changes back through git-based conflict resolution." Each subagent gets an isolated worktree, preventing blocking on
   memory writes.

5. **Three maintenance operations**:
   - **Initialization**: Bootstraps memory by "exploring the codebase and reviewing historical conversation data" using
     concurrent subagents in git worktrees
   - **Reflection**: A "sleep-time" background process that "periodically reviews recent conversation history and
     persists important information" with informative commits
   - **Defragmentation**: Addresses long-horizon disorganization by "reorganizing files, splitting large files, merging
     duplicates" into 15-25 focused files

6. **Self-organizing memory**: Agents can restructure their own memory -- moving files between directories, updating
   frontmatter, splitting/merging -- which means the memory organization improves over time without manual curation.

**Relevance to sase**: Letta's approach strongly validates Alternative 2 (Dedicated Memory Git Repository) and adds
concrete patterns we should adopt. Their `system/` directory maps to always-injected prompt context. Their worktree
concurrency pattern is directly relevant since sase already uses ephemeral workspace directories. Their three
maintenance operations (init/reflect/defrag) map to our implementation phases but with more actionable structure.

## Recommendation: Dedicated Memory Git Repository (Alternative 2)

**Alternative 2 (Dedicated Memory Git Repository)** best satisfies the requirements while maintaining reasonable
implementation complexity. Here's why:

### Rationale

1. **Cleanest separation of concerns**: Memory is a distinct concept from code. Storing it in its own repo avoids
   polluting project repos and works universally (including for projects where you can't commit, like read-only
   dependencies or external repos you contribute to).

2. **Natural fit with sase's architecture**: Sase already organizes per-project state under
   `~/.sase/projects/{project}/`. A memory git repo at `~/.sase/memory/` (with per-project subdirectories) extends this
   pattern without disrupting existing workflows.

3. **Right level of git overhead**: Unlike the hybrid approach, a dedicated repo can commit on every memory write
   without being "too noisy" -- the repo's entire purpose is memory, so every commit is meaningful. Unlike in-repo
   storage, these commits don't clutter code review.

4. **Sharing flexibility**: Push to a private remote for cross-machine sync. Share a remote with teammates for
   collaborative memory. Or keep it purely local. The choice is per-user, not baked into the project.

5. **Compatible with existing runtimes**: Agents already read files and can be instructed to write them. A `sase memory`
   CLI subcommand can handle the git commit step, making memory writes a simple two-step process (write file, run
   `sase memory commit`).

6. **Graceful upgrade from Claude auto-memory**: The format (MEMORY.md index + individual typed files with frontmatter)
   is already proven. Sase can adopt the same format while adding git versioning on top.

### Design Principles (Informed by Letta)

1. **Filesystem-first**: Memory is just files. Agents use familiar tools (`grep`, `cat`, directory traversal) to query
   memory rather than learning a specialized memory API. This keeps the system runtime-agnostic.

2. **Progressive disclosure**: The filetree structure is always visible in agent prompts, acting as a navigational
   index. Agents decide what to read deeper based on directory names and file names. This reduces the load of a separate
   index file and makes the memory self-documenting.

3. **Two-tier context**: A `system/` directory contains files that are always fully loaded into agent prompts.
   Everything else is available on demand. This gives agents (and users) explicit control over what context is always
   present vs. what requires a deliberate lookup.

4. **Self-organizing**: Agents are encouraged to restructure memory -- renaming files, reorganizing directories,
   updating frontmatter -- so memory quality improves over time without requiring manual curation.

### Proposed Architecture

```
~/.sase/memory/                          # Git repository
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
        ├── system/
        │   └── ...
        └── ...
```

**Filetree injection**: The full directory tree (names only, not contents) is always included in agent prompts. This
acts as a navigational index -- agents see what memories exist and can read specific files as needed. The `system/`
directories' contents are loaded in full. This replaces the need for a separate `MEMORY.md` index file, though one can
optionally be maintained for backward compatibility or for richer annotations.

### Proposed CLI Interface

```bash
sase memory init                         # Initialize ~/.sase/memory/ as git repo
sase memory add -p sase -t feedback      # Create a new memory (opens editor or accepts stdin)
sase memory list -p sase                 # List memories for a project
sase memory show -p sase architecture    # Display a memory
sase memory rm -p sase old_decision      # Remove a memory
sase memory sync                         # Push/pull from remote
sase memory inject -p sase              # Output memory content for prompt injection
```

### Integration Points

- **Prompt injection**: The project's filetree is always included in agent system prompts (similar to how CLAUDE.md and
  AGENTS.md are loaded today). Files in `system/` directories are loaded in full. Other files are available for agents
  to read on demand.
- **Agent writes**: Agents write files directly to the memory repo and run `sase memory commit` to persist. A post-run
  hook could auto-commit uncommitted memory changes.
- **Concurrent access**: When multiple agents (e.g., subagents) need to write memory simultaneously, use git worktrees
  to give each agent an isolated copy. Merge back via standard git operations. This aligns with sase's existing
  ephemeral workspace directory pattern.
- **Axe integration**: A lumberjack could periodically review and prune stale memories (see Phase 4 defragmentation).
- **Config**: `sase.yml` gains a `memory:` section for remote URL, auto-commit behavior, and injection preferences.

### Implementation Phases

1. **Phase 1 -- Core storage**: `sase memory init` bootstraps `~/.sase/memory/` as a git repo. Basic CRUD operations
   (add, list, show, rm) with git auto-commit on writes. Support `system/` and non-system directories.
2. **Phase 2 -- Prompt injection**: Automatically inject the filetree + `system/` file contents into agent prompts.
   Integrate with sase's existing prompt assembly pipeline.
3. **Phase 3 -- Memory initialization**: A `sase memory bootstrap` command that explores the codebase and optionally
   reviews historical conversation data (from `~/.sase/chats/`) to seed initial memory. Can use concurrent subagents for
   larger projects (inspired by Letta's init pattern).
4. **Phase 4 -- Reflection and defragmentation**: Automated memory maintenance:
   - **Reflection**: Post-run hook or lumberjack that reviews recent conversation history and persists important
     information into memory (distillation from chat logs to structured knowledge).
   - **Defragmentation**: Periodic reorganization that splits large files, merges duplicates, removes stale entries, and
     keeps the total file count manageable (target: 15-25 focused files per project).
5. **Phase 5 -- Sync and sharing**: Remote push/pull for cross-machine sync. Optional team sharing via shared remotes.
