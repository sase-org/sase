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

## Provider Policy

| Provider policy   | Root                                   | Repository                                                                                      |
| ----------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `in_tree`         | `{workspace}/sdd`                      | The code repository. Built-in bare-git projects use this policy.                                |
| `separate_repo`   | `{workspace}/.sase/sdd`                | A required provider companion repository. GitHub projects use this policy.                      |
| `companion_repos` | `{workspace}/sase/repos/<repo>--plans` | A migrated two-repository store; the bare root is the plans clone.                              |
| no policy         | `{primary}/.sase/sdd`                  | A primary-workspace local store for providerless projects or providers with no SDD declaration. |

A positive materialized-store record at `{primary}/.sase/sdd-store.json` is authoritative, including while offline. Old
negative records are not policy and are retried at the next materialization attempt.

## Split Plans and Research Companions

Migrated projects use a schema-version 2 store record with `storage: companion_repos`. The record identifies both the
plans and research repositories and their remotes. That record—not clone or remote existence—is the migration authority.
Legacy records continue to use the single-root layout unchanged.

The plans companion keeps monthly directories at its root (`<YYYYMM>/*.md` and `<YYYYMM>/prompts/*.md`) with `beads/`
beside them. The research companion likewise keeps `<YYYYMM>/` directories at its root. Kind resolution is therefore:

| Kind       | Migrated path                                |
| ---------- | -------------------------------------------- |
| `plans`    | `<workspace>/sase/repos/<repo>--plans`       |
| `beads`    | `<workspace>/sase/repos/<repo>--plans/beads` |
| `research` | `<workspace>/sase/repos/<repo>--research`    |

The plans clone is synchronized during normal workspace preparation. Research remains lazy until a consumer runs
`sase sdd path research --ensure` (or another operation explicitly ensures that kind). Each clone's `origin` is the real
companion remote, and refresh uses pull-with-rebase semantics.

The retired `sdd.storage` and `sdd.version_controlled` configuration keys no longer select a mode. SASE ignores and
strips them before schema validation, and `sase doctor` reports where to remove them. This keeps old configuration files
loadable without allowing project or user config to override provider policy.

## GitHub Companion Repositories

GitHub projects require a companion repository. By default sase-github finds or creates `<owner>/<repo>--sdd`, labels it
`sase--sdd`, and clones it beneath each active workspace at `.sase/sdd`. New companions are public by default; existing
private companions are left private. Set `sdd.repo.name` to `name` or `owner/name` only when an explicit companion
repository override is needed.

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

The first successful materialization is a single adoption transaction:

1. SASE serializes setup with a primary-workspace lock and asks the provider to find or create the companion.
2. The provider clones into a unique staging directory.
3. SASE preflights and copies durable artifacts from legacy primary/current-workspace `sdd/` and `.sase/sdd/` stores.
4. Conflicting paths abort with an explicit path list before any source is replaced.
5. SASE initializes guides and beads, commits imported content, and requires the initial push to succeed when a commit
   was created.
6. Only then does it atomically adopt the primary clone, write the positive store record, and create the active
   workspace clone.

In-tree legacy sources are retained. Bead SQLite runtime files and git internals are not imported. A failed transaction
leaves no positive record, so the next write retries materialization instead of silently using another store.

## Reads, Writes, and Offline Use

Directory-only consumers resolve paths without network or filesystem writes. Operations that write SDD data—such as
prompt export, bead initialization and mutation, and link repair with `--write`—materialize a provider-required store
first and fail if it cannot be made usable.

Once a positive record and primary clone exist, reads and numbered-workspace cloning can work offline from the primary
clone. Refresh pulls are best effort. Separate-repository commits remain local if an ordinary follow-up push fails so
they can be inspected and pushed manually; only the initial adoption push is transactional.

`sdd.push_after_commit` controls pushes after later SDD commits: `async` starts a detached background push, `true`
pushes synchronously, and `false` skips the push.
