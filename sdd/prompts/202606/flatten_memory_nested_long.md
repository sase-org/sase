---
plan: sdd/epics/202606/flatten_memory_nested_long.md
---
 Can you help me flatten sase's memory/ directory while also adding support for nested long-term memory files (e.g. hub
memory note files that link to other memory note files)?

- We can accomplish this by adding a new, required `parent` field to the frontmatter of all memory/ markdown files
  (except for the README in that directory) and a new, required `type` property that has an enum value that can only
  accept values of "short" or "long".
- AGENTS.md files, which should be the value of the `parent` field for short-term and long-term memory files (those that
  are not children of other long-term memories, at least), should continue to be formatted the way that they are now, by
  the `sase amd init` and `sase memory init` commands.
- The `sase memory read` command, however, should start outputting a `## Children` markdown section that contains
  references to all of the long-term memory files that have the current memory file as their parent. Each file reference
  will have a description, taken from the `description` property of the corresponding memory file. This list of
  filename-description pairs should be formatted in the same way that they are in the `Tier 2 (long-term) Memory`
  section of AGENTS.md files.
- Migrate all of this project's memory/ files and all of the ~/.local/share/chezmoi/home/memory/ files (my chezmoi
  repo--so make sure to run the `chezmoi apply --force` command when you are done) to use this new format.
- Once you think that you are done, verify by running `sase init` to confirm that no new changes are recommended.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 