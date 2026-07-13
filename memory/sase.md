---
type: short
parent: AGENTS.md
---

# SASE = Structured Agentic Software Engineering

## Ephemeral `sase_<N>` Workspace Directories

SASE runs agents (like you) from ephemeral workspace directories, which are full clones of the sase repo. These
directories are named `sase_<N>` where `<N>` is some integer. You need to be mindful not to run commands outside of
these workspace directories, since they have their own isolated virtual environments.

IMPORTANT: Do NOT mention your workspace directory (or any sibling workspace directory) in any plan files that you
generate using your `/sase_plan` skill. The agent(s) that implement the plan might not run in the same workspace
directory as you!

## Linked Repositories

Configured linked repositories for this context:

- `sase-github`: GitHub VCS and workspace provider plugin for repository, issue, and PR workflows.
- `sase-telegram`: Telegram integration plugin for chat-driven SASE workflows and notifications.
- `sase-nvim`: Neovim integration plugin for SASE syntax, completion, and editor support.
- `sase--research`: Durable SASE research reports and generated media.

When you need to make changes to files in a numbered-workspace linked repo or need to review numbered-workspace linked
repo code, agents MUST run:

```bash
sase repo open <linked_repo> -r "<reason>"
```

Run it from your workspace directory (the workspace number is inferred from where you run it; pass `-w <workspace_num>`
only when running from outside the workspace). Use the path printed by `sase repo open` as the only linked repo path for
numbered-workspace linked reads/writes.

IMPORTANT REMINDER: Do NOT attempt to look for a linked repo in any other way than by using `sase repo open`!
