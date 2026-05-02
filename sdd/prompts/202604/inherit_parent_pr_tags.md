---
plan: sdd/tales/202604/inherit_parent_pr_tags.md
---
Can you help me make it so that when `sase commit` creates a new PR, we re-use all of the PR tags found in the parent PR
(if there is a parent PR) description? For example, if a PR has a `FOO=bar` tag in its description and we use the
`sase commit` command to create a new PR that is a child of the first, then the `FOO=bar` PR tag should be added to the
new PR description too. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any
file changes.
