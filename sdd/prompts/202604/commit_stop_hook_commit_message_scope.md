---
plan: sdd/tales/202604/commit_stop_hook_commit_message_scope.md
---
Can you help me change the sase*commit_stop_hook script so that, when the commit type is anything but
"create_pull_request", we instruct the agent to construct a commit message (when using their
`/sase*\*\_commit`skill) that describes their changes only? I've been having a problem with some agents using a commit message that describes the entire pull request in these cases. Think this through thoroughly and create a plan using your`/sase_plan`
skill before making any file changes.
