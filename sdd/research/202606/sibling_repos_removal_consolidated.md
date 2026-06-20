---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Removing Sibling Repos From SASE

## Research Request

Understand the consequences of removing the concept of sibling repos from SASE. Is it feasible without losing
functionality? Is it advisable? End with a recommended solution.

## Executive Summary

Do not delete the capability. Delete or deprecate the "sibling repos" framing.

The current `sibling_repos` feature is load-bearing for SASE's own split-repository workflow. It gives an agent running
in `sase_<N>` the matching checkout for related repos such as `sase-core_<N>`, exports that mapping to the launched
agent, records the mapping in agent metadata, renders agent-facing memory instructions, and lets the commit finalizer
catch dirty related checkouts that the run intentionally opened.

Wholesale removal is mechanically feasible because the implementation is young, Python-owned, and fairly bounded. It is
not feasible without losing functionality unless a replacement keeps the same contracts: relationship declarations,
workspace-number matching, launch metadata, an opened-workspace intent marker, static singleton handling, and
cross-repo finalizer behavior.

The best path is to rename and generalize the feature as `linked_repos`, `linked_repositories`, or `related_projects`,
with `sibling_repos` kept as a compatibility alias during migration. Internally, model these as number-aligned linked
projects rather than as a special "sibling" kind.

## Scope And Disambiguation

The word "sibling" is overloaded in this codebase. This research covers configured sibling repositories only:
`sibling_repos` entries in config, `src/sase/sibling_repos.py`, related launch env, workspace-open behavior, generated
memory, and commit finalization.

Other sibling concepts are unrelated and should not be removed as part of this decision:

- agent siblings and retry-family navigation in the TUI;
- ChangeSpec sibling families and status-state-machine sibling reverts;
- filesystem siblings mentioned by docs or path discovery;
- `PROJECT_STATE: sibling` as a hidden ProjectSpec state, except where it supports configured related repos.

This naming collision is real. Raw `rg sibling` counts exaggerate the size of the repo-sibling feature because many hits
belong to agent families or ChangeSpec families.

## What Sibling Repos Do Today

### Configured Project Relationships

The public config key is `sibling_repos`, defaulting to `[]` in `src/sase/default_config.yml`. The schema requires
`name`, `path`, and `description`, with optional `workspace.strategy` values of `suffix` or `none`.

This repository uses the feature directly in `sase.yml` for:

- `sase-core`
- `sase-github`
- `sase-telegram`
- `sase-nvim`

The required `description` is not just documentation. `sase memory init` consumes it when rendering `memory/sase.md`, so
agents receive purpose-specific guidance for each related repo.

### Workspace-Number Parity

The core invariant is:

> An agent in primary workspace `N` should use related repo workspace `N`.

For a default `workspace.strategy: suffix` sibling, `src/sase/sibling_repos.py` resolves the configured primary path
relative to the primary checkout, then maps workspace `N` to the corresponding related checkout through the workspace
provider. Under adjacent roots this looks like `../sase-core_10`; under managed state roots it can live elsewhere.

For `workspace.strategy: none`, SASE exposes the primary path directly. This supports static singleton repos such as
dotfiles or other non-cloneable/shared state.

### Launch Env And Metadata

Launch resolution emits:

- `SASE_SIBLING_REPOS_JSON`
- `SASE_SIBLING_REPO_<NAME>_DIR`
- `SASE_SIBLING_REPO_<NAME>_PRIMARY_DIR`

`src/sase/agent/launch_spawn.py` scrubs inherited sibling env and applies a freshly resolved map for normal launches.
Deferred-workspace agents start empty and recompute the mapping after they claim a real workspace in
`src/sase/axe/run_agent_phases.py` and `src/sase/axe/run_agent_runner_setup.py`. `src/sase/axe/run_agent_directives.py`
copies the resolved metadata into `agent_meta.json`.

This gives both the running agent and later audit/debug tools the exact related-checkout map used for the run.

### Workspace Open And Intent Tracking

`sase workspace open -p <sibling> <workspace_num>` is not just a path helper. When the named project is a configured
sibling, `src/sase/main/workspace_handler_context.py` can lazily materialize a hidden ProjectSpec with
`PROJECT_STATE: sibling` and the sibling repo's `WORKSPACE_DIR`.

