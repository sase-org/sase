---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Removing Sibling Repos From SASE

## Question

What happens if SASE removes the concept of sibling repositories? Is that feasible without losing functionality, and is
it advisable?

This note treats "sibling repos" as the configured `sibling_repos` feature: related repositories declared in `sase.yml`,
resolved into workspace-matched paths, exposed to launched agents, and checked by the commit finalizer. SASE also uses
the word "sibling" for ChangeSpec families, agent-family navigation, adjacent filesystem paths, and ProjectSpec
migration. Those other concepts should not be removed as part of this decision.

## Summary

Removing the current user-facing concept is reasonable. Removing the capability is not.

The current `sibling_repos` feature is doing real work:

- it defines project-local cross-repository relationships;
- it resolves relative paths from the primary checkout, not from the current numbered workspace;
- it maps a primary repo workspace number to the corresponding related repo workspace;
- it exports `SASE_SIBLING_REPOS_JSON` and per-repo convenience environment variables;
- it records the resolved map in agent metadata;
- it lets deferred `%wait` agents refresh the map after a real workspace is claimed;
- it lets `sase workspace open -p <repo> <num>` lazily materialize a hidden ProjectSpec for the related repo;
- it writes `opened_siblings.json`, which tells the commit finalizer that a numbered related workspace was intentionally
  opened by this run;
- it lets the commit finalizer enforce dirty numbered Git related workspaces and treat static singleton repos as
  advisory;
- it feeds generated `memory/sase.md` with the human description and workspace-open instructions agents rely on.

So a direct deletion would lose functionality. A replacement can avoid that loss, but only if it keeps a relationship
model, a workspace-number mapping, launch metadata, an "opened related workspace" audit marker, and finalizer behavior.

The right move is to stop calling this capability "sibling repos" and replace it with a more explicit related-project or
linked-workspace model. Keep `sibling_repos` as a compatibility input until the replacement proves equivalent.

## Current Behavior

### Configuration

The default config sets `sibling_repos: []` in `src/sase/default_config.yml`. This project declares related checkouts in
`sase.yml`: `sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim`.

`config/sase.schema.json` defines the public shape. Each entry requires:

- `name`
- `path`
- `description`

and optionally accepts:

- `workspace.strategy: suffix`
- `workspace.strategy: none`

The required `description` is not decorative. `sase memory init` uses it to generate agent-facing memory, so agents know
what each related repo is for.

### Resolution

`src/sase/sibling_repos.py` is the core Python resolver. It:

- reads merged config plus the primary checkout's local `sase.yml`;
- deduplicates entries by name, path, and strategy;
- resolves relative paths from the primary workspace, not from `sase_<N>`;
- validates that the primary related path exists;
- materializes or resolves a workspace-matched checkout for `suffix` entries;
- preserves the primary path for `none` entries;
- exports JSON and env vars such as `SASE_SIBLING_REPO_SASE_CORE_DIR`.

For `workspace.strategy: suffix`, workspace `0` and `1` use the primary checkout. Higher numbers use
`ensure_workspace_checkout()`, which delegates to `WorkspaceStore`. Under adjacent layout this is the familiar
`../sase-core_10`; under managed `xdg-state` roots it can be a non-adjacent state-root path.

For `workspace.strategy: none`, the primary path is always exposed. This is how singleton repos such as dotfiles can be
shown to agents without pretending concurrent agents have isolated checkouts.

### Launch And Runtime Metadata

`src/sase/agent/launch_spawn.py` resolves sibling repos after the main workspace number is known. It scrubs stale
inherited sibling env, applies the fresh resolved map, and launches the runner with those values.

Deferred-workspace agents intentionally start with an empty sibling map. Once `claim_deferred_workspace()` assigns a
real workspace, `refresh_sibling_repos_for_workspace()` recomputes the mapping, updates `os.environ`, and writes
`agent_meta.json`.

`src/sase/axe/run_agent_directives.py` also copies the JSON metadata from env into `agent_meta.json`, making the
resolved relationship auditable after the run.

### Workspace Open And Hidden Project Records

`sase workspace open -p <sibling> <workspace_num>` is more than a path helper.

`src/sase/main/workspace_handler_context.py` can lazily materialize ProjectSpec metadata for a configured sibling repo.
It writes `PROJECT_STATE: sibling` plus `WORKSPACE_DIR` for that repo. This keeps related repo records available for
workspace materialization while hiding them from normal launch pickers and broad known-project lookup.

