---
type: short
parent: AGENTS.md
---

# Glossary of Terms Specific to SASE

**Agent Clan**  
An agent clan is a named, rootless container for agents that run in parallel. Every
member is named inside the clan's hood (`<clan>.<suffix>`) and declares `%clan:<clan>`;
the clan name is reserved and is never itself an agent.

**Agent Family**  
An agent family is a strictly sequential chain whose members use `<family>--<suffix>`
names. The first `%n(parent, suffix)` attachment renames the original agent with its own
suffix and reserves the bare family name as a pure container, so a family always has at
least two members.

**Agent Hoods**  
An agent hood is a group of agents that are all named with the same `<name>.` prefix.
For example, agents named `foo.bar`, `foo.baz`, and `foo.bar.1` are all apart of the
same `foo` agent hood. The agent `foo`, if it exists, is also considered part of the
`foo` agent hood.

**Agent Lane**  
An agent lane is a term that describes either an agent family or a single agent that
does not belong to a family. Agent lanes never have a name that ends with `--<suffix>`
since that suffix is reserved for family members. We think of an agent lane like an
agent's house (i.e. where they live). When agent's are single, they live in their own
lane. When a new member joins their family (which can only happen once the original
agent completes, since agents in agent lanes run sequentially), that member moves into
the same lane. At that point, the lane and the family share a name instead of the lane
and the original agent, which is renamed with its own `--<suffix>`.

**Agent Instruction Files (aka agents.md files)**  
An agent instruction file is a `.md` file that an agent CLI reads automatically when
working in a directory that contains it. For example, the `AGENTS.md` file is the name
of the agent instruction file that is supported by codex. sase supports one agent
instruction file per supported agent CLI (ex: `CLAUDE.md` for claude, `GEMINI.md` for
antigravity, etc...). The `sase init` command, which is run automatically as a sase
post-commit hook, initializes the top-level agent instruction files using memories in
the sase/memory/ directory and ensures that all agent instruction files in the same
directory contain the same contents.

**Agent Neighbors**  
An agent neighbor is any agent that is in the same agent hood as another agent. For
example, agents named `foo`, `foo.baz`, and `foo.bar.1` are all neighbors of each other
because they are all in the same `foo` agent hood.

**Agent Tribe**  
An agent tribe is a user-facing label for related agents across clans and families.
Tribes are assigned with `%tribe:<name>` (alias `%t`), managed with `sase agent tribe`,
and displayed with an `@` prefix.

**ChangeSpec**  
Represents a single CL/PR. Active specs live in ProjectSpec `<key>.sase` (directory key
`<key>`; see Projects, Repos, and Workspaces); terminal ones (Submitted, Archived,
Reverted) in `<key>-archive.sase`. Sections: NAME, DESCRIPTION, PARENT, CL/PR, STATUS,
COMMITS, HOOKS, COMMENTS, MENTORS. Status lifecycle: WIP → Draft → Ready → Mailed →
Submitted.

**Projects, Repos, and Workspaces**  
A **project** is a named unit of work registered with SASE. A project is created only
when a new VCS xprompt argument resolves to a valid project: `#git:<name>` accepts any
valid project name, while `#gh:<org>/<repo>` requires an existing GitHub repository. Its
ProjectSpec is `~/.sase/projects/<key>/<key>.sase`, where the directory key `<key>` is
`<name>` for `#git` projects but `gh_<org>__<repo>` for `#gh` projects (ex:
`gh_sase-org__sase`); the user-facing name is the spec's `PROJECT_NAME:` (ex: `sase`)
or, if unset, the key. Projects have exactly two user-facing states, enabled and
disabled; missing `PROJECT_STATE:` means enabled, and only an explicit disable changes
that. The system-managed `home` project remains hidden. A **repo** is any repository
SASE knows: a project's primary repo, an SDD sidecar repo (`<project>--plans` or
`<project>--research`), or a repo declared through `linked_repos:`. Workspace
directories are not repos. A **workspace** is a numbered clone of a project's primary
repo, managed by the workspace store and tracked in that project's `registry.json`. Each
SASE agent claims exactly one workspace until completion. Linked-repo clones
materialized for a workspace are repo checkouts, not additional workspaces.

**xprompt**  
Triggered with `#foo` in agent prompts. Defined in a sase/xprompts/ directory (.md or
.yml file) or in ~/.config/sase/sase.yml (`xprompts` field).

**xprompt Part**  
.md file → single `prompt_part` step with the file's content.

**xprompt Swarm**  
An xprompt whose body contains top-level `---` segment separators outside fenced blocks
and fans out into one agent per segment at launch. Literal user prompts can also use
`---`, but those are generic multi-agent prompts rather than xprompt swarms.

**xprompt Workflow**  
.yml file → multiple steps (`prompt_part`, `python`, `bash`, etc.).
