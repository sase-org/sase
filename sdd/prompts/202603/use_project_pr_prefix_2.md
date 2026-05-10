---
plan: sdd/tales/202603/use_project_pr_prefix_2.md
---
Can you help me add support for a new `use_project_pr_prefix` sase config field that accept a boolean? When true, we
should always make sure to prepend `[<project>] ` to the PR message, where `<project>` is the project name corresponding
with this PR, given when using `sase commit` and the commit method type is "create_pull_request"? We should set this
field to true in the ../retired Mercurial plugin repo's default_config.yml file. Think this through thoroughly and create a plan
using your `/sase_plan` skill before making any file changes.
