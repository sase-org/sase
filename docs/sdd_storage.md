# SDD Storage

The workspace provider owns SDD placement. Use `sase sdd path` when you need the effective root for the current project:

```bash
sase sdd path
sase sdd path research
sase sdd path research --ensure
```

`sase sdd path` is a read-only resolver unless `-e/--ensure` is passed. `--ensure` clones or synchronizes the companion
that backs the selected kind. Launched agents receive `SASE_SDD_DIR` plus `SASE_SDD_PLANS_DIR`, `SASE_SDD_RESEARCH_DIR`,
and `SASE_SDD_BEADS_DIR`.

## Resolved Layouts

| Resolved layout   | Plans root                     | Meaning                                                                                  |
| ----------------- | ------------------------------ | ---------------------------------------------------------------------------------------- |
| `in_tree`         | `{workspace}/sdd`              | The code repository. Built-in bare-git projects use this provider policy.                |
| `separate_repo`   | `{workspace}/.sase/sdd`        | One provider companion. This is GitHub's declared policy and the recorded legacy layout. |
| `companion_repos` | `{workspace}/sase/repos/plans` | A recorded two-repository layout created by managed GitHub initialization.               |
| `local`           | `{primary}/.sase/sdd`          | A primary-workspace fallback for providerless projects or providers with no SDD policy.  |

Provider policy and resolved layout are related but different. A GitHub provider declares `separate_repo`; explicit
initialization resolves that requirement into two companions and records `companion_repos`. The latter is a materialized
store-record value, not another provider policy. Before initialization, or for an unmigrated legacy record, GitHub still
resolves as `separate_repo`.

A positive materialized-store record at `{primary}/.sase/sdd-store.json` is authoritative, including while offline. Old
negative records are not policy and are retried at the next materialization attempt.

## Split Plans and Research Companions

Newly initialized managed GitHub projects and migrated projects use a schema-version 2 store record with
`storage: companion_repos`. The record identifies both the plans and research repositories and their remotes. That
record—not clone or remote existence—is the layout authority. Legacy records continue to use the single-root layout
unchanged.

The plans companion keeps monthly directories at its root (`<YYYYMM>/*.md` and `<YYYYMM>/prompts/*.md`) with `beads/`
beside them. The research companion likewise keeps `<YYYYMM>/` directories at its root. Kind resolution is therefore:

| Kind       | Migrated path                        |
| ---------- | ------------------------------------ |
| `plans`    | `<workspace>/sase/repos/plans`       |
| `beads`    | `<workspace>/sase/repos/plans/beads` |
| `research` | `<workspace>/sase/repos/research`    |

Initialization clones, initializes, and pushes both repositories in the workspace where it runs. After that, normal
workspace preparation automatically clones and synchronizes plans; a newly prepared workspace does not clone research
until a consumer runs `sase sdd path research --ensure` (or another operation explicitly ensures that kind). Each
clone's `origin` is the real companion remote, and refresh uses pull-with-rebase semantics.

The retired `sdd.storage` and `sdd.version_controlled` configuration keys no longer select a mode. SASE ignores and
strips them before schema validation, and `sase doctor` reports where to remove them. This keeps old configuration files
loadable without allowing project or user config to override provider policy.

## GitHub Companion Repositories

Managed GitHub projects initialize two public companions: `<owner>/<repo>--plans` and `<owner>/<repo>--research`. Both
are prepared by initialization in the current workspace. In later workspaces, the plans clone is automatic and owns bead
state, while research materializes on demand. The provider still supports `<owner>/<repo>--sdd` discovery and
`sdd.repo.name` overrides for unmigrated legacy stores.

Set `is_sase_managed: true` in the repository's own `sase.yml`, then run `sase sdd init` to create or connect the
provider store and refresh generated SDD guides. Without that local marker, explicit init and `--check` skip before
provider work. The `#gh` setup step also materializes the companion before claiming and launching work. Authentication,
authorization, network, discovery, creation, label, clone, import, or initial-push failures stop setup; GitHub projects
do not fall back to local storage.

Explicit `sase sdd init` (including `sase init sdd` and bare-onboarding dispatch) probes GitHub before materialization.
If the companion is absent, creation requires a fresh interactive `y`/`yes` response to a prompt naming its host,
repository, and public visibility; the default is no. Non-interactive input and `sase init --yes` cannot grant this
resource-specific authorization. Existing companions and non-explicit materialization consumers retain their normal
provider-owned behavior.

Split initialization is a single record-last transaction:

1. SASE serializes setup and preflights both public repository names.
2. The provider creates or adopts each repository and SASE clones it at the linked-repository location.
3. SASE writes deterministic per-repository README and infographic assets, then commits and pushes generated drift.
4. Only after both repositories succeed does SASE write the schema-version 2 split store record.

Initialization does not import legacy artifacts. Use this order for a project with an existing `.sase/sdd/` or `sdd/`
tree:

```bash
sase sdd init                  # create/adopt and record the split companions
sase sdd migrate --check --diff # preview; exit 1 means migration work remains
sase sdd migrate               # copy, push, then retire the selected local source
```

Migration copies only monthly `plans/<YYYYMM>/` and `research/<YYYYMM>/` content plus durable `beads/` files. It
rewrites legacy plan-link prefixes and excludes `beads.db*`. README files, assets, non-month directories, and other
legacy files are not copied. After both companion pushes succeed, the command removes the selected local legacy source
tree; its Git history remains in any existing remote. Inspect the preview and confirm that remote or make a backup
before applying. A failed transaction leaves the source tree in place.

## Reads, Writes, and Offline Use

Directory-only consumers resolve paths without network or filesystem writes. Operations that write SDD data—such as
prompt export, bead initialization and mutation, and link repair with `--write`—materialize a provider-required store
first and fail if it cannot be made usable.

Once a positive record and primary clone exist, reads and numbered-workspace cloning can work offline from the primary
clone. Refresh pulls are best effort. Separate-repository commits remain local if an ordinary follow-up push fails so
they can be inspected and pushed manually; only the initial adoption push is transactional.

`sdd.push_after_commit` controls pushes after later SDD commits: `async` starts a detached background push, `true`
pushes synchronously, and `false` skips the push.
