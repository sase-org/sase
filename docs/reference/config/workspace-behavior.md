---
title: "Workspace configuration behavior"
description: "Configuration for workspace directory layout and lifecycle."
---

# Workspace configuration behavior

Configuration for workspace directory layout and lifecycle.

## workspace

Controls how SASE chooses the physical location of managed workspace checkouts. See
[`docs/workspace.md`](../../workspace.md#workspace-directory-layout) for the
directory-layout reference and CLI workflows.

```yaml
workspace:
  root: xdg-state # "xdg-state", "adjacent", or an absolute path
  project_key: "" # explicit project-key override; empty = derive from git remote / primary path
  share_git_objects: true # borrow primary Git objects for numbered managed checkouts
  cleanup_ttl_days: 14 # age threshold for `sase workspace cleanup --stale`
  held_claim_ttl_days: 14 # age threshold for releasing pinned dead workspace claims
```

[Generated reference for `workspace`](repositories.md#workspace)

Platform defaults for the `xdg-state` policy:

| Platform | Managed root                                                                       |
| -------- | ---------------------------------------------------------------------------------- |
| Linux    | `$XDG_STATE_HOME/sase/workspaces` (falls back to `~/.local/state/sase/workspaces`) |
| macOS    | `~/Library/Application Support/sase/workspaces`                                    |
| Windows  | `%LOCALAPPDATA%\sase\workspaces`                                                   |

Numeric identity is the same on every root policy: `#0` is the primary checkout,
`#1`–`#9` are reserved, and managed claim workspaces start at `#10`. See
[`docs/workspace.md`](../../workspace.md#numeric-identity) for the full identity model
and backup/container/NFS caveats.

For non-adjacent policies, physical checkouts live under
`<managed-root>/<project_key>/<project>_<num>/`. For example,
`workspace.root: /mnt/sase-workspaces` with project key `github.com_org_repo` places
workspace `#10` at `/mnt/sase-workspaces/github.com_org_repo/<project>_10/`. When
`SASE_WORKSPACE_ROOT` is set, it supplies the same `<managed-root>` base for the
process.

Existing adjacent checkouts are not moved automatically by the default. Run
`sase workspace migrate --to xdg-state` to carry existing flat `<primary>_<num>/`
directories into the managed root, or set `workspace.root: adjacent` explicitly to keep
the old sibling layout.

`sase repo open <primary-repo> -w NUM -r "<reason>"` is an explicit preparation command
for a checkout you plan to use outside a normal `sase run` launch. It uses the same root
policy when it materializes the checkout, backs up uncommitted local changes through the
active VCS provider, cleans the checkout, checks out and syncs the provider default
parent revision, and prints the resulting path. For manual scratch work, choose a
claim-range number such as `10`; `#0` is the primary checkout and `#1` through `#9` are
reserved compatibility numbers.

Source: `src/sase/default_config.yml`, `src/sase/workspace_provider/store.py`

## Related

- [Repositories and version control configuration](repositories.md) — generated
  workspace keys and defaults.
- [Workspaces](../../workspace.md) — workspace lifecycle.
