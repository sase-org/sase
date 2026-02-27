---
bead_id: sase-yyyx
---

# VCS Workflow → Runner Provider Directive Migration

## Overview

Migrate VCS workflows (`#git`, `#gh`, `#hg`) from xprompt workflows with `wraps_all: true` to a new **runner provider**
directive system. Users will write `%gh:sase` instead of `#gh:sase`.

### Motivation

1. VCS workflows don't contribute prompt content (empty `prompt_part: ""`)
2. They control _where and how_ the agent runs — a responsibility that belongs to directives, not xprompts
3. The `wraps_all` flag is a special case bolted onto the workflow model; runner providers make it first-class

### Design: RunnerProvider Protocol

Runner providers implement a two-phase lifecycle:

```python
class RunnerProvider(ABC):
    """Provides workspace setup/teardown for agent execution."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'git', 'gh', 'hg'). Used as directive name."""

    @abstractmethod
    def pre_agent(self, ref: str, *, n: int | None = None, release: bool = True) -> RunnerContext:
        """Phase 1: Allocate workspace, prepare it, chdir into it.

        Called after directive extraction, before embedded workflow expansion.
        Returns context that carries state to post_agent.
        """

    @abstractmethod
    def post_agent(self, ctx: RunnerContext) -> PostAgentResult:
        """Phase 2: Release workspace, capture diff.

        Called after the agent/prompt step completes and all embedded
        workflow post-steps have run.
        """
```

`RunnerContext` is a dataclass carrying workspace state between phases:

```python
@dataclass
class RunnerContext:
    project_name: str
    project_file: str
    workspace_dir: str
    workspace_num: int
    checkout_target: str
    primary_workspace_dir: str
    should_release: bool
    head_before: str = ""       # Set by prepare step
    extra: dict[str, Any] = field(default_factory=dict)
```

`PostAgentResult` returns diff info:

```python
@dataclass
class PostAgentResult:
    diff_path: str | None = None
    meta: dict[str, str] = field(default_factory=dict)
```

### Discovery

Runner providers are discovered via a new entry point group: `sase_runner_provider`.

```toml
# In sase-github/pyproject.toml:
[project.entry-points."sase_runner_provider"]
gh = "sase_github.runner_provider:GitHubRunnerProvider"
```

The core `sase` package registers `git` directly (no entry point needed).

### Directive Parsing

The directive parser (`extract_prompt_directives`) is extended:

- Runner provider names are added to `_KNOWN_DIRECTIVES` dynamically based on discovered providers
- A new `runner` field on `PromptDirectives` holds `(provider_name, ref, named_args)`
- At most one runner provider directive per prompt (validated like `wraps_all`)

### Execution Pipeline Integration

In `_execute_prompt_step` (workflow_executor_steps_prompt.py):

1. After `preprocess_prompt_early()` extracts directives
2. If `directives.runner` is set, call `provider.pre_agent()` — this does workspace setup, \_chdir, etc.
3. Proceed with embedded workflow expansion (non-wraps_all workflows only)
4. Execute the agent/LLM call
5. After embedded workflow post-steps, call `provider.post_agent()`

In `launch_agent_from_cwd` (agent_launcher.py):

1. Detect `%gh:sase` directives in prompt (via `extract_prompt_directives`)
2. Use runner provider to resolve project/workspace info for subprocess spawning
3. Pass VCS ref info to subprocess environment (existing pre-allocation mechanism)

### Backward Compatibility

During the transition:

- `#git:ref`, `#gh:ref`, `#hg:ref` are detected as embedded workflows
- If a `wraps_all` workflow matches a known runner provider name, emit a deprecation warning and route to the runner
  provider instead
- This lets existing prompts continue to work while users migrate to `%` syntax
- The deprecation period lasts until the old YAML files are removed (a future cleanup phase)

---

## Phase 1: RunnerProvider Protocol, Discovery, and Directive Extensions

### Goal

Establish the foundational infrastructure: abstract protocol, plugin discovery, and extended directive parsing.

### Tasks

1. **Create `src/sase/runner_provider.py`** with:
   - `RunnerProvider` ABC with `name`, `pre_agent()`, `post_agent()` abstract methods
   - `RunnerContext` dataclass
   - `PostAgentResult` dataclass
   - `get_runner_providers() -> dict[str, RunnerProvider]` — discovers providers via `sase_runner_provider` entry
     points + built-in registration

2. **Extend `src/sase/xprompt/directives.py`**:
   - Add `runner` field to `PromptDirectives`: `runner: tuple[str, str, dict[str, str]] | None = None` (provider_name,
     ref, named_args)
   - Dynamically add runner provider names to known directives during extraction
   - Parse runner provider directive arguments (ref is the first positional arg; `n`, `release` are named args)
   - Validate at most one runner provider directive per prompt

