---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Workspace Open Tracking For Linked Projects

## Research Request

Evaluate this alternative to configured `sibling_repos`:

- tell agents they can run `sase workspace open -p <project> <workspace_num>` for any SASE project they know about;
- manually document linked/sibling repo names and descriptions in the relevant `AGENTS.md` and memory files;
- track which agents run `sase workspace open`;
- use that tracking data for commit finalizer and diff tracking.

## Executive Summary

This is feasible for the most important case: numbered Git workspaces for related SASE projects such as `sase-core`,
`sase-github`, `sase-telegram`, and `sase-nvim`.

It is not feasible as a docs-only replacement. The current sibling-repo feature does more than tell agents what command
to run: it lazily materializes hidden ProjectSpecs, exports a machine-readable launch map, records opened intent, gives
the finalizer enough target metadata, renders generated memory, and preserves static singleton advisory semantics.

A workable migration would be:

1. make every linked repository a normal registered SASE project with a usable `WORKSPACE_DIR`;
2. keep manually maintained AGENTS/memory prose as the agent-facing discovery layer;
3. change `sase workspace open` to record every agent-run open, not only `ctx.is_sibling` opens;
4. make the marker contain enough path and project metadata for finalizer/diff consumers to use it directly;
5. update finalizer and TUI diff code to read those opened workspace records instead of resolving configured siblings.

That would remove the project-local `sibling_repos` relationship config for numbered related repos. It would also change
the product contract: SASE would only know about cross-repo work after the agent opens the other project. It would no
longer know a run's related repos up front.

My recommendation is to treat this as a viable simplification only if you are comfortable losing launch-time linked-repo
metadata and generated linked-repo memory. If you want full behavior parity, the earlier "linked repositories" model is
still the cleaner migration.

## What Already Works

### `sase workspace open` Can Open Registered Projects

`sase workspace open -p <project> <workspace_num>` resolves `<project>` through
`src/sase/main/workspace_handler_context.py::resolve_project_context`.

For an ordinary registered SASE project with a ProjectSpec containing `WORKSPACE_DIR`, this already works. The command:

1. builds a `WorkspaceStore` for the target project's primary checkout;
2. materializes the requested numbered checkout through `ensure_workspace_checkout`;
3. runs `prepare_workspace`;
4. prints the prepared path.

The configured-sibling special case only matters when the named project has no usable `WORKSPACE_DIR`. In that case,
`_materialize_sibling_project_context()` scans `sibling_repos`, creates hidden `PROJECT_STATE: sibling` ProjectSpec
metadata, and then proceeds as if the sibling were a registered project.

So the proposed direction can work if every linked repo is already registered. Without that registration, removing
`sibling_repos` removes the lazy project-materialization path.

### The Opened-Intent Marker Already Exists

The current implementation writes `opened_siblings.json` under `$SASE_ARTIFACTS_DIR` from
`src/sase/main/workspace_handler_list.py::handle_open_clean`, but only when `ctx.is_sibling` is true.

That marker is already scoped correctly: it lives in the per-agent artifacts directory, so it avoids cross-run false
positives from stale dirty workspaces. The current finalizer reads it with `opened_sibling_names(artifact_root)`.

The marker is too narrow for the proposed replacement because it stores only sibling names and workspace paths, and the
reader returns only names. The finalizer still needs `SASE_SIBLING_REPOS_JSON` or `sibling_repos` config to reconstruct
the target list.

### Open Is Intentionally Not Passive

`sase workspace open` calls `prepare_workspace`, which runs the VCS clean/update/sync path before printing the checkout.
That is appropriate for isolated numbered workspaces. It is a semantic commitment if we tell agents to use it for any
project they know about.

For this proposal, that is probably acceptable for numbered related repos because it makes the opened workspace safe to
edit. It should be documented as "prepare and use this numbered workspace", not merely "look up a path".

## What Would Need To Change

### 1. Register Linked Repos As Projects

The related repos must have ProjectSpecs with `WORKSPACE_DIR`. This replaces the current `sibling_repos[].path` field as
the machine-readable source of the primary checkout.

Open question: should these projects be active, inactive, or hidden under a new neutral lifecycle state?

