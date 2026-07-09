# SDD Storage

SDD artifacts can live in three places. Use `sase sdd path` when you need the effective root for the current project:

```bash
sase sdd path
sase sdd path research
```

`sase sdd path` is a fast directory resolver: it prints the root SASE would use, but it does not create, clone, fetch,
or verify a companion repository. Launched agents also receive `SASE_SDD_DIR`, which points at the same root. Prompt
text, hooks, and skills should use that environment variable instead of assuming `sdd/` is relative to the current
checkout.

## Modes

| Mode            | Root                    | Repository                                                                                                   |
| --------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------ |
| `in_tree`       | `{workspace}/sdd`       | The code repository. SDD files are committed with code changes.                                              |
| `local`         | `{primary}/.sase/sdd`   | A standalone local git repo beside the primary checkout.                                                     |
| `separate_repo` | `{workspace}/.sase/sdd` | A provider-materialized companion repository, such as `owner/repo--sdd` or an explicit `owner/sdd` override. |

Local and separate-repo modes use the same `.sase/sdd/` shape, but not the same workspace rule. `local` is a single
primary-workspace store. `separate_repo` is a real companion-repository checkout under the active workspace, with the
primary workspace holding the materialized-store record at `{primary}/.sase/sdd-store.json`. Code that only needs a
directory should still use `sase sdd path` or `SASE_SDD_DIR` instead of deriving paths by hand.

## Resolution

`sdd.storage` accepts `auto`, `in_tree`, `local`, or `separate_repo` and defaults to `auto`.

When the value is not `auto`, it wins. When it is `auto`, the legacy `sdd.version_controlled: true` alias maps to
`in_tree`; `false` leaves automatic resolution enabled. After that, SASE checks for a materialized separate-repo record,
then provider metadata, then falls back to `local`. Because explicit `sdd.storage` wins, `sdd.version_controlled: true`
does not force in-tree storage if the same config also says `sdd.storage: local` or `sdd.storage: separate_repo`.

Built-in bare-git projects declare `in_tree`, preserving the historical `sdd/` behavior. Providers that opt into
companion storage can declare separate-repo eligibility and materialize the store at setup-shaped moments, not in hot
render or keystroke paths.

## Companion Repositories

For GitHub-style providers, default discovery checks only `<owner>/<repo>--sdd`. The clone lives at
`{workspace}/.sase/sdd`; numbered workspaces get their own best-effort clone or fast-forwarded copy from the primary
checkout. The store record lives at `{primary}/.sase/sdd-store.json` so it is not committed into the companion
repository.

New GitHub companion repositories created by SASE are public by default. Existing private companion repositories are not
made public automatically. During explicit create or verify flows such as `sase sdd init` and `sase init`, SASE also
ensures the selected GitHub companion repository has a `sase--sdd` label; setup-time discovery and cloning do not mutate
GitHub labels.

Providers that support companion storage may also honor `sdd.repo.name` as an override. It accepts either `name` or
`owner/name`; an empty value uses the provider default. For GitHub, set this to `sdd` or `owner/sdd` to use an org-level
companion repository explicitly. Separate-repo commits are local first. `sdd.push_after_commit` controls the follow-up
push: `async` starts a detached background push, `true` pushes synchronously, and `false` skips the push.

Discovery is cached. A missing companion repository keeps setup-time discovery in local mode, but `sase sdd init` and
`sase init` create the project-specific GitHub companion repository automatically when the provider policy is
`separate_repo`. A found companion repository can be cloned or adopted when the existing `.sase/sdd` remote already
matches. Existing local SDD content should not be clobbered by automatic discovery.

## Migration And Offline Behavior

Use `sase sdd migrate` to move an existing in-tree or local store into the provider companion repository:

```bash
sase sdd migrate
sase sdd migrate --create
sase sdd migrate --remove-in-tree
```

The command connects or creates the companion, copies in-tree `sdd/` content into `.sase/sdd/` when needed, initializes
the generated guides and bead store, commits and pushes the companion repo, and writes `sdd.storage: separate_repo` in
the project config. `--create` lets the provider create a missing companion repository. `--remove-in-tree` removes
tracked in-tree `sdd/` files in a separate code-repo commit after the companion migration succeeds. Do not replace
`.sase/sdd` by hand while an agent or bead command may be writing it.

Once a separate-repo store is materialized, directory-only reads and `sase sdd path` work offline against the local
clone. Network fetch and push work belongs to setup, provider-specific migration, and commit/push paths. Local commits
must survive push failures so users can inspect and push manually later.