3. **Add tests** in `tests/test_runner_provider.py`:
   - Test protocol can be subclassed
   - Test `get_runner_providers()` discovery with mock entry points
   - Test directive extraction with runner provider directives (`%git:sase`, `%gh:org/repo`)
   - Test at-most-one validation

### Files to create/modify

- Create: `src/sase/runner_provider.py`
- Modify: `src/sase/xprompt/directives.py`
- Create: `tests/test_runner_provider.py`

### Definition of done

- `PromptDirectives` can hold runner provider info extracted from prompts
- Runner provider discovery works (mock entry points in tests)
- `just check` passes

---

## Phase 2: Execution Pipeline Integration

### Goal

Wire runner providers into the workflow execution pipeline so that `%git:ref` triggers workspace setup/teardown around
agent execution.

### Tasks

1. **Modify `src/sase/xprompt/workflow_executor_steps_prompt.py`** (`_execute_prompt_step`):
   - After `preprocess_prompt_early()`, check `directives.runner`
   - If set, resolve the runner provider from `get_runner_providers()`
   - Call `provider.pre_agent(ref, n=..., release=...)` — this does workspace allocation and `os.chdir()`
   - Store the `RunnerContext` for post-agent use
   - After embedded workflow post-steps complete, call `provider.post_agent(ctx)`
   - Propagate `diff_path` and `meta` from `PostAgentResult` to the step state

2. **Modify `src/sase/agent_launcher.py`** (`launch_agent_from_cwd`):
   - Import and use `extract_prompt_directives()` to detect `%gh:ref` directives
   - When a runner directive is found, use the provider to resolve project/workspace info
   - Continue passing VCS ref info to subprocess environment (existing pre-allocation mechanism)
   - Keep existing `#gh:ref` resolution as fallback (backward compat)

3. **Add backward compatibility layer in `src/sase/xprompt/workflow_executor_steps_embedded.py`**:
   - In `_expand_embedded_workflows_in_prompt`, when a `wraps_all` workflow is detected and a matching runner provider
     exists:
     - Emit a deprecation warning (use `warnings.warn` with `DeprecationWarning`)
     - Skip the embedded workflow and instead set `directives.runner` equivalent state
     - Route through the runner provider lifecycle
   - This ensures `#git:ref` still works during transition

4. **Add tests**:
   - Mock runner provider exercised through prompt step execution
   - Verify pre_agent is called before LLM and post_agent after
   - Verify backward compat: `#git:ref` triggers runner provider with deprecation warning
   - Verify `_chdir` happens during pre_agent phase

### Files to modify

- `src/sase/xprompt/workflow_executor_steps_prompt.py`
- `src/sase/xprompt/workflow_executor_steps_embedded.py`
- `src/sase/agent_launcher.py`
- `tests/` (new or extended test files)

### Definition of done

- A mock runner provider correctly receives `pre_agent`/`post_agent` calls during workflow execution
- `#git:ref` backward compat works with deprecation warning
- `just check` passes

---

## Phase 3: Implement GitRunnerProvider (Built-in)

### Goal

Create the concrete `%git` runner provider, migrating logic from `xprompts/git.yml` and `src/sase/scripts/git_setup.py`.

### Tasks

1. **Create `src/sase/runner_providers/__init__.py`** and **`src/sase/runner_providers/git.py`**:
   - Implement `GitRunnerProvider(RunnerProvider)`
   - `pre_agent()`:
     - Call existing `git_setup.main()` logic (or refactor `git_setup.py` into reusable functions)
     - Run the prepare bash logic (backup dirty workspace, checkout, fetch, pull)
     - `os.chdir(workspace_dir)`
     - Return populated `RunnerContext` with `head_before`
   - `post_agent()`:
     - Release workspace via `release_workspace()` if `should_release`
     - Run diff capture logic (compare `head_before` to current HEAD)
     - Return `PostAgentResult` with `diff_path`

2. **Register the built-in provider** in `src/sase/runner_provider.py`:
   - `get_runner_providers()` should include `GitRunnerProvider` as a built-in (not via entry points)

3. **Refactor `src/sase/scripts/git_setup.py`**:
   - Extract workspace allocation logic into reusable functions that both the runner provider and the script can use
   - The script can remain for backward compat but delegate to shared functions

4. **Add tests** for GitRunnerProvider:
   - Test workspace allocation and chdir
   - Test prepare step (with mocked git commands)
   - Test release and diff capture
   - Integration test: `%git:ref` in a prompt triggers full lifecycle