Current `sase workspace open` does not block hidden/sibling lifecycle records when `WORKSPACE_DIR` exists, but launch
pickers and broad project discovery intentionally hide `PROJECT_STATE: sibling`. If linked repos become ordinary active
projects, project lists and launch surfaces get noisier. If they are inactive/hidden, we should make that behavior an
explicit supported contract for `sase workspace open`, not an accident of the current resolver.

### 2. Move Descriptions To Manual Agent-Facing Docs

Manual `AGENTS.md`/memory descriptions can replace the current generated sibling-repo prose for human/agent discovery.
This is simple operationally, but it shifts correctness from config validation to documentation hygiene.

The current `memory/sase.md` is generated from `sase.yml` by `src/sase/main/init_memory/config.py` and
`src/sase/main/init_memory/roots.py`. If `sibling_repos` is removed and no generator change is made, rerunning
`sase memory init` would render "No sibling repositories are configured for this context" unless the manual content
lives somewhere outside that generated section.

So this proposal needs one of these choices:

- stop generating the linked-repo section and maintain it manually;
- add a neutral generated-memory source separate from `sibling_repos`;
- put linked-project prose in `AGENTS.md` or another manually owned memory file that `sase memory init` will not
  overwrite.

### 3. Record All Agent-Run Workspace Opens

Change the marker from sibling-specific intent to generic opened-workspace intent. A useful shape would be:

```json
{
  "schema_version": 1,
  "workspaces": [
    {
      "project_name": "sase-core",
      "workspace_num": 10,
      "workspace_dir": "/abs/path/to/sase-core_10",
      "primary_workspace_dir": "/abs/path/to/sase-core",
      "project_file": "/home/bryan/.sase/projects/sase-core/sase-core.sase",
      "opened_at": "2026-06-20T00:00:00Z"
    }
  ]
}
```

This should be written by the CLI itself, not inferred later from shell transcripts. Parsing tool-call logs would be
more fragile across LLM providers and tool surfaces, while the existing `$SASE_ARTIFACTS_DIR` marker already has the
right per-run scope.

Whether to record primary-project opens is a product decision. For cross-repo tracking, recording all opens is simpler,
then consumers can ignore the agent's main `project_dir` if needed. Recording only non-current-project opens requires
reliable current-project comparison in the CLI.

### 4. Make Finalizer Consume Opened Paths Directly

The finalizer currently does this:

1. collect sibling targets from `SASE_SIBLING_REPOS_JSON`;
2. fall back to resolving `sibling_repos` from config;
3. read opened sibling names;
4. check only configured suffix targets whose names were opened;
5. check static `none` siblings as advisory.

Under this proposal, the finalizer should instead:

1. read opened workspace records from the artifacts dir;
2. drop the main workspace path if it appears;
3. for each remaining opened workspace, run dirty-state detection at `workspace_dir`;
4. include dirty opened workspaces in the follow-up prompt.

This removes the need for preconfigured sibling targets. It also means the finalizer cannot report dirty related repos
that were not opened, even if the relationship is documented. That is consistent with the current "open is intent"
policy, but the policy becomes more important because there is no config fallback.

The implementation should probably switch from Git-only sibling checks to provider-aware checks if this becomes "any
SASE project" rather than "configured Git sibling repos." Today `commit_finalizer_state.py` uses `git_changed_files()`
for sibling targets.

### 5. Rework Diff Tracking Around Opened Records

The same marker can drive TUI/live diff tracking if it contains concrete paths. Instead of displaying configured
siblings up front from `agent_meta["sibling_repos"]`, the UI can show opened linked workspaces after the agent has run
`sase workspace open`.

That is a behavior change:

- before open: SASE has no machine-readable list of related projects for the run;
- after open: SASE can show and diff the exact workspace path that was prepared.

If the desired UI is "show all possible linked repos before they are opened," manual docs are not enough. There needs to
be a machine-readable relationship list somewhere.

## What This Proposal Loses Or Changes

### Launch-Time Env Vars

Current launches export:

- `SASE_SIBLING_REPOS_JSON`
- `SASE_SIBLING_REPO_<ENV_NAME>_DIR`
- `SASE_SIBLING_REPO_<ENV_NAME>_PRIMARY_DIR`

The `Justfile` currently uses `SASE_SIBLING_REPO_SASE_CORE_DIR` as a workspace-matched `sase-core` fallback. If those
env vars disappear, commands that rely on them need to call `sase workspace open` first, accept an explicit
`SASE_CORE_DIR`, or get a new neutral env contract.

