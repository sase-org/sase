# SASE Memory

## Sibling Repositories

Configured sibling repositories for this context:

- `core`: Shared Rust core backend for SASE domain behavior and cross-frontend APIs.
- `github`: GitHub VCS and workspace provider plugin for repository, issue, and PR workflows.
- `telegram`: Telegram integration plugin for chat-driven SASE workflows and notifications.
- `nvim`: Neovim integration plugin for SASE syntax, completion, and editor support.

When a sibling repository needs changes, agents MUST run:

```bash
sase workspace open -p <sibling_repo> <workspace_num>
```

`<workspace_num>` must be the workspace number assigned to the primary repo. Use the path printed by
`sase workspace open` as the only repository path for sibling edits.
