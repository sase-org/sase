---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Sibling Repos via Workspace-Open Tracking

## Research Request

Evaluate this alternative to configured `sibling_repos`:

- tell agents they can use `sase workspace open -p <project> <workspace_num>` on any SASE project they know about;
- manually document sibling/linked repo names and descriptions in the relevant `AGENTS.md` or memory files;
- track which agents run `sase workspace open`;
- use that tracking data to drive commit finalizer and diff tracking.

This follows the earlier removal research in
[`sibling_repos_removal_consolidated.md`](sibling_repos_removal_consolidated.md).

## Verdict

This is feasible as a migration, but not as a docs-only deletion.

The best part of the proposal is open-driven finalization: SASE should track the concrete workspaces a run actually
opened and let the finalizer consume those paths directly. The current system is already close to that: `sase workspace
open` writes a per-run `opened_siblings.json` marker for configured sibling projects, and that marker already stores the
opened path.

The parts that do not fall out naturally are project registration, launch-time env contracts, generated memory
ownership, static/advisory repo semantics, and pre-open discoverability. Manual prose can tell an agent what to do, but
it cannot create ProjectSpecs, inject env vars, validate path parity, or tell the TUI/finalizer about possible linked
repos before they are opened.

Recommended direction:

1. Generalize the existing open marker first, independent of config removal.
2. Make the finalizer consume opened workspace paths directly.
3. Keep or replace a small declarative layer only for the things runtime opens cannot express: discovery/descriptions,
   registration, static/advisory policy, launch env compatibility, and UI pre-open state.
4. Remove `sibling_repos` only after those contracts have replacements or are intentionally dropped.

## Current Behavior Verified

### `sase workspace open` works for registered projects

`sase workspace open -p <project> <workspace_num>` resolves the target through
`src/sase/main/workspace_handler_context.py::resolve_project_context`. For a normal registered project with a
ProjectSpec containing `WORKSPACE_DIR`, it builds a `WorkspaceStore`, materializes the requested numbered checkout, runs
the same workspace preparation flow used by agents, and prints the path.

The `-p/--project` argument is free-form in `src/sase/main/parser_workspace.py`; there is no hard-coded sibling list.
So the first premise is mechanically true for projects that are already registered with a usable `WORKSPACE_DIR`.

### The current four siblings depend on config seeding

The repo declares `sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim` in `sase.yml` under `sibling_repos`.

When a named project lacks `WORKSPACE_DIR`, `resolve_project_context` falls into
`_materialize_sibling_project_context`, scans the current project's configured `sibling_repos`, and writes hidden
ProjectSpec metadata with `PROJECT_STATE: sibling` and `WORKSPACE_DIR` for the sibling. That means local ProjectSpecs
may already exist after prior use, but they are user-state materialized from config. On a fresh machine, or after
removing the config before registration, `sase workspace open -p sase-core <N>` would fail because prose in memory does
not create the ProjectSpec.

This is the biggest gap in the proposal: "any project they know about" means "any registered project," not "any name
mentioned in AGENTS.md."

### `workspace open` is not a passive path lookup

`sase workspace open` calls `prepare_workspace`, which saves existing changes to a backup diff and updates the checkout
before returning the path. That is the right behavior for a numbered workspace the agent is about to use. It should not
be described as merely "look up a path."

There is a separate `sase workspace path` subcommand for path printing without materializing/preparing, but it does not
serve as the current intent signal and does not create a safe workspace to edit.

### The intent marker already exists

`src/sase/sibling_repos.py::record_opened_sibling` writes
`$SASE_ARTIFACTS_DIR/opened_siblings.json`. The marker is per-run, dedupes by name, and stores both the sibling name and
the opened `workspace_dir`.

Today it is called only when `ctx.is_sibling` is true in `src/sase/main/workspace_handler_list.py::handle_open_clean`.
The finalizer then reads only the opened names through `opened_sibling_names`; it discards the stored path and
re-resolves targets from `SASE_SIBLING_REPOS_JSON` or config.

That shape is narrow but useful. The proposal should generalize this marker instead of trying to infer opens from shell
logs or chat transcripts.

### The finalizer still depends on config/env

`src/sase/llm_provider/commit_finalizer_state.py` currently:

- collects configured sibling targets from `SASE_SIBLING_REPOS_JSON`, falling back to config;
- reads opened sibling names from the artifact marker;
- blocks only dirty `workspace.strategy: suffix` siblings whose names were opened;
- reports `workspace.strategy: none` siblings as advisory without requiring an open marker.

