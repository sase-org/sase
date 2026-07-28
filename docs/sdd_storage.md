# SDD Storage

The workspace provider owns SDD placement. Resolve project-owned storage through repository roles:

```bash
sase repo path plans
sase repo path research
sase repo path beads
sase repo path research --ensure
```

`sase repo path` is read-only unless `-e/--ensure` is passed. `--ensure` clones or synchronizes the selected sidecar.
Launched agents receive `SASE_SDD_DIR` plus `SASE_SDD_PLANS_DIR`, `SASE_SDD_RESEARCH_DIR`, and `SASE_SDD_BEADS_DIR`. In
split layouts, `SASE_SDD_BEADS_DIR` is the dedicated beads sidecar root once a project records one, and
`${SASE_SDD_PLANS_DIR}/beads` for a project that has not been migrated yet.

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

## Split Plans, Research, and Beads Sidecars

Initialized managed GitHub projects use a store record with `storage: sidecar_repos`. For compatibility, the record
identifies the plans and research roles and their resolved remotes; an explicit `repo:` pin can point the research role
at any repository. That record—not clone or remote existence—is the layout authority. Legacy records continue to use the
single-root layout unchanged.

The record also carries an **optional** `beads` sidecar, and its presence selects the schema version:

| Schema version | `sidecars.beads` | Bead state resolves to               |
| -------------- | ---------------- | ------------------------------------ |
| 3              | recorded         | `<workspace>/sase/repos/beads`       |
| 2              | absent           | `<workspace>/sase/repos/plans/beads` |

The schema version is derived from content, not blanket-bumped: a project that has not adopted a beads sidecar keeps
writing a schema-2 record and resolving bead state inside the plans clone exactly as before. A `beads` entry is rejected
below schema version 3, and a schema-3 record is rejected by an older `sase` install with the usual "upgrade sase"
error—so the new build must be installed on every machine that touches a project before that project is migrated.

The plans sidecar keeps monthly directories at its root (`<YYYYMM>/*.md` and `<YYYYMM>/prompts/*.md`). The research
sidecar likewise keeps `<YYYYMM>/` directories at its root. The beads sidecar keeps bead state at its **repository
root**—`config.json`, `metadata.json`, `issues.jsonl`, and `events/`—plus generated bead pages under `pages/`, so its
clone root is itself the bead directory. Kind resolution is therefore:

| Kind       | Resolved path                                                      |
| ---------- | ------------------------------------------------------------------ |
| `plans`    | `<workspace>/sase/repos/plans`                                     |
| `research` | `<workspace>/sase/repos/research`                                  |
| `beads`    | `<workspace>/sase/repos/beads` (schema 2: `.../repos/plans/beads`) |

Once a project is migrated, the plans clone no longer owns bead state; its bead history stays behind only as an archive.
Because the cooperative write lock and repository-health preflight are keyed on the repository root, bead writes and
plan writes no longer contend, and a wedged bead rebase no longer blocks plan commits or epic approval.

`sase bead` materializes the beads sidecar on demand: when the store record names one and `sase/repos/beads` is missing
or has a mismatched origin, the command clones it before reading or writing, and reports an error naming the repository
and remote if that clone cannot be made usable. A project with a schema-2 record clones nothing extra. Because a beads
sidecar is injected into the default linked-repo set for every managed project, but the remote only exists after
adoption, the beads role is reported with `auto_clone: true` only once the store record actually names it; before that
it is inventory-visible but never materialized.

Initialization clones, initializes, and pushes every configured sidecar in the workspace where it runs. After that,
normal numbered-workspace preparation evicts the complete `sase/repos/` tree and clones plans—and, for a migrated
project, beads—directly from their recorded remotes. A newly prepared workspace does not clone research until a consumer
runs `sase repo path research --ensure` (or another operation explicitly ensures that kind). GitHub HTTPS values in
legacy records resolve in memory to canonical SSH (`git@host:owner/repo.git`, or `ssh://git@host:port/owner/repo.git`)
before inventory, launch, retained-clone synchronization, or on-demand materialization consumes them. Each clone's
`origin` is that resolved SSH or local remote; a retained matching HTTPS clone is rewritten in place without losing
local state. Other HTTP(S) values fail before Git executes. This read-time normalization does not rewrite
`.sase/sdd-store.json`; rerun `sase repo init` to persist the migration, but launches are safe without doing so.
Pull-with-rebase applies when synchronizing a retained existing clone; a sidecar freshly cloned for launch is used
without a redundant pull or rebase.

The retired `sdd.storage` and `sdd.version_controlled` configuration keys no longer select a mode. SASE ignores and
strips them before schema validation, and `sase doctor` reports where to remove them. This keeps old configuration files
loadable without allowing project or user config to override provider policy.

## GitHub Sidecar Repositories

