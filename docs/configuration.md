# Configuration Reference

This document is the central reference for all sase configuration: config files, YAML sections, environment variables,
and CLI flags.

## Table of Contents

- [Config File Location](#config-file-location)
- [Deep-Merge System](#deep-merge-system)
- [Configuration Sections](#configuration-sections)
  - [amd_h1_title](#amd_h1_title)
  - [ace](#ace)
  - [llm_provider](#llm_provider)
  - [commit](#commit)
  - [sibling_repos](#sibling_repos)
  - [vcs_provider](#vcs_provider)
  - [axe](#axe)
  - [mentor_profiles](#mentor_profiles)
  - [metahooks](#metahooks)
  - [xprompts](#xprompts)
  - [xprompt_aliases](#xprompt_aliases)
  - [use_chezmoi](#use_chezmoi)
  - [precommit_command](#precommit_command)
  - [timezone](#timezone)
  - [chat_install](#chat_install)
  - [mobile_gateway](#mobile_gateway)
  - [sdd](#sdd)
  - [bead](#bead)
  - [workspace](#workspace)
  - [telemetry](#telemetry)
- [Environment Variables](#environment-variables)
- [CLI Flags](#cli-flags)
- [Directory Sharding](#directory-sharding)

## Config File Location

All sase configuration lives under `~/.config/sase/`. The base config file is:

```
~/.config/sase/sase.yml
```

Overlay files matching the glob `~/.config/sase/sase_*.yml` are merged on top of the base file. A project-local
`./sase.yml` in the current working directory usually takes highest priority. The ACE TUI deliberately disables
project-local config loading for its own process so opening `sase ace` inside a repo does not inherit that repo's
agent-run settings. See [Deep-Merge System](#deep-merge-system) below.

## Deep-Merge System

Sase builds a merged configuration through five layers, each merged on top of the previous:

1. **`default_config.yml`** — bundled package defaults
2. **Plugin `default_config.yml` files** — from installed plugin packages (via `sase_config` entry points), sorted by
   entry-point name; lists concatenate
3. **`sase.yml`** — user config (`~/.config/sase/sase.yml`); lists **replace** defaults (not concatenate)
4. **`sase_*.yml` overlays** — sorted alphabetically; lists **concatenate**
5. **Local `sase.yml`** — project-level config in the current working directory; lists **concatenate** (highest
   priority)

This allows splitting configuration across multiple files (e.g., `sase_work.yml`, `sase_personal.yml`) without
duplication, plugins can provide sensible defaults that users can override, and individual projects can customize
behavior without changing global config.

Merge semantics:

| Type        | Behavior                                                                   |
| ----------- | -------------------------------------------------------------------------- |
| **Dicts**   | Merged recursively (overlay keys override base keys).                      |
| **Lists**   | Concatenated in layers 2, 4, and 5; **replaced** in layer 3 (user config). |
| **Scalars** | Override (overlay value replaces base value).                              |

For example, given a base file with two mentor profiles and an overlay or local project config that adds a third, the
merged result contains all three profiles. A user `~/.config/sase/sase.yml` list replaces earlier defaults instead. If
two files define the same scalar key (e.g., `axe.max_hook_runners`), the later layer wins.

Source: `src/sase/config/core.py`

## Configuration Sections

### amd_h1_title

Opts a root into a generated AMD-managed `AGENTS.md` by providing the Markdown H1 title for that file.

```yaml
amd_h1_title: "Structured Agentic Software Engineering (SASE) - Agent Instructions" # default: null
```

| Field          | Type           | Default | Description                                                                 |
| -------------- | -------------- | ------- | --------------------------------------------------------------------------- |
| `amd_h1_title` | string \| null | `null`  | H1 title used by the AMD `AGENTS.md` generator when enabled for that scope. |

For ordinary project roots, this field is intentionally local to the root being initialized. The AMD generator reads
only that root's `./sase.yml` value, so a global `~/.config/sase/sase.yml` value does not opt every repository on the
machine into generated `AGENTS.md` files.

Home roots are the exception. When `sase amd init` targets the live home root, user config from
`~/.config/sase/sase.yml` and `~/.config/sase/sase_*.yml` can provide the home `AGENTS.md` title. When it targets the
chezmoi home source root, source-side config under `dot_config/sase/` is used instead. With `use_chezmoi: true`, AMD
initializes the chezmoi home source root rather than writing a live-home `AGENTS.md`.

Source: `src/sase/default_config.yml`, `config/sase.schema.json`

### ace

Configures the ACE TUI behavior. Defaults are provided by `src/sase/default_config.yml`.

```yaml
ace:
  inactive_seconds: 600 # seconds before showing IDLE indicator (default: 600)
  keymaps:
    app:
      next_changespec: "j"
      prev_changespec: "k"
      # ... all app-level keybindings are configurable
    modes:
      # Built-in modes (fold, copy, leader, bang) are configurable
      leader_mode:
        prefix: "comma"
        keys:
          repeat_last: "comma" # press the leader prefix, then this key; defaults render as `,,`
          projects: "p"
          temporary_llm_override: "o"
          full_history_refresh: "y"
      fold_mode:
        prefix: "z"
        keys:
          cycle_commits: "c"
          cycle_hooks: "h"
      # Custom modes can be added here
      my_mode:
        prefix: ";"
        keys:
          run_tests:
            key: "t"
            shell: "just test"
```

| Field               | Type         | Default   | Description                                                             |
| ------------------- | ------------ | --------- | ----------------------------------------------------------------------- |
| `inactive_seconds`  | int          | `600`     | Seconds of inactivity before the IDLE badge appears in the TUI top bar. |
| `keymaps`           | dict         | -         | Configurable keybindings (see below).                                   |
| `prompt_completion` | dict         | see below | Live soft-completion settings for the ACE prompt input.                 |
| `snippets`          | dict[string] | `{}`      | Trigger-word → template mappings for prompt input snippet expansion.    |

The IDLE indicator can also be triggered manually via the leader-mode `,I` keybinding. External tools can query idle
status via `sase.ace.tui_activity.is_idle()`.

#### `ace.keymaps`

All TUI keybindings are configurable. The `keymaps` section has two sub-sections:

**`app`** — App-level keybindings. Each key is an action name mapped to a key string. See `src/sase/default_config.yml`
for the full list of configurable actions and their defaults.

**`modes`** — Prefix-key mode definitions. Built-in modes (`fold_mode`, `copy_mode`, `leader_mode`, `bang_mode`) can be
reconfigured, and custom modes can be added. Each mode has:

| Field    | Type | Description                                                                                           |
| -------- | ---- | ----------------------------------------------------------------------------------------------------- |
| `prefix` | str  | The activation key for the mode.                                                                      |
| `keys`   | dict | Sub-key definitions. For custom modes, each entry needs a `key` field and either `shell` or `action`. |

Custom mode key fields:

| Field    | Type | Required | Description                            |
| -------- | ---- | -------- | -------------------------------------- |
| `key`    | str  | yes      | The sub-key to press after the prefix. |
| `shell`  | str  | no\*     | Shell command to execute.              |
| `action` | str  | no\*     | Built-in action name to invoke.        |

\*Exactly one of `shell` or `action` must be provided.

The keymap loader validates configuration: invalid keys are reverted to defaults, duplicate bindings are warned, and
prefix conflicts between custom modes and app bindings are detected.

Source: `src/sase/default_config.yml`, `src/sase/ace/tui/keymaps/`

#### `ace.snippets`

Defines expandable text snippets for the prompt input widget. Each entry maps a trigger word to a template string. Press
`Tab` in the prompt input to expand the trigger word before the cursor.

```yaml
ace:
  snippets:
    fix: "Please fix the following issue:\n$0"
    review: "Review this code for correctness, performance, and style."
    plan: "#plan\n$0"
```

Templates can contain `$0` to mark where the cursor should be placed after expansion. If no `$0` is present, the cursor
moves to the end of the expanded text.

See [docs/ace.md — Snippets](ace.md#snippets) for usage details.

Source: `src/sase/ace/tui/widgets/prompt_text_area.py`

#### `ace.prompt_completion`

Controls automatic non-disruptive suggestions in the ACE prompt input. Suggestions appear in the prompt-bar subtitle and
are accepted with `Ctrl+L`; `Enter` still submits the prompt as typed. Manual `Ctrl+T` completion is independent of
these settings.

```yaml
ace:
  prompt_completion:
    auto: soft
    debounce_ms: 90
    auto_file_paths: false
    max_auto_rows: 1
```

| Field             | Type        | Default | Description                                                                                                  |
| ----------------- | ----------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `auto`            | bool/string | `soft`  | Automatic mode. `soft`, `true`, `on`, `yes`, or `1` enable subtitle suggestions; false/off disables them.    |
| `debounce_ms`     | int         | `90`    | Delay before computing a live suggestion after text or cursor changes.                                       |
| `auto_file_paths` | bool        | `false` | Allow live suggestions to scan file-path candidates. Manual `Ctrl+T` file completion still works when false. |
| `max_auto_rows`   | int         | `1`     | Reserved row limit for automatic completion modes; current soft mode shows one suggestion.                   |

Source: `src/sase/ace/tui/widgets/prompt_completion.py`, `src/sase/ace/tui/widgets/_prompt_soft_completion.py`

### llm_provider

Configures which LLM backend sase uses and how model tiers map to concrete models. See [docs/llms.md](llms.md) for the
full LLM provider architecture, preprocessing pipeline, and invocation lifecycle.

```yaml
llm_provider:
  provider: claude # or "qwen", "opencode", "gemini" (default: auto-detect)
  model_tier_map:
    large: opus
    small: sonnet
  model_aliases:
    other: claude/opus
```

| Field                               | Type   | Default     | Description                                                                                                                                                  |
| ----------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `llm_provider.provider`             | string | auto-detect | Which registered provider to use. Auto-detects by plugin-declared priority; built-ins default to claude → codex → qwen → opencode → gemini.                  |
| `llm_provider.model_tier_map.large` | string | -           | Model identifier for the `large` tier.                                                                                                                       |
| `llm_provider.model_tier_map.small` | string | -           | Model identifier for the `small` tier.                                                                                                                       |
| `llm_provider.model_aliases`        | dict   | -           | Model aliases usable from `%model:<alias>` / `%m:<alias>`. Values can be bare known models, explicit `provider/model`, or nested provider-local model paths. |

Model aliases are resolved when an agent launches, so reusable xprompts can point at names such as `%model:other` while
each user's `sase.yml` controls the concrete provider/model. Unknown aliases and unknown model values keep the existing
fallback behavior and run on the default provider.

The alias name `other` is reserved: when a temporary LLM override is active (see
[Temporary Default Override](llms.md#temporary-default-override)), `%model:other` resolves to the `(provider, model)`
that was the effective default _immediately before_ the override was set, rather than to the static
`model_aliases.other` target. When no override is active, `other` falls back to the configured alias as usual.

The TUI also supports a **temporary** session-level provider/model override that does **not** edit this config. The
override is set/cleared from the ACE `,o` modal and persisted to `~/.sase/llm_override.json`; expired entries are
deleted on next read. See [docs/llms.md](llms.md#temporary-default-override) for the resolution order, state-file
format, and precedence relative to `SASE_MODEL_TIER_OVERRIDE`.

#### `llm_provider.retry`

Per-provider retry and fallback configuration. See [docs/llms.md](llms.md#retry-and-fallback) for the full retry flow
and TUI display.

```yaml
llm_provider:
  retry:
    gemini:
      max_retries: 3
      error_patterns:
        - "An unexpected critical error occurred:"
      wait_times: [60, 300, 1800]
      fallback_model: "gemini-3-flash-preview"
      continuation_prompt: "Please continue from the last preserved work."
      preserve_workspace: true
      spawn_new_agent: false
```

| Field                                               | Type | Default | Description                                                               |
| --------------------------------------------------- | ---- | ------- | ------------------------------------------------------------------------- |
| `llm_provider.retry.<provider>`                     | dict | -       | Retry config for a specific provider (e.g., `gemini`, `claude`, `codex`). |
| `llm_provider.retry.<provider>.max_retries`         | int  | `0`     | Maximum retry attempts. `0` disables retrying.                            |
| `llm_provider.retry.<provider>.error_patterns`      | list | `[]`    | Case-insensitive substring patterns matched against error output.         |
| `llm_provider.retry.<provider>.wait_times`          | list | `[30]`  | Per-retry wait times in seconds. Last value reused if list is shorter.    |
| `llm_provider.retry.<provider>.fallback_model`      | str  | `null`  | Alternate model to use after exhausting all retries.                      |
| `llm_provider.retry.<provider>.continuation_prompt` | str  | `null`  | Prompt text prepended when continuing after a retryable failure.          |
| `llm_provider.retry.<provider>.preserve_workspace`  | bool | `false` | Preserve on-disk edits across legacy in-process retry attempts.           |
| `llm_provider.retry.<provider>.spawn_new_agent`     | bool | `false` | Retry by launching a fresh detached agent that inherits the workspace.    |

Configured retry policy is merged with provider-supplied retry defaults when a provider declares them. For list fields
such as `error_patterns`, built-in patterns are kept and configured patterns are appended with duplicates removed.
Claude's provider hook adds workspace-preserving matching for context-limit, socket-close, and Claude CLI API-error
output, plus a continuation nudge. Those hook defaults are merged with the bundled Claude policy in
`default_config.yml`, so the configured wait times and fallback model still apply unless you override them.

Source: `src/sase/llm_provider/retry_config.py`, `src/sase/llm_provider/config.py`

### commit

Configures commit enforcement around SASE-launched agents. The current commit finalizer is provider-neutral and runs in
the shared LLM invocation layer after a successful provider invocation in a SASE agent session, identified by
`SASE_AGENT_TIMESTAMP`.

```yaml
commit:
  finalizer:
    enabled: true
    max_passes: 2
```

| Field                         | Type | Default | Description                                                                          |
| ----------------------------- | ---- | ------- | ------------------------------------------------------------------------------------ |
| `commit.finalizer.enabled`    | bool | `true`  | Run the post-invocation commit finalizer for SASE-launched agent sessions.           |
| `commit.finalizer.max_passes` | int  | `2`     | Maximum follow-up invocations before a still-dirty enforced workspace fails the run. |

When enabled, the finalizer checks the main workspace through the active VCS provider and checks configured
`sibling_repos` Git worktrees only at their resolved sibling `workspace_dir` for the agent's assigned workspace number.
Dirty enforced workspaces trigger a follow-up invocation that instructs the same provider to use the appropriate commit
skill. Dirty static siblings (`workspace.strategy: none`) are reported to that follow-up as advisory work and do not
fail the finalizer if they remain dirty. Advisory-only static sibling changes still get one follow-up prompt so the
agent can commit them when it made those changes. When the only enforced change is one tracked markdown file under
`sdd/tales/`, `sdd/epics/`, `sdd/legends/`, or `sdd/myths/`, and that file's only diff is leading front matter changing
exactly from `status: wip` to `status: done`, the finalizer creates a direct `chore: Mark SDD plan done` commit instead
of invoking the provider again. When `$SASE_ARTIFACTS_DIR` is set, each pass writes prompt/response artifacts there, and
the final outcome is recorded in `commit_finalizer_result.json`.

Set `SASE_DISABLE_COMMIT_STOP_HOOK=1` for a one-off bypass. The environment variable name is historical; it now disables
the provider-neutral finalizer.

Source: `src/sase/llm_provider/commit_finalizer.py`, `src/sase/commit_instructions.py`

### sibling_repos

Declares related repositories that should be visible to launched agents. Git sibling worktrees using numbered workspace
resolution are also checked by the commit finalizer at their resolved `workspace_dir`. Entries can live in user config
or a project-local `sase.yml`; local entries are resolved relative to the project's primary workspace directory.

```yaml
sibling_repos:
  - name: core
    path: ../sase-core
    description: Shared backend/domain behavior used by SASE frontends.
  - name: github
    path: ../sase-github
    description: GitHub VCS and workspace provider plugin.
  - name: chezmoi
    path: ~/.local/share/chezmoi
    description: User dotfiles source managed by chezmoi.
    workspace:
      strategy: none
```

| Field                                | Type   | Default    | Description                                                                                                  |
| ------------------------------------ | ------ | ---------- | ------------------------------------------------------------------------------------------------------------ |
| `sibling_repos[].name`               | string | required   | Stable alias used in generated environment variable names and memory summaries.                              |
| `sibling_repos[].path`               | string | required   | Primary checkout path. Relative paths resolve from the project's primary workspace.                          |
| `sibling_repos[].description`        | string | required   | Human-readable purpose used when generating agent memory for the sibling repository.                         |
| `sibling_repos[].workspace.strategy` | string | `"suffix"` | `suffix` exposes a workspace-matched checkout for workspace `N`; `none` always exposes the primary checkout. |

For `suffix` siblings, workspace numbers `0` and `1` use the primary checkout. Higher workspace numbers use
workspace-matched sibling checkouts, materializing the checkout through the same `workspace.root` policy when the
workspace provider can do so. With explicit `workspace.root: adjacent` that path is a legacy sibling such as
`sase-core_10`; with the default `xdg-state` it lives under the managed state root. Siblings with
`workspace.strategy: none` are exposed to agents and can appear as advisory dirty targets in commit finalizer prompts,
but they are not commit-finalizer enforcement targets. SASE passes the resolved paths into environment variables and
agent metadata:

| Variable                                   | Description                                       |
| ------------------------------------------ | ------------------------------------------------- |
| `SASE_SIBLING_REPOS_JSON`                  | JSON metadata for all resolved sibling repos.     |
| `SASE_SIBLING_REPO_<ENV_NAME>_DIR`         | Workspace-matched directory for a sibling repo.   |
| `SASE_SIBLING_REPO_<ENV_NAME>_PRIMARY_DIR` | Primary checkout directory for that sibling repo. |

`<ENV_NAME>` is the uppercased, sanitized repo `name`; duplicates are uniquified with a numeric suffix.

Source: `src/sase/sibling_repos.py`, `src/sase/agent/launch_spawn.py`

### vcs_provider

Configures the version control system backend. See [docs/vcs.md](vcs.md) for the full VCS provider reference including
per-command behavior, Git/Mercurial details, and troubleshooting.

```yaml
vcs_provider:
  provider: auto # "git", "hg", or "auto" (default: "auto")
  workspace_root: ~/workspace # optional workspace root directory
  default_hooks: # optional list overriding built-in default hooks
    - "!$my_presubmit"
    - "$my_lint"
  pr_tags: # optional key-value tags appended to PR commit messages
    Bug: "b/12345"
  use_project_pr_prefix: false # prepend [<project>] to PR titles (default: false)
```

| Field                                | Type              | Default  | Description                                                                                             |
| ------------------------------------ | ----------------- | -------- | ------------------------------------------------------------------------------------------------------- |
| `vcs_provider.provider`              | string            | `"auto"` | VCS provider: `"git"`, `"hg"`, or `"auto"` for directory detection.                                     |
| `vcs_provider.workspace_root`        | string            | -        | Legacy VCS helper workspace root. New numbered-checkout layout is configured by `workspace.root` below. |
| `vcs_provider.default_hooks`         | list[string]      | -        | Hook commands added to new ChangeSpecs. Replaces built-in defaults.                                     |
| `vcs_provider.pr_tags`               | dict[string, str] | `{}`     | Key-value tags appended as `TAG=VALUE` lines to PR commit messages.                                     |
| `vcs_provider.use_project_pr_prefix` | bool              | `false`  | Prepend `[<project>] ` to PR titles / CL descriptions (see below).                                      |

When `default_hooks` is not set, plugins may provide their own defaults via `default_config.yml` (for example,
Mercurial-specific hooks from a provider plugin). The core `sase` package has no built-in default hooks.

When `use_project_pr_prefix` is `true`, a `[<project>] ` prefix is prepended to PR titles (GitHub) or CL descriptions
(Mercurial) without polluting the ChangeSpec DESCRIPTION or git commit message. The prefix is automatically stripped
when reading descriptions back.

Source: `src/sase/vcs_provider/config.py`, `src/sase/ace/hooks/defaults.py`

### axe

Configures the `sase axe` lumberjack-based daemon. The axe architecture uses an orchestrator that spawns multiple
lumberjacks, each running a set of chops on a fixed interval. Defaults are provided by `src/sase/default_config.yml`.

```yaml
axe:
  max_hook_runners: 3 # concurrent hook runners (default: 3)
  max_agent_runners: 3 # concurrent agent runners (default: 3)
  zombie_timeout_seconds: 7200 # seconds (default: 7200 = 2 hours)
  query: "" # query filter for ChangeSpecs (default: all)
  chop_script_dirs: [] # additional directories to search for chop scripts
  lumberjacks:
    hooks:
      interval: 5
      chop_timeout: "90s"
      chops:
        - name: hook_checks
          description: Complete finished hooks and start stale ones, with zombie detection
        - name: mentor_checks
          description: Start mentor workflows once all hook prerequisites are met
        - name: workflow_checks
          description: Complete finished CRS/fix-hook workflows and start stale ones
        - name: pending_checks_poll
          description: Poll background is_cl_submitted and critique_comments checks for results
        - name: comment_zombie_checks
          description: Mark comment threads older than zombie_timeout as ZOMBIE
        - name: suffix_transforms
          description: Strip stale suffixes from older proposals and update mail-readiness markers
        - name: orphan_cleanup
          description: Release workspace claims orphaned by reverted CLs with dead PIDs
    waits:
      interval: 10
      chops:
        - name: wait_checks
          description: Resolve successful agent wait dependencies and write ready.json
    checks:
      interval: 300
      chops:
        - name: cl_submitted_checks
          description: Check if CLs have been submitted
        - name: stale_running_cleanup
          description: Clean up stale RUNNING entries
    comments:
      interval: 60
      chops:
        - name: comment_checks
          description: Check for new comments on CLs
    housekeeping:
      interval: 3600
      chops:
        - name: error_digest
          description: Summarize recent errors into a notification
```

**Top-level fields:**

| Field                            | Type         | Default    | Description                                                                   |
| -------------------------------- | ------------ | ---------- | ----------------------------------------------------------------------------- |
| `max_hook_runners`               | int          | `3`        | Maximum concurrent hook runners (non-`$` hooks) across all ChangeSpecs.       |
| `max_agent_runners`              | int          | `3`        | Maximum concurrent agent runners (agents and mentors) across all ChangeSpecs. |
| `zombie_timeout_seconds`         | int          | `7200`     | Seconds after which a running hook or workflow is flagged as a zombie.        |
| `query`                          | string       | `""`       | Query string for filtering ChangeSpecs (empty = all).                         |
| `chop_script_dirs`               | list[string] | `[]`       | Additional directories to search for external chop scripts.                   |
| `lumberjack_log_max_bytes`       | int          | `52428800` | Maximum bytes retained for each bounded lumberjack log.                       |
| `verbose_lumberjack_diagnostics` | bool         | `false`    | Include verbose diagnostics in chop script context JSON.                      |
| `lumberjacks`                    | dict         | -          | Mapping of lumberjack name → config (see below).                              |

**Lumberjack fields** (per entry under `lumberjacks`):

| Field          | Type                 | Default | Description                                                              |
| -------------- | -------------------- | ------- | ------------------------------------------------------------------------ |
| `interval`     | int                  | `1`     | Seconds between chop polling cycles.                                     |
| `chop_timeout` | string               | -       | Default duration limit for each chop in this lumberjack, such as `"90s"` |
| `chops`        | list[string\|object] | `[]`    | List of chops to run on each cycle (see below).                          |

**Chop fields** (per entry under `chops`):

| Field         | Type         | Required | Default | Description                                                                                  |
| ------------- | ------------ | -------- | ------- | -------------------------------------------------------------------------------------------- |
| `name`        | string       | yes      | -       | Chop name identifying the chop script to run.                                                |
| `description` | string       | yes      | -       | Human-readable description of what the chop does.                                            |
| `agent`       | string       | no       | `null`  | XPrompt reference to launch as a background agent (accepts legacy `xprompt` key).            |
| `run_every`   | string       | no       | -       | Time-based duration string (e.g., `"60m"`, `"30s"`, `"2h"`). Limits how often the chop runs. |
| `timeout`     | string       | no       | -       | Per-chop duration limit. Overrides the lumberjack-level `chop_timeout` when set.             |
| `env`         | dict[string] | no       | `{}`    | Environment variables passed to the chop script subprocess.                                  |

On a scheduled lumberjack tick, script chops remain concurrent, but configured agent chops launch sequentially in config
order. This prevents same-tick `run_every` agent chops from racing while they allocate workspaces. A manual
`sase axe chop run <agent-chop>` still launches only that one agent chop.

The built-in `wait_checks` chop writes `ready.json` only after named `%wait` dependencies complete successfully. Failed,
killed, crashed, still-running, malformed, or missing `done.json` artifacts do not satisfy the dependency.

Each chop entry can also be a plain string (chop name only, legacy format):

```yaml
chops:
  # Object format (required for new chops)
  - name: hook_checks
    description: Check for completed or failed hooks
  - name: custom_chop
    description: Run custom analysis
    agent: "#analyze"
    run_every: "5m"
    env:
      MY_API_KEY: "secret"
  # String format (legacy, description defaults to empty)
  - hook_checks
```

CLI flags on `sase axe start` override `max_hook_runners`, `max_agent_runners`, `zombie_timeout_seconds`, and `query`
for a single run (see [CLI Flags](#cli-flags)).

Source: `src/sase/axe/config.py`, `src/sase/default_config.yml`

### mentor_profiles

Defines mentor agents that run automated code reviews when a ChangeSpec's diff, changed files, or amend notes match
configurable criteria. Each profile groups one or more mentors with shared matching rules. See
[docs/mentors.md](mentors.md) for the full mentor system reference.

```yaml
mentor_profiles:
  - profile_name: python_review
    file_globs:
      - "*.py"
    mentors:
      - mentor_name: style_checker
        role: "Python style expert"
        focus_areas:
          - focus_name: style
            description: "PEP 8 compliance and code style"
          - focus_name: naming
            description: "Variable and function naming conventions"

  - profile_name: first_commit_review
    first_commit: true
    mentors:
      - mentor_name: architecture
        role: "Software architect"
        focus_areas:
          - focus_name: design
            description: "Overall design and architectural patterns"
```

**Profile fields:**

| Field                | Type         | Required | Description                                                                       |
| -------------------- | ------------ | -------- | --------------------------------------------------------------------------------- |
| `profile_name`       | string       | yes      | Unique name identifying this profile.                                             |
| `mentors`            | list         | yes      | List of mentor definitions (see below).                                           |
| `file_globs`         | list[string] | no\*     | Glob patterns matched against changed file paths.                                 |
| `diff_regexes`       | list[string] | no\*     | Regex patterns matched against the diff content.                                  |
| `amend_note_regexes` | list[string] | no\*     | Regex patterns matched against commit/amend notes.                                |
| `first_commit`       | bool         | no       | If true, match only on the first commit of a ChangeSpec.                          |
| `projects`           | list[string] | no       | Only match ChangeSpecs in these projects. Auto-set for local `sase.yml` profiles. |

\*At least one of `file_globs`, `diff_regexes`, `amend_note_regexes`, or `first_commit` must be provided per profile.

**Mentor fields:**

| Field         | Type         | Required | Description                                                 |
| ------------- | ------------ | -------- | ----------------------------------------------------------- |
| `mentor_name` | string       | yes      | Unique name identifying this mentor within its profile.     |
| `role`        | string       | yes      | Role or persona for the mentor (e.g., "Security reviewer"). |
| `focus_areas` | list[object] | yes      | List of review focus areas (see below).                     |

**Focus area fields:**

| Field         | Type   | Required | Description                                           |
| ------------- | ------ | -------- | ----------------------------------------------------- |
| `focus_name`  | string | yes      | Short name for this focus area (e.g., "correctness"). |
| `description` | string | yes      | Description of what this focus area reviews.          |

Mentors run automatically on ChangeSpecs with Ready or Mailed status when their matching criteria are met. Mentor
comments are structured JSON with severity levels (error, warning, suggestion) that can be reviewed and applied through
the ACE TUI's Mentor Review modal (`,m`).

Source: `src/sase/config/mentor.py`

### metahooks

Metahooks intercept failing hooks before the summarize agent runs. They match based on the hook command (substring
match) and the hook output (regex match). When a metahook matches, it can trigger specialized handling instead of the
default summarization.

```yaml
metahooks:
  - name: scuba
    hook_command: sase_hg_presubmit
    output_regex: "SCUBA_ERROR.*timeout"

  - name: flaky_test
    hook_command: blaze test
    output_regex: "FLAKY"
```

| Field          | Type   | Required | Description                                            |
| -------------- | ------ | -------- | ------------------------------------------------------ |
| `name`         | string | yes      | Unique identifier for this metahook.                   |
| `hook_command` | string | yes      | Substring matched against the executed hook command.   |
| `output_regex` | string | yes      | Regex pattern matched against hook output (multiline). |

Source: `src/sase/config/metahook.py`

### xprompts

Defines reusable prompt snippets that can be referenced with `#name` syntax in any prompt. Supports both simple string
content and structured definitions with typed inputs and Jinja2 templates.

```yaml
xprompts:
  # Simple string format
  greeting: "Hello, please review this code."

  # Structured format with inputs
  review:
    input:
      language: word
      strict: { type: bool, default: false }
    content: "Review this {{ language }} code.{{ ' Be strict.' if strict }}"

  # With tags for semantic role lookup
  my_crs:
    content: "Summarize the code review..."
    tags: [crs]
```

Xprompts defined in `sase.yml` are priority 6 out of 9 in the resolution order:

1. `.xprompts/*.md` (CWD, hidden directory)
2. `xprompts/*.md` (CWD)
3. `~/.xprompts/*.md` (home, hidden directory)
4. `~/xprompts/*.md` (home)
5. `~/.config/sase/xprompts/{project}/*.md` (project-specific)
6. `sase.yml` `xprompts:` section (local `./sase.yml` overrides global; see [Deep-Merge System](#deep-merge-system))
7. Plugin packages (via `sase_xprompts` entry points)
8. `<sase_package>/default_xprompts/*.md` (built-in default markdown xprompts)
9. `<sase_package>/xprompts/*.md` (built-in package xprompts)

Earlier sources win on name conflicts. File-based xprompts use YAML front matter for metadata and the file body for
content.

Source: `src/sase/xprompt/loader.py`

### xprompt_aliases

Defines raw text-level alias substitutions that are applied _before_ any xprompt processing. This is useful for creating
shorthand references where the alias must be present in the raw text for other processing logic (such as VCS
directory-switching) to work correctly.

```yaml
xprompt_aliases:
  c: commit # #c → #commit
  p: propose # #p → #propose
  gh_sase: "gh:sase" # #gh_sase → #gh:sase
  gh_foo: "gh:foo/bar" # #gh_foo → #gh:foo/bar
```

| Field             | Type         | Default                   | Description                                                  |
| ----------------- | ------------ | ------------------------- | ------------------------------------------------------------ |
| `xprompt_aliases` | dict[string] | `{c: commit, p: propose}` | Mapping of alias name → target. Applied as text substitution |

The built-in defaults provide `#c` as a shorthand for `#commit` and `#p` for `#propose`. Additional aliases can be added
in user config files.

Each entry maps an alias name to a target string. When the processor encounters `#alias_name` in a prompt, it replaces
it with `#target` before any other xprompt resolution occurs. Only `#`-prefixed references are substituted; the alias
name must match `[a-zA-Z_][a-zA-Z0-9_]*`.

Source: `src/sase/xprompt/processor.py`

### use_chezmoi

Enables chezmoi-aware home-file writes. When set to `true`, SASE writes generated home instructions, memory, skills, and
home-directory xprompt paths through the chezmoi source tree under `~/.local/share/chezmoi/home/` instead of writing the
live home files directly. For example, `~/.xprompts/` is remapped to `~/.local/share/chezmoi/home/dot_xprompts/`.

This affects initialization workflow as well as xprompt editing. `sase amd init` targets the chezmoi home source root
when it needs to initialize home-level `AGENTS.md`; `sase memory init` writes home memory there and may run the
configured chezmoi deploy path; `sase skills init` writes provider skill files there before optional commit, push, and
apply steps.

```yaml
use_chezmoi: true # default: false
```

| Field         | Type | Default | Description                                                         |
| ------------- | ---- | ------- | ------------------------------------------------------------------- |
| `use_chezmoi` | bool | `false` | Write home-managed SASE files through the chezmoi source directory. |

Source: `src/sase/config/core.py`

### precommit_command

A shell command to run before commits (e.g., linting, formatting). If set, the commit workflow executes this command
before creating a commit. An empty string (the default) means no precommit command is run.

```yaml
precommit_command: "just fix" # default: ""
```

| Field               | Type   | Default | Description                                                       |
| ------------------- | ------ | ------- | ----------------------------------------------------------------- |
| `precommit_command` | string | `""`    | Shell command to run before commits. Empty string means disabled. |

Source: `src/sase/default_config.yml`, `src/sase/workflows/commit/workflow.py`

### timezone

The timezone used for formatting timestamps in notifications, agent logs, and TUI displays.

```yaml
timezone: "America/New_York" # default: "America/New_York"
```

| Field      | Type   | Default              | Description                               |
| ---------- | ------ | -------------------- | ----------------------------------------- |
| `timezone` | string | `"America/New_York"` | IANA timezone name for timestamp display. |

### chat_install

Configuration for chat-driven update workflows. External chat integrations can call
`sase.integrations.chat_install.start_chat_install_worker()` to run the configured command in a detached worker while
briefly stopping axe, syncing the registered primary workspace for the `sase` project, and restarting axe afterward.

```yaml
chat_install:
  command: "" # default: disabled
  sync_workspace: true
  timeout_seconds: 900
  restart_attempts: 3
```

| Field                           | Type   | Default | Description                                                                                   |
| ------------------------------- | ------ | ------- | --------------------------------------------------------------------------------------------- |
| `chat_install.command`          | string | `""`    | Shell command to run from the registered `sase` primary workspace. Empty string disables use. |
| `chat_install.sync_workspace`   | bool   | `true`  | Sync the registered `sase` primary workspace via the selected VCS provider before updating.   |
| `chat_install.timeout_seconds`  | int    | `900`   | Maximum runtime for the update command before returning exit code `124`.                      |
| `chat_install.restart_attempts` | int    | `3`     | Number of axe restart attempts after the update command completes/fails.                      |

Only one chat update worker may run at a time; a lock under `~/.sase/chat_install/install.lock` rejects concurrent
starts. Worker output is written to timestamped logs under `~/.sase/chat_install/logs/`. The configuration key and state
paths remain named `chat_install` for compatibility. See [`docs/integrations.md`](integrations.md#chat-update-worker)
for the integration-facing Python API.

Source: `src/sase/default_config.yml`, `src/sase/integrations/chat_install.py`

### mobile_gateway

Configuration for `sase mobile gateway start`, which launches the workstation-hosted Rust gateway for paired mobile
clients.

```yaml
mobile_gateway:
  bind_address: "127.0.0.1"
  port: 7629
  state_dir: ""
  allow_non_loopback: false
  command: ""
  push_provider: "disabled"
  fcm_project_id: ""
  fcm_service_account_json: ""
  fcm_credential_env: ""
  fcm_dry_run: false
  push_timeout_seconds: 5
  push_retry_limit: 1
  startup_timeout_seconds: 10
```

| Field                                     | Type   | Default       | Description                                                               |
| ----------------------------------------- | ------ | ------------- | ------------------------------------------------------------------------- |
| `mobile_gateway.bind_address`             | string | `"127.0.0.1"` | Host address to bind. Non-loopback values require explicit opt-in.        |
| `mobile_gateway.port`                     | int    | `7629`        | Gateway HTTP port.                                                        |
| `mobile_gateway.state_dir`                | string | `""`          | SASE state root for gateway storage. Empty uses the Rust gateway default. |
| `mobile_gateway.allow_non_loopback`       | bool   | `false`       | Allow LAN or tailnet binds after explicit user opt-in.                    |
| `mobile_gateway.command`                  | string | `""`          | Gateway binary command override, parsed without a shell.                  |
| `mobile_gateway.push_provider`            | string | `"disabled"`  | Push provider: `disabled`, `test`, or `fcm`.                              |
| `mobile_gateway.fcm_project_id`           | string | `""`          | Firebase project ID for FCM HTTP v1.                                      |
| `mobile_gateway.fcm_service_account_json` | string | `""`          | Local service-account JSON path. Do not commit this file.                 |
| `mobile_gateway.fcm_credential_env`       | string | `""`          | Env var containing an FCM bearer token or service-account JSON.           |
| `mobile_gateway.fcm_dry_run`              | bool   | `false`       | Ask FCM to validate messages without delivering them.                     |
| `mobile_gateway.push_timeout_seconds`     | float  | `5`           | Timeout per push provider HTTP attempt.                                   |
| `mobile_gateway.push_retry_limit`         | int    | `1`           | Retry attempts for best-effort push delivery.                             |
| `mobile_gateway.startup_timeout_seconds`  | float  | `10`          | Seconds to wait for gateway readiness before exiting.                     |

Push payloads are hint-only and must not contain bearer tokens, pairing codes, prompt bodies, response text, attachment
contents, attachment tokens, or host paths. Only credential paths or environment-variable names are placed on the
gateway command line. See [`docs/mobile_gateway.md`](mobile_gateway.md#push-hints) for setup examples and security
notes.

Source: `src/sase/default_config.yml`, `src/sase/integrations/mobile_gateway.py`

### sdd

Configuration for spec-driven development features, including prompt, tale, epic, legend, myth, research, and bead
storage.

```yaml
sdd:
  version_controlled: false # default: false
```

| Field                    | Type | Default | Description                                                                                                                                 |
| ------------------------ | ---- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `sdd.version_controlled` | bool | `false` | For non-bare-git projects, store SDD artifacts and beads under `sdd/` in the project repo instead of `.sase/sdd/` in the primary workspace. |

When enabled, prompt snapshots, tales, epics, legends, myths, research notes, and the bead database directory are placed
in the project root so they can be committed with the code. When disabled, SDD writes to a standalone `.sase/sdd/` git
repo in the primary workspace for providers that support local SDD mode. Projects resolved as the built-in `bare_git`
VCS provider always use version-controlled SDD under `sdd/`, even if this option is false. See [`docs/sdd.md`](sdd.md)
for storage behavior and [`docs/beads.md`](beads.md) for the bead system reference.

Built-in bare-git projects also auto-create or refresh generated SDD guide files during `sase git init`, existing bare
repo registration, `#git`/workspace materialization, and the first version-controlled SDD write. Setup/materialization
flows commit and push only those generated init paths with an `Initialize SDD` init commit when needed.

Running `sase sdd init` or its `sase init sdd` alias is an explicit non-bare-git opt-in: it creates or updates the
project-local `sase.yml` so `sdd.version_controlled` is true, then refreshes generated SDD guide files and the directory
map.

Source: `src/sase/default_config.yml`

### bead

Configuration for the bead issue tracker.

```yaml
bead:
  push_after_commit: true # default: true
```

| Field                    | Type | Default | Description                                                                                                                     |
| ------------------------ | ---- | ------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `bead.push_after_commit` | bool | `true`  | When true, `sase bead work` runs `git push` after committing the bead-state event/projection mutation. Push failures only warn. |

Set to `false` for local-only checkouts, or when you would rather batch the bead-launch commit with later commits before
pushing. See [`docs/beads.md`](beads.md#sase-bead-work-id) for the full `sase bead work` flow.

Source: `src/sase/default_config.yml`

### workspace

Controls how SASE chooses the physical location of managed workspace checkouts. See
[`docs/workspace.md`](workspace.md#workspace-directory-layout) for the directory-layout reference and CLI workflows.

```yaml
workspace:
  root: xdg-state # "xdg-state", "adjacent", or an absolute path
  project_key: "" # explicit project-key override; empty = derive from git remote / primary path
  cleanup_ttl_days: 14 # age threshold for `sase workspace cleanup --stale`
```

| Field                        | Type   | Default       | Description                                                                                                                                                                                                                                    |
| ---------------------------- | ------ | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workspace.root`             | string | `"xdg-state"` | Root policy. `"xdg-state"` uses the platform state dir; `"adjacent"` keeps the legacy `<primary>_<num>/` layout as an explicit opt-in; an absolute path is used as the managed-root base. `SASE_WORKSPACE_ROOT` overrides this base directory. |
| `workspace.project_key`      | string | `""`          | Override the per-project namespace under managed roots. Empty derives a stable key from a single git remote slug or the primary-path basename plus a short hash.                                                                               |
| `workspace.cleanup_ttl_days` | int    | `14`          | Minimum age (in days) of an unclaimed managed checkout before `sase workspace cleanup --stale` will remove it.                                                                                                                                 |

Platform defaults for the `xdg-state` policy:

| Platform | Managed root                                                                       |
| -------- | ---------------------------------------------------------------------------------- |
| Linux    | `$XDG_STATE_HOME/sase/workspaces` (falls back to `~/.local/state/sase/workspaces`) |
| macOS    | `~/Library/Application Support/sase/workspaces`                                    |
| Windows  | `%LOCALAPPDATA%\sase\workspaces`                                                   |

Numeric identity is the same on every root policy: `#0` is the primary checkout, `#1`–`#9` are reserved, and managed
claim workspaces start at `#10`. See [`docs/workspace.md`](workspace.md#numeric-identity) for the full identity model
and backup/container/NFS caveats.

For non-adjacent policies, physical checkouts live under `<managed-root>/<project_key>/<project>_<num>/`. For example,
`workspace.root: /mnt/sase-workspaces` with project key `github.com_org_repo` places workspace `#10` at
`/mnt/sase-workspaces/github.com_org_repo/<project>_10/`. When `SASE_WORKSPACE_ROOT` is set, it supplies the same
`<managed-root>` base for the process.

Existing adjacent checkouts are not moved automatically by the default. Run `sase workspace migrate --to xdg-state` to
carry legacy `<primary>_<num>/` directories into the managed root, or set `workspace.root: adjacent` explicitly to keep
the old sibling layout.

`sase workspace open NUM` is an explicit preparation command for a checkout you plan to use outside a normal `sase run`
launch. It uses the same root policy when it materializes the checkout, backs up uncommitted local changes through the
active VCS provider, cleans the checkout, checks out and syncs the provider default parent revision, and prints the
resulting path. For manual scratch work, choose a claim-range number such as `10`; `#0` is the primary checkout and `#1`
through `#9` are reserved compatibility numbers.

Source: `src/sase/default_config.yml`, `src/sase/workspace_provider/store.py`

### telemetry

Configures Prometheus-based telemetry for monitoring sase internals. See [docs/telemetry.md](telemetry.md) for the full
telemetry reference including CLI commands, metric catalog, and monitoring stack setup.

```yaml
telemetry:
  enabled: false
  prometheus:
    exposition_port: 9464
    pushgateway_url: "localhost:9091"
  health_thresholds:
    error_rate_warn: 10.0
    error_rate_critical: 25.0
    retry_rate_warn: 10.0
    retry_rate_critical: 25.0
    p95_latency_warn: 300.0
    p95_latency_critical: 600.0
```

| Field                                              | Type  | Default          | Description                                      |
| -------------------------------------------------- | ----- | ---------------- | ------------------------------------------------ |
| `telemetry.enabled`                                | bool  | `false`          | Enable or disable telemetry globally.            |
| `telemetry.prometheus.exposition_port`             | int   | `9464`           | HTTP server port for metric exposition.          |
| `telemetry.prometheus.pushgateway_url`             | str   | `localhost:9091` | Prometheus Push Gateway address.                 |
| `telemetry.health_thresholds.error_rate_warn`      | float | `10.0`           | Error rate % threshold for WARN health status.   |
| `telemetry.health_thresholds.error_rate_critical`  | float | `25.0`           | Error rate % threshold for CRITICAL status.      |
| `telemetry.health_thresholds.retry_rate_warn`      | float | `10.0`           | Retry rate % threshold for WARN health status.   |
| `telemetry.health_thresholds.retry_rate_critical`  | float | `25.0`           | Retry rate % threshold for CRITICAL status.      |
| `telemetry.health_thresholds.p95_latency_warn`     | float | `300.0`          | P95 latency threshold (seconds) for WARN status. |
| `telemetry.health_thresholds.p95_latency_critical` | float | `600.0`          | P95 latency threshold (seconds) for CRITICAL.    |

Source: `src/sase/default_config.yml`, `src/sase/telemetry/_config.py`

## Environment Variables

### LLM Provider

| Variable                         | Description                                                                |
| -------------------------------- | -------------------------------------------------------------------------- |
| `SASE_MODEL_TIER_OVERRIDE`       | Force all LLM invocations to a specific tier (`large` or `small`).         |
| `SASE_MODEL_SIZE_OVERRIDE`       | Legacy alias for `SASE_MODEL_TIER_OVERRIDE` (`big` or `little`).           |
| `SASE_LLM_LARGE_ARGS`            | Extra CLI args appended for `large` tier invocations (any provider).       |
| `SASE_LLM_SMALL_ARGS`            | Extra CLI args appended for `small` tier invocations (any provider).       |
| `SASE_CLAUDE_LARGE_ARGS`         | Claude-specific extra args for `large` tier (fallback if generic unset).   |
| `SASE_CLAUDE_SMALL_ARGS`         | Claude-specific extra args for `small` tier (fallback if generic unset).   |
| `SASE_CODEX_PATH`                | Path to the Codex CLI binary (default: PATH lookup, then NVM_BIN/codex).   |
| `SASE_CODEX_LARGE_ARGS`          | Codex-specific extra args for `large` tier (fallback if generic unset).    |
| `SASE_CODEX_SMALL_ARGS`          | Codex-specific extra args for `small` tier (fallback if generic unset).    |
| `SASE_CODEX_DISABLE_SHADOW_HOME` | Set to `1` to launch Codex with the inherited `CODEX_HOME`.                |
| `SASE_AGENT_PLAN_MODE`           | Enable Codex two-phase plan/implement flow.                                |
| `SASE_QWEN_PATH`                 | Path to the Qwen Code CLI binary (default: `qwen`).                        |
| `SASE_QWEN_LARGE_ARGS`           | Qwen-specific extra args for `large` tier (fallback if generic unset).     |
| `SASE_QWEN_SMALL_ARGS`           | Qwen-specific extra args for `small` tier (fallback if generic unset).     |
| `SASE_OPENCODE_PATH`             | Path to the OpenCode CLI binary (default: `opencode`).                     |
| `SASE_OPENCODE_LARGE_ARGS`       | OpenCode-specific extra args for `large` tier (fallback if generic unset). |
| `SASE_OPENCODE_SMALL_ARGS`       | OpenCode-specific extra args for `small` tier (fallback if generic unset). |
| `SASE_GEMINI_PATH`               | Path to the Gemini CLI binary (default: `gemini`).                         |

For the per-provider args, the generic `SASE_LLM_*_ARGS` variables are checked first. If unset, the provider-specific
variable is used as a fallback. Values are split on whitespace and appended to the CLI command.

SASE-launched Codex subprocesses use a disposable shadow `CODEX_HOME` by default. The shadow home is created under
`~/.cache/sase/codex_home/`, receives a copy of the real `config.toml`, symlinks other Codex home entries back to the
real home, and is removed when the subprocess exits. If the real Codex home does not provide `AGENTS.override.md` or
`AGENTS.md`, SASE also links `~/AGENTS.md` into the shadow as Codex's `$CODEX_HOME/AGENTS.md` fallback. This prevents
Codex runtime config rewrites from dirtying the user-managed Codex config while preserving auth, hooks, skills, logs,
and caches.

Qwen Code uses `qwen --input-format text --output-format stream-json --yolo --model <model>` and expects users to
configure Qwen auth through Qwen's supported settings path. Qwen OAuth free tier access ended on 2026-04-15; use API
keys, Alibaba Cloud Coding Plan, OpenRouter, Fireworks, or another Qwen-supported provider.

OpenCode uses `opencode run --format json --dangerously-skip-permissions --model <provider/model> --dir <cwd> <prompt>`
and expects users to configure OpenCode auth/settings through its normal XDG paths. OpenCode model names usually include
a provider prefix; use `opencode models` to list models in your configured environment.

### VCS Provider

| Variable                           | Description                                                                                                                                               |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_VCS_PROVIDER`                | Override VCS provider selection (`git`, `hg`, or `auto`).                                                                                                 |
| `SASE_WORKSPACE_ROOT`              | Override the workspace-root base for this process. Use an absolute path; `WorkspaceStore` appends `<project_key>/<project>_<num>/` for managed checkouts. |
| `SASE_BUG_ID`                      | Bug ID for PR workflows. When set and non-zero, injects `BUG=<id>` into PR tags and ChangeSpec.                                                           |
| `SASE_BEAD_ID`                     | Bead ID for commit workflows. When set, `sase commit` automatically tags the commit message.                                                              |
| `SASE_DISABLE_COMMIT_STOP_HOOK`    | Disable commit finalization for this process.                                                                                                             |
| `SASE_SIBLING_REPOS_JSON`          | Resolved sibling-repo metadata passed to launched agents.                                                                                                 |
| `SASE_SIBLING_REPO_<ENV_NAME>_DIR` | Workspace-matched directory for one configured sibling repo.                                                                                              |

### Plugin System

These switches affect plugin-provided resource loading. The VCS, workspace, and LLM provider registries load provider
entry points directly.

| Variable                       | Description                                                             |
| ------------------------------ | ----------------------------------------------------------------------- |
| `SASE_DISABLE_PLUGINS`         | Disable plugin-provided xprompts, workflows, and config defaults.       |
| `SASE_DISABLE_PLUGIN_XPROMPTS` | Disable plugin-provided xprompt and workflow files.                     |
| `SASE_DISABLE_PLUGIN_CONFIG`   | Disable plugin-provided `default_config.yml` files and config xprompts. |

### State Root

| Variable    | Description                                                                                                                                                          |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_HOME` | Override the SASE state root. Defaults to `~/.sase`; project files, chats, artifacts, notifications, dismissed bundles, saved groups, and logs move under this root. |

### General

| Variable                              | Description                                                                                                     |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `SASE_TMPDIR`                         | Override the temp directory for all sase operations. Falls back to system default when unset.                   |
| `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION` | Plan-specific auto-approval action for an agent; currently `approve` or `epic`.                                 |
| `SASE_AGENT_AUTO_PLAN_ACTION`         | Backward-compatible alias for `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION`.                                            |
| `SASE_AGENT_AUTO_APPROVE`             | Legacy boolean auto-approve flag; maps plan submissions to normal approval.                                     |
| `SASE_XPROMPT_LSP_CMD`                | Override the command used by `sase lsp` to launch the xprompt language server.                                  |
| `SASE_CORE_DIR`                       | Preferred `sase-core` source checkout for `Justfile` Rust build/install targets; overrides `../sase-core`.      |
| `SASE_PYTEST_WORKERS`                 | Override the xdist worker count used by `just test`, `just test-slow`, `just test-visual`, and `just test-cov`. |
| `SASE_JUST_INVOCATION_DIR`            | Internal value set by `just` so test selectors are normalized from the caller's directory.                      |

### Workspace Management (Internal)

These are set automatically by sase when launching agent subprocesses and are not intended for manual use. Workspace
plugins declare an env-var prefix, then SASE passes `<PREFIX>_PRE_ALLOCATED`, `<PREFIX>_WORKSPACE_NUM`, and
`<PREFIX>_WORKSPACE_DIR` into the child process. Built-in prefixes include `SASE_CD` for `#cd` and `SASE_GIT` for
`#git`; plugin packages may add prefixes such as `SASE_GH` for GitHub. The launcher clears inherited
`SASE_*_PRE_ALLOCATED`, `SASE_*_WORKSPACE_NUM`, and `SASE_*_WORKSPACE_DIR` variables before applying the current
launch's values so follow-up agents cannot inherit stale workspace claims.

| Variable                       | Description                                                                 |
| ------------------------------ | --------------------------------------------------------------------------- |
| `SASE_SYNC_CWD`                | Working directory override for sync operations.                             |
| `<PREFIX>_PRE_ALLOCATED`       | Set to `"1"` when a workspace provider has pre-allocated a launch context.  |
| `<PREFIX>_WORKSPACE_NUM`       | Pre-allocated workspace number, or `0` for non-claiming directory contexts. |
| `<PREFIX>_WORKSPACE_DIR`       | Pre-allocated workspace directory path.                                     |
| `SASE_CD_*`, `SASE_GIT_*`, ... | Concrete forms for built-in and plugin-provided workspace prefixes.         |

## CLI Flags

Command groups that default to a nested `list` command still parse flags at the subcommand level. Use the explicit
`list` form when passing list options, such as `sase notify list -j`, `sase memory episodes list -p <project>`, or
`sase workspace list --json`.

### `sase ace`

| Flag                     | Values              | Default                   | Description                                                                                                                                                                           |
| ------------------------ | ------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[query]`                | string              | last saved query or `!!!` | Query string for filtering ChangeSpecs.                                                                                                                                               |
| `-m, --model-tier`       | `large`, `small`    | -                         | Override model tier for all LLM invocations.                                                                                                                                          |
| `-M, --model-size`       | `big`, `little`     | -                         | Deprecated alias for `--model-tier`.                                                                                                                                                  |
| `-p, --profile`          | optional path       | -                         | Profile the TUI session with pyinstrument (default output `$SASE_TMPDIR/ace_profile_<ts>.txt`); after exit, print a shortened path and copy it to the system clipboard when possible. |
| `-r, --refresh-interval` | int (seconds)       | `10`                      | Auto-refresh interval (0 to disable).                                                                                                                                                 |
| `-R, --restart-axe`      | flag                | -                         | Restart the axe daemon on startup (no-op if axe is not running).                                                                                                                      |
| `-x, --no-axe`           | flag                | -                         | Disable auto-starting the axe daemon.                                                                                                                                                 |
| `-v, --vcs-provider`     | `git`, `hg`, `auto` | -                         | Override VCS provider.                                                                                                                                                                |

### `sase axe`

| Flag                 | Values              | Default | Description            |
| -------------------- | ------------------- | ------- | ---------------------- |
| `-v, --vcs-provider` | `git`, `hg`, `auto` | -       | Override VCS provider. |

### `sase axe start`

| Flag                      | Values        | Default          | Description                                         |
| ------------------------- | ------------- | ---------------- | --------------------------------------------------- |
| `-q, --query`             | string        | `""` (all)       | Query string for filtering ChangeSpecs.             |
| `-H, --max-hook-runners`  | int           | config or `3`    | Maximum concurrent hook runners.                    |
| `-A, --max-agent-runners` | int           | config or `3`    | Maximum concurrent agent runners.                   |
| `-z, --zombie-timeout`    | int (seconds) | config or `7200` | Timeout before marking a hook/workflow as a zombie. |

For `sase axe start`, CLI flags take precedence over values from the `axe` config section in `sase.yml`. If neither is
set, the built-in defaults from `default_config.yml` are used.

### `sase repro`

Agents-tab reproduction bundles capture and replay the loader/apply sequence used to render agent rows. The command is
intended for debugging row disappearance, reappearance, and duplicate-parent regressions; see
[Agents Tab Reproduction Bundles](ace.md#agents-tab-reproduction-bundles).

| Form                            | Flag                | Values | Default  | Description                                                                |
| ------------------------------- | ------------------- | ------ | -------- | -------------------------------------------------------------------------- |
| `sase repro capture agents-tab` | `--output`          | path   | required | Directory where `agents_tab_repro.json` and capture artifacts are written. |
| `sase repro capture agents-tab` | `--commit-safe`     | flag   | enabled  | Redact local names and paths for a shareable bundle.                       |
| `sase repro capture agents-tab` | `--no-commit-safe`  | flag   | -        | Keep unredacted local identifiers in the capture.                          |
| `sase repro capture agents-tab` | `--size`            | `WxH`  | `120x40` | Terminal size label stored with the bundle.                                |
| `sase repro capture agents-tab` | `--json`            | flag   | -        | Emit a machine-readable capture result.                                    |
| `sase repro replay`             | `path`              | path   | required | Bundle JSON file or bundle directory to replay.                            |
| `sase repro replay`             | `--assert-stable`   | flag   | -        | Exit non-zero if replay invariants fail.                                   |
| `sase repro replay`             | `--json`            | flag   | -        | Emit a machine-readable replay verdict.                                    |
| `sase repro replay`             | `--write-artifacts` | path   | -        | Directory for replay screen text and SVG artifacts.                        |
| `sase repro replay`             | `--size`            | `WxH`  | `120x40` | Headless terminal size used for replay.                                    |

### `sase axe stop`

No flags. Stops the running axe orchestrator.

### `sase axe maintenance`

Maintenance mode pauses scheduled lumberjack ticks without stopping the orchestrator.

| Command                       | Flags / exit code                    | Description                                     |
| ----------------------------- | ------------------------------------ | ----------------------------------------------- |
| `sase axe maintenance enter`  | `-r, --reason` required              | Write the maintenance marker with a reason.     |
| `sase axe maintenance exit`   | exits 0                              | Remove the marker if present.                   |
| `sase axe maintenance status` | exits 0 when active, 1 when inactive | Print the active marker reason, PID, timestamp. |

See [axe.md — Maintenance Mode](axe.md#maintenance-mode) for the runtime behavior.

### `sase commit`

Dispatches a commit, proposal, or PR via the VCS provider layer. See [commit_workflows.md](commit_workflows.md) for the
full flow, payload, checkpoint, and resume semantics.

| Flag                    | Values                        | Default                 | Description                                                                                      |
| ----------------------- | ----------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------ |
| `-m, --message`         | string                        | -                       | Commit message (mutually exclusive with `-M`).                                                   |
| `-M, --message-file`    | path                          | -                       | File containing the commit message / PR description (mutually exclusive with `-m`).              |
| `-f, --file`            | path (repeatable)             | stage all               | Specific file to stage. Repeat for multiple; omit to stage everything.                           |
| `-n, --name`            | string                        | -                       | Branch/CL name (required for `create_pull_request`).                                             |
| `-B, --bug-id`          | int                           | `$SASE_BUG_ID`          | Bug ID to associate with the commit.                                                             |
| `-c, --checkout-target` | string                        | `HEAD~1`                | Branch point for PR creation.                                                                    |
| `-p, --parent`          | ChangeSpec name               | auto                    | Parent ChangeSpec name (overrides branch-based auto-detection). Unresolvable values are dropped. |
| `-r, --resume`          | flag                          | -                       | Resume a previously-checkpointed commit after manual conflict resolution.                        |
| `-s, --status`          | `wip` / `draft` / `ready`     | `$SASE_PR_STATUS`/draft | ChangeSpec status override for PRs.                                                              |
| `-t, --type`            | `commit` / `propose` / `pr` … | `$SASE_COMMIT_METHOD`   | Commit method — full names (`create_commit`, etc.) and short aliases are both accepted.          |

### `sase changespec search`

| Flag           | Values                      | Default    | Description                                           |
| -------------- | --------------------------- | ---------- | ----------------------------------------------------- |
| `query`        | string                      | (required) | Query string for filtering ChangeSpecs.               |
| `-f, --format` | `plain`, `rich`, `markdown` | `rich`     | Output format (`markdown` for agent-friendly output). |

Search uses the normal active-project discovery scope. Inactive and sibling projects are omitted from this CLI path; run
`sase project list --state all` or `sase project show <project>` to inspect hidden projects, then reactivate the project
with `sase project activate <project>` before using normal search and launch surfaces for new work.

### `sase changespec migrate-extension`

One-time cleanup for older installs: renames legacy ProjectSpec files under `~/.sase/projects` from `.gp` to `.sase`,
including archive siblings. Current readers still accept `.gp` as a fallback, so migration is not required before using
SASE; it just normalizes on-disk filenames to the canonical extension.

If a `.sase` sibling already exists with identical contents, the redundant `.gp` copy is removed. If the sibling
differs, the command reports a conflict and preserves both files unless `--force` is set.

| Flag             | Values | Default             | Description                                                               |
| ---------------- | ------ | ------------------- | ------------------------------------------------------------------------- |
| `--force`        | flag   | -                   | Replace an existing differing `.sase` sibling with the legacy `.gp` file. |
| `--projects-dir` | path   | `~/.sase/projects/` | Override the project root scanned for legacy `.gp` files.                 |

### `sase project`

With no subcommand, `sase project` defaults to `sase project list`. Project lifecycle state is stored as `PROJECT_STATE`
metadata in the ProjectSpec header; missing state means `active`.

| Form                                       | Flags                                        | Description                                                                    |
| ------------------------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------ |
| `sase project list`                        | `-s, --state active\|inactive\|sibling\|all` | List projects in one lifecycle state; default is `active`.                     |
| `sase project list`                        | `-j, --json`                                 | Emit machine-readable lifecycle records.                                       |
| `sase project show <project>`              | `-j, --json`                                 | Show state, source, project/archive files, workspace, launchability, warnings. |
| `sase project set-state <project> <state>` | `-f, --force`                                | Set `active`, `inactive`, or `sibling`.                                        |
| `sase project activate <project>`          | `-f, --force`                                | Alias for `set-state <project> active`; `--force` has no effect for `active`.  |
| `sase project deactivate <project>`        | `-f, --force`                                | Alias for `set-state <project> inactive`.                                      |

Deactivating refuses projects with live `RUNNING` claims or live artifact markers (`running.json`, `waiting.json`, or
`pending_question.json`) unless `--force` is passed. Legacy `archive` and `close` aliases still set `inactive`, and
legacy `PROJECT_STATE: archived` / `PROJECT_STATE: closed` files are read as inactive. The system-managed `home` project
cannot be mutated through this command. Normal launch and discovery surfaces default to active projects; use
`list --state all` or `show` for historical or sibling inspection, then `activate` before launching normal work in a
hidden project. The `sibling` state is intended for configured sibling repository records used by
`sase workspace open -p <sibling> <workspace_num>`.

ACE exposes the same lifecycle mutations through the Project Management panel at `,p`. That panel also supports marks
for bulk lifecycle operations, ProjectSpec editing through `$EDITOR`, and confirmed deletion of whole SASE project
directories under `~/.sase/projects/` without deleting workspace checkouts. The temporary model override uses `,o` by
default.

### `sase revert`

| Flag   | Values | Default    | Description                       |
| ------ | ------ | ---------- | --------------------------------- |
| `name` | string | (required) | NAME of the ChangeSpec to revert. |

### `sase restore`

| Flag         | Values | Default | Description                                 |
| ------------ | ------ | ------- | ------------------------------------------- |
| `[name]`     | string | -       | NAME of the reverted ChangeSpec to restore. |
| `-l, --list` | flag   | -       | List all reverted ChangeSpecs.              |

### `sase run`

| Flag           | Values | Default | Description                                                                                                   |
| -------------- | ------ | ------- | ------------------------------------------------------------------------------------------------------------- |
| `[query]`      | string | -       | Prompt text, inline reference (`#name`), standalone workflow reference (`#!name`), or `.` for history picker. |
| `-d, --daemon` | flag   | -       | Run as a detached background agent (appears in TUI Agents tab).                                               |
| `-l, --list`   | flag   | -       | List all available chat history files.                                                                        |
| `-r, --resume` | string | -       | Resume a previous conversation by agent name or history file basename.                                        |

When invoked with no arguments, opens `$EDITOR` for composing a prompt interactively. When invoked with `.`, opens a
prompt history picker. Multi-prompt queries (containing `---` separators) are auto-detected and launched as sequential
daemon agents.

### `sase repro`

`sase repro` captures and replays debugging bundles for narrow, reproducible TUI bug classes. The current target is the
Agents-tab loader/apply sequence used to diagnose row disappearance, reappearance, and duplicate workflow parents.

| Form                            | Flags                                                                     | Description                                                                                        |
| ------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `sase repro replay <path>`      | `--assert-stable`, `--json`, `--write-artifacts <dir>`, `--size`          | Replay a bundle JSON file or bundle directory through the headless TUI harness.                    |
| `sase repro capture agents-tab` | `--output <dir>`, `--commit-safe`, `--no-commit-safe`, `--size`, `--json` | Capture a baseline bundle from current filesystem state. `--commit-safe` redaction is the default. |

Use the in-TUI `,R` capture when a transient row-list bug has just happened in a live ACE session. The CLI capture path
is out-of-band: it loads current filesystem state and cannot reconstruct refreshes that already passed through the
running TUI.

### `sase xprompt`

With no subcommand, `sase xprompt` defaults to `sase xprompt list`.

### `sase xprompt expand`

| Flag          | Values | Default | Description                                                  |
| ------------- | ------ | ------- | ------------------------------------------------------------ |
| `[prompt]`    | string | stdin   | Prompt text to expand (reads from stdin if omitted).         |
| `-t, --trace` | flag   | -       | Print expansion trace to stderr showing resolved references. |

### `sase xprompt explain`

| Flag            | Values | Default    | Description                                 |
| --------------- | ------ | ---------- | ------------------------------------------- |
| `workflow_name` | string | (required) | Workflow name to explain.                   |
| `[args]`        | string | -          | Positional arguments for the workflow.      |
| `-a, --arg`     | string | -          | Named argument as `KEY=VALUE` (repeatable). |

### `sase xprompt list`

No flags. Outputs a JSON array of all available xprompts with name, type, source, inputs, tags, `is_skill`, and preview.
Clients that insert references should prefer `kind`/`insertion` metadata when present so standalone workflows are
inserted as `#!name` and inline-capable entries are inserted as `#name`. Slash skill completion clients should filter to
entries where `is_skill` is `true`.

### `sase xprompt graph`

| Flag              | Values           | Default   | Description                                             |
| ----------------- | ---------------- | --------- | ------------------------------------------------------- |
| `[workflow_name]` | string           | -         | Workflow name to graph. Lists all workflows if omitted. |
| `-f, --format`    | `mermaid`,`text` | `mermaid` | Output format for the DAG visualization.                |

### `sase xprompt catalog`

| Flag        | Values | Default | Description                                       |
| ----------- | ------ | ------- | ------------------------------------------------- |
| `-o, --out` | path   | tempdir | Directory where the rendered PDF should be saved. |

### `sase init`

Bare `sase init` is the onboarding coordinator for SASE-managed resources. It runs read-only planners for AMD, memory,
SDD, and skills, prints a grouped summary, and prompts once per initializer that needs work when stdin is interactive.
Non-interactive runs never prompt; they print the drift summary and ask the caller to rerun with `--yes`. The AMD
planner only generates managed project `AGENTS.md` from bare `sase init` when the current project's own `./sase.yml`
sets `amd_h1_title`.

Advanced deploy controls stay on explicit subcommands such as `sase init amd --check`, `sase init memory --no-commit`,
and `sase skills init --no-push`.

| Flag          | Values | Default | Description                                                                          |
| ------------- | ------ | ------- | ------------------------------------------------------------------------------------ |
| `-c, --check` | flag   | -       | Report initialization drift without writing; exits non-zero when changes are needed. |
| `-y, --yes`   | flag   | -       | Run every needed initializer in AMD, memory, SDD, skills order without prompting.    |

### `sase amd`

With no subcommand, `sase amd` defaults to `sase amd list`.

| Form            | Flags         | Description                                                                                        |
| --------------- | ------------- | -------------------------------------------------------------------------------------------------- |
| `sase amd`      | -             | Show the same read-only agent-markdown inventory as `sase amd list`.                               |
| `sase amd list` | -             | Inspect project, home, and chezmoi `AGENTS.md` files and provider shims.                           |
| `sase amd init` | `-c, --check` | Create or refresh `AGENTS.md` files and shims for the selected AMD root or roots, or report drift. |
| `sase init amd` | `-c, --check` | Compatibility alias for `sase amd init`.                                                           |

### `sase memory`

With no subcommand, `sase memory` defaults to `sase memory list`.

| Form                      | Flags                                                                                                                                                                | Description                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `sase memory`             | -                                                                                                                                                                    | Show the same read-only memory context dashboard as `sase memory list`.                             |
| `sase memory list`        | -                                                                                                                                                                    | Show loaded, referenced, available, and missing memory files for the current launch context.        |
| `sase memory read <path>` | `-r, --reason <reason>` required                                                                                                                                     | Agent-side read of a `memory/long/` Markdown file without leading frontmatter, plus an audit event. |
| `sase memory write`       | `--title`, `--target` or `--slug`, repeatable `--evidence`, `--from-chat`, `--keyword`, `--body`, `--file`, `--allow-large`, `--manual-author`, `--notify`, `--json` | Create an attributable long-term memory proposal without modifying canonical memory files.          |
| `sase memory review [id]` | `--list`, `--show`, `--approve`, `--edit`, `--reject`, `--all`, `--target`, `--edited-file`, `--reason`, `--json`                                                    | Human review of pending memory proposals; a bare TTY command opens the interactive review app.      |
| `sase memory log`         | `--path`, `--agent`, `--id`, `--include`, `--json`                                                                                                                   | Summarize or inspect audited memory reads, optionally including proposal and review events.         |
| `sase memory episodes`    | `auto`, `build`, `doctor`, `export`, `list`, `recall`, `show`, `status`, `verify`                                                                                    | Build, inspect, verify, export, recall, and maintain deterministic source-linked episode records.   |

Examples:

```bash
# read requires SASE agent identity; write requires agent identity unless --manual-author is used for demos
sase memory read long/generated_skills.md --reason "Need generated skill context"
sase memory write --title "Generated skills" --slug generated_skills --evidence chat:abc123 --body "Durable memory body" --notify
sase memory review --list
sase memory review mem-20260523-142233-a1b2c3d4 --approve
sase memory log
sase memory log --include proposals
sase memory log --path long/generated_skills.md
sase memory log --id <read-id>
```

#### `sase memory episodes`

`sase memory episodes` stores deterministic records of prior agent work under `~/.sase/projects/<project>/episodes/`.
With no subcommand, it defaults to `sase memory episodes list` with default options. Use the explicit subcommand when
passing flags, for example `sase memory episodes list -p <project> -j`. All subcommands accept
`-p, --project <project>`.

| Form                                 | Flags                                                                                                                                                                                                             | Description                                                                    |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `sase memory episodes auto`          | `-D, --dry-run`, `-l, --limit`, `-j, --json`                                                                                                                                                                      | Run one checkpointed automatic episode-build cycle over new done markers.      |
| `sase memory episodes build`         | `-n, --agent`, `-a, --artifact-dir`, `-c, --changespec`, `-C, --chat`, `-s, --since`, `-u, --until`, `-l, --limit`, `-S, --split`, `-A, --aggregate`, `-D, --dry-run`, `-f, --force`, `-q, --quiet`, `-j, --json` | Build split v2 component episodes or aggregate compatibility output.           |
| `sase memory episodes doctor`        | `-R, --repair`, `-j, --json`                                                                                                                                                                                      | Inspect automatic-builder state and apply safe repairs when requested.         |
| `sase memory episodes export`        | `-s, --since`, `-u, --until`, `-b, --band`, `-n, --agent`, `-c, --changespec`, `-B, --bead`, `-q, --query`, `-o, --order`, `-l, --limit`, `-j, --json`                                                            | Export bounded read-only episode summaries for future event review.            |
| `sase memory episodes list`          | `-s, --since`, `-u, --until`, `-b, --band`, `-n, --agent`, `-c, --changespec`, `-B, --bead`, `-q, --query`, `-g, --group`, `-o, --order`, `-l, --limit`, `-j, --json`                                             | Inventory stored episodes by event span, importance, metadata, and query.      |
| `sase memory episodes show <id>`     | `-f, --format overview\|timeline\|graph\|sources\|agent\|json\|lesson`, `-e, --edge-mode strong\|all`, `-j, --json`                                                                                               | Show overview, graph, provenance, agent evidence pack, JSON, or legacy lesson. |
| `sase memory episodes status`        | `-j, --json`                                                                                                                                                                                                      | Show automatic-builder checkpoint, lock, index, and latest metrics status.     |
| `sase memory episodes verify [id]`   | `-A, --all`, `-j, --json`                                                                                                                                                                                         | Verify source existence, size, and hashes for one episode or all stored rows.  |
| `sase memory episodes recall -q <q>` | `-l, --limit`, `-j, --json`                                                                                                                                                                                       | Search stored episode evidence with deterministic keyword matching.            |

Human-mode `build` emits phase progress to stderr; `--quiet` suppresses that progress while keeping the final stdout
summary. JSON aggregate build output is stderr-silent and includes `episode`, `build_request`, and `build_report`
objects. JSON split build output includes `components` and `build_reports` lists. Current episode writes are
content-idempotent. `--force` is accepted and appears in the JSON build request, but unchanged episode files are still
left untouched.

### `sase memory init`

Creates or refreshes project and home memory roots and keeps `AGENTS.md` memory references reachable. It creates a
minimal `AGENTS.md` when absent for repositories that are not opted into AMD-managed instructions, and it still repairs
provider instruction shims for compatibility. When the project-local `./sase.yml` sets `amd_h1_title`, memory init
synchronizes that project's AMD-managed short/long memory blocks and inserts missing long-memory `description`
frontmatter. By default it also tries to commit, rebase-pull, and push generated project-side files. `sase init memory`
is a compatibility alias for this command. Generated sibling-repository memory lists direct paths for
`workspace.strategy: none` siblings and only includes `sase workspace open` guidance when a configured sibling uses
numbered workspace resolution.

| Flag              | Values | Default | Description                                                                                             |
| ----------------- | ------ | ------- | ------------------------------------------------------------------------------------------------------- |
| `-c, --check`     | flag   | -       | Report memory initialization drift without writing project or home files.                               |
| `-C, --no-commit` | flag   | -       | Write files, but skip only the project git commit/pull/push path; home deployment still follows config. |

### `sase init sdd`

`sase init sdd` is an alias for `sase sdd init`. It enables version-controlled SDD in the project-local `sase.yml`, then
creates or refreshes generated SDD README files and the directory map asset. Bare-git projects run the generated-file
refresh automatically during repository setup and first SDD writes, but the explicit command remains available for
manual opt-in, refresh, and `--check` audits.

| Flag          | Values | Default                  | Description                                                       |
| ------------- | ------ | ------------------------ | ----------------------------------------------------------------- |
| `-c, --check` | flag   | -                        | Report SDD config and generated-file drift without writing files. |
| `-p, --path`  | path   | `./sdd` or `./.sase/sdd` | SDD root or project root path.                                    |

### `sase skills`

With no subcommand, `sase skills` defaults to the read-only `sase skills list` dashboard. It reports loaded skill
sources, provider targets, and deployed-file drift without writing files. `sase skills init` generates and deploys agent
skill files from xprompt sources marked with the `skill` field. See [xprompt.md — Skill Field](xprompt.md#skill-field)
for the skill-source contract and provider targets. Existing files are skipped in non-interactive runs unless `--force`
is passed; interactive runs prompt before overwriting. `sase init skills` is a compatibility alias for
`sase skills init`.

| Form               | Flags                                                | Description                                                                                 |
| ------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `sase skills`      | -                                                    | Show the same read-only dashboard as `sase skills list`.                                    |
| `sase skills list` | -                                                    | Inspect generated skill sources, provider targets, and deployed-file drift.                 |
| `sase skills init` | `-f, --force`                                        | Overwrite existing deployed skill files without confirmation.                               |
| `sase skills init` | `-n, --dry-run`                                      | Show what would be written without writing files.                                           |
| `sase skills init` | `-p, --provider {claude,gemini,codex,opencode,qwen}` | Deploy only for one provider.                                                               |
| `sase skills init` | `-A, --no-apply`                                     | With `use_chezmoi`, skip `chezmoi apply` after generated files are committed and pushed.    |
| `sase skills init` | `-C, --no-commit`                                    | With `use_chezmoi`, skip the entire git commit, push, and apply sequence.                   |
| `sase skills init` | `-P, --no-push`                                      | With `use_chezmoi`, commit generated files but skip pull/rebase, push, and `chezmoi apply`. |
| `sase init skills` | same as `sase skills init`                           | Compatibility alias for `sase skills init`.                                                 |

### `sase git init`

| Flag              | Values | Default                    | Description                                             |
| ----------------- | ------ | -------------------------- | ------------------------------------------------------- |
| `project_name`    | string | (required)                 | Name of the project to initialize.                      |
| `-b, --bare-dir`  | path   | `~/.sase/repos/<name>.git` | Override bare repo path.                                |
| `-c, --clone-dir` | path   | `~/projects/git/<name>/`   | Override clone path.                                    |
| `-e, --existing`  | path   | -                          | Register an existing bare repo instead of creating one. |

New bare-git projects include generated SDD guide files in their initial commit. When `--existing` registers a bare repo
that lacks current generated SDD guide files, SASE commits and pushes only those generated paths before writing the
ProjectSpec.

### `sase workspace`

Workspace commands inspect and maintain the managed checkout registry for the inferred project, or for the project named
by `-p/--project`. With no subcommand, `sase workspace` defaults to `sase workspace list` with default options. Use
`sase workspace list -p <project>` or `sase workspace list --json` when passing list flags.

| Command                  | Flag / argument            | Values       | Description                                                                                         |
| ------------------------ | -------------------------- | ------------ | --------------------------------------------------------------------------------------------------- |
| `sase workspace list`    | `-p, --project`            | project name | Query a project other than the one inferred from the current directory.                             |
| `sase workspace list`    | `-j, --json`               | flag         | Emit a machine-readable JSON object.                                                                |
| `sase workspace path`    | `workspace_num`            | integer      | Workspace number to resolve; `0` is the primary checkout and managed claims normally start at `10`. |
| `sase workspace path`    | `-p, --project`            | project name | Query a project other than the inferred one.                                                        |
| `sase workspace open`    | `workspace_num`            | integer      | Workspace number to materialize, prepare, and print.                                                |
| `sase workspace open`    | `-p, --project`            | project name | Query a project other than the inferred one.                                                        |
| `sase workspace open`    | `-P, --print`              | flag         | Explicitly print the prepared path; this is also the current default behavior.                      |
| `sase workspace open`    | `-c, --clean`              | flag         | Compatibility flag for the default prepare/clean/sync behavior.                                     |
| `sase workspace cleanup` | `-p, --project`            | project name | Clean a project other than the inferred one.                                                        |
| `sase workspace cleanup` | `-s, --stale`              | flag         | Remove unclaimed managed checkouts older than `workspace.cleanup_ttl_days`.                         |
| `sase workspace cleanup` | `-i, --include-shares`     | flag         | Also consider workflow-share managed checkouts for removal.                                         |
| `sase workspace cleanup` | `-n, --dry-run`            | flag         | Report planned removals without touching the filesystem.                                            |
| `sase workspace repair`  | `-p, --project`            | project name | Repair a project other than the inferred one.                                                       |
| `sase workspace repair`  | `-n, --dry-run`            | flag         | Report registry/filesystem reconciliation without writing.                                          |
| `sase workspace migrate` | `-p, --project`            | project name | Migrate a project other than the inferred one.                                                      |
| `sase workspace migrate` | `-t, --to`                 | `xdg-state`  | Target managed root policy for migration.                                                           |
| `sase workspace migrate` | `-s, --symlink-transition` | flag         | Leave `<primary>_<num>` symlinks pointing to migrated managed checkouts.                            |
| `sase workspace migrate` | `-f, --finalize`           | flag         | Remove transition symlinks left behind by a prior migration.                                        |
| `sase workspace migrate` | `-n, --dry-run`            | flag         | Report planned migration or finalization actions without touching files or the registry.            |

For built-in bare-git projects, `sase workspace open` may initialize generated SDD guide files in the primary checkout
before materializing a numbered workspace. `sase workspace list` and `sase workspace path` remain read-only and do not
run SDD initialization.

### `sase bead`

With no subcommand, `sase bead` defaults to `sase bead list`.

| Flag         | Values                                                                                                                                     | Default | Description     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------ | ------- | --------------- |
| _subcommand_ | `init`, `create`, `list`, `show`, `ready`, `open`, `update`, `close`, `rm`, `dep`, `blocked`, `sync`, `stats`, `doctor`, `onboard`, `work` | `list`  | Bead subcommand |

#### `sase bead create`

| Flag                | Values                   | Default    | Description                                                                 |
| ------------------- | ------------------------ | ---------- | --------------------------------------------------------------------------- |
| `-t, --title`       | string                   | (required) | Issue title                                                                 |
| `-T, --type`        | string                   | (required) | Bead type: `plan(<file>)`, `plan(<file>,<parent>)`, or `phase(<parent_id>)` |
| `-d, --description` | string                   | -          | Issue description                                                           |
| `-a, --assignee`    | string                   | -          | Assignee name                                                               |
| `--tier`            | `plan`, `epic`, `legend` | -          | Plan-bead tier                                                              |
| `-c, --changespec`  | ChangeSpec name          | -          | Attach ChangeSpec metadata to a plan bead                                   |
| `-b, --bug-id`      | string                   | -          | Bug ID for the attached ChangeSpec; requires `--changespec`                 |
| `-E, --epic-count`  | positive integer         | -          | Number of epics proposed by a legend plan bead                              |

#### `sase bead list`

| Flag           | Values                          | Default | Description                           |
| -------------- | ------------------------------- | ------- | ------------------------------------- |
| `-s, --status` | `open`, `in_progress`, `closed` | -       | Filter by status (repeatable)         |
| `-t, --type`   | `plan`, `phase`                 | -       | Filter by type (repeatable)           |
| `--tier`       | `plan`, `epic`, `legend`        | -       | Filter by plan-bead tier (repeatable) |

#### `sase bead show`

| Flag | Values | Default    | Description |
| ---- | ------ | ---------- | ----------- |
| `id` | string | (required) | Issue ID    |

#### `sase bead open`

| Flag | Values | Default    | Description        |
| ---- | ------ | ---------- | ------------------ |
| `id` | string | (required) | Issue ID to reopen |

#### `sase bead update`

| Flag                | Values                          | Default    | Description              |
| ------------------- | ------------------------------- | ---------- | ------------------------ |
| `id`                | string                          | (required) | Issue ID to update       |
| `-s, --status`      | `open`, `in_progress`, `closed` | -          | Change status            |
| `-t, --title`       | string                          | -          | Change title             |
| `-d, --description` | string                          | -          | Change description       |
| `-n, --notes`       | string                          | -          | Change notes             |
| `-D, --design`      | path                            | -          | Change plan path         |
| `-a, --assignee`    | string                          | -          | Change assignee          |
| `--tier`            | `plan`, `epic`, `legend`        | -          | Change plan-bead tier    |
| `-E, --epic-count`  | positive integer                | -          | Change legend epic count |

#### `sase bead close`

| Flag           | Values | Default    | Description                |
| -------------- | ------ | ---------- | -------------------------- |
| `ids`          | string | (required) | One or more issue IDs      |
| `-r, --reason` | string | -          | Optional close reason text |

#### `sase bead rm`

| Flag | Values | Default    | Description        |
| ---- | ------ | ---------- | ------------------ |
| `id` | string | (required) | Issue ID to remove |

#### `sase bead dep add`

| Flag         | Values | Default    | Description               |
| ------------ | ------ | ---------- | ------------------------- |
| `issue`      | string | (required) | Issue that depends        |
| `depends_on` | string | (required) | Issue being depended upon |

#### `sase bead sync`

| Flag           | Values | Default | Description                          |
| -------------- | ------ | ------- | ------------------------------------ |
| `-s, --status` | flag   | -       | Check sync status without committing |

#### `sase bead work`

| Flag            | Values | Default    | Description                                                              |
| --------------- | ------ | ---------- | ------------------------------------------------------------------------ |
| `id`            | string | (required) | Epic or legend plan bead ID.                                             |
| `-n, --dry-run` | flag   | -          | Print the wave plan and rendered multi-prompt without mutating state.    |
| `-y, --yes`     | flag   | -          | Skip the launch confirmation prompt when launching phase or epic agents. |

### `sase sdd`

`sase sdd` manages SDD prompt/artifact documentation and frontmatter links. Every subcommand accepts `-p/--path`, which
may point at an SDD root or at a project root containing `sdd/`. With no subcommand, `sase sdd` defaults to
`sase sdd list`. `sase init sdd` is an alias for `sase sdd init`.

| Subcommand     | Flags                                                                    | Description                                                                                                           |
| -------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `init`         | `-p/--path`, `-c/--check`                                                | Create or refresh `sdd/README.md`, tier READMEs, and the directory map asset; `--check` reports drift without writing |
| `list`         | `-p/--path`, `-k/--kind`, `-j/--json`                                    | List SDD markdown files; kind is `prompts`, `tales`, `epics`, `legends`, or `all`                                     |
| `links`        | `-p/--path`, `-j/--json`                                                 | List prompt/artifact frontmatter links and bidirectional status                                                       |
| `validate`     | `-p/--path`, `-j/--json`, `-q/--quiet`, `--strict`, `-W/--show-warnings` | Validate SDD frontmatter links; strict mode turns unpaired historical files into errors                               |
| `repair-links` | `-p/--path`, `-w/--write`                                                | Infer unambiguous prompt/artifact pairs and optionally write link fixes                                               |

### `sase validate`

`sase validate` is the top-level SASE validation command. It currently runs `sase init --check` and `sase sdd validate`,
prints one status line per check, and exits non-zero if any check fails. Because `sase init --check` includes home-level
memory and skill deployment surfaces, this command can fail on user/home initialization drift even when repository-local
SDD validation passes.

### `sase var`

`sase var set` attaches small named string values to the current SASE agent run by merging them into
`agent_meta.json["output_variables"]`. The command is agent-scoped and requires `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR`.
The variables appear in ACE's Agents-tab metadata panel and can be rendered by later waited agents as Jinja namespaces.

| Form                           | Flags / arguments      | Description                                               |
| ------------------------------ | ---------------------- | --------------------------------------------------------- |
| `sase var set KEY=VALUE [...]` | positional assignments | Store one or more output variables for the current agent. |

Keys must be valid Jinja attribute identifiers (`[A-Za-z_][A-Za-z0-9_]*`). Values are strings split on the first `=`, so
values may contain additional equals signs. Multiple calls merge into the same variable map; later writes for the same
key replace earlier values. Producer namespaces are derived from agent names for downstream rendering: dots create
nested namespaces, hyphens become underscores, and digit-leading components are prefixed with `_`. Do not store secrets;
output variables are persisted in `agent_meta.json` and shown in ACE.

### `sase telemetry`

With no subcommand, `sase telemetry` defaults to `sase telemetry list`.

| Flag         | Values                                                               | Default | Description          |
| ------------ | -------------------------------------------------------------------- | ------- | -------------------- |
| _subcommand_ | `status`, `list`, `snapshot`, `dashboard`, `health`, `export-config` | `list`  | Telemetry subcommand |

See [docs/telemetry.md](telemetry.md) for the full CLI reference including per-subcommand flags.

### `sase logs`

| Flag        | Values | Default    | Description                                                     |
| ----------- | ------ | ---------- | --------------------------------------------------------------- |
| `daterange` | string | (required) | Date range to collect (e.g., `-7d`, `260318`, `260315..260318`) |

Supported date range formats:

- **Absolute**: `YYmmdd` or `YYmmddHHMMSS`
- **Relative**: `-Nd` (days ago), `-Nh` (hours ago), `-Nm` (minutes ago), `0d` (today)
- **Ranges**: `START..END` (e.g., `-7d..0d`); single point means "from that point to now"

### `sase editor`

`sase editor` exposes JSON-over-stdin helper operations for editor integrations. It is intentionally a fixed-operation
bridge rather than a generic shell or filesystem API.

| Form                                        | Input                | Description                                                                                                      |
| ------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `sase editor helper-bridge xprompt-catalog` | JSON object on stdin | Return the structured xprompt catalog; accepts the same schema as the mobile `xprompt-catalog` helper operation. |
| `sase editor helper-bridge snippet-catalog` | JSON object on stdin | Return the composed ACE snippet registry used by `sase lsp` and editor completion clients.                       |

The structured catalog includes insertion metadata (`insertion`, `reference_prefix`, `kind`), typed argument metadata,
display/source fields, and `definition_path` when SASE can resolve a real file to jump to.

The snippet catalog uses the same source ordering as ACE: xprompts marked with `snippet` front matter plus user-defined
`ace.snippets`, with `ace.snippets` winning on trigger collisions.

### `sase file`

With no subcommand, `sase file` defaults to `sase file list`.

| Form             | Flags                     | Description                                                                                     |
| ---------------- | ------------------------- | ----------------------------------------------------------------------------------------------- |
| `sase file list` | `-p/--path`, `-t/--token` | Emit JSON filesystem completion candidates rooted at `--path` and filtered by the cursor token. |

### `sase file-history`

With no subcommand, `sase file-history` defaults to `sase file-history list`.

| Form                       | Flags       | Description                                                      |
| -------------------------- | ----------- | ---------------------------------------------------------------- |
| `sase file-history list`   | none        | Emit the recency-ordered file-reference history as a JSON array. |
| `sase file-history delete` | `-p/--path` | Remove one entry from the file-reference history.                |

### `sase plugin`

With no subcommand, `sase plugin` defaults to `sase plugin list` with default options. Use `sase plugin list --verbose`
or `sase plugin doctor --json` when passing diagnostic flags.

| Form                 | Flags                       | Description                                                                          |
| -------------------- | --------------------------- | ------------------------------------------------------------------------------------ |
| `sase plugin list`   | `-j/--json`, `-v/--verbose` | Inventory installed SASE entry points and configured or available chop scripts.      |
| `sase plugin doctor` | `-j/--json`, `-v/--verbose` | Diagnose resource loading, configured chops, and optional integration prerequisites. |

### `sase lsp`

Starts the xprompt language server over stdio for editor integrations. `SASE_XPROMPT_LSP_CMD` can override the server
command during development. Without that override, `sase lsp` uses `sase-xprompt-lsp` from `PATH`, then checks a sibling
`../sase-core` checkout for debug/release binaries, then falls back to `cargo run` from that sibling checkout when Cargo
is available.

| Flag              | Values | Default | Description                            |
| ----------------- | ------ | ------- | -------------------------------------- |
| `-V`, `--version` | flag   | -       | Print the xprompt LSP version and exit |

### `sase path`

| Flag   | Values                                                                           | Default    | Description         |
| ------ | -------------------------------------------------------------------------------- | ---------- | ------------------- |
| `name` | `xprompts-dir`, `xprompts-schema`, `xprompts-collection-schema`, `config-schema` | (required) | Which path to print |

### `sase notify`

With no subcommand, `sase notify` defaults to the compact `sase notify list` view. Use `sase notify list` for JSON,
limit, query, unread, dismissed, or the clearest sender/tag filtering form. Use `sase notify create` to write a
notification from stdin JSON.

| Form                 | Flags                                                                                         | Description                                                 |
| -------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `sase notify`        | `-s/--sender`, `-t/--tag`                                                                     | Shortcut for `sase notify list` with default compact output |
| `sase notify create` | `-s/--sender`, `-t/--tag`                                                                     | Create a notification from stdin JSON                       |
| `sase notify list`   | `-j/--json`, `-l/--limit`, `-q/--query`, `-t/--tag`, `-s/--sender`, `-u/--unread`, `-a/--all` | List recent notifications; `-j` emits the stable JSON shape |
| `sase notify show`   | `-i/--id`, `-f/--format` (`markdown` or `json`)                                               | Show one notification by id; defaults to markdown           |

Create accepts a JSON `tags` field and repeatable `-t/--tag`; CLI tags are appended to JSON tags, then normalized and
deduplicated. `sase notify list -q` also matches tags, and `sase notify list --tag <tag>` filters to notifications with
that exact normalized tag.

### `sase plan`

| Flag        | Values | Default    | Description                 |
| ----------- | ------ | ---------- | --------------------------- |
| `plan_file` | path   | (required) | Path to the plan `.md` file |

### `sase artifact`

`sase artifact create` is intended for code agents running with `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR` set. It moves a
generated file into persistent SASE artifact storage and associates it with the current agent so the Agents tab can open
it with `A`, even after the agent has been dismissed and revived.

| Form                   | Flags                                  | Description                                       |
| ---------------------- | -------------------------------------- | ------------------------------------------------- |
| `sase artifact create` | `-p/--path`, `-n/--label`, `-k/--kind` | Store one explicit artifact for the current agent |

### `sase questions`

| Flag             | Values | Default    | Description                             |
| ---------------- | ------ | ---------- | --------------------------------------- |
| `questions_json` | string | (required) | JSON string containing questions to ask |

### `sase agents`

`sase agents` provides cross-project visibility into running agents. Subcommands:

| Subcommand | Flags                                                                                        | Description                                                                                                                                                                                                                                                                                                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`   | `-a/--all`, `-j/--json`, `-p/--project`                                                      | List running agents. `-a` includes DONE/FAILED agents (capped at 50 per project). `-j` emits a JSON array with a stable schema. `-p` limits output to a single project.                                                                                                                                                                                                         |
| `show`     | `-n/--name`                                                                                  | Render a full detail panel (prompt, reply, metadata) for a single agent by name.                                                                                                                                                                                                                                                                                                |
| `kill`     | `-n/--name`                                                                                  | SIGTERM a running agent by name.                                                                                                                                                                                                                                                                                                                                                |
| `tag`      | `set` / `unset` / `list`                                                                     | Manage the user-defined tag on an agent (used by the Agents tab tag side panels). `tag set -n <agent> -t <tag>` replaces any prior tag; `tag unset -n <agent>` clears it; `tag list [-n <agent>]` prints tags as JSON (filtered when given).                                                                                                                                    |
| `archive`  | `rebuild-index` / `verify`                                                                   | Maintain the dismissed-agent bundle summary index under `~/.sase/dismissed_bundles/`. `verify` exits non-zero if rows are stale or missing.                                                                                                                                                                                                                                     |
| `index`    | `status` / `rebuild` / `verify` / `gc`, `-i/--index-path`, `-p/--projects-root`, `-j/--json` | Maintain the persistent agent artifact index. Defaults are `~/.sase/agent_artifact_index.sqlite` and `~/.sase/projects`; `status` performs a lightweight visible-inbox check without scanning source artifacts, `verify` exits non-zero when the index diverges from source artifacts, and `gc` rebuilds the index from source artifacts and replaces the dismissed projection. |
| `names`    | `migrate-auto`, `-f/--force`, `-j/--json`                                                    | Maintain the permanent agent-name registry. `migrate-auto` runs the historical generated-name namespace migration; `--force` reruns it after the completion marker exists and `--json` emits a machine-readable summary.                                                                                                                                                        |

### `sase chats`

`sase chats` discovers and inspects saved agent chat transcripts. With no subcommand, it defaults to `sase chats list`.
Subcommands:

| Subcommand | Flags                                                     | Description                                                                                              |
| ---------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `list`     | `-j/--json`, `-l/--limit`, `-q/--query`                   | List recent transcripts. `-j` emits the stable JSON shape consumed by the `/sase_chats` skill.           |
| `show`     | `-n/--agent`, `-p/--path`, `-b/--basename`, `-f/--format` | Show one transcript by agent name, path, or basename. `--format` accepts `raw`, `resume`, or `response`. |

## Directory Sharding

A fresh install writes agent artifacts (chat logs, notifications, prompt history, workflow state, etc.) directly under
`~/.sase/<kind>/`. After a few months of heavy use those directories can accumulate tens of thousands of files, which
slows down filesystem walks and makes `ls`-style inspection painful.

New files are automatically written into a `YYYYMM/` shard inside each high-volume directory (keyed by the current
month). Readers transparently merge sharded and non-sharded files, so the layout is backwards-compatible — existing
unsharded files at the top level are still found and the layout is fully read/write compatible across both forms.