### Lazy Hidden ProjectSpec Creation

Today, a configured sibling can be opened even if its ProjectSpec is missing or incomplete. Removing `sibling_repos`
means there is no local path to materialize from. Project registration becomes a prerequisite.

### Generated Memory Validation

The current config path validates that every linked/sibling entry has a name, path, and description before generating
memory. Manual docs have no equivalent validation unless we add a checker.

### Static Singleton Advisory Semantics

`workspace.strategy: none` currently means "use this one real path and report dirty state as advisory." Ordinary
`sase workspace open -p <project> <workspace_num>` does not express that. For a normal registered project, workspace
number `10` means a numbered checkout, not a static singleton.

If static linked repos remain in scope, they need a separate mechanism:

- keep a machine-readable static/advisory link model;
- document them as direct paths and do not include them in generic `workspace open` finalizer enforcement;
- or add an advisory flag to the opened-workspace marker.

### Open Command Side Effects

Because `workspace open` cleans and updates, using it for arbitrary known projects can save away existing dirty state
before the agent starts editing. That is normally desired for numbered agent workspaces, but it should not be used as a
passive inspection command for shared primary checkouts or static repos.

### Config Context

`sase workspace open` builds its `WorkspaceStore` from `load_merged_config()`, whose local config layer comes from the
current working directory. In normal agent use, the command is run from the primary repo workspace, so the primary
repo's local `sase.yml` config applies. If agents run the command from a different CWD after changing directories, the
workspace-root policy could differ.

Agent instructions should say to run `sase workspace open` from the primary workspace, use the printed path, and avoid
guessing or recomputing paths.

## Minimal Viable Migration

1. Ensure `sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim` have registered ProjectSpecs with correct
   `WORKSPACE_DIR` values.
2. Move the current descriptions into a manually owned AGENTS/memory section that will not be overwritten by
   `sase memory init`.
3. Add a new helper beside `record_opened_sibling()`, for example `record_opened_workspace(ctx, workspace_num, path)`.
4. Call it for every successful `sase workspace open` when `$SASE_ARTIFACTS_DIR` is set.
5. Add `opened_workspaces.json` and continue reading `opened_siblings.json` during migration.
6. Change the finalizer to check dirty opened workspace paths directly.
7. Update TUI diff tracking to read opened workspace paths from artifacts.
8. Keep `SASE_SIBLING_*` env compatibility until `Justfile`, docs, tests, and existing agent workflows no longer need
   it.
9. Remove `sibling_repos` config only after the opened-workspace path has been proven in real agent runs.

## Recommendation

Use this proposal if the goal is to simplify toward "agents explicitly open every non-primary workspace they touch, and
SASE finalizes exactly those opened workspaces."

Do not use it as a complete replacement for linked-repo semantics if you still want SASE to know all related projects at
launch time, generate validated related-repo memory, expose workspace-matched env vars, or handle static singleton repos
as advisory targets.

The most pragmatic path is a hybrid:

- first generalize `opened_siblings.json` into opened workspace tracking;
- make finalizer/diff tracking capable of using opened workspace records directly;
- keep a neutral linked-project model only for discovery, descriptions, static/advisory policy, and compatibility env;
- then decide whether the machine-readable linked-project list is still worth keeping once the opened-workspace path has
  real usage data.

## Open Questions

1. Should linked repos be active SASE projects, hidden lifecycle records, or a new neutral state such as
   `linked`/`related`?
2. Should the finalizer enforce every opened non-primary workspace, or only opened workspaces that match a documented
   allowlist?
3. Should dirty opened workspaces use Git-only checks for parity with current sibling behavior, or provider-neutral VCS
   dirty detection for true "any SASE project" support?
4. How should static singleton repos be represented if `workspace.strategy: none` goes away?
5. Is losing `SASE_SIBLING_REPO_*` env acceptable, or do build/test commands need a replacement env contract?
6. Where should manually maintained linked-project descriptions live so `sase memory init` does not overwrite them?
7. Should `sase workspace open` have a passive/materialize-only mode for read-only review, or is clean/update always the
   intended behavior?
8. Should the marker record only successful opens, or also failed open attempts for debugging/audit?
9. How should retries/follow-up agents inherit or intentionally not inherit opened workspace records?
10. Should finalizer commits across multiple opened repos be one follow-up prompt, separate prompts per repo, or grouped
    by provider/project?
