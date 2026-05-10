# Supporting Same-Named GitHub Repos in `sase-github`

## Question

How could `sase-github` support working with multiple GitHub repositories that
share the same short name but live under different owners, such as
`zettel-org/zorg` and `bbugyi200/zorg`, at the same time?

Today the GitHub plugin preserves the owner in the clone path but drops it
before handing the project to the host `sase` workspace machinery. The first
`zorg` to be resolved owns the `~/.sase/projects/zorg/` metadata slot; a
second `zorg` from another owner either errors with `WORKSPACE_DIR conflict`
or collides with the first repo's metadata.

## TL;DR

The fix needs to make repository identity owner-aware at the project-id layer.
The clone layer is already unique:

```text
~/projects/github/zettel-org/zorg/
~/projects/github/bbugyi200/zorg/
```

The metadata layer is not:

```text
~/.sase/projects/zorg/zorg.gp
~/.sase/projects/zorg/branch_map.json
```

Recommended path:

1. Introduce a canonical GitHub project id, for example
   `zettel-org__zorg`, that is used anywhere SASE needs a durable metadata
   key.
2. Preserve `owner/repo` as display metadata and as the preferred user-facing
   ref.
3. Keep short `zorg` refs as aliases only when they resolve to exactly one
   known repo or an explicit config alias.
4. Migrate legacy GitHub projects from bare `repo` ids to qualified ids using
   the actual GitHub remote URL, not only the checkout path.

Option A from the previous research, "qualify the project id everywhere", is
still the right base design. Option C, explicit aliases, should layer on top
for ergonomics. Lazy sidecar promotion is still higher risk because the
hard part is making every downstream reader owner-aware.

## Current Behavior

### `sase-github` resolution

`resolve_gh_ref()` in `../sase-github/src/sase_github/workspace_plugin.py`
has three modes:

1. `owner/repo`: derive the checkout as
   `~/projects/github/<owner>/<repo>/`, clone it if needed, then set the
   project file to `~/.sase/projects/<repo>/<repo>.gp`.
2. `repo`: read `~/.sase/projects/<repo>/<repo>.gp`.
3. `changespec-name`: scan all ChangeSpecs and return the matched
   `cs.project_basename`.

The owner survives only long enough to build `primary_workspace_dir`. The
returned `ResolvedRef.project_name` is the bare repo name, so the host repo
allocates all project state under the short name.

The existing conflict guard is doing the right thing for the current model:

```text
WORKSPACE_DIR conflict for 'zorg':
  existing=.../zettel-org/zorg/
  derived=.../bbugyi200/zorg/
```

The guard should not be deleted. It should run after the ref has been mapped
to a key that is already unique, such as `bbugyi200__zorg`.

### Host repo identity assumptions

The host repo mostly treats "project name", "project basename", and
"directory under `~/.sase/projects`" as the same value. Important consumers:

| Surface | Current key | Why it matters |
| --- | --- | --- |
| `ResolvedRef.project_name` | `zorg` | Launch, setup, claims, ChangeSpec creation, artifacts |
| Project file | `~/.sase/projects/zorg/zorg.gp` | Single metadata slot per repo short name |
| Archive file | `~/.sase/projects/zorg/zorg-archive.gp` | Terminal ChangeSpecs collide too |
| Branch map | `~/.sase/projects/zorg/branch_map.json` | Immutable GitHub branch aliases collide |
| RUNNING field | inside the project file | Workspace claims share one table |
| Agent artifacts | `~/.sase/projects/zorg/artifacts/...` | TUI agent scan and revive paths assume project dir identity |
| ChangeSpec names | `zorg_<slug>_<N>` | Global scans often match by `cs.name` alone |
| `get_known_project_workspaces()` | `gp_file.stem` | Generic `#gh:repo` fallback and project-local xprompts key by stem |
| `detect_project()` / local xprompts | workspace name | Git/GitHub currently derives only the repo basename |
| TUI grouping and navigation | `Path(project_file).parent.name` | User-visible grouping becomes whatever storage id we choose |
| Rust wire models | project dir name | `agent_scan_wire.py` and launch wire docs encode the same path shape |

This means a correct fix cannot live only in `sase-github`. The plugin can
return a qualified `ResolvedRef`, but the host repo must consistently treat
that value as the durable project key.

## Gaps Filled In

### 1. `ResolvedRef.extra` can carry display metadata

The previous note suggested changing the `ResolvedRef` shape. That may not be
necessary for the first implementation because the dataclass already has:

```python
extra: dict[str, str] = field(default_factory=dict)
```

The plugin can return:

```python
ResolvedRef(
    project_name="zettel-org__zorg",
    extra={
        "github_owner": "zettel-org",
        "github_repo": "zorg",
        "display_name": "zettel-org/zorg",
    },
    ...
)
```

