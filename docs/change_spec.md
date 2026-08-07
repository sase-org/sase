# ChangeSpec Format Documentation

A **ChangeSpec** is a structured record for one pull request (PR). It lives inside a
project `.sase` file and records the change's description, dependency metadata, review
URL, lifecycle status, commits, hooks, comments, mentor runs, timestamps, and computed
file deltas.

## Format Overview

Each ChangeSpec is a block of top-level fields and optional sections. `NAME`,
`DESCRIPTION`, and `STATUS` are the normal minimum for a hand-written entry;
`sase commit` creates and updates most other sections automatically.

The canonical order is:

```
NAME: <NAME>
DESCRIPTION:
  <TITLE>

  <BODY>
PARENT: <PARENT>
PR: <PR>
BUG: <BUG>
STATUS: <STATUS>
REFS:
  <ARTIFACT_REFERENCE>
COMMITS:
  <COMMIT_ENTRIES>
DELTAS:
  <DELTA_ENTRIES>
HOOKS:
  <HOOK_ENTRIES>
COMMENTS:
  <COMMENT_ENTRIES>
MENTORS:
  <MENTOR_ENTRIES>
TIMESTAMPS:
  <TIMESTAMP_ENTRIES>
```

The parser is tolerant of some older ordering and timestamp variants, but new docs,
scripts, and examples should use the order above. See individual field specifications
below for optionality and automatic behavior.

**IMPORTANT**: When outputting multiple ChangeSpecs, separate each one with **two blank
lines**.

## Field Specifications

### NAME

The unique identifier for the ChangeSpec.

**Recommended format**: `<project_or_area>_<descriptive_suffix>`

- Prefer a project- or area-specific prefix followed by an underscore
- Suffix should use underscores to separate words
- Suffix should be descriptive but concise
- `sase commit` appends a numeric suffix such as `_1` when it needs to make a new name
  unique

**Examples**:

- `my_project_add_config_parser`
- `feature_x_implement_validation`
- `refactor_database_layer`

### DESCRIPTION

A comprehensive description of what the PR does and why.

**Structure**:

1. **TITLE** (first line): A brief one-line summary
2. **Blank line**: Always include one blank line after the title
3. **BODY** (remaining lines): Detailed multi-line description

**Formatting**:

- **All lines must be 2-space indented** (including the blank line)
- TITLE should be concise (one line)
- BODY should include:
  - What changes are being made
  - Why the changes are needed
  - High-level approach or implementation details
  - What will be tested (if applicable)

