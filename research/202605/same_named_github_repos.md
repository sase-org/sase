# Supporting Same-Named GitHub Repos in `sase-github`

## Question

How could `sase-github` support working with multiple GitHub repositories that
share the same short name but live under different owners (e.g.
`zettel-org/zorg` and `bbugyi200/zorg`) at the same time?

Today the plugin keys nearly everything off the bare repo name. The first
`zorg` to be resolved "owns" the project slot; a second `zorg` from a different
owner either errors out (`WORKSPACE_DIR conflict`) or silently overwrites the
first.

## TL;DR

Owner is captured during clone but never persisted. Every downstream artifact
(project dir, `.gp` file, branch map, workspace claims, ChangeSpec basenames)
is keyed on `<repo>` only. Disambiguation needs to happen at the *project
identity* layer, not just at the resolver. The cleanest path is:

1. Introduce an explicit `<owner>__<repo>` (or `<owner>/<repo>` with on-disk
   escaping) project identity that flows through `ResolvedRef.project_name`.
2. Keep the short name (`zorg`) as a user-facing alias that resolves to a
   single owner unless ambiguous, in which case the user (or a config-pinned
   default) picks.
3. Migrate existing single-owner projects in place (rename
   `~/.sase/projects/zorg/` → `~/.sase/projects/zettel-org__zorg/`, leave a
   forwarding alias).

## Current Behavior (where the bare name leaks)

All paths below are in `../sase-github` unless prefixed.

### Identification

- `ResolvedRef.project_name` (`workspace_provider/_hookspec.py:11-19` in the
  host repo) is a flat string. The GitHub plugin sets it to just the repo name:

  ```python
  # workspace_plugin.py:397-402
  return ResolvedRef(
      project_file=project_file,
      project_name=project,           # "zorg" — owner discarded
      primary_workspace_dir=primary_workspace_dir,
      checkout_target=checkout_target,
  )
  ```

- `resolve_gh_ref()` accepts three input forms (`workspace_plugin.py:352-432`):
  1. `user/project` — owner is used to clone and to derive the on-disk clone
     path, but only `project` survives into `project_file` and `project_name`.
  2. `project` shorthand — looks up `~/.sase/projects/<project>/<project>.gp`.
     No owner involved.
  3. ChangeSpec name — finds an existing CS by name and returns its
     `project_basename`.

- The clone path *does* preserve owner:
  `~/projects/github/<user>/<project>/` (`workspace_plugin.py:377-378`). So
  two `zorg` clones can physically coexist on disk; the conflict is purely in
  sase's project metadata.

### Collision points (highest impact first)

1. **Project file location** (`workspace_plugin.py:380`)
   `~/.sase/projects/<project>/<project>.gp` — single slot per short name.
2. **`WORKSPACE_DIR` conflict guard** (`workspace_plugin.py:382-389`)
   Resolving `bbugyi200/zorg` after `zettel-org/zorg` raises:
   ```
   WORKSPACE_DIR conflict for 'zorg': existing=…/zettel-org/zorg/,
                                     derived=…/bbugyi200/zorg/
   ```
   That guard is exactly the protection that has to be relaxed (or rerouted
   onto a different key) once we permit two `zorg`s.
3. **Branch map JSON** — `~/.sase/projects/<project>/branch_map.json`. Shared
   across repos with same name; aliases would clobber each other.
4. **Workspace allocation / claims** — `running_field/__init__.py` and
   `_workspace.py` look up workspace numbers and `RUNNING` claims using
   `project_basename`. Two `zorg`s would share the `zorg_2`, `zorg_3`,
   … allocation pool *and* the same RUNNING table.
5. **ChangeSpec basenames** — `workspace_provider/changespec.py:50-66` derives
   `<project_basename>_<slug>`, e.g. `zorg_my_feature`. Two repos produce
   colliding CS names that resolve back to whichever `.gp` happens to exist.
6. **Default-config xprompts and project listings** — anything that grep-finds
   "the zorg project" by short name will be ambiguous.

### Data shapes that need to learn about owner

| Surface | Field | Today | Needed |
| --- | --- | --- | --- |
| `ResolvedRef` | `project_name` | `"zorg"` | qualified id (`"zettel-org__zorg"`) |
| `.gp` filename | path | `~/.sase/projects/zorg/zorg.gp` | `~/.sase/projects/zettel-org__zorg/zettel-org__zorg.gp` |
| `branch_map.json` | path | `…/zorg/branch_map.json` | qualified dir |
| RUNNING / workspace claims | key | `project_basename` | qualified id |
| ChangeSpec name prefix | `cs.project_basename` | `zorg` | qualified id (or owner-aware lookup) |
| Workspace dir suffix (`_2`, `_3`) | base | `<repo>` | `<owner>/<repo>` already unique on disk; no change needed |

## Design Options

### Option A — Qualify the project id everywhere

Replace `project_name = "zorg"` with `project_name = "zettel-org__zorg"` (or
similar separator that survives filesystem and `.gp` parsing). All
filesystem-keyed state moves under the qualified directory.

