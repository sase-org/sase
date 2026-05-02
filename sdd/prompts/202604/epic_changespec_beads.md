---
plan: sdd/epics/202604/epic_changespec_beads.md
---
 Can you help me add support for attatching a ChangeSpec name to a sase epic bead?

- When this is done, our epic integration should have special behavior: We should start the first phase bead using the
  normal VCS xprompt (of the form `#<vcs>:<project>`, but it should also have the `#pr:<changespec_name>` embedded in
  its prompt. Every other phase bead (and the "land" bead) should have `#<vcs>:<changespec_name>` embedded in its prompt
  instead of `#<vcs>:<project>`.
- We will need to update the `#bd/new_epic` xprompt to accept an optional `changespec` input and an optional `bug_id`
  input (only valid when `changespec` is also provided--passed to `#pr` if provided).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

