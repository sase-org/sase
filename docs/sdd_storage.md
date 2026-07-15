# SDD Storage

The workspace provider owns SDD placement. Resolve project-owned storage through repository roles:

```bash
sase repo path plans
sase repo path research
sase repo path research --ensure
```

`sase repo path` is read-only unless `-e/--ensure` is passed. `--ensure` clones or synchronizes the selected sidecar.
Launched agents receive `SASE_SDD_DIR` plus `SASE_SDD_PLANS_DIR`, `SASE_SDD_RESEARCH_DIR`, and `SASE_SDD_BEADS_DIR`;
beads live at `${SASE_SDD_PLANS_DIR}/beads` in split layouts.

## Resolved Layouts

| Resolved layout | Plans root                     | Meaning                                                                                 |
| --------------- | ------------------------------ | --------------------------------------------------------------------------------------- |
| `in_tree`       | `{workspace}/sdd`              | The code repository. Built-in bare-git projects use this provider policy.               |
| `separate_repo` | `{workspace}/.sase/sdd`        | One provider sidecar. This is GitHub's declared policy and the recorded legacy layout.  |
| `sidecar_repos` | `{workspace}/sase/repos/plans` | A recorded split layout created by managed GitHub initialization.                       |
| `local`         | `{primary}/.sase/sdd`          | A primary-workspace fallback for providerless projects or providers with no SDD policy. |

Provider policy and resolved layout are related but different. A GitHub provider declares `separate_repo`; explicit
initialization resolves that requirement into configured sidecars and records `sidecar_repos`. The latter is a
materialized store-record value, not another provider policy. Before initialization, or for an unmigrated legacy record,
GitHub still resolves as `separate_repo`.

A positive materialized-store record at `{primary}/.sase/sdd-store.json` is authoritative, including while offline. Old
negative records are not policy and are retried at the next materialization attempt.

## Split Plans and Research Sidecars

Initialized managed GitHub projects use a schema-version 2 store record with `storage: sidecar_repos`. For
compatibility, the record identifies the plans and research roles and their resolved remotes; an explicit `repo:` pin
can point the research role at any repository. That record—not clone or remote existence—is the layout authority. Legacy
records continue to use the single-root layout unchanged.

The plans sidecar keeps monthly directories at its root (`<YYYYMM>/*.md` and `<YYYYMM>/prompts/*.md`) with `beads/`
beside them. The research sidecar likewise keeps `<YYYYMM>/` directories at its root. Kind resolution is therefore:

| Kind       | Resolved path                        |
| ---------- | ------------------------------------ |
| `plans`    | `<workspace>/sase/repos/plans`       |
| `beads`    | `<workspace>/sase/repos/plans/beads` |
| `research` | `<workspace>/sase/repos/research`    |

Initialization clones, initializes, and pushes every configured sidecar in the workspace where it runs. After that,
normal workspace preparation automatically clones and synchronizes plans; a newly prepared workspace does not clone
research until a consumer runs `sase repo path research --ensure` (or another operation explicitly ensures that kind).
Each clone's `origin` is the configured sidecar remote, and refresh uses pull-with-rebase semantics.

The retired `sdd.storage` and `sdd.version_controlled` configuration keys no longer select a mode. SASE ignores and
strips them before schema validation, and `sase doctor` reports where to remove them. This keeps old configuration files
loadable without allowing project or user config to override provider policy.

## GitHub Sidecar Repositories

Managed GitHub projects initialize public `<owner>/<repo>--plans` and `<owner>/<repo>--research` sidecars by default,
writing both project-local `repos.sidecar` declarations when absent. Additional sidecars are declared under
`repos.sidecar`, and any entry can pin `repo:` to override the derived `<owner>/<repo>--<name>` convention. Configured
sidecars are prepared by initialization in the current workspace. In later workspaces, the plans clone is automatic and
owns bead state, while research materializes on demand. The provider still supports `<owner>/<repo>--sdd` discovery and
`sdd.repo.name` overrides for unmigrated legacy stores.

Set `is_sase_managed: true` in the repository's own `sase.yml`, then run `sase repo init` to create or connect the
provider store and refresh generated SDD guides. Without that local marker, explicit init and `--check` skip before
provider work. The `#gh` setup step also materializes the sidecar before claiming and launching work. Authentication,
authorization, network, discovery, creation, label, clone, import, or initial-push failures stop setup; GitHub projects
do not fall back to local storage.

Explicit `sase repo init` (including `sase init repo` and bare-onboarding dispatch) probes GitHub before
materialization. If the sidecar is absent, creation requires a fresh interactive `y`/`yes` response to a prompt naming
its host, repository, and public visibility; the default is no. Non-interactive input and `sase init --yes` cannot grant
this resource-specific authorization. Existing sidecars and non-explicit materialization consumers retain their normal
provider-owned behavior.

Split initialization is a single record-last transaction:

1. SASE serializes setup and preflights every enabled configured sidecar repository.
2. The provider creates or adopts each repository and SASE clones it at the linked-repository location.
3. SASE writes deterministic per-repository README and infographic assets, then commits and pushes generated drift.
4. Only after the configured compatibility roles succeed does SASE write the schema-version 2 split store record.

## Reads, Writes, and Offline Use

Directory-only consumers resolve paths without network or filesystem writes. Operations that write SDD data—such as
prompt export, bead initialization and mutation, and link repair with `--write`—materialize a provider-required store
first and fail if it cannot be made usable.

Once a positive record and primary clone exist, reads and numbered-workspace cloning can work offline from the primary
clone. Refresh pulls are best effort. Separate-repository commits remain local if an ordinary follow-up push fails so
they can be inspected and pushed manually; only the initial adoption push is transactional.

`sdd.push_after_commit` controls pushes after later SDD commits: `async` starts a detached background push, `true`
pushes synchronously, and `false` skips the push.
