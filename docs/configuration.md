# Configuration Reference

This document is the central reference for all sase configuration: config files, YAML sections, environment variables,
and CLI flags.

## Table of Contents

- [Config File Location](#config-file-location)
- [Deep-Merge System](#deep-merge-system)
- [Configuration Sections](#configuration-sections)
  - [llm_provider](#llm_provider)
  - [vcs_provider](#vcs_provider)
  - [axe](#axe)
  - [mentor_profiles](#mentor_profiles)
  - [metahooks](#metahooks)
  - [xprompts](#xprompts)
- [Environment Variables](#environment-variables)
- [CLI Flags](#cli-flags)

## Config File Location

All sase configuration lives under `~/.config/sase/`. The base config file is:

```
~/.config/sase/sase.yml
```

Overlay files matching the glob `~/.config/sase/sase_*.yml` are merged on top of the base file (see
[Deep-Merge System](#deep-merge-system) below).

## Deep-Merge System

Sase loads `sase.yml` as the base configuration, then deep-merges each `sase_*.yml` overlay file **sorted
alphabetically** on top. This allows splitting configuration across multiple files (e.g., `sase_work.yml`,
`sase_personal.yml`) without duplication.

Merge semantics:

| Type        | Behavior                                              |
| ----------- | ----------------------------------------------------- |
| **Dicts**   | Merged recursively (overlay keys override base keys). |
| **Lists**   | Concatenated (overlay items appended to base items).  |
| **Scalars** | Override (overlay value replaces base value).         |

For example, given a base file with two mentor profiles and an overlay that adds a third, the merged result contains all
three profiles. If both files define the same scalar key (e.g., `axe.max_runners`), the overlay wins.

Source: `src/sase/config.py`

## Configuration Sections

### llm_provider

Configures which LLM backend sase uses and how model tiers map to concrete models. See [docs/llms.md](llms.md) for the
full LLM provider architecture, preprocessing pipeline, and invocation lifecycle.

```yaml
llm_provider:
  provider: claude # or "gemini" (default: "gemini")
  model_tier_map:
    large: opus
    small: sonnet
```

| Field                               | Type   | Default    | Description                            |
| ----------------------------------- | ------ | ---------- | -------------------------------------- |
| `llm_provider.provider`             | string | `"gemini"` | Which registered provider to use.      |
| `llm_provider.model_tier_map.large` | string | -          | Model identifier for the `large` tier. |
| `llm_provider.model_tier_map.small` | string | -          | Model identifier for the `small` tier. |

Source: `src/sase/llm_provider/config.py`

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

The built-in default hooks (used when `default_hooks` is not set) are `!$sase_hg_presubmit` and `$sase_hg_lint`.

Source: `src/sase/vcs_provider/config.py`, `src/sase/ace/hooks/defaults.py`

### axe

Configures the `sase axe` background scheduler daemon. All values have sensible defaults; this section is entirely
optional.

```yaml
axe:
  full_check_interval: 300 # seconds (default: 300 = 5 minutes)
  comment_check_interval: 60 # seconds (default: 60 = 1 minute)
  hook_interval: 1 # seconds (default: 1)
  zombie_timeout_seconds: 7200 # seconds (default: 7200 = 2 hours)
  max_runners: 5 # concurrent runners (default: 5)
```

| Field                    | Type | Default | Description                                                                 |
| ------------------------ | ---- | ------- | --------------------------------------------------------------------------- |
| `full_check_interval`    | int  | `300`   | Seconds between full CL-submitted check cycles.                             |
| `comment_check_interval` | int  | `60`    | Seconds between reviewer/author comment check cycles.                       |
| `hook_interval`          | int  | `1`     | Seconds between hook/mentor/workflow polling cycles.                        |
| `zombie_timeout_seconds` | int  | `7200`  | Seconds after which a running hook or workflow is flagged as a zombie.      |
| `max_runners`            | int  | `5`     | Maximum concurrent runners (hooks, agents, mentors) across all ChangeSpecs. |

CLI flags on `sase axe` override these values for a single run (see [CLI Flags](#cli-flags)).

Source: `src/sase/axe_config.py`, `src/sase/axe/core.py`

### mentor_profiles

Defines mentor agents that run automatically when a ChangeSpec's diff, changed files, or amend notes match configurable
criteria. Each profile groups one or more mentors with shared matching rules.

```yaml
mentor_profiles:
  - profile_name: python_review
    file_globs:
      - "*.py"
    mentors:
      - prompt: "#mentor/python_style"
      - mentor_name: docstrings
        prompt: "#mentor/docstrings"
        run_on_wip: true

  - profile_name: proto_check
    diff_regexes:
      - "^\\+.*\\.proto"
    amend_note_regexes:
      - "proto"
    mentors:
      - prompt: "#mentor/proto_review"
```

**Profile fields:**

| Field                | Type         | Required | Description                                        |
| -------------------- | ------------ | -------- | -------------------------------------------------- |
| `profile_name`       | string       | yes      | Unique name identifying this profile.              |
| `mentors`            | list         | yes      | List of mentor definitions (see below).            |
| `file_globs`         | list[string] | no\*     | Glob patterns matched against changed file paths.  |
| `diff_regexes`       | list[string] | no\*     | Regex patterns matched against the diff content.   |
| `amend_note_regexes` | list[string] | no\*     | Regex patterns matched against commit/amend notes. |

\*At least one of `file_globs`, `diff_regexes`, or `amend_note_regexes` must be provided per profile.

**Mentor fields:**

| Field         | Type   | Required | Default | Description                                                     |
| ------------- | ------ | -------- | ------- | --------------------------------------------------------------- |
| `prompt`      | string | yes      | -       | The xprompt reference (e.g., `"#mentor/foo"`) or inline prompt. |
| `mentor_name` | string | no       | -       | Derived from `prompt` if omitted (last segment after `/`).      |
| `run_on_wip`  | bool   | no       | `false` | If `true`, the mentor runs even when CL status is WIP.          |

Source: `src/sase/mentor_config.py`

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

Source: `src/sase/metahook_config.py`

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
```

Xprompts defined in `sase.yml` are priority 6 out of 7 in the resolution order:

1. `.xprompts/*.md` (CWD, hidden directory)
2. `xprompts/*.md` (CWD)
3. `~/.xprompts/*.md` (home, hidden directory)
4. `~/xprompts/*.md` (home)
5. `~/.config/sase/xprompts/{project}/*.md` (project-specific)
6. `sase.yml` `xprompts:` section
7. `<sase_package>/xprompts/*.md` (built-in)

Earlier sources win on name conflicts. File-based xprompts use YAML front matter for metadata and the file body for
content.

Source: `src/sase/xprompt/loader.py`

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

For the per-provider args, the generic `SASE_LLM_*_ARGS` variables are checked first. If unset, the provider-specific
variable is used as a fallback. Values are split on whitespace and appended to the CLI command.

### VCS Provider

| Variable              | Description                                                              |
| --------------------- | ------------------------------------------------------------------------ |
| `SASE_VCS_PROVIDER`   | Override VCS provider selection (`git`, `hg`, or `auto`).                |
| `SASE_WORKSPACE_ROOT` | Override the workspace root directory (takes priority over config file). |

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
| `--model-size`           | `big`, `little`     | -                         | Deprecated alias for `--model-tier`.           |
| `-r, --refresh-interval` | int (seconds)       | `10`                      | Auto-refresh interval (0 to disable).          |
| `--vcs-provider`         | `git`, `hg`, `auto` | -                         | Override VCS provider.                         |
| `--agent`                | flag                | -                         | Run in headless agent mode (returns JSON).     |
| `--keys`                 | strings             | -                         | Key names to press in agent mode.              |
| `--size`                 | `WxH`               | `120x40`                  | Terminal size for agent mode (e.g., `200x50`). |

### `sase axe`

| Flag                       | Values              | Default          | Description                                         |
| -------------------------- | ------------------- | ---------------- | --------------------------------------------------- |
| `-q, --query`              | string              | `""` (all)       | Query string for filtering ChangeSpecs.             |
| `--full-check-interval`    | int (seconds)       | config or `300`  | Full CL-submitted check interval.                   |
| `--comment-check-interval` | int (seconds)       | config or `60`   | Comment check interval.                             |
| `--hook-interval`          | int (seconds)       | config or `1`    | Hook/mentor/workflow polling interval.              |
| `-r, --max-runners`        | int                 | config or `5`    | Maximum concurrent runners globally.                |
| `--zombie-timeout`         | int (seconds)       | config or `7200` | Timeout before marking a hook/workflow as a zombie. |
| `--vcs-provider`           | `git`, `hg`, `auto` | -                | Override VCS provider.                              |

For `sase axe`, CLI flags take precedence over values from the `axe` config section in `sase.yml`. If neither is set,
the built-in defaults are used.

### `sase commit`

| Flag              | Values | Default            | Description                                                   |
| ----------------- | ------ | ------------------ | ------------------------------------------------------------- |
| `cl_name`         | string | (required)         | CL name for the commit.                                       |
| `[file_path]`     | path   | -                  | File containing the CL description (opens editor if omitted). |
| `-b, --bug`       | string | auto-detected      | Bug number for the `BUG=` tag.                                |
| `-B, --fixed-bug` | string | -                  | Bug number for the `FIXED=` tag.                              |
| `--chat`          | path   | -                  | Chat file path for the COMMITS entry.                         |
| `-m, --message`   | string | -                  | Commit message (mutually exclusive with file_path).           |
| `-n, --note`      | string | `"Initial Commit"` | Custom note for the initial COMMITS entry.                    |
| `-p, --project`   | string | auto-detected      | Project name prefix.                                          |
| `--timestamp`     | string | -                  | Shared timestamp (YYmmdd_HHMMSS format).                      |
| `--end-timestamp` | string | -                  | End timestamp for duration calculation.                       |

### `sase amend`

| Flag            | Values | Default | Description                                                 |
| --------------- | ------ | ------- | ----------------------------------------------------------- |
| `[note...]`     | string | -       | Amend note (or proposal entries when using `--accept`).     |
| `-a, --accept`  | flag   | -       | Accept proposed COMMITS entries by applying their diffs.    |
| `--chat`        | path   | -       | Chat file path for this amend.                              |
| `--cl`          | string | -       | CL name (defaults to current branch). Used with `--accept`. |
| `-p, --propose` | flag   | -       | Create a proposed COMMITS entry without amending.           |
| `--target-dir`  | path   | CWD     | Directory to run commands in.                               |
| `--timestamp`   | string | -       | Shared timestamp (YYmmdd_HHMMSS format).                    |

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

| Flag           | Values | Default | Description                                                   |
| -------------- | ------ | ------- | ------------------------------------------------------------- |
| `-l, --list`   | flag   | -       | List all available chat history files.                        |
| `-r, --resume` | string | -       | Resume a previous conversation (optional: history file path). |

### `sase xprompt`

| Flag       | Values | Default | Description                                          |
| ---------- | ------ | ------- | ---------------------------------------------------- |
| `[prompt]` | string | stdin   | Prompt text to expand (reads from stdin if omitted). |

### `sase init-git`

| Flag           | Values | Default                    | Description                                             |
| -------------- | ------ | -------------------------- | ------------------------------------------------------- |
| `project_name` | string | (required)                 | Name of the project to initialize.                      |
| `--bare-dir`   | path   | `~/.sase/repos/<name>.git` | Override bare repo path.                                |
| `--clone-dir`  | path   | `~/projects/git/<name>/`   | Override clone path.                                    |
| `--existing`   | path   | -                          | Register an existing bare repo instead of creating one. |

### `sase path`

| Flag   | Values                            | Default    | Description         |
| ------ | --------------------------------- | ---------- | ------------------- |
| `name` | `xprompts-dir`, `xprompts-schema` | (required) | Which path to print |

### `sase notify`

| Flag       | Values | Default | Description                                               |
| ---------- | ------ | ------- | --------------------------------------------------------- |
| `--sender` | string | -       | Notification sender name (overrides sender in JSON input) |
