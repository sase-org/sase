---
type: long
parent: AGENTS.md
description: |-
  Read this note before relying on any of these SASE glossary terms and aliases:

  - Agent Clan
  - Agent Family
  - Agent Hood (aka hood, agent neighborhood)
  - Agent Lane
  - Agent Instruction File (aka agents.md file)
  - Agent Neighbor
  - Agent Tribe
  - Artifact Reference (aka ref)
  - Patch
  - Sase Project (aka project)
  - Sase Repo (aka repo)
  - Sase Workspace (aka workspace)
  - Stitch
  - Xprompt
  - Xprompt Memory (aka memory file)
  - Xprompt Part
  - Xprompt Swarm
  - Xprompt Workflow

  Read it with `sase memory read glossary.md` whenever one of those terms or aliases appears in a prompt, bead, plan, or code comment and you are not certain what it means in SASE.
sase_generated: glossary
---

# Glossary of Terms

## Agent Clan

An agent clan is a named, rootless container for agents that run in parallel. Every
member is named inside the clan's hood (`<clan>.<suffix>`) and declares `%clan:<clan>`;
the clan name is reserved and is never itself an agent.

## Agent Family

An agent family is a strictly sequential chain whose members use `<family>--<suffix>`
names. The first `%id(parent, suffix)` attachment renames the original agent with its
own suffix and reserves the bare family name as a pure container, so a family always has
at least two members.

## Agent Hood

ALIASES: hood, agent neighborhood

An agent hood is a group of agents that are all named with the same `<name>.` prefix.
For example, agents named `foo.bar`, `foo.baz`, and `foo.bar.1` are all apart of the
same `foo` agent hood. The agent `foo`, if it exists, is also considered part of the
`foo` agent hood.

## Agent Lane

An agent lane is a term that describes either an agent family or a single agent that
does not belong to a family. Agent lanes never have a name that ends with `--<suffix>`
since that suffix is reserved for family members. We think of an agent lane like an
agent's house (i.e. where they live). When agent's are single, they live in their own
lane. When a new member joins their family (which can only happen once the original
agent completes, since agents in agent lanes run sequentially), that member moves into
the same lane. At that point, the lane and the family share a name instead of the lane
and the original agent, which is renamed with its own `--<suffix>`.

## Agent Instruction File

ALIASES: agents.md file

An agent instruction file is a `.md` file that an agent CLI reads automatically when
working in a directory that contains it. For example, the `AGENTS.md` file is the name
of the agent instruction file that is supported by codex. sase supports one agent
instruction file per supported agent CLI (ex: `CLAUDE.md` for claude, `GEMINI.md` for
antigravity, etc...). The `sase init` command, which is run automatically as a sase
post-commit hook, initializes the top-level agent instruction files using memories in
the sase/memory/ directory and ensures that all agent instruction files in the same
directory contain the same contents.

## Agent Neighbor

An agent neighbor is any agent that is in the same agent hood as another agent. For
example, agents named `foo`, `foo.baz`, and `foo.bar.1` are all neighbors of each other
because they are all in the same `foo` agent hood.

## Agent Tribe

An agent tribe is a user-facing label for related agents across clans and families.
Assign a tribe at launch with `%id(tribe=<tribe>)` or `#tribe:<tribe>` for an auto-named
agent, `%id(<id>, tribe=<tribe>)` for an explicitly named agent, or
`%clan(<clan>, tribe=<tribe>)` for a clan. Tribes can also be managed after launch with
`sase agent tribe` and are displayed with an `@` prefix.

## Artifact Reference

ALIASES: ref

An artifact reference (ref) is a typed `@<kind>:<argument>` citation in an agent prompt.
Builtin kinds are `@stitch`, `@patch`, `@bead`, `@agent`, and the special `@file`;
artifact repos add document kinds such as `@plan` and `@research` through a project's
`ref:` config, written inline or with `use: <provider>` from an installed provider
plugin. Every ref expands to prompt text, is recorded against the agent that used it,
and publishes as a `[@kind:arg][N]` link.

## Patch

A Patch is SASE's local unit of change. Every PR created or managed by SASE is
associated with exactly one Patch, but a Patch may exist without a PR, represented by an
absent `PR:` field. Active Patches live in ProjectSpec `<key>.sase` (directory key
`<key>`; see Project, Repo, and Workspace); terminal ones (Submitted, Archived,
Reverted) live in `<key>-archive.sase`. Sections: NAME, DESCRIPTION, PARENT, PR, STATUS,
STITCHES, HOOKS, COMMENTS, MENTORS. Status lifecycle: WIP -> Draft -> Ready -> Mailed ->
Submitted.

## Sase Project

ALIASES: project

A sase project is a named unit of work registered with SASE. A project is created only
when a new VCS xprompt argument resolves to a valid project: `#git:<name>` accepts any
valid project name, while `#gh:<org>/<repo>` requires an existing GitHub repository. Its
ProjectSpec is `~/.sase/projects/<key>/<key>.sase`, where the directory key `<key>` is
`<name>` for `#git` projects but `gh_<org>__<repo>` for `#gh` projects (ex:
`gh_sase-org__sase`); the user-facing name is the spec's `PROJECT_NAME:` (ex: `sase`)
or, if unset, the key. Projects have exactly two user-facing states, enabled and
disabled; missing `PROJECT_STATE:` means enabled, and only an explicit disable changes
that. The system-managed `home` project remains hidden.

## Sase Repo

ALIASES: repo

A sase repo is any repository SASE knows: a project's primary repo, an artifact sidecar
repo such as `<project>--plans` or `<project>--research`, or a repo declared through
`repos.linked`.

## Sase Workspace

ALIASES: workspace

A sase workspace is a numbered clone of a project's primary repo, managed by the
workspace store and tracked in that project's `registry.json`. Each SASE agent claims
exactly one workspace until completion. Workspace directories are not repos. Linked-repo
clones materialized for a workspace are repo checkouts, not additional workspaces.

## Stitch

A stitch is the lightweight ordered change record inside a Patch's `STITCHES:` section.
Every VCS commit made through the tracked workflow has an associated numeric stitch, but
a stitch need not have a commit: proposals retain numeric-plus-letter IDs such as
`(2a)`. The `sase commit` command and real Git/Mercurial commits are still called
commits.

## Xprompt

Triggered with `#foo` in agent prompts. Defined in a sase/xprompts/ directory (.md or
.yml file) or in ~/.config/sase/sase.yml (`xprompts` field).

## Xprompt Memory

ALIASES: memory file

A flat SASE memory note exposed as a namespaced xprompt: `sase/memory/foo.md` expands
with `#memory/foo`, and the `memory/` prefix is required.

## Xprompt Part

.md file -> single `prompt_part` step with the file's content.

## Xprompt Swarm

An xprompt whose body contains top-level `---` segment separators outside fenced blocks
and fans out into one agent per segment at launch. Literal user prompts can also use
`---`, but those are generic multi-agent prompts rather than xprompt swarms.

## Xprompt Workflow

.yml file -> multiple steps (`prompt_part`, `python`, `bash`, etc.).