The irreducible datum here is policy, not path. A filesystem path does not tell the finalizer whether a dirty repo
should block completion or be advisory. If static singleton repos and read-only/nonblocking opens remain in scope, the
opened-workspace marker needs to carry a policy bit such as `dirty_policy: blocking|advisory`.

### Workspace number is available, but not as one universal env var

Generated memory tells agents to derive `<workspace_num>` from the directory they were started in. That remains a safe
instruction.

There is no generic `SASE_WORKSPACE_NUM`. VCS launches can expose provider-specific env such as
`SASE_GIT_WORKSPACE_NUM` or `SASE_CD_WORKSPACE_NUM`, and the finalizer also checks those. Deferred agents refresh those
after they claim a real workspace. A manual-doc migration should keep the cwd-based instruction because it works across
more launch shapes.

### Generated memory is owned by code

`memory/sase.md` is generated from `sibling_repos` by `src/sase/main/init_memory/config.py` and
`src/sase/main/init_memory/roots.py`. The current generated section lists the four related repos and the exact
`sase workspace open` command. The memory validation path compares expected generated content against files on disk.

Therefore "move descriptions to memory manually" is feasible only if the generated section is removed, moved, or
replaced with a manual-owned file. Hand-editing the generated output is not a durable migration.

### Launch env still matters for local builds

Launch resolution emits:

- `SASE_SIBLING_REPOS_JSON`
- `SASE_SIBLING_REPO_<NAME>_DIR`
- `SASE_SIBLING_REPO_<NAME>_PRIMARY_DIR`

The repo `Justfile` uses `SASE_SIBLING_REPO_SASE_CORE_DIR` as the workspace-matched `sase-core` fallback for Rust builds.
CI sets `SASE_CORE_DIR` explicitly, so CI is not the problem. The risk is local agent work: without sibling env, an
agent may build against `../sase-core` or nothing unless it first opens `sase-core` and exports `SASE_CORE_DIR` itself.

Manual prose can tell agents to do that, but it is weaker than launch-time injection.

## Feasibility by Pillar

### P1: Let agents open any known SASE project

Feasible with a registration step.

The implementation already supports `sase workspace open -p <registered-project> <N>`. The migration has to ensure each
linked repo has durable ProjectSpec state with a correct `WORKSPACE_DIR` before removing `sibling_repos`.

Open design choices:

- register linked repos as normal active projects;
- keep hidden `PROJECT_STATE: sibling` records but create them eagerly instead of lazily;
- add a neutral lifecycle state such as `linked`;
- store links in ProjectSpec metadata rather than project-local config.

Promoting them to active projects increases project-list, launch-picker, TUI, and doctor surface area. Keeping them
hidden preserves current UX but requires an explicit supported contract for opening hidden linked projects.

### P2: Move descriptions to AGENTS.md or memory

Feasible, but not free.

If the descriptions live in a generated file, the generator must be changed. If they live in `AGENTS.md` or a separate
manual memory file, `sase memory init` must not overwrite them. A useful split is:

- manual prose for agent-facing "what these repos are and when to use them";
- machine-readable project registration for "where they are and how to open them";
- optional generated snippets only for compatibility or validation.

The drawback is loss of validation. Today config requires name/path/description and reports incomplete memory inputs.
Manual docs can drift unless a new checker compares documented links against registered ProjectSpecs or a neutral
linked-project registry.

### P3: Track `sase workspace open` and feed finalizer/diff tracking

Feasible and probably an improvement even if a declarative link model survives.