When that open happens from an agent run, `src/sase/main/workspace_handler_list.py` records it through
`opened_siblings.json`. This marker is the finalizer's answer to "which related workspaces did this run intentionally
open?"

That distinction matters. It avoids both false negatives and false positives:

- a dirty opened numbered sibling is enforced;
- a dirty configured sibling that was never opened is ignored;
- a dirty static singleton can be reported as advisory instead of blocking.

### Commit Finalizer Coverage

The shared commit finalizer reads sibling targets from `SASE_SIBLING_REPOS_JSON`, falling back to config when env is
absent. For numbered siblings, it checks only names found in `opened_siblings.json`. For static `none` siblings, it
reports advisory dirty state without making finalization fail.

Tests in `tests/llm_provider/test_commit_finalizer_siblings.py` pin the key behavior:

- dirty configured sibling without an open marker is ignored;
- dirty configured sibling with an open marker triggers a follow-up turn;
- dirty primary sibling checkout is ignored when a numbered workspace checkout is configured;
- static `none` siblings are advisory;
- multiple opened siblings are listed and rechecked;
- unopened dirty siblings are omitted.

### Generated Memory And Build Ergonomics

`src/sase/main/init_memory/roots.py` renders the `## Sibling Repositories` section in `memory/sase.md`, including the
instruction to run:

```bash
sase workspace open -p <sibling_repo> <workspace_num>
```

This is why agents in this repository are told how to open `sase-core`, `sase-github`, `sase-telegram`, and `sase-nvim`
without guessing paths.

The `Justfile` also consumes the env contract:

```just
sase_core_dir := env_var_or_default("SASE_CORE_DIR", env_var_or_default("SASE_SIBLING_REPO_SASE_CORE_DIR", env_var_or_default("SASE_SIBLING_REPO_CORE_DIR", "../sase-core")))
```

So a SASE-launched agent can build/install against the workspace-matched `sase-core` checkout instead of falling back to
the shared `../sase-core`.

## What Would Break On Direct Deletion

### Concurrent Multi-Repo Isolation

Without relationship-aware workspace matching, agents working in `sase_10` and `sase_20` would have no reliable
tool-provided path to `sase-core_10` and `sase-core_20`. They would fall back to prompts, `../sase-core`, shell memory,
or manual `sase workspace open` usage with no primary-to-related relationship.

That is exactly the failure mode the feature prevents: concurrent agents accidentally editing the same related checkout
or the wrong numbered checkout.

### Cross-Repo Commit Safety

The finalizer would stop seeing dirty related repos touched by the run. An agent could edit both `sase` and
`sase-core`, commit only `sase`, and finish with the core change left dirty unless the user or agent remembered to
commit it manually.

This is a functional regression in ChangeSpec hygiene, not just a UX regression.

### Agent Guidance And Auditability

Generated memory would stop listing related repos and the workspace-open command. Launched agents would lose the JSON
map and per-repo env vars. `agent_meta.json` would no longer capture the resolved relationship map for later inspection.

### Static Singleton Advisory Behavior

Plain projects do not reproduce the current `workspace.strategy: none` semantics. Static shared repos need different
treatment: expose the path, report dirty state if relevant, but do not fail finalization by default because the dirty
state may predate the run or be shared with the user's normal workflow.

### Hidden Bookkeeping State

Configured related repos currently become hidden `PROJECT_STATE: sibling` records when needed. Promoting all of them to
ordinary active projects would make launch pickers and project lists noisier. Making them inactive would require a new
way for workspace-open and finalizer logic to discover them.

## Feasibility

Direct removal is technically feasible. The core module is `src/sase/sibling_repos.py`, introduced on 2026-05-21, with a
short history and no direct Rust implementation. The primary source touch points are:

- launch env resolution and scrubbing;
- deferred-workspace re-resolution;
- `agent_meta.json` metadata;
- commit finalizer target discovery and prompting;
- `workspace open -p` sibling ProjectSpec materialization and open-marker recording;
- init-memory parsing/rendering;
- config defaults, schema, docs, and tests.

That makes removal a bounded change, but not a behavior-preserving one.

A replacement can preserve functionality if it keeps these contracts:

- project-local relationship declarations with stable aliases and descriptions;
- relative paths resolved from the primary checkout, not from an arbitrary numbered workspace;
- workspace matching through `WorkspaceStore` or equivalent provider logic;
- support for static singleton relationships;
- resolved launch JSON/env metadata;
- refreshed metadata after deferred workspace claims;
- an opened related workspace marker;
- finalizer enforcement only for opened numbered Git relationships;
- advisory finalizer treatment for static relationships;
- hidden bookkeeping records that do not pollute normal launch pickers.

## Replacement Options

### 1. Delete And Use Raw Paths

This is the simplest implementation and the worst behavior. Users and agents could manually `cd ../sase-core` or pass
raw paths, but SASE would lose workspace-number matching, metadata, generated guidance, finalizer coverage, static
advisory handling, and opened-workspace intent tracking.

This option is only acceptable if SASE intentionally gives up coordinated multi-repo agent sessions.

### 2. Make Every Related Repo A Normal Project

Every repo can already be a SASE project with its own workspace store and launches. That is useful, but insufficient by
itself. The missing piece is the relationship "this `sase_10` run intentionally opened `sase-core_10`."

Normal projects should remain the substrate. A linked-repo model should be a relationship policy on top of projects,
not a replacement for projects.

### 3. Rename To Linked Repositories Or Related Projects

This keeps current behavior while removing the overloaded public concept.

Example shape:

```yaml
linked_repositories:
  - name: sase-core
    path: ../sase-core
    description: Shared Rust core backend for SASE domain behavior and cross-frontend APIs.
    workspace:
      strategy: matched
  - name: dotfiles
    path: ~/.local/share/chezmoi
    description: User dotfiles source.
    workspace:
      strategy: static
```

Compatibility mapping:

- `sibling_repos` -> `linked_repositories`
- `suffix` -> `matched`
- `none` -> `static`
- `opened_siblings.json` -> `opened_linked_workspaces.json`, with both read during migration;
- `SASE_SIBLING_REPOS_JSON` and `SASE_SIBLING_REPO_*` kept as aliases until generated memory, Justfile helpers, docs,
  and existing agents have moved.

This is feasible without losing functionality.

### 4. Store Project Links In ProjectSpec

Longer term, relationships could live in ProjectSpec metadata rather than user config. That may fit future provider
identity and remote execution better, but it is a larger migration because ProjectSpecs are mutable state and need
locking, lifecycle rules, and backward compatibility.

This is a future storage candidate, not the first step.

## Advisability

It is advisable to remove the public "sibling repo" concept because:

- the term collides with agent siblings and ChangeSpec siblings;
- related repos are not necessarily filesystem siblings;
- managed workspace roots mean resolved paths may not be adjacent;
- future remote execution needs provider identity and materialization policy, not a local sibling path assumption;
- the hidden ProjectSpec behavior already implies these are linked projects.

It is not advisable to remove the capability because:

- SASE's own repo depends on it for four related repositories;
- the `Justfile` consumes the workspace-matched `sase-core` env var;
- workspace-number parity is easy to get wrong manually;
- finalizer coverage prevents real cross-repo commit mistakes;
- generated memory is useful operational guidance;
- static singleton advisory behavior is not reproduced by ordinary projects.

## Recommended Solution

Keep the capability and migrate the name/model.

1. Introduce an internal neutral model such as `LinkedRepository`, `RelatedWorkspace`, or `ProjectLink`.
2. Parse existing `sibling_repos` into that model unchanged.
3. Add a new public key, preferably `linked_repositories` or `linked_repos`; keep `sibling_repos` as a deprecated alias
   for at least one release line.
4. Rename generated memory to "Linked Repositories" or "Related Repositories."
5. Add new env vars such as `SASE_LINKED_REPOSITORIES_JSON` and `SASE_LINKED_REPO_<NAME>_DIR`, while continuing to emit
   the old `SASE_SIBLING_*` names during migration.
6. Replace `opened_siblings.json` with a neutral marker such as `opened_linked_workspaces.json`, but read both during
   migration.
7. Preserve the important semantics: matched workspace numbers, static singleton support, launch metadata,
   deferred-workspace refresh, hidden bookkeeping records, and finalizer enforcement/advisory behavior.
8. Only after the new model is proven equivalent, warn on `sibling_repos` and remove it in a later breaking release.

Recommended final answer: do not remove sibling-repo functionality. Deprecate the overloaded name, reframe it as
number-aligned linked projects, and migrate in compatibility layers so SASE keeps the workflow safety that the current
feature provides.
