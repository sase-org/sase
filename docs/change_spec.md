# Patch Format Documentation

A **Patch** is SASE's durable local record for one unit of reviewable work. Every PR
created or managed by SASE is associated with exactly one Patch, but a Patch may exist
without a PR; in that case the `PR:` field is absent. SASE does not discover external
PRs and create local Patches for them automatically.

Each Patch lives inside a project `.sase` file and records the change's description,
dependency metadata, PR URL, lifecycle status, stitches, hooks, comments, mentor runs,
timestamps, and computed file deltas.

The filename for this guide remains `change_spec.md` so older public links keep
resolving.

## Format Overview

Each Patch is a block of top-level fields and optional sections. `NAME`, `DESCRIPTION`,
and `STATUS` are the normal minimum for a hand-written entry; `sase stitch create`
creates and updates most other sections automatically.

The canonical order is:

```text
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
STITCHES:
  <STITCH_ENTRIES>
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

The parser also accepts legacy `COMMITS:` sections and legacy `## ChangeSpec` block
headers. New Patches and newly created sections use `STITCHES:`. When SASE edits an
older Patch for an unrelated reason, it preserves the existing section header instead of
rewriting the whole block.

**Important:** when outputting multiple Patches, separate each one with **two blank
lines**.

## Field Specifications

### NAME

The unique identifier for the Patch.

**Recommended format:** `<project_or_area>_<descriptive_suffix>`

- Prefer a project- or area-specific prefix followed by an underscore.
- Use underscores to separate suffix words.
- Keep the suffix descriptive but concise.
- `sase stitch create` appends a numeric suffix such as `_1` when it needs to make a new
  name unique.

**Examples:**

- `my_project_add_config_parser`
- `feature_x_implement_validation`
- `refactor_database_layer`

### DESCRIPTION

A comprehensive description of what the PR-sized change does and why.

**Structure:**

1. **Title:** the first line is a brief one-line summary.
2. **Blank line:** always include one blank line after the title.
3. **Body:** remaining lines give detailed multi-line context.

**Formatting:**

- All lines must be 2-space indented, including the blank line.
- The title should be concise.
- The body should cover what changes are being made, why they are needed, the high-level
  approach, and what will be tested when applicable.

