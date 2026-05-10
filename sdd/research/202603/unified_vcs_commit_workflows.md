# Unified VCS Commit/Propose/PR Workflows

## Problem Statement

The `#commit`, `#propose`, and `#cl`/`#pr` xprompt workflows are currently duplicated across VCS plugins (retired Mercurial plugin,
sase-github). The goal is to unify them into 3 built-in xprompts in sase core that work across all VCS providers via a
plugin-dispatched `sase commit` command.

## Current State

### retired Mercurial plugin Workflows

Three xprompt workflows in `retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/`:

- **`#cl`** - Creates a new CL from uncommitted changes. Steps: inject `#no_cl_ops` + `#cldd`, check changes, save
  response, generate description, call `sase_cl_workflow --create` (which runs `hg addremove`, `hg commit`, `hg fix`,
  `hg upload tree`, creates ChangeSpec).
- **`#commit`** - Amends an existing CL with a COMMITS entry. Steps: inject context, check changes, save response, call
  `retired_mercurial_plugin_commit_workflow` (which calls `provider.amend()`, adds COMMITS entry).
- **`#propose`** - Creates a PROPOSED entry without amending. Steps: inject context, check changes, save response, call
  `sase_propose_workflow` (adds PROPOSED entry, cleans workspace).

### sase-github Workflows

One main workflow in `sase-github/src/sase_github/xprompts/`:

- **`#pr`** - Creates a PR from commits on a feature branch. Steps: create/checkout branch, inject prompt, create
  ChangeSpec, extract agent metadata, push + `gh pr create`, update ChangeSpec with PR URL.

### sase Core

- **`sase commit`** - Creates a new CL via `CommitWorkflow`: validates, formats description, saves diff, creates VCS
  commit, runs fix/upload, creates ChangeSpec.
- **`sase amend`** - Amends existing CL via `AmendWorkflow`: saves diff, calls `provider.amend()`, adds COMMITS entry.
  Also supports `--propose` (proposed entry) and `--accept` (accept proposed entry).
- **Built-in xprompts** - `gcommit.yml`, `gpropose.yml`, `gchange.yml` already exist for git-based workflows.
- **VCS Provider interface** - `VCSProvider` ABC with pluggy hookspec, discovered via `sase_vcs` entry points.
  Resolution: `SASE_VCS_PROVIDER` env var > config > auto-detection.
- **No `sase_commit_stop_hook`** exists in core currently.

### Key Observations

1. The prompt_part content is nearly identical across providers: "make file changes, but do NOT create/amend a CL."
2. The _workflow orchestration_ differs significantly: Google uses `hg` commands + CL semantics; GitHub uses branch +
   push + `gh pr create`.
3. Both track results in ChangeSpec entries (COMMITS, PROPOSED sections).
4. The `sase amend` command already handles the three modes (amend, propose, accept) that the unified system needs.

---

## Prior Art

### Jujutsu (jj) - Backend Abstraction

jj separates concerns into a `Backend` trait (interface for VCS storage), a `Store` caching layer, and sidecar storage
for data that the abstract model supports but a specific backend doesn't (e.g., change IDs stored in
`.jj/repo/store/extra/` when using a Git backend).

**Relevance**: When the unified commit abstraction needs to track data that a specific VCS doesn't natively support
(like CL numbers in bare git), sase's ChangeSpec/project file already serves as this sidecar storage. This validates the
current approach.

### Sapling (Meta)

Sapling's design insight: "the UX and scale of version control can be separated from the repository format." It built
internal abstractions that made adding Git support straightforward. Three-tier architecture: `sl` client, Mononoke
server, EdenFS virtual filesystem.

**Relevance**: Mirrors sase's separation of CLI/TUI layer from VCS provider layer. Confirms that clean abstraction
boundaries are the key to multi-backend support.

### VS Code SCM API

Provider-registration model. Extensions register `SourceControl` instances. Resources are organized into groups. The API
is "slim yet powerful" -- exposes resource states, not VCS-specific operations. The UI renders uniformly.

**Relevance**: VS Code abstracts at the _resource/state_ level rather than the _command_ level. sase's `VCSProvider`
operates at the command level (checkout, diff, commit), which is more granular but more tightly coupled to VCS
semantics. Consider whether the unified commit workflows should operate at a higher abstraction level.