That keeps the hook ABI stable while giving the TUI and future commands a
place to display `owner/repo` instead of leaking `owner__repo` everywhere. If
we later need a stronger typed contract, the host can add fields after the
qualified-id migration proves out.

### 2. GitHub lacks an owner-aware workspace-name hook

The GitHub workspace plugin implements `ws_resolve_ref()` and
`ws_get_workspace_directory()`, but not `ws_get_workspace_name()`.

That matters because `sase.xprompt.loader.detect_project()` calls
`workspace_provider.get_workspace_name(os.getcwd())` to namespace local
xprompts and infer project context. Today the bare-git workspace plugin and
the VCS Git helper derive workspace names from the trailing remote path
segment, so a GitHub remote like `git@github.com:zettel-org/zorg.git` becomes
`zorg`, not `zettel-org__zorg`.

Add a GitHub workspace hook that parses GitHub remotes and returns the same
canonical project id used by `resolve_gh_ref()`. Otherwise local xprompts,
prompt history, SDD helpers, and "current project" detection will continue to
collapse same-named repos even if `#gh:owner/repo` works.

### 3. Known-project fallback paths need review

Some launch paths intentionally handle known VCS refs even when the provider
is not available in the current process:

- `src/sase/xprompt/loader.py:get_known_project_workspaces()`
- `src/sase/xprompt/_parsing.py:extract_known_project_vcs_ref()`
- `src/sase/agent/launcher.py:resolve_known_project_vcs_launch_ref()`
- `src/sase/main/query_handler/_query.py` known-project handling

These paths enumerate `~/.sase/projects/*/*.gp` and use `gp_file.stem` as the
ref key. This works with a flat qualified id like `zettel-org__zorg`, but it
does not support a literal slash id like `zettel-org/zorg` without deeper path
changes. This is a strong reason to keep the storage id flat.

These fallback paths also need alias lookup. After migration, `#gh:zorg`
should not just look for `~/.sase/projects/zorg/zorg.gp`; it should search
known GitHub project metadata for repos whose short name is `zorg`, then:

- return the one match when exactly one exists;
- apply configured aliases when present;
- raise an ambiguity error when multiple owners match.

### 4. ChangeSpec names are still global in many flows

`find_all_changespecs()` scans every `~/.sase/projects/<project>/<project>.gp`
and archive file. Many callers then match `cs.name` without also requiring
`cs.file_path`. If two repos can both create `zorg_add_index_1`, the ambiguity
moves from project resolution into ChangeSpec resolution.

The least surprising implementation is to use the qualified project id as the
ChangeSpec prefix:

```text
zettel-org__zorg_add_index_1
bbugyi200__zorg_add_index_1
```

That is longer, but it keeps existing global ChangeSpec lookup semantics
working. If we want short display names, display should be a view-layer
concern, not a storage-key shortcut.

One caveat: the ChangeSpec suffix helpers already treat `__<N>` as a legacy
suffix form. A project id containing `__` still appears workable because
normal generated names have the prefix `owner__repo_`, but this should be
covered by tests around:

- `ensure_project_prefix()`
- `strip_reverted_suffix()`
- `changespec_name_to_branch()`
- `changespec_name_to_branch_with_suffix()`
- sibling grouping in the TUI

### 5. Migration should derive owner from Git remotes

The previous note proposed deriving owner from the checkout path
`~/projects/github/<owner>/<repo>/`. That is useful but insufficient. Users
can have manually-created workspaces, symlinks, old clone locations, or moved
directories.

Migration should prefer parsing `remote.origin.url` from the `WORKSPACE_DIR`
repo. It should handle at least:

```text
git@github.com:owner/repo.git
https://github.com/owner/repo.git
ssh://git@github.com/owner/repo.git
https://github.com/owner/repo
```

If the remote is missing or not GitHub, fall back to the current
`~/projects/github/<owner>/<repo>/` path convention. If neither works, skip
with a clear report rather than guessing.

Also decide whether the canonical id is case-preserving or lowercased. GitHub
owner/repo lookup is effectively case-insensitive for most operations, but
SASE filesystem keys are not. Lowercasing the id avoids duplicate metadata for
`Zettel-Org/zorg` and `zettel-org/zorg`; preserve display casing separately if
we care.

### 6. Agent artifacts and metadata are part of migration

Renaming `~/.sase/projects/zorg/` to `~/.sase/projects/zettel-org__zorg/`
moves the artifact tree with it, but several files inside artifacts can embed
the old project file path or project name:

- `agent_meta.json`
- `done.json`
- `running.json`
- `workflow_state.json`
- retry handoff/state files
- chop-agent registry records

Most historical completed artifacts can probably remain as-is if the TUI uses
the scanned artifact path as authoritative. Active or resumable agents are
different. A safe migration should refuse to run when the legacy project has
active RUNNING claims or active artifact markers unless a dedicated
active-agent rewrite path is implemented.

