# ChangeSpec Format Documentation

A **ChangeSpec** is a structured specification for a change list (CL), also known as a pull request (PR). It defines the
metadata, description, dependencies, and status of a proposed code change.

## Format Overview

Each ChangeSpec follows this exact format:

```
NAME: <NAME>
DESCRIPTION:
  <TITLE>

  <BODY>
PARENT: <PARENT>
CL: <CL>
BUG: <BUG>
TEST TARGETS: <TEST_TARGETS>
STATUS: <STATUS>
KICKSTART:
  <KICKSTART_TEXT>
COMMITS:
  <COMMIT_ENTRIES>
TIMESTAMPS:
  <TIMESTAMP_ENTRIES>
HOOKS:
  <HOOK_ENTRIES>
COMMENTS:
  <COMMENT_ENTRIES>
MENTORS:
  <MENTOR_ENTRIES>
```

Not all fields are required — see individual field specifications below.

**IMPORTANT**: When outputting multiple ChangeSpecs, separate each one with **two blank lines**.

## Field Specifications

### NAME

The unique identifier for the change list.

**Format**: `<prefix>_<descriptive_suffix>`

- Must start with a project-specific prefix followed by an underscore
- Suffix should use underscores to separate words
- Suffix should be descriptive but concise

**Examples**:

- `my_project_add_config_parser`
- `feature_x_implement_validation`
- `refactor_database_layer`

### DESCRIPTION

A comprehensive description of what the CL does and why.

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