5. **Verify** `xprompts/git.yml` backward compat still works (via Phase 2's deprecation layer)

### Files to create/modify

- Create: `src/sase/runner_providers/__init__.py`
- Create: `src/sase/runner_providers/git.py`
- Modify: `src/sase/runner_provider.py`
- Modify: `src/sase/scripts/git_setup.py`
- Create/extend: tests

### Definition of done

- `%git:myproject` works end-to-end (workspace setup, agent runs, workspace released, diff captured)
- `#git:myproject` still works with deprecation warning
- `just check` passes

---

## Phase 4: Implement GitHubRunnerProvider (sase-github Plugin)

### Goal

Create the `%gh` runner provider in the sase-github plugin repo, migrating logic from `gh.yml`.

### Important

Use your `/commit` skill (NOT `git commit`) to commit changes to the sase-github repo at `../sase-github`.

### Tasks

1. **Create `../sase-github/src/sase_github/runner_provider.py`**:
   - Implement `GitHubRunnerProvider(RunnerProvider)`
   - `pre_agent()`:
     - Reuse/refactor logic from `sase_github/scripts/gh_setup.py`
     - Run prepare bash logic (same as git: backup, checkout, fetch, pull)
     - `os.chdir(workspace_dir)`
     - Return `RunnerContext`
   - `post_agent()`:
     - Release workspace
     - Diff capture (same as git but also captures `meta_commit_message`)
     - Return `PostAgentResult`

2. **Register via entry point** in `../sase-github/pyproject.toml`:

   ```toml
   [project.entry-points."sase_runner_provider"]
   gh = "sase_github.runner_provider:GitHubRunnerProvider"
   ```

3. **Refactor `../sase-github/src/sase_github/scripts/gh_setup.py`**:
   - Extract reusable functions for the runner provider

4. **Add tests** in sase-github repo

5. **Commit** changes to sase-github repo using the `/commit` skill

### Files to create/modify (in ../sase-github/)

- Create: `src/sase_github/runner_provider.py`
- Modify: `pyproject.toml`
- Modify: `src/sase_github/scripts/gh_setup.py`
- Create/extend: tests

### Definition of done

- `%gh:org/repo` works end-to-end
- `#gh:org/repo` still works with deprecation warning
- `just check` passes in sase-github repo
- Changes committed to sase-github repo

---

## Phase 5: Implement HgRunnerProvider (sase-hg Plugin) + Reference Migration + Cleanup

### Goal

Create the `%hg` runner provider, update all references from `#` to `%` syntax, and clean up.

### Important

Use your `/commit` skill (NOT `git commit`) to commit changes to plugin repos.

### Tasks

1. **Create `../sase-hg/src/sase_hg/runner_provider.py`**:
   - Implement `HgRunnerProvider(RunnerProvider)`
   - `pre_agent()`:
     - Reuse/refactor logic from `sase_hg/scripts/hg_setup.py`
     - Run prepare: `sase_hg_clean`, `sase_hg_update`
     - `os.chdir(workspace_dir)`
     - Return `RunnerContext`
   - `post_agent()`:
     - Release workspace
     - Return `PostAgentResult` (hg.yml has no diff step)

2. **Register via entry point** in `../sase-hg/pyproject.toml`:

   ```toml
   [project.entry-points."sase_runner_provider"]
   hg = "sase_hg.runner_provider:HgRunnerProvider"
   ```

3. **Commit** changes to sase-hg repo using the `/commit` skill

4. **Update all xprompt references** that use `#gh`, `#git`, `#hg` VCS workflows:
   - `.xprompts/pylimit_split.yml`: `#gh:sase` → `%gh:sase`
   - `sase.yml` (chezmoi): Check and update if needed
   - Any other xprompt files that embed VCS workflows

5. **Update documentation**:
   - `docs/xprompt.md`: Document runner provider directives
   - `docs/workspace.md`: Update references

6. **Cleanup** (optional, can be deferred):
   - Remove `wraps_all` field from `Workflow` model if no longer needed
   - Remove `wraps_all` handling from embedded workflow expansion
   - Delete `xprompts/git.yml` (now superseded by runner provider)
   - Mark `gh.yml` and `hg.yml` in plugin repos as deprecated
   - Remove backward compat deprecation warnings

### Files to create/modify

- Create: `../sase-hg/src/sase_hg/runner_provider.py`
- Modify: `../sase-hg/pyproject.toml`
- Modify: `.xprompts/pylimit_split.yml`
- Modify: `docs/xprompt.md`, `docs/workspace.md`
- Possibly modify: chezmoi sase.yml files
- Cleanup: `src/sase/xprompt/workflow_models.py`, `workflow_executor_steps_embedded.py`, `xprompts/git.yml`

### Definition of done

- `%hg:cl_name` works end-to-end
- All xprompt files updated to use `%` syntax
- Old `#` syntax still works (deprecation warnings)
- `just check` passes in all repos
- Changes committed to sase-hg repo