### 7. TUI display needs a separate display-name plan

If `project_name` becomes `zettel-org__zorg`, many current UI paths will show
that exact string because they derive the label from
`Path(project_file).parent.name` or `cs.project_name`.

That is acceptable for a first correctness pass, but not ideal long term.
Add a display helper that maps storage id to:

- `owner/repo` for GitHub projects;
- existing project basename for legacy and non-GitHub projects;
- optionally short `repo` only when not ambiguous in the current list.

The helper should be shared by TUI grouping, notification navigation, prompt
history, xprompt catalog, and project filters. Avoid letting each surface
invent its own ambiguity policy.

### 8. This crosses the Rust boundary

Several identity-sensitive paths are now Rust-backed or Rust-facing, including
agent launch and artifact scanning wire contracts. The current wire docs
explicitly describe:

```text
projects/<project_name>/<project_name>.gp
projects/*/artifacts/<workflow>/<timestamp>/
```

A flat qualified id is compatible with that shape. A nested `owner/repo`
layout is not. If project-id parsing, GitHub remote parsing, or display-name
mapping becomes shared behavior, it belongs in `../sase-core` with Python
callers using the binding rather than reimplementing it in multiple frontends.

## Design Options

### Option A: Qualify the project id everywhere

Use a flat canonical id such as `zettel-org__zorg` for:

- project directory name;
- `.gp` basename;
- branch map directory;
- RUNNING claims;
- ChangeSpec prefix;
- artifact directory root;
- generic known-project refs.

Pros:

- collision-proof by construction;
- fits existing `projects/*/*.gp` and artifact scan globs;
- keeps the existing conflict guard meaningful;
- requires fewer special cases after migration.

Cons:

- visible names become longer unless display mapping is added;
- migration touches project files, archive files, branch maps, artifacts, and
  possibly active claims;
- branch names generated from ChangeSpec names may become longer if no
  additional branch-display logic is added.

### Option B: Keep short id until a collision appears

Keep `zorg` as the storage id for single-owner repos and promote to
`owner__repo` only when a second `zorg` is introduced.

Pros:

- minimal visible change for existing users without collisions.

Cons:

- all code still has to support qualified ids;
- promotion is racy with active agents;
- users get different path shapes before and after a collision;
- alias and migration code becomes harder to reason about.

This is not worth the complexity.

### Option C: Explicit aliases on top of qualified ids

Add config such as:

```yaml
github:
  aliases:
    zorg: zettel-org/zorg
    bzorg: bbugyi200/zorg
```

Aliases should resolve to qualified ids internally. They should not be the
storage key.

Pros:

- preserves short commands for humans;
- gives users a deterministic answer for ambiguous short names.

Cons:

- adds config and validation;
- still requires Option A first.

## Recommended Implementation Sequence

1. Add GitHub identity helpers in `sase-github`.

   Suggested helpers:

   - `parse_github_remote_url(url) -> (owner, repo) | None`
   - `github_project_id(owner, repo) -> str`
   - `github_display_name(owner, repo) -> str`
   - `github_project_file(owner, repo) -> Path`

   Keep these helpers the only place that knows the separator.

2. Update `resolve_gh_ref()` Mode 1.

   For `owner/repo`, compute `project_id = github_project_id(owner, repo)`,
   set `project_file = ~/.sase/projects/<project_id>/<project_id>.gp`, and
   return `project_name=project_id` with `extra` display metadata. Keep the
   `WORKSPACE_DIR` conflict check, but check within the qualified project file.

3. Add owner-aware shorthand resolution.

   For `#gh:zorg`, search known GitHub project files for metadata indicating
   repo short name `zorg`. Resolve only if exactly one match or an alias exists.
   Otherwise raise an error that lists the candidates and asks for
   `#gh:owner/repo` or a configured alias.

4. Persist GitHub repo metadata.

   `WORKSPACE_DIR` alone is enough to detect workflow type, but shorthand and
   display need stable metadata even if a checkout moves. Add header fields in
   `.gp`, for example:

   ```text
   WORKSPACE_DIR: /home/bryan/projects/github/zettel-org/zorg/
   GITHUB_OWNER: zettel-org
   GITHUB_REPO: zorg
   GITHUB_FULL_NAME: zettel-org/zorg
   ```

   Put parsing/setter helpers next to the existing `WORKSPACE_DIR` helpers or
   in the GitHub plugin if we want these fields provider-specific.

5. Add `ws_get_workspace_name()` to `sase-github`.

   It should parse the current repo's GitHub remote and return the canonical
   project id. This fixes project detection from inside checkouts, local
   xprompt namespacing, and prompt history grouping.