**PR tag stripping:** When a ChangeSpec is created from a PR workflow or its description is synced after a reword, any
trailing `KEY=VALUE` metadata lines (matching `^[A-Z][A-Z0-9_]*=`) are automatically stripped. This prevents
provider-specific tags like `AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT` or `MARKDOWN=true` from polluting the description. See
[commit_workflows.md](commit_workflows.md#pull-request-pr) for details.

**Example**:

```
DESCRIPTION:
  Add configuration file parser for user settings

  This CL implements a YAML-based configuration parser that reads
  user settings from ~/.myapp/config.yaml. The parser includes a
  ConfigParser class with load() and validate() methods, along with
  type definitions for the configuration schema. Tests will cover
  valid YAML parsing, invalid config validation, and missing file
  handling.
```

### PARENT

Specifies the dependency relationship between CLs.

**Values**:

- Omit this field entirely - This CL has no dependencies (default, preferred for parallelization)
- `<parent_cl_name>` - The NAME of a parent CL that must be completed first

**CRITICAL Dependency Guidelines**:

- **Default to omitting PARENT** to maximize parallel development
- **Only set a PARENT when there's a real content dependency**:
  - CL B calls a function/class that CL A creates
  - CL B modifies a file that CL A creates
  - CL B extends functionality that CL A introduces
- **DO NOT set a PARENT for**:
  - Independent features that don't interact
  - Changes to different files/modules
  - Tests for independent features
  - Documentation that doesn't reference new code

**Examples**:

```
# No PARENT field = no dependencies (preferred)
PARENT: my_project_add_config_parser   # Depends on another CL
```

### CL / PR

The CL or PR identifier (e.g., CL number or PR URL). Both `CL:` and `PR:` are accepted and treated identically — use
whichever matches your project's terminology.

**Values**:

- Omit this field entirely - CL/PR not yet created (initial state)
- `http://cl/<CL_ID>` - URL to the created CL
- `https://github.com/<owner>/<repo>/pull/<N>` - URL to the PR

**Example**:

```
# No CL field = CL not yet created
CL: http://cl/12345        # After CL creation
PR: https://github.com/org/repo/pull/42   # PR variant
```

### BUG

An optional bug reference linking the CL to an issue tracker.

**Example**:

```
BUG: b/12345
```

### TEST TARGETS

Specifies the test targets that need to pass for this CL.

**This field has three possible states**:

1. **Omitted entirely**: For CLs that don't require tests
   - Config-only changes
   - SQL data changes
   - Documentation-only changes
   - New enum values
   - Small changes where tests aren't justified

2. **Specified with targets**: For CLs that require specific tests
   - Single-line format: `TEST TARGETS: //path/to:test`
   - Multi-line format (preferred for multiple targets):
     ```
     TEST TARGETS:
       //path/to:test1
       //path/to:test2
     ```
   - Each target must be 2-space indented in multi-line format
   - No blank lines between targets

3. **Field present but no value specified**: Tests are required but targets are TBD
   - Format: `TEST TARGETS:` (with nothing after the colon)

**NEVER use `TEST TARGETS: None`** — either specify targets or omit the field.

**Target Format**:

- General: `//path/to/package:target_name`

**Examples**:

```
# Single target
TEST TARGETS: //my/project:config_parser_test

# Multiple targets (single-line)
TEST TARGETS: //my/project:test1 //my/project:test2

# Multiple targets (multi-line, preferred)
TEST TARGETS:
  //my/project:integration_test
  //my/project:config_parser_test

# No tests required (omit field entirely)
```

### STATUS

The current state of the CL in its lifecycle.

**Valid Values**:

| Status      | Description                                     |
| ----------- | ----------------------------------------------- |
| `WIP`       | Work in progress — initial development          |
| `Draft`     | CL created as a draft, not yet ready for review |
| `Ready`     | Ready for review                                |
| `Mailed`    | Sent out for review                             |
| `Submitted` | Merged / submitted to the codebase (terminal)   |
| `Reverted`  | CL was reverted after submission (terminal)     |
| `Archived`  | CL was abandoned without submission (terminal)  |

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

**Status Selection Rules**:

- New CLs typically start as `WIP`
- Move to `Draft` once a CL has been created
- Move to `Ready` when the CL is ready for review
- Move to `Mailed` when sent out for review
- Update status as work progresses through the lifecycle

### KICKSTART

Optional initial prompt or instructions used to bootstrap the CL's development. This is a multi-line field with 2-space
indentation.

**Example**:

```
KICKSTART:
  Create a new module that handles configuration parsing.
  Use YAML format and support schema validation.
```

### COMMITS

Tracks the commit history associated with this CL. This section is managed automatically by `sase commit`.

**Entry format:**

```
COMMITS:
  (1) First commit note
      | CHAT: ~/.sase/chats/mybranch-commit-260328_143052.md (2m15s)
      | DIFF: ~/.sase/diffs/mybranch-260328_143052.diff
      | PLAN: plans/my_plan.md
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

**Multi-line body:** The first line of the commit message becomes the note. Subsequent paragraphs (separated by a blank
line in the original message) become 6-space-indented body lines below the note. Empty body lines are stored as a dot
(`.`) placeholder to preserve structure.

**Drawers:** Each entry can have zero or more drawer lines (6-space indent, `| ` prefix):

| Drawer | Format                         | Description                                     |
| ------ | ------------------------------ | ----------------------------------------------- |
| `CHAT` | `\| CHAT: <path> (<duration>)` | Agent chat log file with optional run duration  |
| `DIFF` | `\| DIFF: <path>`              | Saved diff file                                 |
| `PLAN` | `\| PLAN: <path>`              | Plan file associated with this commit (via SDD) |

The CHAT drawer's duration (e.g., `2m15s`) is calculated from the chat filename timestamp to the commit time. The PLAN
drawer is emitted when the `SASE_PLAN` environment variable is set during the commit workflow.

### TIMESTAMPS

Records a chronological audit trail of lifecycle events. Each entry includes a timestamp, event type, and detail string.

**Entry format:**

```
TIMESTAMPS:
  260328_143052 COMMIT  Add JWT token validation
  260328_151203 STATUS  WIP -> Draft
  260328_151510 SYNC    Synced with remote
  260328_160044 REWORD  Updated description title
```

**Event types:**

| Type     | Description                                    |
| -------- | ---------------------------------------------- |
| `COMMIT` | A commit was added to the ChangeSpec           |
| `STATUS` | A status transition occurred (e.g., WIP→Draft) |
| `SYNC`   | A sync operation was performed                 |
| `REWORD` | The description was edited                     |

Timestamps use the format `YYMMDD_HHMMSS` (matching the HOOKS field format) and are recorded atomically by sase — this
section is not manually edited. Multiple events of the same type may appear (e.g., multiple COMMITs or STATUS
transitions).

### HOOKS

Defines lifecycle hooks attached to this CL — shell commands that run automatically at specific points (e.g., after
commit, before mail). Hooks are managed via the `h` keybinding in ACE.

### COMMENTS

Stores review comments and discussion threads. Comments are added via the ACE TUI or through the review workflow.

### MENTORS

Configures mentor workflows for the CL — automated agents that monitor and provide guidance during development.

## Complete Examples

### Example 1: Independent CL with Tests

```
NAME: auth_system_add_jwt_validator
DESCRIPTION:
  Add JWT token validation for authentication

  This CL implements JWT token validation using the PyJWT library.
  It includes a JWTValidator class that handles token parsing,
  signature verification, and expiration checking. The implementation
  supports both RS256 and HS256 algorithms. Tests cover valid tokens,
  expired tokens, invalid signatures, and malformed tokens.
TEST TARGETS: //auth/system:jwt_validator_test
STATUS: WIP
```

### Example 2: Dependent CL with Multiple Test Targets

```
NAME: auth_system_integrate_validator
DESCRIPTION:
  Integrate JWT validator into authentication middleware

  This CL integrates the JWT validator from the previous CL into
  the main authentication middleware. The middleware will validate
  tokens on protected routes and handle validation errors gracefully.
  Tests verify both successful authentication and various failure
  scenarios including missing tokens, expired tokens, and invalid
  signatures.
PARENT: auth_system_add_jwt_validator
TEST TARGETS:
  //auth/system:middleware_test
  //auth/system:integration_test
STATUS: WIP
```

### Example 3: Config-Only CL (No Tests)

```
NAME: auth_system_update_config
DESCRIPTION:
  Update JWT configuration with new secret key

  This CL updates the production configuration file to use a new
  secret key for JWT signing. This is a config-only change that
  rotates the signing key for security purposes.
STATUS: WIP
```

### Example 4: CL with Bug Reference

```
NAME: auth_system_fix_token_expiry
DESCRIPTION:
  Fix incorrect token expiry calculation

  The token expiry was being computed from the issue time rather
  than the current time, causing tokens to expire prematurely
  under clock skew conditions.
BUG: b/98765
TEST TARGETS: //auth/system:jwt_validator_test
STATUS: Draft
```

## Best Practices

1. **Keep CLs Small and Focused**: Each CL should address a single, well-defined change
2. **Maximize Parallelization**: Omit `PARENT` whenever possible
3. **Include Tests**: Most CLs should specify TEST TARGETS
4. **Write Clear Descriptions**: Explain what, why, and how
5. **Use Descriptive Names**: NAME should clearly indicate what the CL does
6. **Think About Dependencies**: Only create dependencies when truly necessary
7. **Update Status Appropriately**: Keep STATUS field current as work progresses
