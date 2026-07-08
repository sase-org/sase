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

| Mode            | Root                  | Repository                                                              |
| --------------- | --------------------- | ----------------------------------------------------------------------- |
| `in_tree`       | `{workspace}/sdd`     | The code repository. SDD files are committed with code changes.         |
| `local`         | `{primary}/.sase/sdd` | A standalone local git repo beside the primary checkout.                |
| `separate_repo` | `{primary}/.sase/sdd` | A provider-materialized companion repository, such as `owner/repo-sdd`. |

The local and separate-repo modes intentionally share the same filesystem layout. Code that only needs a directory can
use the fast resolver without knowing whether the store is a local-only repo or a companion checkout.

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

For GitHub-style providers, the convention is a companion repository named `<owner>/<repo>-sdd`. The clone lives at
`{primary}/.sase/sdd`, and the store record lives next to it at `{primary}/.sase/sdd-store.json` so it is not committed
into the companion repository.

Providers that support companion storage may also honor `sdd.repo.name` as an override. It accepts either `name` or
`owner/name`; an empty value uses the provider convention. Separate-repo commits are local first.
`sdd.push_after_commit` controls the follow-up push: `async` starts a detached background push, `true` pushes
synchronously, and `false` skips the push.

Discovery is cached. A missing companion repository should keep the project in local mode; a found companion repository
can be cloned or adopted when the existing `.sase/sdd` remote already matches. Existing local SDD content should not be
clobbered by automatic discovery.

## Migration And Offline Behavior

Treat migration from an existing in-tree or local store into a companion repository as a provider-specific operation
today. Do not replace `.sase/sdd` by hand while an agent or bead command may be writing it.

Once a separate-repo store is materialized, directory-only reads and `sase sdd path` work offline against the local
clone. Network fetch and push work belongs to setup, provider-specific migration, and commit/push paths. Local commits
must survive push failures so users can inspect and push manually later.