Managed GitHub projects initialize public `<owner>/<repo>--plans`, `<owner>/<repo>--research`, and
`<owner>/<repo>--beads` sidecars by default, writing their project-local `repos.sidecar` declarations when absent.
Additional sidecars are declared under `repos.sidecar`, and any entry can pin `repo:` to override the derived
`<owner>/<repo>--<name>` convention. Configured sidecars are prepared by initialization in the current workspace. In
later workspaces, the plans and recorded beads clones are automatic, while research materializes on demand. The provider
still supports `<owner>/<repo>--sdd` discovery and `sdd.repo.name` overrides for unmigrated legacy stores.

Set `is_sase_managed: true` in the repository's own `sase/sase.yml`, then run `sase repo init` to create or connect the
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
3. SASE writes deterministic per-repository README and infographic assets, then commits and pushes generated drift. The
   beads clone is seeded with a root-level `beads.db*` ignore rule; an un-migrated plans clone keeps its
   `beads/`-prefixed one.
4. SASE adopts any bead state still living in the plans clone (see below).
5. Only after the configured compatibility roles succeed does SASE write the split store record—schema version 3 when a
   beads sidecar was recorded, schema version 2 otherwise.

### Bead State Adoption

`sase repo init` moves bead state out of the plans sidecar. The move is rerunnable and idempotent, and
`sase repo init --check` reports it as a distinct planned action (`adopt bead state from the plans sidecar`) so a dry
run tells you a data move is pending.

1. Adoption is a no-op when the plans clone has no `beads/` directory, or when the beads clone already holds bead state.
2. Otherwise every entry of `<plans>/beads/` is copied to the beads clone root, excluding the local `beads.db`,
   `beads.db-shm`, and `beads.db-wal` cache files. A minimal store of only `config.json` and `issues.jsonl` is valid and
   copies cleanly.
3. The copy is committed to the beads clone as `Import bead state from <plans-repo>@<sha>` and **pushed**. A failed push
   aborts adoption, so the record is never written against bead state that exists only locally.
4. The schema-3 record is written. This is the switch: bead commands now resolve to the beads sidecar.
5. Only afterwards is `beads/` removed from the plans clone, along with its `beads/beads.db*` ignore lines, and
   committed as `Move bead state to the beads sidecar`. A failure here is a warning, not a command failure—the
   authoritative switch already happened, and the next `sase repo init` cleans up the duplicate.

Adoption is therefore reversible until step 4: everything before the record write leaves a complete but unreferenced
beads repository and a fully working project. Bead history is not filtered out of the plans repository; it stays there
as an archive, and the event store remains the real history source for `sase bead history`.

## Reads, Writes, and Offline Use

Directory-only consumers resolve paths without network or filesystem writes. Operations that write SDD data—such as
prompt export, bead initialization and mutation, and link repair with `--write`—materialize a provider-required store
first and fail if it cannot be made usable.

Once a positive record and primary clone exist, reads and numbered-workspace cloning can work offline from the primary
clone. Refresh pulls are best effort. Separate-repository commits remain local if an ordinary follow-up push fails so
they can be inspected and pushed manually; only the initial adoption push is transactional.

`sdd.push_after_commit` controls pushes after later SDD commits: `async` starts a detached background push, `true`
pushes synchronously, and `false` skips the push.

### Concurrency and Recovery

SASE serializes cooperating SDD writers with a lock in the store repository's Git directory and retries transient Git
index-lock errors. Short Git-directory metadata writes wait up to 10 seconds by default. Operations that can mutate the
shared worktree—bead mutation, sync, commit, mutation health preflight, integration, and recovery—wait up to 180 seconds
and abort without changing the worktree if the lock remains unavailable. Transactional integration reports that
contention as a busy-but-healthy outcome, so it cannot authorize destructive recovery.
`SASE_SDD_STORE_WRITE_LOCK_TIMEOUT` sets one non-negative override for both wait bounds, and
`SASE_SDD_GIT_LOCK_RETRY_DELAYS` supplies comma-separated per-command retry delays.

Managed Git commands disable `rerere` and `rerere.autoupdate`, so a user's ambient Git configuration cannot replay a
cached textual conflict resolution over SASE's semantic bead merge. Ordinary transactional integration restores the
pre-rebase state after a failed rebase and refuses unsafe or unprovable recovery.

Machine-managed disposable sidecar clones have one additional recovery path for a wedged checkout. Before resetting to
the configured upstream, SASE snapshots local branch and dirty-worktree state under `refs/sase/recovery/` and a
SASE-labelled stash for manual inspection. After a later successful integration, cleanup removes at most 50 snapshots
per pass that are older than 30 days **and** whose protected history is already reachable from a remote-tracking ref.
Fresh snapshots and snapshots protecting unpushed commits are retained.

When an upstream-present sidecar integration reaches a repeatable failure such as unsupported conflicts or failed
recovery, SASE records a per-clone failure marker. Further pulls are suppressed for the machine-recovery cooldown
instead of retrying the same rebase on every command; the cooldown is at least five minutes and grows to match a larger
configured bead-refresh TTL. A successful integration clears the marker. Remote outages and an unavailable cooperative
lock do not create this failure cooldown.
