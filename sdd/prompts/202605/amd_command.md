---
plan: sdd/epics/202605/amd_command.md
---
 Can you help me add a new `sase amd` command and corresponding `amd_h1_title: <H1 Section Title for AGENTS.md>`
project-local sase.yml configuration field?

- When the `amd_h1_title` field is set (it defaults to null / unset), we should automatically generated the AGENTS.md
  file contents for the current project when the `sase init` command is run.
- We will accomplish this by adding a new `sase amd init` command, which should have a `sase init amd` alias.
- The `sase amd init` command should always (regardless of whether the `amd_h1_title` field is set or not) create all of
  the non-AGENTS.md agent markdown files (ex: CLAUDE.md, GEMINI.md, etc...) using the same practice that this repo does
  (just `@`-reference the AGENTS.md file in these files).
- If `amd_h1_title` is not set, then we should try to migrate any single existing non-AGENTS.md file (ex: if the repo
  just has a CLAUDE.md file) to a AGENTS.md file. The previous non-AGENTS.md file should just `@`-reference the
  AGENTS.md file.
- If `amd_h1_title` is set, then we should use it for the H1 section title in the AGENTS.md file (this repo, for
  example, should have its `amd_h1_title` field set to
  `Structured Agentic Software Engineering (SASE) - Agent Instructions`). Also, we should use a fairly prescriptive
  AGENTS.md file template. It should match the current AGENTS.md file in this repo almost exactly (the short/long-term
  memory file path references are all specific to each repo except for the sase.md file + it might be useful to add some
  sort of tag/marker to make it easier for `sase memory init` to add the necessary bullets / description-list entries to
  the right location). Make sure you verify this by using the `sase ace --tmux` command, emulating user keypresses, and
  then capturing the tmux pane's contents.
- When the `amd_h1_title` field is set, the `sase memory init` should:
  - Ensure that all markdown files in the memory/short/ directory have `@`-references in the AGENTS.md file (add them if
    not).
  - Ensure that all markdown files in the memory/long/ directory have a new `description` field and then use the value
    for those fields to automatically generate the markdown description-list entries (note the need for the two spaces
    after the description-list entry keys) used in the `Tier 3` section. not).
- We should also add a new `sase amd list` command (the `sase amd` command should default to this if no subcommand is
  explicitly given) that provides a nice view of all global/home AGENTS.md files and project-specific AGENTS.md files
  (this includes AGENTS.md files in subdirectories of the current project repo). I want you to lead the design on this one. Just make sure it looks beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