`src/sase/main/workspace_handler_list.py` records opened sibling projects into `opened_siblings.json` when the command
is run inside an agent with `SASE_ARTIFACTS_DIR` set.

This is an important safety signal. It means the finalizer enforces only configured numbered related workspaces that the
agent actually opened, not every nearby repo and not every configured related repo that happens to be dirty.

### Commit Finalizer

`src/sase/llm_provider/commit_finalizer_state.py` reads related repo targets from `SASE_SIBLING_REPOS_JSON`, falling
back to config when env is absent. It then:

- enforces `suffix` targets only if their name appears in `opened_siblings.json`;
- checks dirty related repos with `git status`;
- treats `workspace.strategy: none` targets as advisory instead of blocking;
- ignores dirty primary related checkouts when the configured workspace path is a numbered checkout.

`src/sase/llm_provider/commit_finalizer_prompting.py` generates follow-up instructions that tell the agent to `cd` into
the exact related workspace before using `/sase_git_commit`.

The tests in `tests/llm_provider/test_commit_finalizer_siblings.py` pin these semantics:

- dirty configured sibling without an open marker is ignored;
- dirty configured sibling with an open marker triggers a follow-up;
- dirty primary sibling checkout is ignored when a numbered workspace is configured;
- static `none` sibling changes are advisory and do not fail finalization;
- multiple opened sibling repos are listed and rechecked;
- unopened dirty configured siblings are omitted.

### Generated Memory

`src/sase/main/init_memory/config.py` parses `sibling_repos` and requires descriptions.
`src/sase/main/init_memory/roots.py` renders the generated `memory/sase.md` section listing configured sibling
repositories and the `sase workspace open` instruction when at least one entry uses numbered workspace resolution.

This is why the current `memory/sase.md` tells agents to open `sase-core`, `sase-github`, `sase-telegram`, and
`sase-nvim` through `sase workspace open -p <sibling_repo> <workspace_num>`.

### SASE Development Ergonomics

The SASE repository is deliberately split:

- `sase-core` owns shared Rust backend behavior, the PyO3 package, the xprompt LSP, and mobile gateway pieces.
- `sase-github` owns GitHub VCS and workspace provider behavior.
- `sase-telegram` owns Telegram integration.
- `sase-nvim` owns the Neovim integration.

The `Justfile` also consumes `SASE_SIBLING_REPO_SASE_CORE_DIR` and `SASE_SIBLING_REPO_CORE_DIR` as local development
overrides for the Rust core checkout, falling back to `../sase-core`.

Some older code still hard-codes `../sase-core`, notably the xprompt LSP and mobile gateway binary discovery paths.
Those hard-coded paths are a reason to improve the model, not evidence that the model is unnecessary.

## What Would Break If We Deleted It

### Cross-Repo Agent Guidance Would Disappear

Agents would no longer receive a resolved related repo map, env vars, or generated memory instructions. Prompts would
fall back to ad hoc paths like `../sase-core`, which are wrong under managed workspace roots and unsafe in numbered
workspace sessions.

### Workspace-Number Isolation Would Be Lost

The core invariant is "if the primary agent is in workspace `N`, related repo edits go to that related repo's workspace
`N`." Deleting `sibling_repos` removes the only project-local mapping from the primary workspace number to the related
repo workspace.

Normal projects can independently materialize `core_10`, but there is no relationship tying `sase_10` to `core_10`.
Without that relationship, agents can easily edit the primary checkout, the wrong numbered checkout, or a managed-root
path they do not know exists.

### Commit Finalizer Coverage Would Regress

The finalizer currently catches a specific class of multi-repo mistakes: an agent opens a related workspace, edits it,
and forgets to commit it. If `sibling_repos` is removed without replacement, that dirty repo becomes invisible to the
main agent finalizer.

The system would still detect main workspace changes, but it would no longer provide cross-repo follow-up prompts,
`/sase_git_commit` instructions for related repos, or advisory handling for static singleton repos.

### The Opened-Workspace Intent Signal Would Vanish

`opened_siblings.json` is a simple but useful answer to "which related repos did this run intentionally touch?" It
prevents both under-enforcement and over-enforcement:

- under-enforcement: dirty opened related repo is caught;
- over-enforcement: unrelated dirty configured repo is ignored unless opened;
- static singleton dirty state is advisory.

