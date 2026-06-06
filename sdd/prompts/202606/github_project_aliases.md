---
plan: sdd/epics/202606/github_project_aliases.md
---
 I've been thinking about how to support GitHub projects that have the same project name but live in different
organizations for a while now. Currently this is not possible because we treat `#gh:foo` as `#gh:foo-org/foo` after the
first time `#gh:foo-org/foo` is used in a sase agent prompt. We recently added support for project aliases though, and
I'm thinking these can solve our issue! Can you help me implement this solution by automatically creating the
appropriate project alias for GitHub projects when they are first used to replicate the current behavior? This new
solution should check for duplicate project names first and if any are found should use `<name>_<N>` for the project
alias instead of `<name>`, where `<N>` is the smallest positive integer such that the project name `<name>-<N>` is
available (ex: we should use `foo-2` for the project alias instead of `foo` if `foo` is already taken by some
`bar-org/foo` project).

There are likely some architecture changes that need to happen in order to implement this. Think about this hard and use
your best judgement. This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

