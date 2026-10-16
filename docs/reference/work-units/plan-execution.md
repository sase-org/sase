---
title: Plan configuration
description: Configuration and multi-workspace behavior for SASE plan execution.
---

# Plan configuration

This page describes settings and workspace behavior that affect plan execution.

## Configuration

```yaml
sdd:
  bead_refresh:
    mode: background
    ttl_seconds: 120
  repo:
    name: "" # optional sidecar repo override for providers that support it
  push_after_commit: async
```

| Option                         | Type        | Default      | Description                                                                                                                                                                                                                                                  |
| ------------------------------ | ----------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sdd.bead_refresh.mode`        | string      | `background` | `background` launches TTL-gated command refreshes, `blocking` pulls before commands, and `off` disables remote refreshes, including the axe bead-wait refresh job and the refresh step in the waiting runner's fallback. Local dependency rechecks continue. |
| `sdd.bead_refresh.ttl_seconds` | float       | `120`        | Minimum seconds between successful command-triggered background integrations.                                                                                                                                                                                |
| `sdd.repo.name`                | string      | `""`         | Optional sidecar repo override for providers that support `separate_repo`; accepts `name` or `owner/name`. For GitHub, empty checks only `<owner>/<repo>--sdd`; set `sdd.repo.name` to use another repo such as `sdd` or `owner/sdd`.                        |
| `sdd.push_after_commit`        | bool/string | `async`      | Sidecar-repository push behavior after SDD commits: `async`, `true`, or `false`.                                                                                                                                                                             |

Storage selection is not configurable. The workspace provider owns it. Retired
`sdd.storage` and `sdd.version_controlled` keys are ignored and reported by
`sase doctor` for cleanup.

See the [configuration reference](../config/index.md) for configuration keys and
[SDD Storage](../../contribute/sdd-storage.md) for mode behavior.

## Multi-Workspace Behavior

SDD artifact placement follows provider policy. With `in_tree`, bead commands use the
current checkout's `sdd/beads/` store. With `separate_repo`, commands first require a
usable provider sidecar and then use the active workspace's `.sase/sdd/` clone. With
`sidecar_repos`, each workspace auto-clones `--plans` at `sase/repos/plans`; schema-3
records materialize `--beads` at `sase/repos/beads` on demand, in `sase bead` and in the
agent-launch bead claim, while schema-2 records keep bead state under
`sase/repos/plans/beads`. Initialization also prepares every configured document sidecar
at `sase/repos/<role>` in its current workspace; other workspaces clone lazy roles,
including beads, when explicitly ensured. Providerless local storage uses the primary
workspace. Numbered sibling stores are not merged; coordinate shared state through the
normal VCS sync path. Prefer `sase repo path plans`, `sase repo path beads`,
`sase repo path <document-role>`, or the `SASE_SDD_*_DIR` variables over hard-coded
relative paths. Numbered-workspace sidecar clones borrow Git objects from the primary
workspace's clone of the same sidecar when one exists; see
[Network Git Operations](../../contribute/sdd-storage.md#network-git-operations) for
clone retries and timeouts.

## Related

- [Plans](plans.md)
- [Plan commands](plan-cli.md)
