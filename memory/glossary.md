---
type: short
parent: AGENTS.md
---

# Glossary of Terms Specific to SASE

**Agent Family**  
A `<name>` agent family refers to a group of agents that are all named with the same `<name>` prefix separated from the
rest of its name by `--`. For example, agents named `foo--plan-0`, `foo--plan-1`, and `foo--code` are all apart of the
same `foo` agent family. Agent families are all grouped under the same root agent/workflow entry in the "Agents" tab of
the `sase ace` TUI.

**Agent Hoods**  
An agent hood is a group of agents that are all named with the same `<name>.` prefix. For example, agents named
`foo.bar`, `foo.baz`, and `foo.bar.1` are all apart of the same `foo` agent hood. The agent `foo`, if it exists, is also
considered part of the `foo` agent hood.

**Agent Neighbors**  
An agent neighbor is any agent that is in the same agent hood as another agent. For example, agents named `foo`,
`foo.baz`, and `foo.bar.1` are all neighbors of each other because they are all in the same `foo` agent hood.

**ChangeSpec**  
Represents a single CL/PR. Stored in `.gp` files at `~/.sase/projects/<project>/`. Sections: NAME, DESCRIPTION, PARENT,
CL/PR, STATUS, COMMITS, HOOKS, COMMENTS, MENTORS. Active specs in `<project>.gp`; terminal ones (Submitted, Archived,
Reverted) in `<project>-archive.gp`. Status lifecycle: WIP → Draft → Ready → Mailed → Submitted.

**VCS Repo Completion**  
Completion mode for repository names inside registered VCS workflow refs after the namespace slash. For example,
`#gh:bbugyi200/` asks the owning workspace plugin for repositories under `bbugyi200`; accepting a row rewrites only the
ref value, such as `#gh:bbugyi200/sase ` or `#gh(bbugyi200/sase)`.

**Child Agent/Workflow Step Entry**  
Any agent row entry on the "Agents" tab of the `sase ace` TUI that is a child of some root agent/workflow entry.
Workflow entries can have python/bash children as well as agent children. Agents root entries can only have (one or
more) agent child entries. Child entries are not visible by default; the `h` and `l` keymaps are used to hide and reveal
them, respectively.

**Multi-agent xprompt**  
An xprompt whose body contains `---` segment separators (outside fenced blocks). Normal user prompts can also use `---`
to create multi-agent prompts (i.e. prompts that result in the prompt being split in order to launch one agent for each
part of the prompt).

**Root Agent/Workflow Entry**  
Any agent row entry on the "Agents" tab of the `sase ace` TUI that has child entries.

**xprompt**  
Triggered with `#foo` in agent prompts. Defined in an xprompts/ directory (.md or .yml file) or in
~/.config/sase/sase.yml (`xprompts` field).

**xprompt Part**  
.md file → single `prompt_part` step with the file's content.

**xprompt Workflow**  
.yml file → multiple steps (`prompt_part`, `python`, `bash`, etc.).