### Gerrit vs GitHub PR Workflow

Fundamental divergence: Gerrit reviews individual commits (push to `refs/for/master`, amend to update); GitHub reviews
branches (push new commits to update). sase already handles this via `VCSProvider.mail()` mapping to "upload for review"
abstractly.

### Terraform / Pulumi Provider Patterns

Both use CRUD-style interfaces with provider discovery. Terraform: providers declare what operations they support, core
adapts behavior. Pulumi: three-layer architecture (gRPC, generated bindings, higher-level SDKs).

**Relevance**: Terraform's **capability declaration** pattern is worth adopting. Rather than catching
`NotImplementedError`, providers could declare `capabilities()` -> `frozenset[str]` so the commit workflow can adapt its
behavior (e.g., skip `fix()` if provider doesn't support it) without try/except.

### Commitizen / Conventional Commits

Commitizen provides an adapter pattern for commit message formatting across projects. Conventional Commits standardizes
`<type>[scope]: <description>`.

**Relevance**: The commit message formatting is currently hardcoded per workflow. A lightweight formatter interface (or
just a config-driven template) could standardize this.

### Environment Variable Dispatch

The proposed `$SASE_COMMIT_METHOD` env var approach follows the 12-factor app pattern. Tools like direnv, mise, and asdf
use env vars for context-dependent tool management.

**Pros**: Language/OS-agnostic, easy to override, works with subprocess inheritance. **Cons**: Global mutable state,
risk of cross-contamination, values always strings, all subprocesses inherit them.

sase's existing pattern (`SASE_VCS_PROVIDER` with env > config > auto-detect fallback) works well.

### Hook-Based Commit Workflows

- **Git hooks**: pre-commit, prepare-commit-msg, commit-msg, post-commit. External scripts, limited context.
- **Mercurial hooks**: Can be in-process Python with full repo API access. More powerful.
- **Husky/pre-commit/Lefthook**: Hook management tools that standardize hook definition and execution.

sase's pluggy-based in-process approach is more powerful than either system's native hooks.

---

## Design Alternatives

### Alternative A: Environment Variable Dispatch (Proposed Approach)

Built-in `#commit`, `#propose`, `#pr` xprompts set `$SASE_COMMIT_METHOD` env var. A rewritten `sase_commit_stop_hook`
reads `$SASE_VCS_TYPE` + `$SASE_COMMIT_METHOD` and dispatches to `sase commit`. The `sase commit` command uses these env
vars to determine which provider operations to invoke.

**Pros**: Simple, VCS-agnostic dispatch, easy for plugins to override via env vars. **Cons**: Env vars are
stringly-typed global state; the stop hook becomes a complex dispatch point; debugging env var interactions is harder
than structured config; requires careful ordering of env var setup across workflow steps.

### Alternative B: VCS Provider Method Dispatch

Instead of env vars, add `create_commit()`, `create_proposal()`, `create_pull_request()` as standard methods on
`VCSProvider`. Built-in xprompts call `sase commit --method create_commit|create_proposal|create_pull_request`, and
`sase commit` dispatches to the appropriate provider method.

**Pros**: Type-safe, discoverable, self-documenting. Providers implement only the methods they support. Easy to add new
methods. **Cons**: Requires all providers to implement new methods (though they can raise `NotImplementedError`).

### Alternative C: Workflow-Level Plugin Hooks

Define pluggy hooks for the workflow level: `sase_commit_workflow`, `sase_propose_workflow`, `sase_pr_workflow`. The
built-in xprompts invoke these hooks. Plugins implement the hooks with provider-specific logic.

**Pros**: Maximum flexibility for plugins. Each provider can customize the entire workflow, not just individual VCS
operations. **Cons**: More complex plugin API surface. Risk of inconsistent behavior across providers if workflow
customization is too unconstrained.

### Alternative D: Command Pattern with Operation Registry

Define a `CommitOperation` base class with `execute()` and `rollback()`. Providers register operations for each commit
method. The `sase commit` command composes and executes the operation sequence.

**Pros**: Built-in rollback support, composable, testable. Cleanly separates "what to do" from "how to do it." **Cons**:
Over-engineered for current needs. The additional abstraction may not pay for itself.

### Alternative E: Hybrid (Recommended)

Combine the best aspects:

1. **Built-in xprompts** with shared prompt_part content (from proposal).
2. **CLI flag dispatch** (`sase commit --method`) instead of env var dispatch -- structured, type-safe, and explicit.
3. **Provider capability detection** via a `capabilities()` method rather than try/except on `NotImplementedError`.
4. **Workflow hooks** for provider-specific pre/post logic (e.g., `hg fix` + `hg upload` for Google, `git push` +
   `gh pr create` for GitHub), registered via pluggy.

---

## Recommendation

### Use Alternative E (Hybrid) with the following structure:

**1. Three built-in xprompts in `src/sase/xprompts/`:**

- `commit.yml` - For amending existing CLs/branches with new changes
- `propose.yml` - For creating proposed changes without committing
- `change.yml` - For creating new CLs/PRs (replaces both `#cl` and `#pr`)

Each xprompt contains:

- A shared `prompt_part` step: "Make file changes but do NOT create/amend a CL/commit."
- A post-prompt step that invokes `sase commit --method <method>`.

Note: renaming `#cl`/`#pr` to `#change` provides a VCS-agnostic name and avoids the awkward "which one do I use?"
question.

**2. Rewrite `sase commit` as a unified dispatch point:**

```
sase commit --method create_commit|create_proposal|create_change
```

Internally, `sase commit` should:

1. Detect the VCS provider (existing resolution chain).
2. Check provider capabilities (does it support the requested method?).
3. Dispatch to provider-specific workflow hooks.

**3. Add pluggy workflow hooks instead of env-var dispatch:**

```python
# In _hookspec.py
@hookspec
def vcs_create_commit(note: str, who: str, ...) -> tuple[bool, str | None]: ...

@hookspec
def vcs_create_proposal(note: str, who: str, ...) -> tuple[bool, str | None]: ...

@hookspec
def vcs_create_change(name: str, ...) -> tuple[bool, str | None]: ...
```

This keeps the dispatch VCS-agnostic (sase core calls the hook; plugins implement it) without env var coupling.

**4. Use `$SASE_COMMIT_METHOD` only as a stop-hook signal, not as the primary dispatch mechanism:**

If the stop hook needs to know what method to use (because it runs outside the workflow context), an env var is fine for
_that specific purpose_. But the main dispatch path should be the CLI flag + pluggy hooks, not env vars threaded through
the workflow.

**5. Remove `sase amend` by merging its functionality into `sase commit`:**

`sase commit --method create_commit` replaces `sase amend`. `sase commit --method create_proposal` replaces
`sase amend --propose`. This simplifies the CLI surface.

### Why not pure env-var dispatch?

The proposal's env-var approach works but has downsides:

- **Debugging**: When something goes wrong, tracing env var values through workflow steps, stop hooks, and subprocess
  calls is harder than tracing a CLI flag.
- **Type safety**: Env vars are strings. A typo in `$SASE_COMMIT_METHOD` silently does the wrong thing. A CLI flag with
  `choices=` fails loudly.
- **Coupling**: The stop hook becomes a complex dispatch point that needs to understand all env vars. With pluggy hooks,
  each provider encapsulates its own logic.
- **Testing**: Mocking env vars is awkward. Mocking pluggy hooks or CLI args is straightforward.

That said, env vars are fine for the narrow case of signaling between the xprompt workflow and the stop hook (since the
stop hook runs in a separate process context). Just don't make them the _primary_ dispatch mechanism.

### Migration Path

1. Add the three pluggy workflow hooks to `_hookspec.py`.
2. Implement them in `BareGitPlugin` (core) with the existing git logic from `gcommit.yml` / `gpropose.yml`.
3. Create the three built-in xprompts.
4. Rewrite `sase commit` to use `--method` dispatch.
5. Update sase-github to implement the hooks (move `#pr` logic into `vcs_create_change`).
6. Update retired Mercurial plugin to implement the hooks (move `#cl`/`#commit`/`#propose` logic).
7. Deprecate and remove `sase amend`.
8. Remove the old per-plugin xprompt workflows.
