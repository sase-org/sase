---
plan: sdd/epics/202606/version_command.md
---
 Can you help me create a new `sase version` command that shows the version of sase, sase-core, and any other
installed sase plugins (ex: sase-github, sase-telegram)?

- This command should show the versions of each of these packages as well as the directory that contains the Python /
  Rust code that is being used by `sase` for that package.
- See the recent `sase-4e` epic bead for context on the semantic versions that will be used for release.
- You should also use a good syntax for developer versions of packages (e.g. if I am using a version of sase-github that
  is two commits ahead of version v0.2.3, you want the version number that you show to reflect that somehow).
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

