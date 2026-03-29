# Mentors

## Overview

Mentors are automated AI code review agents that run in the background when a ChangeSpec's commits match configurable
criteria. Each mentor produces structured comments with severity levels that can be reviewed and applied through the ACE
TUI.

Mentors are triggered by the Axe daemon, run in isolated workspaces, and produce JSON output. The review workflow is:
profile matching -> hook readiness -> execution -> structured output -> user review -> apply.

## Configuration

Mentors are configured through `mentor_profiles` in `sase.yml`. See
[`docs/configuration.md`](configuration.md#mentor_profiles) for the full field reference.

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

  - profile_name: security_review
    diff_regexes:
      - "password|secret|token|api_key"
    mentors:
      - mentor_name: security
        role: "Security reviewer"
        focus_areas:
          - focus_name: credentials
            description: "Hardcoded credentials and secret exposure"
          - focus_name: injection
            description: "SQL injection, XSS, and command injection"

  - profile_name: first_look
    first_commit: true
    mentors:
      - mentor_name: architecture
        role: "Software architect"
        focus_areas:
          - focus_name: design
            description: "Overall design and architectural patterns"
```

### Profile Matching Criteria

Each profile must have at least one matching criterion:

| Criterion            | Matches against                     |
| -------------------- | ----------------------------------- |
| `file_globs`         | Changed file paths (glob patterns)  |
| `diff_regexes`       | Diff content (regex patterns)       |
| `amend_note_regexes` | Commit/amend notes (regex patterns) |
| `first_commit`       | First commit of a ChangeSpec        |

When multiple criteria are present on a profile, they are combined with OR logic — any match triggers the profile.

### Project Scoping

Mentor profiles from a project-local `sase.yml` are automatically scoped to that project. This means a profile defined
in `/home/user/myproject/sase.yml` will only match ChangeSpecs belonging to `myproject`, preventing local profiles from
firing on unrelated projects.

You can also explicitly set the `projects` field on any profile to restrict it to specific projects:

```yaml
mentor_profiles:
  - profile_name: backend_review
    projects: ["myproject", "other_project"]
    file_globs:
      - "*.py"
    mentors:
      - mentor_name: reviewer
        role: "Python expert"
        focus_areas:
          - focus_name: correctness
            description: "Logic and correctness"
```

Profiles defined in user-level config (`~/.config/sase/sase.yml`) remain unscoped by default and apply to all projects
unless `projects` is explicitly set.

### Mentor Definition

Each mentor in a profile requires:

- **`mentor_name`**: Unique identifier within the profile.
- **`role`**: Persona for the review (e.g., "Python expert", "Security reviewer"). This shapes the LLM's review
  perspective.
- **`focus_areas`**: List of review dimensions, each with a `focus_name` and `description`. These define what the mentor
  looks for and structure its output.

### Debugging Profile Matching

Use `sase config mentor-match <changespec_name>` to trace which profiles match a given ChangeSpec and why. The output
shows per-criterion match results with details about what matched.

```bash
sase config mentor-match my_feature_cl
```

## Execution Lifecycle

### 1. Profile Registration

When a commit is added to a ChangeSpec, the scheduler checks all mentor profiles against the commit's changed files and
notes. Matching profiles are registered in the MENTORS field with `[0/N]` counts before execution begins.

### 2. Hook Readiness

Mentors wait for all non-skip hooks on the same commit to reach a terminal state (PASSED, FAILED with proposal, or
summarized). Hooks prefixed with `!` are skipped and don't block mentor eligibility.

### 3. Execution

Each mentor runs as a background process in an isolated workspace:

1. The mentor is marked STARTING (prevents race conditions).
2. A background subprocess is spawned with its own session.
3. The `#mentor` xprompt workflow renders the prompt with focus areas and invokes the LLM.
4. Structured JSON output is parsed and saved to `~/.sase/mentors/`.

### 4. Completion

Mentors reach one of these terminal statuses:

| Status    | Meaning                                                   |
| --------- | --------------------------------------------------------- |
| PASSED    | Completed successfully, no review comments                |
| COMMENTED | Completed successfully, produced one or more comments     |
| FAILED    | Execution error or invalid JSON response                  |
| KILLED    | Manually killed or auto-killed due to newer commit        |
| DEAD      | Process exited unexpectedly (detected via dead PID check) |

### 5. Stale Mentor Cleanup

When a newer commit is added to a ChangeSpec, mentors running against older commits are automatically killed. This
prevents stale reviews from continuing after new code is committed.

## Output Format

Mentor output is saved as JSON to `~/.sase/mentors/`. Each comment includes:

| Field         | Type    | Description                                |
| ------------- | ------- | ------------------------------------------ |
| `focus_name`  | string  | Focus area this comment addresses          |
| `file_path`   | string  | Path to the file being commented on        |
| `line_number` | integer | Line number in the file                    |
| `description` | string  | Actionable description of the issue        |
| `severity`    | string  | One of `error`, `warning`, or `suggestion` |

## MENTORS Field in ChangeSpec Files

Mentor status is tracked in the MENTORS section of ChangeSpec files:

```
MENTORS:
  (1) python_review[2/2] security_review[1/1]
      | [260320_150530] python_review:style_checker - COMMENTED - (0h2m15s)
      | [260320_150530] python_review:naming - PASSED - (0h1m45s)
      | [260320_151500] security_review:security - COMMENTED - (0h3m10s)
  (2) python_review[0/2]
      | python_review:style_checker - STARTING
```

The header line shows profile names with `[started/total]` counts. Status lines show timestamp, profile:mentor name,
status, and duration for completed mentors.

## ACE TUI Integration

### Review Mentors (`,m`)

Press `,m` on the CLs tab to open the Mentor Review modal for the current ChangeSpec. The modal shows all mentor
comments and lets you accept or reject individual suggestions.

| Key                 | Action                                                   |
| ------------------- | -------------------------------------------------------- |
| `j` / `k`           | Navigate between mentors                                 |
| `n` / `p`           | Navigate between comments within a mentor                |
| `Ctrl+D` / `Ctrl+U` | Scroll comment details down / up                         |
| `Space`             | Toggle acceptance of the current comment                 |
| `Enter`             | Apply all accepted comments (launches agent)             |
| `a`                 | Apply accepted comments and propose (amend with propose) |
| `A`                 | Apply accepted comments and commit                       |
| `r`                 | Run a mentor profile (opens profile picker)              |
| `Shift+K`           | Kill a running mentor                                    |
| `Esc` / `q`         | Close modal                                              |

#### Apply Modes

There are three ways to apply accepted mentor comments:

- **`Enter`** — Launches the `make_mentor_changes` workflow, which passes the accepted comments to an agent that
  implements the suggested changes.
- **`a`** — Same as `Enter`, but also appends the `propose` xprompt (tagged with `propose`) to the agent prompt, so the
  agent proposes its changes as an amend rather than directly committing.
- **`A`** — Same as `Enter`, but appends the `commit` xprompt (tagged with `commit`) so the agent commits directly.

#### Running Mentor Profiles

Press `r` to open a profile picker showing all configured mentor profiles. Selecting a profile starts (or restarts) all
mentors in that profile for the current ChangeSpec. This is useful for re-running a specific review after making
changes.

### Code Snippets in Review

Each mentor comment in the review modal is displayed alongside a syntax-highlighted code snippet centered on the
referenced line number. The snippet uses Rich's Monokai theme with line numbers, word wrapping, and the target line
highlighted. Syntax highlighting is determined by the file extension (supports Python, JavaScript, TypeScript, Go, Rust,
and 18 other languages).

Code snippets are loaded from file snapshots when available (instant), falling back to the VCS provider's object store
for older mentor outputs.

### File Snapshots

When a mentor completes, the contents of all files referenced in its comments are snapshotted and saved alongside the
mentor output at `~/.sase/mentors/<cl>-<profile>-<mentor>-<ts>-files.json`. This ensures that the Mentor Review modal
can display code snippets instantly without fetching files from VCS, even if the working tree has changed since the
mentor ran.

### Read Tracking

The Mentor Review modal tracks which comments you have viewed. As you navigate between comments, each one is
automatically marked as read. The modal header shows a mini progress bar for each mentor (`■` = read, `□` = unread)
along with an accepted/total count. Read state persists across modal opens and is stored per ChangeSpec and commit
entry.

Unread comment counts also appear inline in the CLs tab list (see [ACE docs](ace.md#mentor-comment-stats-in-cl-list)).

### Kill Mentors (`,M`)

Press `,M` on the CLs tab to kill all running mentors for the current ChangeSpec.

### Fold Mentors (`z` `m`)

Press `z` `m` to toggle the MENTORS section visibility in the ChangeSpec detail view.

## Trigger Conditions

Mentors run on ChangeSpecs that meet **all** of the following:

- Status is **Ready** (not WIP, Draft, Mailed, Submitted, Reverted, or Archived).
- The ChangeSpec has at least one commit.
- At least one mentor profile's matching criteria are satisfied.
- All non-skip hooks for the matched commit have reached a terminal state.