**PR tag stripping:** When a ChangeSpec is created from a PR workflow or its description
is synced after a reword, any trailing `KEY=VALUE` metadata lines (matching
`^[A-Z][A-Z0-9_]*=`) are automatically stripped. The pattern matches both the legacy
unprefixed spelling and the new `SASE_`-prefixed footer tags (e.g.
`SASE_AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT`, `SASE_MARKDOWN=true`), so neither pollutes the
description. See [commit_workflows.md](commit_workflows.md#pull-request-pr) for details.

**Example**:

```
DESCRIPTION:
  Add configuration file parser for user settings

  This PR implements a YAML-based configuration parser that reads
  user settings from ~/.myapp/config.yaml. The parser includes a
  ConfigParser class with load() and validate() methods, along with
  type definitions for the configuration schema. Tests will cover
  valid YAML parsing, invalid config validation, and missing file
  handling.
```

### PARENT

Specifies the dependency relationship between ChangeSpecs.

**Values**:

- Omit this field entirely - This PR has no dependencies (default, preferred for
  parallelization)
- `<parent_changespec_name>` - The `NAME` of a parent ChangeSpec that must be completed
  first

The PARENT field is a ChangeSpec **name** — never a VCS ref. Values like `origin/main`,
`origin/master`, or the Mercurial sentinel `p4head` are not valid here; they describe
checkout targets for the VCS, not dependency relationships between PRs. "No parent
ChangeSpec" is represented by omitting the field entirely. `sase commit` drops the
PARENT field and warns when the value passed via `-p` does not resolve to an existing
ChangeSpec.

**Auto-detection:** When creating a new ChangeSpec via `sase commit`, the PARENT field
is automatically set if the current branch corresponds to an existing ChangeSpec. This
can be overridden with the `-p`/`--parent` flag (see
[commit_workflows.md](commit_workflows.md) for details).

**CRITICAL Dependency Guidelines**:

- **Default to omitting PARENT** to maximize parallel development
- **Only set a PARENT when there's a real content dependency**:
  - PR B calls a function/class that PR A creates
  - PR B modifies a file that PR A creates
  - PR B extends functionality that PR A introduces
- **DO NOT set a PARENT for**:
  - Independent features that don't interact
  - Changes to different files/modules
  - Tests for independent features
  - Documentation that doesn't reference new code

**Examples**:

```
# No PARENT field = no dependencies (preferred)
PARENT: my_project_add_config_parser   # Depends on another PR
```

### PR

The PR identifier (usually a PR URL). New and updated ChangeSpecs use `PR:`. Legacy
`CL:` fields are still accepted during the compatibility window and are rewritten as
`PR:` when touched.

**Values**:

- Omit this field entirely - PR not yet created (initial state)
- `<review-url>` - URL to the created PR
- `https://github.com/<owner>/<repo>/pull/<N>` - URL to the PR

**Example**:

```
# No PR field = PR not yet created
PR: https://github.com/org/repo/pull/42
```

### BUG

An optional bug reference linking the PR to an issue tracker. SASE stores this as plain
text. PR workflows that receive `SASE_BUG_ID` or `sase commit --bug-id` write it as
`http://b/<id>` in the ChangeSpec and add `SASE_BUG=<id>` to provider tag metadata.

**Example**:

```
BUG: http://b/12345
```

### STATUS

The current state of the PR in its lifecycle.

**Valid Values**:

| Status      | Description                                     |
| ----------- | ----------------------------------------------- |
| `WIP`       | Work in progress — initial development          |
| `Draft`     | PR created as a draft, not yet ready for review |
| `Ready`     | Ready for review                                |
| `Mailed`    | Sent out for review                             |
| `Submitted` | Merged / submitted to the codebase (terminal)   |
| `Reverted`  | PR was reverted after submission (terminal)     |
| `Archived`  | PR was abandoned without submission (terminal)  |

**Valid Transitions**:

```
WIP → Draft, Ready
Draft → Ready
Ready → Mailed, Draft
Mailed → Submitted
Submitted → (terminal)
Reverted → (terminal)
Archived → (terminal)
```

These transitions are enforced by the status state machine. Terminal statuses are moved
to the archive project file.

**Status Selection Rules**:

- New PRs typically start as `WIP`
- PR workflows default new ChangeSpecs to `Draft` unless `sase commit --status` or
  `SASE_PR_STATUS` says otherwise
- Move to `Ready` when the PR is ready for review
- Move to `Mailed` when sent out for review
- Update status as work progresses through the lifecycle

### REFS

Stores durable artifact references that justify or contextualize the change. Entries are
one canonical reference token per 2-space-indented line, without the prompt-time `@`
sigil.

**Entry format:**

```
REFS:
  research:202607/artifact_capture_and_retention/artifact_capture_and_retention.md
  file:default:0123456789abcdef01234567
  bead:sase-b7
```

Accepted kinds include `file:`, `chat:`, `bug:`, `commit:`, `agent:`, `bead:`, and
configured document roles such as `plans:` and `research:`. `sase changespec ref add`
normalizes entries before writing, deduplicates them while preserving first-write order,
and stores the canonical rendered form. Hand-edited entries are preserved by the parser
so `sase doctor -C project.changespec_refs` can report malformed or unresolved
references instead of silently erasing them.

Use the command group instead of editing the section by hand:

```bash
sase changespec ref add -c <name> research:202607/report.md
sase changespec ref list -c <name> --resolve
sase changespec ref rm -c <name> research:202607/report.md
```

### COMMITS

Tracks the commit history associated with this PR. This section is managed automatically
by `sase commit`.

**Entry format:**

```
COMMITS:
  (1) First commit note
      | CHAT: ~/.sase/chats/mybranch-commit-260328_143052.md (2m15s)
      | DIFF: ~/.sase/diffs/mybranch-260328_143052.diff
      | PLAN: sdd/plans/202603/my_plan.md
  (2) Second commit note
      Multi-line body continues here with 6-space indent.
      Blank body lines use a dot (.) placeholder.
      .
      Another paragraph after the blank line.
      | CHAT: ~/.sase/chats/mybranch-commit-260328_153012.md (1m42s)
      | DIFF: ~/.sase/diffs/mybranch-260328_153012.diff
  (2a) Proposed alternative - (!: NEW PROPOSAL)
      | DIFF: ~/.sase/diffs/mybranch-260328_160000.diff
```

**Entry numbering:**

- Regular entries use sequential integers: `(1)`, `(2)`, `(3)`, ...
- Proposal entries use the last regular number plus a letter suffix: `(2a)`, `(2b)`, ...
- Proposals are marked with `(!: NEW PROPOSAL)` to flag them for review.

**Multi-line body:** The first line of the commit message becomes the note. Subsequent
paragraphs (separated by a blank line in the original message) become 6-space-indented
body lines below the note. Empty body lines are stored as a dot (`.`) placeholder to
preserve structure.

**Drawers:** Each entry can have zero or more drawer lines (6-space indent, `| `
prefix):

| Drawer | Format                         | Description                                     |
| ------ | ------------------------------ | ----------------------------------------------- |
| `CHAT` | `\| CHAT: <path> (<duration>)` | Agent chat log file with optional run duration  |
| `DIFF` | `\| DIFF: <path>`              | Saved diff file                                 |
| `PLAN` | `\| PLAN: <path>`              | Plan file associated with this commit (via SDD) |

The CHAT drawer's duration (e.g., `2m15s`) is calculated from the chat filename
timestamp to the commit time. The PLAN drawer is emitted when the `SASE_PLAN`
environment variable is set during the commit workflow.

### TIMESTAMPS

Records a chronological audit trail of lifecycle events. Each entry includes a
timestamp, event type, and detail string.

**Entry format:**

```
TIMESTAMPS:
  [260328_143052] COMMIT  (1)
  [260328_151203] STATUS  WIP -> Draft
  [260328_151510] SYNC    Synced with remote
  [260328_160044] REWORD  Updated description title
  [260328_163012] REWIND  (2)
  [260328_170100] RENAME  old_name -> new_name
  [260328_171500] REBASE  old_parent -> new_parent
```

**Event types:**

| Type     | Description                                                      |
| -------- | ---------------------------------------------------------------- |
| `COMMIT` | A commit was added to the ChangeSpec; detail is usually `(N)`    |
| `STATUS` | A status transition occurred (e.g., `WIP -> Draft`)              |
| `SYNC`   | A sync operation was performed                                   |
| `REWORD` | The description or PR-derived metadata was edited                |
| `REWIND` | A rewind to a previous commit entry occurred; detail shows `(N)` |
| `RENAME` | The ChangeSpec name changed; detail records `old -> new`         |
| `REBASE` | The parent relationship changed; detail records `old -> new`     |

New entries use the format `[YYMMDD_HHMMSS]` in the configured SASE timezone. The parser
also accepts older bare `YYMMDD_HHMMSS` and `[YYYY-MM-DD HH:MM:SS]` forms for
compatibility. TIMESTAMPS are recorded atomically by SASE and are not normally edited by
hand. Multiple events of the same type may appear.

### DELTAS

A computed summary of files added, modified, or deleted by this PR relative to its
parent. The section is maintained automatically by sase from VCS state — it is not
edited by hand.

**Entry format:**

```
DELTAS:
  + path/to/added_file.py
      | LINES: +128
  ~ path/to/modified_file.py
      | LINES: +12 ~7 -3
  - path/to/deleted_file.py
      | LINES: -44
```

The optional `LINES` drawer records semantic line counts. Git-style raw
additions/deletions are converted so paired add/delete lines are shown as modified lines
(`~N`); binary files use `LINES: binary`. Older ChangeSpecs without `LINES` drawers
remain valid.

| Glyph | Change type | Notes                                                                                    |
| ----- | ----------- | ---------------------------------------------------------------------------------------- |
| `+`   | Added       | File introduced by this PR (`A` from VCS); copies are represented as added target files. |
| `~`   | Modified    | File edited (`M`); typechange, unmerged, or future statuses are coerced to modified.     |
| `-`   | Deleted     | File removed (`D`).                                                                      |

Renames (VCS status `R`) are split into a `-` for the source path and a `+` for the
target path. Line counts attach to the target path when the VCS reports them; a pure
rename can therefore show `0 lines`. Entries are sorted alphabetically by path. The
section is omitted entirely when there are no deltas.

**When DELTAS is recomputed:** refresh hooks run after commit creation, rewind, sync,
proposal accept, and proposal rebase. The refresh is best-effort — if the required VCS
query fails, the existing DELTAS section is left untouched and the parent workflow
proceeds. Providers without line stats still refresh file-level DELTAS.

**Manual refresh:** run `sase changespec sync-deltas -c <CL_NAME>` to recompute DELTAS
for a single ChangeSpec from the current VCS state. Optional `-p/--project-file` and
`-w/--workspace-dir` flags override the inferred defaults.

In ACE, DELTAS renders with colored glyphs (green `+`, gold `~`, red `-`). The section
has two semantic fold states: folded and unfolded. The folded state shows the `DELTAS:`
header plus a one-line file and line-count summary; the unfolded state shows the full
alphabetical entry list with inline line tokens. The shared fold model still has an
internal intermediate value for other sections, but DELTAS normalizes any non-folded
value to the unfolded full list. In ACE fold mode, `z1`, `z2`, and `z3` set COMMITS,
HOOKS, MENTORS, TIMESTAMPS, and DELTAS together to collapsed, expanded, or fully
expanded. DELTAS preserves its two-state rendering: both levels 2 and 3 display the
unfolded list.

### HOOKS

Defines lifecycle hooks attached to this PR — shell commands that run automatically at
specific points (e.g., after commit, before mail). Hooks are managed via the `h`
keybinding in ACE.

**Entry format:**

```
HOOKS:
  just test
      | (1) [260328_143200] PASSED (12s)
      | (2) [260328_153300] FAILED (8s) - (!: Hook Command Failed)
```

Hook commands are 2-space indented. Status drawer lines are 6-space indented and start
with `| `. A leading `!` on a hook command means failed runs should skip fix-hook hints;
a leading `$` means the hook is not run for proposal entries and is not subject to the
normal runner limit. Prefixes can be combined, for example `!$just presubmit`.

ACE leaves a running hook's output file untouched. When ACE observes the completion
marker, a capture larger than 500 KiB is atomically compacted, retaining up to the first
200 KiB and last 300 KiB with an explicit byte-elision marker between them. Completion
parsing, metahook matching, and failure summarization inspect the full output before
compaction; later manual viewing uses the compacted capture.

### COMMENTS

Stores review comments and discussion threads. Comments are added via the ACE TUI or
through the review workflow.

**Entry format:**

```
COMMENTS:
  [critique] ~/.sase/comments/auth_system_fix-critique-260328_143500.json
  [critique] ~/.sase/comments/auth_system_fix-critique-260328_150000.json - (!: Unresolved Critique Comments)
```

### MENTORS

Configures mentor workflows for the PR — automated agents that monitor and provide
guidance during development.

**Entry format:**

```
MENTORS:
  (1) security[1/2] reliability[1/1]
      | [260328_143700] security:auth-review - PASSED - (1m05s)
      | [260328_143705] reliability:tests-review - COMMENTED - (2m10s)
```

The entry id matches a `COMMITS` entry such as `(1)` or `(2a)`. Profile names may
include progress counts; legacy entries without counts still parse.

## Complete Examples

### Example 1: Independent PR with Tests

```
NAME: auth_system_add_jwt_validator
DESCRIPTION:
  Add JWT token validation for authentication

  This PR implements JWT token validation using the PyJWT library.
  It includes a JWTValidator class that handles token parsing,
  signature verification, and expiration checking. The implementation
  supports both RS256 and HS256 algorithms. Tests cover valid tokens,
  expired tokens, invalid signatures, and malformed tokens.
STATUS: WIP
```

### Example 2: Dependent PR

```
NAME: auth_system_integrate_validator
DESCRIPTION:
  Integrate JWT validator into authentication middleware

  This PR integrates the JWT validator from the previous PR into
  the main authentication middleware. The middleware will validate
  tokens on protected routes and handle validation errors gracefully.
  Tests verify both successful authentication and various failure
  scenarios including missing tokens, expired tokens, and invalid
  signatures.
PARENT: auth_system_add_jwt_validator
STATUS: WIP
```

### Example 3: Config-Only PR (No Tests)

```
NAME: auth_system_update_config
DESCRIPTION:
  Update JWT configuration with new secret key

  This PR updates the production configuration file to use a new
  secret key for JWT signing. This is a config-only change that
  rotates the signing key for security purposes.
STATUS: WIP
```

### Example 4: PR with Bug Reference

```
NAME: auth_system_fix_token_expiry
DESCRIPTION:
  Fix incorrect token expiry calculation

  The token expiry was being computed from the issue time rather
  than the current time, causing tokens to expire prematurely
  under clock skew conditions.
BUG: http://b/98765
STATUS: Draft
```

## Best Practices

1. **Keep PRs Small and Focused**: Each PR should address a single, well-defined change
2. **Maximize Parallelization**: Omit `PARENT` whenever possible
3. **Include Tests**: Attach relevant test commands in `HOOKS`
4. **Write Clear Descriptions**: Explain what, why, and how
5. **Use Descriptive Names**: NAME should clearly indicate what the PR does
6. **Think About Dependencies**: Only create dependencies when truly necessary
7. **Update Status Appropriately**: Keep STATUS field current as work progresses