Deleting sibling repos without replacing this marker means the finalizer must either scan too broadly, scan too
narrowly, or give up on cross-repo enforcement.

### Static Singleton Repos Would Lose Their Advisory Path

`workspace.strategy: none` handles repos where a numbered clone would be wrong or impossible. The current finalizer can
tell an agent about dirty singleton state without failing the run if the state was not created by that agent.

That distinction matters for personal dotfiles, shared notes, and any non-cloneable external state. Treating them as
normal active projects does not reproduce the advisory behavior.

### Project Discovery Would Get Noisier Or Less Useful

`PROJECT_STATE: sibling` currently hides configured related repo records from default launch pickers and broad
known-project lookup. If related repos become ordinary active projects, they will appear in places where users usually
want launch targets, not bookkeeping records. If they become inactive projects, workspace-open flows and finalizer
intent tracking need another way to find them.

### Documentation And Tests Have A Large Blast Radius

There are focused tests for resolver behavior, spawn env scrubbing, deferred workspace refresh, workspace-open sibling
ProjectSpec creation, memory generation, schema validation, and commit finalizer semantics. Docs under
`docs/configuration.md`, `docs/commit_workflows.md`, `docs/project_spec.md`, `docs/workspace.md`, `docs/init.md`, and
`docs/llms.md` all describe current behavior.

This is not a tiny rename. It is a public model with launch, workspace, finalizer, memory, docs, and tests attached.

## What Functionality Is Actually Redundant

Some of the current implementation is duplicative or confusing:

- A related repo becomes a hidden ProjectSpec anyway, so it is already partly a project.
- `sibling` is overloaded across ChangeSpecs, agent navigation, filesystem siblings, and related repositories.
- The path-backed config is too local for future remote/Apollo execution.
- The relation is named by local path and alias, not by provider-normalized project identity.
- Older direct `../sase-core` discovery paths still exist.
- There is no `sase sibling add/list/remove` onboarding command, so users hand-edit YAML.

These are arguments for reworking the abstraction. They are not arguments for dropping the capability.

## Replacement Options

### Option 1: Delete `sibling_repos` And Use Raw Paths

Users and agents could use `#cd:/path`, `#cd:../repo`, shell `cd`, or hand-written prompts.

This is technically easy, but it loses the most functionality:

- no workspace-number mapping;
- no launch env map;
- no generated memory;
- no finalizer enforcement;
- no static advisory model;
- no opened related workspace marker;
- no project-local relationship metadata.

This option is not viable if the goal is to keep current multi-repo behavior.

### Option 2: Promote Every Related Repo To A Normal Active Project

Each repo can already be a SASE project with its own `WORKSPACE_DIR`, lifecycle, aliases, workspaces, artifacts, and
launches.

This keeps independent work on each repo. It does not preserve "this primary run intentionally opened repo X's matching
workspace." The finalizer for a SASE agent in `sase_10` still needs relationship metadata to know that `sase-core_10` is
in scope for that run.

This is useful as part of a replacement, but insufficient by itself.

### Option 3: Keep Capability, Rename To Related Projects

Introduce a more explicit model such as:

```yaml
related_projects:
  - name: core
    project: sase-core
    path: ../sase-core
    description: Shared Rust backend/domain behavior.
    workspace:
      strategy: matched
  - name: dotfiles
    path: ~/.local/share/chezmoi
    description: User dotfiles source.
    workspace:
      strategy: static
```

This model can preserve current behavior while dropping the overloaded "sibling repo" terminology. Over time, `project`
or provider refs can become the primary identity and `path` can become one way to locate the primary checkout.

Current `sibling_repos` entries can be parsed into this internal model as a compatibility alias:

- `workspace.strategy: suffix` maps to `workspace.strategy: matched`;
- `workspace.strategy: none` maps to `workspace.strategy: static`;
- `name`, `path`, and `description` keep their meanings.

This option is feasible without losing functionality.

### Option 4: Model Relationships As Project Links In ProjectSpec

Instead of config, store links in ProjectSpec metadata, for example:

```text
PROJECT_LINKS:
  core: project=sase-core, strategy=matched
  dotfiles: path=~/.local/share/chezmoi, strategy=static
```

This would colocate relationships with project identity and make them easier for Rust core to own. But it also turns a
currently user-authored config concern into a mutable ProjectSpec concern, and it would need careful locking and
migration rules. It is a better future storage candidate than a first migration step.