6. Update host path consumers to tolerate qualified ids.

   Most code already works if the id is a flat path segment. The important
   review points are:

   - `src/sase/workflows/utils.py:get_project_file_path()`
   - `src/sase/xprompt/loader.py:get_known_project_workspaces()`
   - `src/sase/agent/launcher.py:resolve_known_project_vcs_launch_ref()`
   - `src/sase/core/branch_map.py`
   - `src/sase/core/changespec.py`
   - TUI filters/grouping/navigation that display `Path(project_file).parent.name`
   - Rust wire docs and any tests that assume short names

7. Write migration as an explicit command.

   For each legacy project under `~/.sase/projects/<repo>/<repo>.gp`:

   - skip non-GitHub projects;
   - parse `WORKSPACE_DIR`;
   - inspect `git config --get remote.origin.url`;
   - derive `(owner, repo)` and `project_id`;
   - refuse if `project_id` already exists with a different workspace;
   - refuse if the legacy project has active RUNNING claims;
   - rename main and archive project files to the qualified basename;
   - move `branch_map.json` with the project dir;
   - rewrite embedded project-file paths in active metadata only if active
     migration is deliberately supported;
   - leave an alias/forwarding record or report telling the user which short
     refs changed.

8. Add tests in both repos.

   Minimum tests:

   - resolving `zettel-org/zorg` and `bbugyi200/zorg` creates two project files;
   - resolving short `zorg` with two matches raises an ambiguity error;
   - resolving short `zorg` with one match succeeds;
   - alias config resolves to the right qualified id;
   - `ws_get_workspace_name()` returns the qualified id from GitHub remotes;
   - two same-named repos allocate independent RUNNING claims and branch maps;
   - generated ChangeSpec names and branch names remain valid with `__`;
   - `get_known_project_workspaces()` and generic `#gh:<id>` fallback work with
     qualified ids.

## Separator Recommendation

Prefer a flat id over nested directories:

```text
zettel-org__zorg
```

Reasons:

- works with existing `~/.sase/projects/*/*.gp` scans;
- works with current artifact scan shape;
- fits the existing ref regex character set;
- avoids changing `get_project_file_path(project)`;
- easy to grep and manually inspect.

Avoid literal `/` in the storage id unless we are willing to change every
project glob, artifact scan, archive path, known-project fallback, and wire
contract that assumes two path levels.

Open concern: because `__<N>` is a legacy ChangeSpec suffix form, include
tests for qualified ids containing `__`. If those tests expose edge cases, a
different separator such as `~` may be safer, but `__` is still the best
default candidate based on current path constraints.

## Files To Touch

`../sase-github`:

- `src/sase_github/workspace_plugin.py`: qualified id, metadata persistence,
  shorthand ambiguity, `ws_get_workspace_name()`.
- `src/sase_github/config.py`: alias config helpers.
- `src/sase_github/scripts/gh_setup.py`: ensure printed `project_name` is the
  qualified id and optionally print `display_name`.
- `tests/test_workspace_plugin.py`: same-name repo resolution and ambiguity.
- new migration script or CLI entry point under `src/sase_github/scripts/`.

Host `sase` repo:

- `src/sase/workspace_provider/_hookspec.py`: probably no required ABI change,
  but document `ResolvedRef.extra` keys if used.
- `src/sase/workspace_provider/utils.py`: maybe provider metadata helpers if
  not kept in the plugin.
- `src/sase/workflows/utils.py`: project-file path assumptions.
- `src/sase/core/branch_map.py`: tests for qualified ids.
- `src/sase/core/changespec.py`: tests for qualified prefixes and suffixes.
- `src/sase/xprompt/loader.py`: known-project and project-local xprompt names.
- `src/sase/xprompt/_parsing.py`: known VCS ref extraction with aliases.
- `src/sase/agent/launcher.py` and `src/sase/main/query_handler/_query.py`:
  known-project fallback behavior.
- TUI modules that display or filter by `Path(project_file).parent.name`.
- `../sase-core` if project-id/display-name parsing is shared across
  Python, TUI, and future Rust-backed flows.

## Remaining Open Questions

1. Should canonical ids be lowercased while display names preserve remote
   casing?
2. Should generated Git branches include the owner prefix, or should
   `changespec_name_to_branch()` strip `owner__repo_` so branches stay short?
3. Should `#gh:repo` auto-resolve to the current checkout's owner when run
   from inside a matching GitHub repo, even if multiple known owners exist?
4. Should migration leave a persistent alias from `repo` to `owner/repo` when
   there is only one known owner?
5. How much old artifact metadata should be rewritten? Completed artifacts can
   likely remain historical; active/resumable artifacts need a stricter policy.
6. Does `retired Mercurial plugin` need an analogous namespace model, or are its project
   names already globally unique enough for the expected workflow?