The best target shape is a new marker, e.g. `opened_workspaces.json` or `opened_linked_workspaces.json`, written by the
CLI whenever `sase workspace open` succeeds under `$SASE_ARTIFACTS_DIR`:

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
      "dirty_policy": "blocking",
      "opened_at": "2026-06-20T00:00:00Z"
    }
  ]
}
```

Then finalizer state can:

1. read opened workspace records from the artifacts dir;
2. exclude the main project workspace and optionally primary-project sibling workspaces;
3. run dirty detection on each recorded path;
4. block or advise according to `dirty_policy`;
5. keep reading legacy `opened_siblings.json` during migration.

This deletes complexity from finalizer target discovery because it no longer has to reconstruct opened paths from env or
config. It also makes diff tracking more precise after the agent opens a repo: the UI can display exactly the checkout
the run prepared, not a guessed related path.

The behavior change is important: before open, SASE no longer has a machine-readable list of related repos unless a
declarative layer remains. If the TUI should show possible linked repos before they are opened, manual docs are
insufficient.

## What You Might Be Missing

1. The four current siblings are not safely covered by "known about" unless they are registered outside
   `sibling_repos`. Existing local hidden ProjectSpecs are not enough for a migration because they are mutable user
   state seeded by the config you would remove.

2. Workspace-number parity becomes a registration invariant. Today config seeding keeps `sase_10` and `sase-core_10`
   aligned through the same `WorkspaceStore` policy. If linked repos become independent projects, their `WORKSPACE_DIR`,
   project key, and workspace root policy must be pinned so `sase workspace open -p sase-core 10` resolves to the same
   physical checkout SASE expects.

3. Manual docs cannot replace launch env injection. If local agents need workspace-matched Rust builds, keep a neutral
   env contract or teach build commands to resolve/open `sase-core` automatically.

4. Static singleton support is lost unless policy survives somewhere. `workspace.strategy: none` currently means
   "check this static path as advisory." Generic workspace-open tracking cannot infer that from a path.

5. Tracking every open widens the finalizer's scope. An agent might open an unrelated project to inspect it. If the repo
   is dirty, should that block the run? Blocking every dirty opened repo is simple and safe, but it changes the meaning
   from "declared relationship was touched" to "anything opened was touched." Advisory-by-default for undeclared opens is
   another viable policy, but then a declaration has reappeared.

6. The command has side effects. `sase workspace open` cleans and updates; that is fine for isolated numbered
   workspaces, but risky as a general read-only inspection habit. Agent instructions should say to use the printed path
   as the prepared workspace, not to run it just to discover arbitrary paths.

7. Provider neutrality is unresolved. Current sibling finalizer checks use Git status. If the new model truly means
   "any SASE project," dirty detection should eventually dispatch through the project's VCS provider rather than assume
   Git.

8. Pre-open UI/audit data goes away unless replaced. `agent_meta["sibling_repos"]` is not heavily consumed today, but it
   is still a launch-time record of what SASE resolved for the run. Open-tracking alone only knows about repos after the
   agent opens them.

## Recommended Migration

1. Add a generic opened-workspace marker and keep writing the legacy `opened_siblings.json` for compatibility.
2. Write the marker for every successful `sase workspace open` under `$SASE_ARTIFACTS_DIR`; include concrete paths,
   project identity, workspace number, and dirty policy.
3. Update the finalizer to consume opened workspace records directly, while still supporting current sibling config/env
   as a fallback during migration.
4. Update live/TUI diff tracking to use opened workspace paths after they appear; keep any pre-open linked-repo display
   backed by machine-readable links if that UX is desired.
5. Register `sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim` as durable projects with correct
   `WORKSPACE_DIR` and workspace root behavior.
6. Decide whether linked repos should be active, inactive, hidden `sibling`, or a new `linked` lifecycle state.
7. Move descriptions into a manual-owned `AGENTS.md` or memory location, or replace the generator with a neutral
   linked-project generator.
8. Preserve `SASE_SIBLING_*` env vars as compatibility aliases until the `Justfile`, tests, docs, and agent workflows
   use a new neutral env contract or no env contract.
9. Remove `sibling_repos` config only after opened-workspace finalization has real usage data and the registration/env
   decisions are settled.

The sequencing matters. Landing open-driven finalization first gives immediate value and shows how much declaration is
still needed in practice.

## Hard Open Questions

1. Is `sibling_repos` intended as a user-facing SASE feature, or only as internal plumbing for this repo? If it is
   product-facing, manual docs are an onboarding regression.

2. Do local agents actually rely on workspace-matched `sase-core` builds? If yes, replacing or preserving launch env is
   required. If no, the env loss is less important.

3. Is `workspace.strategy: none` still needed for static shared repos? If yes, pure open tracking is insufficient
   without a policy field or declaration.

4. What is the durable registration mechanism for linked repos: `sase project add`, eager hidden-spec materialization,
   ProjectSpec link metadata, or a renamed config key?

5. Should dirty non-declared opened repos block finalization, advise only, or be ignored unless opened with an explicit
   "track this" mode?

6. Should `sase workspace open` gain a separate read-only/passive mode for review-only access, or should "open" remain
   the explicit prepare-and-track intent signal?

7. Should opened workspace records be inherited by retries/follow-up agents, or should each agent run have an isolated
   open set as it does today?

## Bottom Line

The proposal is coherent if the desired product rule is: "agents explicitly open every non-primary workspace they touch,
and SASE finalizes exactly those opened workspaces."

It is not a full replacement for linked-repo semantics if SASE should know related projects at launch, validate
descriptions, inject workspace-matched build env, preserve static advisory repos, or show possible related repos before
they are opened.

The strongest design is hybrid: generalize open tracking now, then either keep a renamed `linked_repositories` model for
discovery/policy/env or deliberately drop those behaviors after answering the open questions above.