### Option 5: Package-Family Metadata Only

For SASE itself, package-family metadata could know that `sase`, `sase-core`, `sase-github`, `sase-telegram`, and
`sase-nvim` are related. That would help release coordination and docs, but it would not solve generic user projects or
static singleton repos.

This can complement related projects, but it cannot replace them.

## Feasibility

### Direct Removal

Direct removal is technically feasible but functionally lossy.

The code to delete is mostly local:

- `src/sase/sibling_repos.py`
- launch integration in `src/sase/agent/launch_spawn.py`
- deferred refresh in `src/sase/axe/run_agent_runner_setup.py` and `src/sase/axe/run_agent_phases.py`
- finalizer sibling target collection and prompting
- workspace-open hidden sibling materialization and opened marker recording
- init-memory sibling rendering
- schema and docs
- tests around all of the above

But after that deletion, SASE would no longer have an equivalent way to run and finalize multi-repo work from a single
agent session. That is a real regression.

### Replacement Without Loss

Replacement is feasible if the new model keeps these contracts:

- relationship declarations are project-local and can also come from user/plugin config;
- each relationship has a stable alias and human description;
- paths resolve from the primary workspace;
- workspace matching uses `WorkspaceStore`, not ad hoc string suffixes;
- static singleton relationships stay supported;
- launch exports a machine-readable related-workspace JSON map;
- agent metadata records the resolved map;
- deferred workspaces refresh after the real workspace is claimed;
- `workspace open` records an opened related workspace marker;
- the finalizer enforces only opened matched Git relationships and treats static relationships as advisory;
- hidden bookkeeping records do not pollute normal launch pickers.

The current code already implements most of this. A replacement can be staged by adding an internal "related workspace"
model, routing `sibling_repos` through it, then exposing a new public config name.

## Is It Advisable?

It is advisable to remove or deprecate the term "sibling repo" from the public model.

Reasons:

- "sibling" is overloaded in the codebase and docs.
- The relationship is not necessarily a filesystem sibling.
- Managed workspace roots mean the resolved path may not be adjacent.
- Future remote execution needs provider identity and host-local materialization, not local sibling paths.
- Hidden ProjectSpec records already imply these are related projects, not a separate kind of repository.

It is not advisable to delete the capability now.

Reasons:

- The current SASE split-repo workflow depends on it.
- The finalizer protection is valuable and specific.
- The generated memory is useful operational guidance.
- Static singleton behavior is not covered by normal projects.
- A direct deletion would make agents more likely to edit the wrong checkout.
- Apollo/remote work becomes harder without a relationship model, not easier.

The best path is consolidation, not removal.

## Migration Shape

1. Add an internal neutral type, probably `RelatedWorkspace` or `ProjectLink`, with fields equivalent to today's
   resolved sibling record.
2. Parse current `sibling_repos` into that type unchanged.
3. Add a new public config key such as `related_projects` or `linked_repositories`.
4. Let both config keys work for one release line. If both are present, merge and dedupe with a clear precedence rule.
5. Rename environment variables only after adding compatibility aliases. Keep `SASE_SIBLING_REPOS_JSON` until all
   generated skills, Justfile helpers, docs, and existing agents have migrated.
6. Replace `opened_siblings.json` with `opened_related_workspaces.json`, but read both during migration.
7. Decide whether `PROJECT_STATE: sibling` should remain a hidden bookkeeping state or become a more neutral
   `PROJECT_STATE: linked`. This likely belongs in `sase-core` because lifecycle parsing is already Rust-owned.
8. Migrate docs and generated memory text to say "related repositories" or "linked repositories."
9. Keep static singleton advisory behavior intact.
10. Only after compatibility is proven, warn on `sibling_repos` and remove it in a later breaking release.

## Recommended Solution

Do not remove sibling-repo functionality. Remove the public concept by replacing it with a generalized related-project
or linked-workspace model, while keeping `sibling_repos` as a compatibility alias during migration.

The replacement should preserve the current core contracts: workspace-number matching, static singleton support,
resolved launch metadata, generated memory descriptions, explicit `workspace open` intent markers, and commit-finalizer
enforcement/advisory behavior. Internally, the model should be named around relationships, not siblings, and should be
designed to grow from path-backed checkouts into provider-identity-backed related projects for future remote execution.

Short version: deprecate the name, keep the capability, and migrate toward `related_projects` or `linked_repositories`
rather than deleting the feature.
