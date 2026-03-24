# Configuration Reference

This document is the central reference for all sase configuration: config files, YAML sections, environment variables,
and CLI flags.

## Table of Contents

- [Config File Location](#config-file-location)
- [Deep-Merge System](#deep-merge-system)
- [Configuration Sections](#configuration-sections)
  - [ace](#ace)
  - [llm_provider](#llm_provider)
  - [vcs_provider](#vcs_provider)
  - [axe](#axe)
  - [mentor_profiles](#mentor_profiles)
  - [metahooks](#metahooks)
  - [xprompts](#xprompts)
  - [xprompt_aliases](#xprompt_aliases)
  - [use_chezmoi](#use_chezmoi)
  - [precommit_command](#precommit_command)
- [Environment Variables](#environment-variables)
- [CLI Flags](#cli-flags)

## Config File Location

All sase configuration lives under `~/.config/sase/`. The base config file is:

```
~/.config/sase/sase.yml
```

Overlay files matching the glob `~/.config/sase/sase_*.yml` are merged on top of the base file. A project-local
`./sase.yml` in the current working directory takes highest priority. See [Deep-Merge System](#deep-merge-system) below.

## Deep-Merge System

Sase builds a merged configuration through five layers, each merged on top of the previous:

1. **`default_config.yml`** — bundled package defaults
2. **Plugin `default_config.yml` files** — from installed plugin packages (via `sase_config` entry points), sorted by
   entry-point name; lists concatenate
3. **`sase.yml`** — user config (`~/.config/sase/sase.yml`); lists **replace** defaults (not concatenate)
4. **`sase_*.yml` overlays** — sorted alphabetically; lists **concatenate**
5. **Local `sase.yml`** — project-level config in the current working directory; lists **replace** (highest priority)

This allows splitting configuration across multiple files (e.g., `sase_work.yml`, `sase_personal.yml`) without
duplication, plugins can provide sensible defaults that users can override, and individual projects can customize
behavior without changing global config.

Merge semantics:

| Type        | Behavior                                                                            |
| ----------- | ----------------------------------------------------------------------------------- |
| **Dicts**   | Merged recursively (overlay keys override base keys).                               |
| **Lists**   | Concatenated in layers 2 and 4; **replaced** in layers 3 and 5 (user/local config). |
| **Scalars** | Override (overlay value replaces base value).                                       |

For example, given a base file with two mentor profiles and an overlay that adds a third, the merged result contains all
three profiles. If both files define the same scalar key (e.g., `axe.max_hook_runners`), the overlay wins.

Source: `src/sase/config/core.py`

## Configuration Sections

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

| Field              | Type         | Default | Description                                                             |
| ------------------ | ------------ | ------- | ----------------------------------------------------------------------- |
| `inactive_seconds` | int          | `600`   | Seconds of inactivity before the IDLE badge appears in the TUI top bar. |
| `keymaps`          | dict         | -       | Configurable keybindings (see below).                                   |
| `snippets`         | dict[string] | `{}`    | Trigger-word → template mappings for prompt input snippet expansion.    |

The IDLE indicator can also be triggered manually via the `i` keybinding. External tools can query idle status via
`sase.ace.tui_activity.is_idle()`.

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

### llm_provider

Configures which LLM backend sase uses and how model tiers map to concrete models. See [docs/llms.md](llms.md) for the
full LLM provider architecture, preprocessing pipeline, and invocation lifecycle.

```yaml
llm_provider:
  provider: claude # or "gemini" (default: auto-detect)
  model_tier_map:
    large: opus
    small: sonnet
```

| Field                               | Type   | Default     | Description                                                                                 |
| ----------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------- |
| `llm_provider.provider`             | string | auto-detect | Which registered provider to use. Auto-detects: claude if on PATH, then codex, else gemini. |
| `llm_provider.model_tier_map.large` | string | -           | Model identifier for the `large` tier.                                                      |
| `llm_provider.model_tier_map.small` | string | -           | Model identifier for the `small` tier.                                                      |

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
```

| Field                                          | Type | Default | Description                                                              |
| ---------------------------------------------- | ---- | ------- | ------------------------------------------------------------------------ |
| `llm_provider.retry.<provider>`                | dict | -       | Retry config for a specific provider (e.g., `gemini`, `claude`, `codex`) |
| `llm_provider.retry.<provider>.max_retries`    | int  | `0`     | Maximum retry attempts. `0` disables retrying.                           |
| `llm_provider.retry.<provider>.error_patterns` | list | `[]`    | Case-insensitive substring patterns matched against error output.        |
| `llm_provider.retry.<provider>.wait_times`     | list | `[30]`  | Per-retry wait times in seconds. Last value reused if list is shorter.   |
| `llm_provider.retry.<provider>.fallback_model` | str  | `null`  | Alternate model to use after exhausting all retries.                     |

Source: `src/sase/llm_provider/retry_config.py`, `src/sase/llm_provider/config.py`

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
```

| Field                         | Type         | Default  | Description                                                         |
| ----------------------------- | ------------ | -------- | ------------------------------------------------------------------- |
| `vcs_provider.provider`       | string       | `"auto"` | VCS provider: `"git"`, `"hg"`, or `"auto"` for directory detection. |
| `vcs_provider.workspace_root` | string       | -        | Root directory for workspaces. Overridden by `SASE_WORKSPACE_ROOT`. |
| `vcs_provider.default_hooks`  | list[string] | -        | Hook commands added to new ChangeSpecs. Replaces built-in defaults. |

When `default_hooks` is not set, plugins may provide their own defaults via `default_config.yml` (e.g., the
`sase-google` plugin supplies Mercurial-specific hooks). The core `sase` package has no built-in default hooks.

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
      interval: 1
      chops:
        - name: hook_checks
          description: Check for completed or failed hooks
        - name: mentor_checks
          description: Check for completed mentor agents
        - name: workflow_checks
          description: Check for completed workflows
        - name: pending_checks_poll
          description: Poll for pending check results
        - name: comment_zombie_checks
          description: Detect zombie comment processes
        - name: suffix_transforms
          description: Apply suffix transformations
        - name: orphan_cleanup
          description: Clean up orphaned workspaces
        - name: wait_checks
          description: Check wait coordination status
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

| Field                    | Type         | Default | Description                                                                   |
| ------------------------ | ------------ | ------- | ----------------------------------------------------------------------------- |
| `max_hook_runners`       | int          | `3`     | Maximum concurrent hook runners (non-`$` hooks) across all ChangeSpecs.       |
| `max_agent_runners`      | int          | `3`     | Maximum concurrent agent runners (agents and mentors) across all ChangeSpecs. |
| `zombie_timeout_seconds` | int          | `7200`  | Seconds after which a running hook or workflow is flagged as a zombie.        |
| `query`                  | string       | `""`    | Query string for filtering ChangeSpecs (empty = all).                         |
| `chop_script_dirs`       | list[string] | `[]`    | Additional directories to search for external chop scripts.                   |
| `lumberjacks`            | dict         | -       | Mapping of lumberjack name → config (see below).                              |

**Lumberjack fields** (per entry under `lumberjacks`):

| Field      | Type                 | Default | Description                                     |
| ---------- | -------------------- | ------- | ----------------------------------------------- |
| `interval` | int                  | `1`     | Seconds between chop polling cycles.            |
| `chops`    | list[string\|object] | `[]`    | List of chops to run on each cycle (see below). |

**Chop fields** (per entry under `chops`):

| Field         | Type         | Required | Default | Description                                                                                  |
| ------------- | ------------ | -------- | ------- | -------------------------------------------------------------------------------------------- |
| `name`        | string       | yes      | -       | Chop name identifying the chop script to run.                                                |
| `description` | string       | yes      | -       | Human-readable description of what the chop does.                                            |
| `agent`       | string       | no       | `null`  | XPrompt reference to launch as a background agent (accepts legacy `xprompt` key).            |
| `run_every`   | string       | no       | -       | Time-based duration string (e.g., `"60m"`, `"30s"`, `"2h"`). Limits how often the chop runs. |
| `env`         | dict[string] | no       | `{}`    | Environment variables passed to the chop script subprocess.                                  |

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

| Field                | Type         | Required | Description                                              |
| -------------------- | ------------ | -------- | -------------------------------------------------------- |
| `profile_name`       | string       | yes      | Unique name identifying this profile.                    |
| `mentors`            | list         | yes      | List of mentor definitions (see below).                  |
| `file_globs`         | list[string] | no\*     | Glob patterns matched against changed file paths.        |
| `diff_regexes`       | list[string] | no\*     | Regex patterns matched against the diff content.         |
| `amend_note_regexes` | list[string] | no\*     | Regex patterns matched against commit/amend notes.       |
| `first_commit`       | bool         | no       | If true, match only on the first commit of a ChangeSpec. |

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

Mentors run automatically on ChangeSpecs with Draft or Mailed status when their matching criteria are met. Mentor
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

Xprompts defined in `sase.yml` are priority 6 out of 8 in the resolution order:

1. `.xprompts/*.md` (CWD, hidden directory)
2. `xprompts/*.md` (CWD)
3. `~/.xprompts/*.md` (home, hidden directory)
4. `~/xprompts/*.md` (home)
5. `~/.config/sase/xprompts/{project}/*.md` (project-specific)
6. `sase.yml` `xprompts:` section (local `./sase.yml` overrides global; see [Deep-Merge System](#deep-merge-system))
7. Plugin packages (via `sase_xprompts` entry points)
8. `<sase_package>/xprompts/*.md` (built-in)

Earlier sources win on name conflicts. File-based xprompts use YAML front matter for metadata and the file body for
content.

Source: `src/sase/xprompt/loader.py`

### xprompt_aliases

Defines raw text-level alias substitutions that are applied _before_ any xprompt processing. This is useful for creating
shorthand references where the alias must be present in the raw text for other processing logic (such as VCS
directory-switching) to work correctly.

```yaml
xprompt_aliases:
  gh_sase: "gh:sase" # #gh_sase → #gh:sase
  gh_foo: "gh:foo/bar" # #gh_foo → #gh:foo/bar
```

| Field             | Type         | Default | Description                                                  |
| ----------------- | ------------ | ------- | ------------------------------------------------------------ |
| `xprompt_aliases` | dict[string] | `{}`    | Mapping of alias name → target. Applied as text substitution |

Each entry maps an alias name to a target string. When the processor encounters `#alias_name` in a prompt, it replaces
it with `#target` before any other xprompt resolution occurs. Only `#`-prefixed references are substituted; the alias
name must match `[a-zA-Z_][a-zA-Z0-9_]*`.

Source: `src/sase/xprompt/processor.py`

### use_chezmoi

Enables chezmoi path remapping for xprompt file operations. When set to `true`, home-directory xprompt paths
(`~/.xprompts/`, `~/xprompts/`) are remapped to their chezmoi-managed equivalents under `~/.local/share/chezmoi/home/`
(e.g., `~/.xprompts/` becomes `~/.local/share/chezmoi/home/dot_xprompts/`). This ensures that xprompt edits and
creations go through chezmoi's dotfile management rather than modifying the symlinked targets directly.

```yaml
use_chezmoi: true # default: false
```

| Field         | Type | Default | Description                                              |
| ------------- | ---- | ------- | -------------------------------------------------------- |
| `use_chezmoi` | bool | `false` | Remap home xprompt paths to chezmoi-managed equivalents. |

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

## Environment Variables

### LLM Provider

| Variable                   | Description                                                              |
| -------------------------- | ------------------------------------------------------------------------ |
| `SASE_MODEL_TIER_OVERRIDE` | Force all LLM invocations to a specific tier (`large` or `small`).       |
| `SASE_MODEL_SIZE_OVERRIDE` | Legacy alias for `SASE_MODEL_TIER_OVERRIDE` (`big` or `little`).         |
| `SASE_LLM_LARGE_ARGS`      | Extra CLI args appended for `large` tier invocations (any provider).     |
| `SASE_LLM_SMALL_ARGS`      | Extra CLI args appended for `small` tier invocations (any provider).     |
| `SASE_CLAUDE_LARGE_ARGS`   | Claude-specific extra args for `large` tier (fallback if generic unset). |
| `SASE_CLAUDE_SMALL_ARGS`   | Claude-specific extra args for `small` tier (fallback if generic unset). |
| `SASE_CODEX_LARGE_ARGS`    | Codex-specific extra args for `large` tier (fallback if generic unset).  |
| `SASE_CODEX_SMALL_ARGS`    | Codex-specific extra args for `small` tier (fallback if generic unset).  |
| `SASE_AGENT_PLAN_MODE`     | Enable Codex two-phase plan/implement flow.                              |
| `SASE_GEMINI_PATH`         | Path to the Gemini CLI binary (default: `gemini`).                       |

For the per-provider args, the generic `SASE_LLM_*_ARGS` variables are checked first. If unset, the provider-specific
variable is used as a fallback. Values are split on whitespace and appended to the CLI command.

### VCS Provider

| Variable              | Description                                                              |
| --------------------- | ------------------------------------------------------------------------ |
| `SASE_VCS_PROVIDER`   | Override VCS provider selection (`git`, `hg`, or `auto`).                |
| `SASE_WORKSPACE_ROOT` | Override the workspace root directory (takes priority over config file). |

### Plugin System

| Variable                        | Description                                               |
| ------------------------------- | --------------------------------------------------------- |
| `SASE_DISABLE_PLUGINS`          | Disable all plugin groups when set (any non-empty value). |
| `SASE_DISABLE_PLUGIN_VCS`       | Disable VCS plugins only.                                 |
| `SASE_DISABLE_PLUGIN_WORKSPACE` | Disable workspace plugins only.                           |
| `SASE_DISABLE_PLUGIN_XPROMPTS`  | Disable xprompt plugins only.                             |
| `SASE_DISABLE_PLUGIN_CONFIG`    | Disable config plugins only.                              |

### General

| Variable      | Description                                                                                   |
| ------------- | --------------------------------------------------------------------------------------------- |
| `SASE_TMPDIR` | Override the temp directory for all sase operations. Falls back to system default when unset. |

### Workspace Management (Internal)

These are set automatically by sase when launching agent subprocesses and are not intended for manual use.

| Variable                 | Description                                            |
| ------------------------ | ------------------------------------------------------ |
| `SASE_SYNC_CWD`          | Working directory override for sync operations.        |
| `SASE_GH_PRE_ALLOCATED`  | Set to `"1"` when a GitHub workspace is pre-allocated. |
| `SASE_GH_WORKSPACE_NUM`  | Pre-allocated GitHub workspace number.                 |
| `SASE_GH_WORKSPACE_DIR`  | Pre-allocated GitHub workspace directory path.         |
| `SASE_GIT_PRE_ALLOCATED` | Set to `"1"` when a Git workspace is pre-allocated.    |
| `SASE_GIT_WORKSPACE_NUM` | Pre-allocated Git workspace number.                    |
| `SASE_GIT_WORKSPACE_DIR` | Pre-allocated Git workspace directory path.            |

## CLI Flags

### `sase ace`

| Flag                     | Values              | Default                   | Description                                    |
| ------------------------ | ------------------- | ------------------------- | ---------------------------------------------- |
| `[query]`                | string              | last saved query or `!!!` | Query string for filtering ChangeSpecs.        |
| `-m, --model-tier`       | `large`, `small`    | -                         | Override model tier for all LLM invocations.   |
| `-M, --model-size`       | `big`, `little`     | -                         | Deprecated alias for `--model-tier`.           |
| `-r, --refresh-interval` | int (seconds)       | `10`                      | Auto-refresh interval (0 to disable).          |
| `-x, --no-axe`           | flag                | -                         | Disable auto-starting the axe daemon.          |
| `-v, --vcs-provider`     | `git`, `hg`, `auto` | -                         | Override VCS provider.                         |
| `-a, --agent`            | flag                | -                         | Run in headless agent mode (returns JSON).     |
| `-k, --keys`             | strings             | -                         | Key names to press in agent mode.              |
| `-s, --size`             | `WxH`               | `120x40`                  | Terminal size for agent mode (e.g., `200x50`). |

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

### `sase axe stop`

No flags. Stops the running axe orchestrator.

### `sase commit`

| Flag                  | Values | Default            | Description                                                   |
| --------------------- | ------ | ------------------ | ------------------------------------------------------------- |
| `cl_name`             | string | (required)         | CL name for the commit.                                       |
| `[file_path]`         | path   | -                  | File containing the CL description (opens editor if omitted). |
| `-b, --bug`           | string | auto-detected      | Bug number for the `BUG=` tag.                                |
| `-B, --fixed-bug`     | string | -                  | Bug number for the `FIXED=` tag.                              |
| `-c, --chat`          | path   | -                  | Chat file path for the COMMITS entry.                         |
| `-m, --message`       | string | -                  | Commit message (mutually exclusive with file_path).           |
| `-n, --note`          | string | `"Initial Commit"` | Custom note for the initial COMMITS entry.                    |
| `-p, --project`       | string | auto-detected      | Project name prefix.                                          |
| `-t, --timestamp`     | string | -                  | Shared timestamp (YYmmdd_HHMMSS format).                      |
| `-e, --end-timestamp` | string | -                  | End timestamp for duration calculation.                       |

### `sase amend`

| Flag               | Values | Default | Description                                                 |
| ------------------ | ------ | ------- | ----------------------------------------------------------- |
| `[note...]`        | string | -       | Amend note (or proposal entries when using `--accept`).     |
| `-a, --accept`     | flag   | -       | Accept proposed COMMITS entries by applying their diffs.    |
| `-c, --chat`       | path   | -       | Chat file path for this amend.                              |
| `-C, --cl`         | string | -       | CL name (defaults to current branch). Used with `--accept`. |
| `-p, --propose`    | flag   | -       | Create a proposed COMMITS entry without amending.           |
| `-t, --target-dir` | path   | CWD     | Directory to run commands in.                               |
| `-T, --timestamp`  | string | -       | Shared timestamp (YYmmdd_HHMMSS format).                    |

### `sase search`

| Flag           | Values          | Default    | Description                             |
| -------------- | --------------- | ---------- | --------------------------------------- |
| `query`        | string          | (required) | Query string for filtering ChangeSpecs. |
| `-f, --format` | `plain`, `rich` | `rich`     | Output format.                          |

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

| Flag           | Values | Default | Description                                                            |
| -------------- | ------ | ------- | ---------------------------------------------------------------------- |
| `[query]`      | string | -       | Prompt text, workflow reference (`#name`), or `.` for history picker.  |
| `-d, --daemon` | flag   | -       | Run as a detached background agent (appears in TUI Agents tab).        |
| `-l, --list`   | flag   | -       | List all available chat history files.                                 |
| `-r, --resume` | string | -       | Resume a previous conversation by agent name or history file basename. |

When invoked with no arguments, opens `$EDITOR` for composing a prompt interactively. When invoked with `.`, opens a
prompt history picker. Multi-prompt queries (containing `---` separators) are auto-detected and launched as sequential
daemon agents.

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

No flags. Outputs a JSON array of all available xprompts with name, type, source, inputs, tags, and preview.

### `sase xprompt graph`

| Flag              | Values           | Default   | Description                                             |
| ----------------- | ---------------- | --------- | ------------------------------------------------------- |
| `[workflow_name]` | string           | -         | Workflow name to graph. Lists all workflows if omitted. |
| `-f, --format`    | `mermaid`,`text` | `mermaid` | Output format for the DAG visualization.                |

### `sase init-git`

| Flag              | Values | Default                    | Description                                             |
| ----------------- | ------ | -------------------------- | ------------------------------------------------------- |
| `project_name`    | string | (required)                 | Name of the project to initialize.                      |
| `-b, --bare-dir`  | path   | `~/.sase/repos/<name>.git` | Override bare repo path.                                |
| `-c, --clone-dir` | path   | `~/projects/git/<name>/`   | Override clone path.                                    |
| `-e, --existing`  | path   | -                          | Register an existing bare repo instead of creating one. |

### `sase bead`

| Flag         | Values                                                                                                                     | Default    | Description     |
| ------------ | -------------------------------------------------------------------------------------------------------------------------- | ---------- | --------------- |
| _subcommand_ | `init`, `create`, `list`, `show`, `ready`, `update`, `close`, `rm`, `dep`, `blocked`, `sync`, `stats`, `doctor`, `onboard` | (required) | Bead subcommand |

#### `sase bead create`

| Flag                | Values | Default    | Description                                      |
| ------------------- | ------ | ---------- | ------------------------------------------------ |
| `-t, --title`       | string | (required) | Issue title                                      |
| `-p, --plan`        | path   | -          | Path to plan file (creates a plan bead)          |
| `-P, --parent`      | string | -          | Parent bead ID (creates a phase under this plan) |
| `-d, --description` | string | -          | Issue description                                |
| `-a, --assignee`    | string | -          | Assignee name                                    |

#### `sase bead list`

| Flag           | Values                          | Default | Description                   |
| -------------- | ------------------------------- | ------- | ----------------------------- |
| `-s, --status` | `open`, `in_progress`, `closed` | -       | Filter by status (repeatable) |
| `-t, --type`   | `plan`, `phase`                 | -       | Filter by type (repeatable)   |

#### `sase bead show`

| Flag | Values | Default    | Description |
| ---- | ------ | ---------- | ----------- |
| `id` | string | (required) | Issue ID    |

#### `sase bead update`

| Flag                | Values                          | Default    | Description        |
| ------------------- | ------------------------------- | ---------- | ------------------ |
| `id`                | string                          | (required) | Issue ID to update |
| `-s, --status`      | `open`, `in_progress`, `closed` | -          | Change status      |
| `-t, --title`       | string                          | -          | Change title       |
| `-d, --description` | string                          | -          | Change description |
| `-n, --notes`       | string                          | -          | Change notes       |
| `-D, --design`      | path                            | -          | Change plan path   |
| `-a, --assignee`    | string                          | -          | Change assignee    |

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

### `sase logs`

| Flag        | Values | Default    | Description                                                     |
| ----------- | ------ | ---------- | --------------------------------------------------------------- |
| `daterange` | string | (required) | Date range to collect (e.g., `-7d`, `260318`, `260315..260318`) |

Supported date range formats:

- **Absolute**: `YYmmdd` or `YYmmddHHMMSS`
- **Relative**: `-Nd` (days ago), `-Nh` (hours ago), `-Nm` (minutes ago), `0d` (today)
- **Ranges**: `START..END` (e.g., `-7d..0d`); single point means "from that point to now"

### `sase path`

| Flag   | Values                                             | Default    | Description         |
| ------ | -------------------------------------------------- | ---------- | ------------------- |
| `name` | `xprompts-dir`, `xprompts-schema`, `config-schema` | (required) | Which path to print |

### `sase notify`

| Flag           | Values | Default | Description                                               |
| -------------- | ------ | ------- | --------------------------------------------------------- |
| `-s, --sender` | string | -       | Notification sender name (overrides sender in JSON input) |

### `sase plan`

| Flag        | Values | Default    | Description                 |
| ----------- | ------ | ---------- | --------------------------- |
| `plan_file` | path   | (required) | Path to the plan `.md` file |

### `sase questions`

| Flag             | Values | Default    | Description                             |
| ---------------- | ------ | ---------- | --------------------------------------- |
| `questions_json` | string | (required) | JSON string containing questions to ask |