- **Pros:** Conceptually clean. Owner is first-class; collisions become
  literally impossible; the existing `WORKSPACE_DIR conflict` check still works
  but on a key that's already unique.
- **Cons:** Migration cost. Every `.gp` filename, every `branch_map.json`
  path, and every CS basename changes. Need a one-time mover plus probably a
  fallback that reads the legacy short-name path if the qualified one is
  missing.
- **Display:** Render as `zettel-org/zorg` in TUI; persist as
  `zettel-org__zorg` (or url-encode the `/`). Pick one separator and stick
  to it; `__` is grep-safe and won't collide with directory boundaries.

### Option B — Keep short name, add an owner sidecar

Leave `project_name = "zorg"`. Introduce `~/.sase/projects/zorg/owner` (or a
new field in the `.gp` file header) that records `zettel-org`. When a second
owner appears for the same name, *promote* both projects to qualified ids and
move them.

- **Pros:** Zero migration for users with no collision (the common case).
- **Cons:** Lazy migration is a footgun — code paths that read
  `project_basename` need to handle "this might suddenly point at a moved
  directory." The promotion event is racy under concurrent agents.
  Effectively this still requires Option A's full implementation, just
  triggered conditionally.

### Option C — Owner-as-namespace via config

Require users to pre-declare which owner "wins" the short name `zorg` in
`sase.yml` (`xprompts:` style), with explicit aliases like:

```yaml
github:
  aliases:
    zorg: zettel-org/zorg
    bzorg: bbugyi200/zorg
```

The resolver maps `#gh_zorg` → `zettel-org/zorg` and `#gh_bzorg` →
`bbugyi200/zorg`. Internally projects are *still* keyed by qualified id (so
this layers on top of A).

- **Pros:** Gives users a one-keystroke shorthand even when collisions exist.
  Nice for the TUI and ref tags.
- **Cons:** Yet another config surface; doesn't replace A, only augments it.

### Recommendation

**Do A, then layer C on top.** B is just A delayed.

Rough sequence:

1. Add a `qualified_project_id()` helper that returns
   `<owner>__<repo>` and is the only thing that touches the filesystem.
2. Plumb owner into `resolve_gh_ref()` Mode 1, persist it in the new
   `.gp` location, and have Mode 2 (`#gh_zorg`) fall back to the legacy path
   when only one match exists, otherwise raise an "ambiguous; use
   `<owner>/<repo>` or define an alias" error.
3. Write a one-time migration: walk `~/.sase/projects/*/`, read
   `WORKSPACE_DIR`, derive owner from `~/projects/github/<owner>/<repo>/`,
   rename the directory and `.gp` file, rewrite RUNNING/COMMITS path
   references inside the `.gp`.
4. Optional: alias config (Option C) for ergonomics.

## Open Questions

1. **Separator choice.** `__` (double underscore), `/` with on-disk escaping,
   or a dedicated `<owner>/<repo>` directory layout
   (`~/.sase/projects/zettel-org/zorg/zorg.gp`)? The nested layout reads best
   in `ls` but breaks every `glob("*/*.gp")` style lookup; I'd prefer flat
   `__` unless someone finds a strong reason otherwise.
2. **ChangeSpec naming.** Do CS basenames also become
   `zettel-org__zorg_my_feature`, or do we keep the short prefix and rely on
   the parent `.gp` for disambiguation? The latter is shorter for branch
   names; the former is bulletproof.
3. **TUI display.** Always show `owner/repo`, or only when ambiguous? "Always"
   is simpler; "only when ambiguous" matches what humans actually need to see.
4. **`#gh_<short>` ref tags.** Once `zorg` is ambiguous, do unaliased uses
   error, or auto-resolve against the *current* workspace's owner if you're
   inside a clone of `zettel-org/zorg`?
5. **Migration safety.** If an active agent holds a workspace claim during
   migration, we must either (a) refuse to migrate, or (b) rewrite the
   RUNNING entry's project key atomically. (a) is safer.
6. **Other plugins.** `sase-google` (Mercurial) presumably has the same
   problem. Worth checking whether the qualified-id helper should live in the
   host `sase.workspace_provider` package so all plugins share it.

## Files to Touch (rough map)

- `sase-github/src/sase_github/workspace_plugin.py` — `resolve_gh_ref`,
  `_clone_gh_repo`, `ws_*` hooks.
- `sase-github/src/sase_github/config.py` — alias config (Option C).
- Host `sase` repo:
  - `src/sase/workspace_provider/_hookspec.py` (`ResolvedRef` shape).
  - `src/sase/workspace_provider/changespec.py` (basename derivation).
  - `src/sase/workspace_provider/branch_map.py` (path derivation).
  - `src/sase/workspace_provider/running_field/` (claim keys).
  - `src/sase/workspace_provider/utils.py` (`parse_workspace_dir` and
    friends — they take a `.gp` path today, which is fine; the path just
    moves).
- One-shot migration: new script under
  `sase-github/src/sase_github/scripts/` (e.g. `migrate_qualified_ids.py`),
  invokable via the plugin's CLI.
- Tests in both repos that exercise the two-`zorg` scenario end-to-end:
  resolve, clone, allocate workspaces, create CSes, submit.
