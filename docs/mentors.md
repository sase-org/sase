# Mentors

## Overview

Mentors are automated AI code review agents for ChangeSpecs. A ChangeSpec is SASE's
local record for one proposed code change; mentors watch its commits, decide whether
configured review profiles match, and then run focused review agents in the background.

The Axe daemon drives mentor checks. When a mentor finds issues, it writes structured
JSON comments with severities (`error`, `warning`, or `suggestion`). You review those
comments in the ACE TUI and can launch an apply agent for the accepted comments.

The lifecycle is:

1. Match mentor profiles against ChangeSpec commits.
2. Register matching profiles in the ChangeSpec `MENTORS` field.
3. Wait for non-skipped hooks on the latest regular commit to become ready.
4. Start mentor agents when runner slots are available.
5. Save structured JSON output and file snapshots.
6. Review, accept, and apply comments from ACE.

## Configuration

Mentors are configured through `mentor_profiles` in `sase.yml`. SASE loads merged
config, so user-level profiles from `~/.config/sase/sase.yml` and project-local profiles
from `sase/sase.yml` can both contribute profiles. See
[`docs/configuration.md`](configuration.md#mentor_profiles) for the field reference.

A profile defines when it should run. Each profile contains one or more mentors, and
each mentor has a role plus focus areas that constrain what it should review.

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

Each profile must have at least one matching criterion. If a profile has more than one
criterion, SASE uses OR logic: any criterion can match.

| Criterion            | Matches against                                        |
| -------------------- | ------------------------------------------------------ |
| `file_globs`         | Changed file paths extracted from the diff             |
| `diff_regexes`       | Diff content using Python regular expressions          |
| `amend_note_regexes` | Commit or amend notes using Python regular expressions |
| `first_commit`       | The first regular commit entry of a ChangeSpec         |

Profile matching ignores proposal entries such as `(2a)` and uses regular commit entries
such as `(1)` and `(2)`. Matching profiles are added to the latest regular commit's
`MENTORS` entry before the mentors actually start.

### Project Scoping

Mentor profiles from a project-local `sase/sase.yml` are automatically scoped to that
project. This means a profile defined in `/home/user/myproject/sase/sase.yml` will only
match ChangeSpecs belonging to `myproject`, preventing local profiles from firing on
unrelated projects.

You can also explicitly set the `projects` field on any profile to restrict it to
specific projects:

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

Profiles defined in user-level config (`~/.config/sase/sase.yml`) remain unscoped by
default and apply to all projects unless `projects` is explicitly set.

### Mentor Definition

Each mentor in a profile requires these fields:

- **`mentor_name`**: Unique identifier within the profile.
- **`role`**: Persona for the review (e.g., "Python expert", "Security reviewer"). This
  shapes the LLM's review perspective.
- **`focus_areas`**: List of review dimensions, each with a `focus_name` and
  `description`. These define what the mentor looks for and structure its output.

### Debugging Profile Matching

Use `sase config mentor-match <changespec_name>` to trace which profiles match a given
ChangeSpec and why. The command loads the current config, inspects the ChangeSpec
commits, and reports per-criterion results.

```bash
sase config mentor-match my_feature_cl
```

## Execution Lifecycle

### 1. Profile Registration

When a ChangeSpec is in a reviewable status (`Ready` or `Mailed`), the scheduler checks
all mentor profiles against the regular commits since the last mentor entry. Matching
profiles are registered in the `MENTORS` field with `[0/N]` counts before execution
begins.

### 2. Hook Readiness

Mentors wait for all non-skipped hooks on the latest regular commit to become ready. A
hook is ready when it passed, or when a failed hook has been handled by a fix-hook,
proposal, summarizer, or metahook. Hooks prefixed with `!` are skipped and do not block
mentor eligibility.

### 3. Execution

Each mentor runs as a background process:

1. The mentor is marked STARTING (prevents race conditions).
2. A background subprocess is spawned with its own session.
3. The `#mentor` xprompt workflow renders the prompt with the mentor role and focus
   areas.
4. The project's registered workspace workflow (for example, `#git` or `#gh`) provides
   the workspace context.
5. The LLM response is parsed as structured JSON and saved to `~/.sase/mentors/`.

### 4. Completion

Mentors use these statuses:

| Status    | Meaning                                                      |
| --------- | ------------------------------------------------------------ |
| STARTING  | Registered and about to spawn a runner                       |
| RUNNING   | Background mentor runner is active                           |
| PASSED    | Completed successfully with no review comments               |
| COMMENTED | Completed successfully with one or more comments             |
| FAILED    | Execution error or invalid JSON response                     |
| KILLED    | Manually killed or auto-killed because a newer commit exists |
| DEAD      | Runner process disappeared or its PID was reused             |

### 5. Stale Mentor Cleanup

When a newer commit is added to a ChangeSpec, mentors running against older commits are
automatically killed. This prevents stale reviews from continuing after new code is
committed.

## Output Format

Mentor output is saved as JSON to `~/.sase/mentors/`. Each output file records the
mentor metadata and a `comments` array. Each comment includes:

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

The entry id matches a regular `COMMITS` entry. The header line shows profile names with
`[started/total]` counts. Status lines show timestamp, `profile:mentor`, status, and
duration for completed mentors.

## ACE TUI Integration

### Review Mentors (`,C`)

Press `,C` on the PRs sub-tab to open the Mentor Review modal for the current
ChangeSpec. The modal shows all mentor comments and lets you accept or reject individual
suggestions.

| Key                 | Action                                                   |
| ------------------- | -------------------------------------------------------- |
| `j` / `k`           | Navigate between mentors                                 |
| `n` / `p`           | Navigate between comments within a mentor                |
| `N` / `P`           | Navigate between accepted comments only                  |
| `Ctrl+D` / `Ctrl+U` | Scroll comment details down / up                         |
| `Space`             | Toggle acceptance of the current comment                 |
| `a`                 | Apply accepted comments and propose (amend with propose) |
| `A`                 | Apply accepted comments and commit                       |
| `r`                 | Run a mentor profile (opens profile picker)              |
| `y`                 | Copy the current comment to the clipboard                |
| `K`                 | Kill the selected running mentor                         |
| `Esc` / `q`         | Close modal                                              |

#### Apply Modes

There are two ways to apply accepted mentor comments:

- **`a`** — Launches the `make_mentor_changes` workflow with the `propose` xprompt
  appended, so the agent proposes its changes as an amend.
- **`A`** — Launches the `make_mentor_changes` workflow with the `commit` xprompt
  appended, so the agent commits directly.

Both modes save the accepted comments as an artifact under `~/.sase/mentors/` before
launching the apply agent.

#### Running Mentor Profiles

Press `r` to open a profile picker showing all configured mentor profiles. Selecting a
profile starts (or restarts) all mentors in that profile for the current ChangeSpec.
This is useful for re-running a specific review after making changes.

Running and completed mentor agents are visible in the Agents tab under tribe `@review`.
The same tribe is used for CRS, fix-hook, and summarize-hook review agents, so review
automation can be inspected, killed, dismissed, or resumed from one side panel.

### Code Snippets in Review

Each mentor comment in the review modal is displayed alongside a syntax-highlighted code
snippet centered on the referenced line number. The snippet uses Rich's Monokai theme
with line numbers, word wrapping, and the target line highlighted. Syntax highlighting
is determined by the file extension (supports Python, JavaScript, TypeScript, Go, Rust,
Markdown, YAML, JSON, shell, SQL, and other common languages).

Code snippets are loaded from file snapshots when available. Older mentor outputs
without snapshots fall back to the VCS provider when a revision is available.

### File Snapshots

When a mentor completes, the contents of all files referenced in its comments are
snapshotted and saved alongside the mentor output at
`~/.sase/mentors/<cl>-<profile>-<mentor>-<ts>-files.json`. This ensures that the Mentor
Review modal can display code snippets instantly without fetching files from VCS, even
if the working tree has changed since the mentor ran.

### Read Tracking

The Mentor Review modal tracks which comments you have viewed. As you navigate between
comments, each one is automatically marked as read. The modal header displays the
current global comment position (`N / total`) and an acceptance count (`✓ N accepted`).
The side panel shows a mini progress bar for each mentor (`■` = read, `□` = unread)
along with an accepted/total count. The side panel also shows a status indicator per
mentor: `▸` (selected), `●` (running), `✗` (failed/killed), or `✓` (all comments
accepted). Read state persists across modal opens and is stored per ChangeSpec and
commit entry.

Unread comment counts also appear inline in the PRs sub-tab list (see
[ACE docs](ace.md#mentor-comment-stats-in-pr-list)).

### Kill Mentors (`,M`)

Press `,M` on the PRs sub-tab to kill all running mentors for the current ChangeSpec.

### Fold Mentors (`z` `m`)

Press `z` `m` to toggle the MENTORS section visibility in the ChangeSpec detail view.

## Trigger Conditions

Mentors run on ChangeSpecs that meet **all** of the following:

- Status is **Ready** or **Mailed** (not WIP, Draft, Submitted, Reverted, or Archived).
- The ChangeSpec has at least one commit.
- At least one mentor profile's matching criteria are satisfied.
- All non-skipped hooks for the latest regular commit are ready.