**PR tag stripping:** when a Patch is created from a PR workflow or its description is
synced after a reword, any trailing `KEY=VALUE` metadata lines matching
`^[A-Z][A-Z0-9_]*=` are automatically stripped. The pattern matches both the legacy
unprefixed spelling and the `SASE_`-prefixed footer tags, such as
`SASE_AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT` and `SASE_MARKDOWN=true`, so neither pollutes the
description. See [commit_workflows.md](commit_workflows.md#pull-request-pr) for details.

**Example:**

```text
DESCRIPTION:
  Add configuration file parser for user settings

  This PR implements a YAML-based configuration parser that reads
  user settings from ~/.myapp/config.yaml. The parser includes a
  ConfigParser class with load() and validate() methods, along with
  type definitions for the configuration schema. Tests cover valid
  YAML parsing, invalid config validation, and missing file handling.
```

### PARENT

Specifies the dependency relationship between Patches.

**Values:**

- Omit this field entirely: this Patch has no dependency.
- `<parent_patch_name>`: the `NAME` of a parent Patch that must be completed first.

The `PARENT` field is a Patch **name**, never a VCS ref. Values like `origin/main`,
`origin/master`, or the Mercurial sentinel `p4head` describe checkout targets, not
dependencies between Patches. "No parent Patch" is represented by omitting the field
entirely. `sase stitch create` drops the `PARENT` field and warns when the value passed
via `-p` does not resolve to an existing Patch.

**Auto-detection:** when creating a new Patch via `sase stitch create`, the `PARENT`
field is automatically set if the current branch corresponds to an existing Patch. This
can be overridden with `-p`/`--parent`; see [commit_workflows.md](commit_workflows.md)
for details.

**Dependency guidelines:**

- Default to omitting `PARENT` to maximize parallel development.
- Only set `PARENT` when there is a real content dependency, such as calling a function
  introduced by another Patch or modifying a file that another Patch creates.
- Do not set `PARENT` for independent features, unrelated files, tests for independent
  features, or documentation that does not reference new code.

**Examples:**

```text
# No PARENT field = no dependency
PARENT: my_project_add_config_parser
```

### PR

The PR identifier, usually a PR URL. `PR:` is optional because a Patch can exist before
or without a PR.

Legacy `CL:` fields are still accepted during the compatibility window and are rewritten
as `PR:` when touched.

**Values:**

- Omit this field entirely: no PR has been created yet.
- `<review-url>`: URL to the created PR.
- `https://github.com/<owner>/<repo>/pull/<N>`: URL to a GitHub PR.

**Example:**

```text
PR: https://github.com/org/repo/pull/42
```

### BUG

An optional bug reference linking the Patch to an issue tracker. SASE stores this as
plain text. PR workflows that receive `SASE_BUG_ID` or `sase stitch create --bug-id`
write it as `http://b/<id>` in the Patch and add `SASE_BUG=<id>` to provider tag
metadata.

**Example:**

```text
BUG: http://b/12345
```

### STATUS

The current state of the Patch in its lifecycle.

| Status      | Description                                     |
| ----------- | ----------------------------------------------- |
| `WIP`       | Work in progress; initial development           |
| `Draft`     | PR created as a draft, not yet ready for review |
| `Ready`     | Ready for review                                |
| `Mailed`    | Sent out for review                             |
| `Submitted` | Merged or submitted to the codebase             |
| `Reverted`  | PR was reverted after submission                |
| `Archived`  | PR was abandoned without submission             |

Valid transitions:

```text
WIP -> Draft, Ready
Draft -> Ready
Ready -> Mailed, Draft
Mailed -> Submitted
Submitted -> terminal
Reverted -> terminal
Archived -> terminal
```

The status state machine enforces these transitions. Terminal Patches are moved to the
archive project file.

### REFS

Stores durable artifact references that justify or contextualize the change. Entries are
one canonical reference token per 2-space-indented line, without the prompt-time `@`
sigil.

**Entry format:**

```text
REFS:
  research:202607/artifact_capture_and_retention/artifact_capture_and_retention.md
  file:default:0123456789abcdef01234567
  bead:sase-b7
```

Accepted kinds include `file:`, `chat:`, `bug:`, `commit:`, `agent:`, `bead:`, and
configured document roles such as `plans:` and `research:`. `sase patch ref add`
normalizes entries before writing, deduplicates them while preserving first-write order,
and stores the canonical rendered form. Hand-edited entries are preserved by the parser
so `sase doctor -C project.changespec_refs` can report malformed or unresolved
references instead of silently erasing them.

Use the command group instead of editing the section by hand:

```bash
sase patch ref add --patch <name> research:202607/report.md
sase patch ref list --patch <name> --resolve
sase patch ref rm --patch <name> research:202607/report.md
```

`-c`/`--changespec` and `sase changespec ref ...` remain accepted compatibility aliases.

### STITCHES

A stitch is the lightweight ordered change record inside a Patch. A stitch has a stable
numeric or numeric-plus-letter ID. Numeric stitches are created for real VCS commits
made through the tracked workflow. Proposal stitches such as `(2a)` are intentionally
commitless until accepted.

This section is managed automatically by `sase stitch create`.

**Entry format:**

```text
STITCHES:
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

- Regular stitches use sequential integers: `(1)`, `(2)`, `(3)`, and so on.
- Proposal stitches use the last regular number plus a letter suffix: `(2a)`, `(2b)`,
  and so on.
- Proposals are marked with `(!: NEW PROPOSAL)` to flag them for review.

**Multi-line body:** the first line of the commit message becomes the stitch note.
Subsequent paragraphs become 6-space-indented body lines below the note. Empty body
lines are stored as a dot (`.`) placeholder to preserve structure.

**Drawers:** each stitch can have zero or more drawer lines with a 6-space indent and
`| ` prefix:

| Drawer | Format                         | Description                                    |
| ------ | ------------------------------ | ---------------------------------------------- |
| `CHAT` | `\| CHAT: <path> (<duration>)` | Agent chat log file with optional run duration |
| `DIFF` | `\| DIFF: <path>`              | Saved diff file                                |
| `PLAN` | `\| PLAN: <path>`              | Plan file associated with this stitch          |

The `CHAT` drawer's duration is calculated from the chat filename timestamp to the
commit time. The `PLAN` drawer is emitted when `SASE_PLAN` is set during the commit
workflow.

Legacy `COMMITS:` sections are parsed as stitches. "Commit" remains the correct term for
real Git or Mercurial commits, SHAs, VCS logs, commit statistics, the
`sase stitch create` command, and the act of committing.

### TIMESTAMPS

Records a chronological audit trail of lifecycle events. Each entry includes a
timestamp, event type, and detail string.

**Entry format:**

```text
TIMESTAMPS:
  [260328_143052] COMMIT  (1)
  [260328_151203] STATUS  WIP -> Draft
  [260328_151510] SYNC    Synced with remote
  [260328_160044] REWORD  Updated description title
  [260328_163012] REWIND  (2)
  [260328_170100] RENAME  old_name -> new_name
  [260328_171500] REBASE  old_parent -> new_parent
```

| Type     | Description                                                  |
| -------- | ------------------------------------------------------------ |
| `COMMIT` | A real commit added a numeric stitch; detail is usually ID   |
| `STATUS` | A status transition occurred, such as `WIP -> Draft`         |
| `SYNC`   | A sync operation was performed                               |
| `REWORD` | The description or PR-derived metadata was edited            |
| `REWIND` | A rewind to a previous stitch occurred                       |
| `RENAME` | The Patch name changed; detail records `old -> new`          |
| `REBASE` | The parent relationship changed; detail records `old -> new` |

New entries use `[YYMMDD_HHMMSS]` in the configured SASE timezone. The parser also
accepts older bare `YYMMDD_HHMMSS` and `[YYYY-MM-DD HH:MM:SS]` forms for compatibility.
`TIMESTAMPS` is recorded atomically by SASE and is not normally edited by hand.

### DELTAS

A computed summary of files added, modified, or deleted by this Patch relative to its
parent. The section is maintained automatically by SASE from VCS state and is not edited
by hand.

**Entry format:**

```text
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
(`~N`); binary files use `LINES: binary`. Older Patches without `LINES` drawers remain
valid.

| Glyph | Change type | Notes                                                                         |
| ----- | ----------- | ----------------------------------------------------------------------------- |
| `+`   | Added       | File introduced by this Patch; copies are represented as added target files   |
| `~`   | Modified    | File edited; typechange, unmerged, or future statuses are coerced to modified |
| `-`   | Deleted     | File removed                                                                  |

Renames are split into a `-` for the source path and a `+` for the target path. Entries
are sorted alphabetically by path. The section is omitted entirely when there are no
deltas.

**When DELTAS is recomputed:** refresh hooks run after commit creation, rewind, sync,
proposal accept, and proposal rebase. The refresh is best-effort; if the required VCS
query fails, the existing `DELTAS` section is left untouched and the parent workflow
proceeds.

**Manual refresh:** run `sase patch sync-deltas --patch <name>` to recompute `DELTAS`
for a single Patch from the current VCS state. Optional `-p`/`--project-file` and
`-w`/`--workspace-dir` flags override the inferred defaults. The legacy
`sase changespec sync-deltas -c <name>` spelling remains accepted.

In ACE, `DELTAS` renders with colored glyphs. The section has two semantic fold states:
folded and unfolded. The folded state shows the header plus a one-line file and
line-count summary; the unfolded state shows the full alphabetical entry list.

### HOOKS

Defines lifecycle hooks attached to this Patch: shell commands that run automatically at
specific points, such as after commit or before mail. Hooks are managed via ACE.

**Entry format:**

```text
HOOKS:
  just test
      | (1) [260328_143200] PASSED (12s)
      | (2) [260328_153300] FAILED (8s) - (!: Hook Command Failed)
```

Hook commands are 2-space indented. Status drawer lines are 6-space indented and start
with `| `. A leading `!` on a hook command means failed runs should skip fix-hook hints;
a leading `$` means the hook is not run for proposal stitches and is not subject to the
normal runner limit. Prefixes can be combined, for example `!$just presubmit`.

ACE leaves a running hook's output file untouched. When ACE observes the completion
marker, large captures are atomically compacted for manual viewing while completion
parsing, metahook matching, and failure summarization still inspect the full output.

### COMMENTS

Stores review comments and discussion threads. Comments are added via ACE or through the
review workflow.

**Entry format:**

```text
COMMENTS:
  [critique] ~/.sase/comments/auth_system_fix-critique-260328_143500.json
  [critique] ~/.sase/comments/auth_system_fix-critique-260328_150000.json - (!: Unresolved Critique Comments)
```

### MENTORS

Configures mentor workflows for the Patch: automated agents that monitor and provide
guidance during development.

**Entry format:**

```text
MENTORS:
  (1) security[1/2] reliability[1/1]
      | [260328_143700] security:auth-review - PASSED - (1m05s)
      | [260328_143705] reliability:tests-review - COMMENTED - (2m10s)
```

The entry ID matches a stitch such as `(1)` or `(2a)`. Profile names may include
progress counts; legacy entries without counts still parse.

## Complete Examples

### Example 1: Independent Patch With Tests

```text
NAME: auth_system_add_jwt_validator
DESCRIPTION:
  Add JWT token validation for authentication

  This PR implements JWT token validation using the PyJWT library.
  It includes a JWTValidator class that handles token parsing,
  signature verification, and expiration checking. Tests cover valid tokens,
  expired tokens, invalid signatures, and malformed tokens.
STATUS: WIP
```

### Example 2: Dependent Patch

```text
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

### Example 3: Patch With A PR And Stitches

```text
NAME: auth_system_fix_token_expiry
DESCRIPTION:
  Fix incorrect token expiry calculation

  The token expiry was being computed from the issue time rather
  than the current time, causing tokens to expire prematurely.
PR: https://github.com/org/repo/pull/42
BUG: http://b/98765
STATUS: Draft
STITCHES:
  (1) Fix token-expiry calculation
      | CHAT: ~/.sase/chats/auth_system_fix_token_expiry-commit-260328_143052.md (2m15s)
      | DIFF: ~/.sase/diffs/auth_system_fix_token_expiry-260328_143052.diff
  (1a) Alternative skew-handling proposal - (!: NEW PROPOSAL)
      | DIFF: ~/.sase/diffs/auth_system_fix_token_expiry-260328_160000.diff
```

## Best Practices

1. Keep Patches small and focused.
2. Omit `PARENT` whenever possible.
3. Attach relevant test commands in `HOOKS`.
4. Write clear descriptions that explain what, why, and how.
5. Use descriptive `NAME` values.
6. Update `STATUS` as work progresses.
7. Use `sase patch ref ...` for artifact references instead of hand-editing `REFS:`.
