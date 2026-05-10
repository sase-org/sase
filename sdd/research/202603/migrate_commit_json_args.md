# Research: Migrating `sase commit` JSON Arguments to a Better Interface

## Problem Statement

The `sase commit` command currently accepts a single positional argument: a raw JSON string describing the commit
operation. This interface has several ergonomic and engineering problems that warrant migration to a better design.

## Current Interface

```bash
sase commit '{"message": "feat: Add auth", "files": ["src/auth.py"], "bead_id": "sase-42"}' -m create_commit
```

### How it works

1. **Parser** (`parser_commands.py:26-41`): Registers a positional `payload` arg and optional `-m/--method` flag.
2. **Handler** (`cl_handler.py:12-38`): Calls `json.loads(args.payload)` to parse the JSON string into a dict.
3. **Workflow** (`workflows/commit/workflow.py`): Receives the dict, validates required fields, mutates it (adds
   `_plan_path`, `_pr_body`, modifies `message`), and passes it to the VCS provider.
4. **VCS Providers** (`_git_common.py`, `retired Mercurial plugin/plugin.py`): Extract fields from the dict via `.get()` calls.

### Payload fields by method

| Field              | `create_commit` | `create_proposal` | `create_pull_request` | Notes                         |
| ------------------ | --------------- | ----------------- | --------------------- | ----------------------------- |
| `message`          | Required        | Required          | Optional (used)       | Commit/CL description         |
| `files`            | Optional        | -                 | Optional              | Files to stage; empty = all   |
| `name`             | -               | Optional          | **Required**          | Branch/CL name                |
| `bead_id`          | Optional        | -                 | Optional              | Bead to close                 |
| `checkout_target`  | -               | -                 | Optional              | Branch point (default HEAD~1) |
| `note`             | Optional (hg)   | -                 | -                     | COMMITS note (hg only)        |
| `_plan_path`       | Internal        | Internal          | Internal              | Set by workflow               |
| `_pr_body`         | -               | -                 | Internal              | Set by workflow               |
| `_cl_name`         | -               | Fallback          | -                     | Fallback for `name`           |
| `_skip_bead_amend` | Internal        | -                 | -                     | Skips post-commit amend       |

### Primary callers

1. **AI agents** (most common) - construct JSON per skill instructions and pass via `sase commit '<json>'`
2. **Bash wrapper** (`sase_git_commit` script) - passes through the JSON payload from the agent
3. **Stop hook** - instructs agents to invoke the skill, which then constructs JSON
4. **Humans** (rare) - would call `sase commit` directly

## Problems with the Current Design

### 1. Shell quoting fragility

JSON strings containing quotes, newlines, or special characters require careful shell escaping. AI agents frequently
produce multi-line commit messages, and constructing valid shell-escaped JSON is error-prone:

```bash
# This is what agents have to produce:
sase commit '{"message": "feat: Add auth\n\nThis adds OAuth2 support for the \"primary\" flow.", "files": ["src/auth.py"]}'
```

### 2. No schema validation

The payload is a raw `dict` with no schema. Invalid field names are silently ignored. Missing required fields are caught
only by ad-hoc checks in `CommitWorkflow.run()`. Type errors (e.g., `"files": "auth.py"` instead of
`"files": ["auth.py"]`) aren't caught until git fails.

### 3. Undiscoverable interface

`sase commit --help` shows only "JSON string describing the commit operation." There's no indication of what fields
exist, which are required, or what types they expect. All documentation lives in skill SKILL.md files.

### 4. Mutation of the payload dict

`CommitWorkflow` mutates the payload dict in-place: injecting bead IDs into `message`, adding `_plan_path`, computing
suffixed names, etc. This makes the data flow hard to follow and couples the workflow tightly to the dict structure.

### 5. Mixed internal and external fields

Internal fields (`_plan_path`, `_pr_body`, `_skip_bead_amend`, `_cl_name`) share the same dict as user-facing fields.
The `_` prefix convention is the only separation.

### 6. VCS provider interface is untyped

The pluggy hookspecs pass `payload: dict` to providers. Each provider has to know which keys to extract, and there's no
contract enforcement.

## Options Considered

### Option A: Named CLI flags

Replace the JSON positional arg with explicit flags:

```bash
sase commit --message "feat: Add auth" --files src/auth.py --bead-id sase-42
sase commit -m "feat: Add auth" -f src/auth.py -f src/login.py --bead-id sase-42
```

**Pros:**

- Standard CLI ergonomics — discoverable via `--help`, shell completion
- No quoting issues — argparse handles escaping
- Multi-line messages work naturally with heredocs or `$'...\n...'`
- Type validation via argparse (`type=`, `nargs=`, `choices=`)
- Flags not relevant to a method can be cleanly omitted

**Cons:**

- Agents need updated skill instructions (one-time migration)
- Multi-value `--files` needs `nargs='*'` or repeated `-f` flags
- Slightly more verbose for the common case

**Impact on VCS provider interface:** The handler converts flags to a typed dataclass before passing to the workflow.
Provider hooks could accept the dataclass or individual kwargs instead of `dict`.

### Option B: Pydantic/dataclass schema for the JSON payload

Keep JSON input but validate it through a typed schema:

```python
class CommitPayload(BaseModel):
    message: str
    files: list[str] = []
    bead_id: str | None = None
    name: str | None = None  # Required for create_pull_request
    checkout_target: str = "HEAD~1"
```

```bash
# Invocation unchanged:
sase commit '{"message": "feat: Add auth", "files": ["src/auth.py"]}'
```

**Pros:**

- Backward compatible — no caller changes needed
- Type validation, clear error messages for invalid payloads
- Schema serves as documentation
- Can generate JSON Schema for external tooling

**Cons:**

- Still has shell quoting problems
- Still not discoverable via `--help`
- Doesn't fix the fundamental UX issue for agents or humans

### Option C: Subcommands with method-specific flags

Replace the single `sase commit` command with method-specific subcommands:

```bash
sase commit create -m "feat: Add auth" -f src/auth.py --bead-id sase-42
sase commit propose -m "Proposed refactor" -f src/refactor.py
sase commit pr --name add-auth -m "feat: Add auth" -f src/auth.py
```

**Pros:**

- Cleanest separation — each subcommand has exactly the flags it needs
- `--name` is required only for `pr`, enforced by the parser
- `--help` per subcommand is precise and unambiguous
- Removes the `--method` flag entirely — the method is the subcommand

**Cons:**

- Larger CLI surface and more parser boilerplate
- `SASE_COMMIT_METHOD` env var interaction becomes less natural (would need to map env var to subcommand)
- Breaking change for all callers (agents, scripts, stop hook)

### Option D: Stdin/file-based payload

Read JSON from stdin or a file instead of a positional argument:

```bash
echo '{"message": "feat: Add auth"}' | sase commit
sase commit --payload-file /tmp/commit.json
```

**Pros:**

- Eliminates shell quoting entirely
- Handles arbitrarily large/complex payloads
- Common pattern for tools that accept structured input (e.g., `kubectl apply -f`)

**Cons:**

- More complex invocation for the common case
- Agents would need to write a temp file or use shell pipes
- Harder to see what's being committed in logs/audit trails
- Still doesn't provide discoverability or schema validation

### Option E: Named flags + JSON fallback (hybrid)

Primary interface is named flags; JSON accepted as a fallback for backward compatibility:

```bash
# New primary interface:
sase commit -m "feat: Add auth" -f src/auth.py --bead-id sase-42

# Legacy fallback (deprecated):
sase commit --json '{"message": "feat: Add auth"}'
```

**Pros:**

- Clean migration path — old callers can use `--json` while new callers use flags
- All the benefits of Option A
- Backward compatible during transition

**Cons:**

- Two interfaces to document and maintain (temporarily)
- Risk of the JSON fallback becoming permanent cruft

### Option F: Named flags with subcommands (A + C combined)

Subcommands for the method, named flags for the payload:

```bash
sase commit create -m "feat: Add auth" -f src/auth.py --bead-id sase-42
sase commit propose -m "Proposed refactor"
sase commit pr --name add-auth -m "feat: Add auth" --bead-id sase-42
```

With `SASE_COMMIT_METHOD` env var as a default subcommand selector (so bare `sase commit -m "..."` uses the env var to
pick the subcommand).

**Pros:**

- Combines the best of A and C
- Cleanest per-method validation
- Env var fallback preserves xprompt workflow compatibility

**Cons:**

- Most complex parser implementation
- Bare `sase commit -m "..."` behavior depends on env var, which may confuse users

## Analysis

### What matters most

The primary callers are AI agents, which means:

1. **Clear error messages on invalid input** matter more than discoverability (agents read skill docs, not `--help`).
2. **Reliable quoting/escaping** matters a lot — agents frequently produce broken JSON shell escapes.
3. **Simplicity of construction** matters — agents construct commands from instructions, simpler is better.
4. **Backward compatibility** matters less — skill instructions can be updated atomically.

### Comparison matrix

| Criterion                  | A: Flags | B: Schema | C: Subcmds | D: Stdin | E: Hybrid | F: Flags+Subcmds |
| -------------------------- | -------- | --------- | ---------- | -------- | --------- | ---------------- |
| Eliminates quoting issues  | Yes      | No        | Yes        | Yes      | Yes       | Yes              |
| Schema validation          | Partial  | Yes       | Partial    | Partial  | Partial   | Partial          |
| Discoverable via `--help`  | Yes      | No        | Yes        | No       | Yes       | Yes              |
| Backward compatible        | No       | Yes       | No         | No       | Yes       | No               |
| Simple for agents          | Yes      | Same      | Yes        | Worse    | Yes       | Yes              |
| Method-specific validation | No       | Possible  | Yes        | Possible | No        | Yes              |
| Implementation complexity  | Low      | Low       | Medium     | Low      | Medium    | High             |
| Env var interaction        | Fine     | Fine      | Awkward    | Fine     | Fine      | Needs design     |

### Key trade-off: backward compatibility vs. clean break

Option B is the only fully backward-compatible option, but it doesn't fix the fundamental quoting problem. All other
options require updating callers. Since the callers are:

- Skill SKILL.md files (in chezmoi, easy to update)
- The `sase_git_commit` bash wrapper (in this repo)
- The stop hook instructions (in this repo)

...the migration surface is small and fully controlled. Backward compatibility is nice-to-have, not essential.

### Key trade-off: subcommands vs. flat flags

Subcommands (C, F) give the cleanest per-method validation but interact awkwardly with `SASE_COMMIT_METHOD`. The env var
is set by xprompt workflows (`commit.yml`, `propose.yml`, `pr.yml`) and read by the handler. With subcommands, either:

- The env var maps to a default subcommand (complex, implicit)
- The xprompt workflows pass the method as a subcommand (requires workflow changes)
- The env var is removed entirely and the method is always explicit

The simplest option is to keep `--method` as a flag (Option A) since it already works with the env var fallback.

## Recommendation: Option A (Named CLI flags)

Option A provides the best balance of simplicity, ergonomics, and implementation cost. It solves the core problems
(quoting, validation, discoverability) without introducing unnecessary complexity.

### Proposed interface

```bash
sase commit \
  --message "feat: Add user authentication" \
  --files src/auth.py src/login.py \
  --bead-id sase-42 \
  --method create_commit

# Short flags:
sase commit -m "feat: Add auth" -f src/auth.py -f src/login.py --bead-id sase-42
```

### Proposed parser

```python
def register_commit_parser(subparsers: argparse._SubParsersAction) -> None:
    commit_parser = subparsers.add_parser(
        "commit",
        help="Dispatch a VCS commit operation",
    )
    commit_parser.add_argument(
        "-m", "--message",
        required=True,
        help="Commit message (tag prefix + description)",
    )
    commit_parser.add_argument(
        "-f", "--files",
        nargs="*",
        default=[],
        help="Files to stage (default: all changes)",
    )
    commit_parser.add_argument(
        "--name",
        help="Branch/CL name (required for create_pull_request)",
    )
    commit_parser.add_argument(
        "--bead-id",
        help="Bead ID to close and associate with the commit",
    )
    commit_parser.add_argument(
        "--checkout-target",
        default="HEAD~1",
        help="Branch point for create_pull_request (default: HEAD~1)",
    )
    commit_parser.add_argument(
        "--method",
        choices=["create_commit", "create_proposal", "create_pull_request"],
        help="Commit method (default: $SASE_COMMIT_METHOD or create_commit)",
    )
```

### Proposed handler change

```python
def handle_commit_command(args: argparse.Namespace) -> NoReturn:
    import os

    method = args.method or os.environ.get("SASE_COMMIT_METHOD", "create_commit")

    payload = {
        "message": args.message,
        "files": args.files or [],
        "name": args.name or "",
        "bead_id": args.bead_id or "",
        "checkout_target": args.checkout_target,
    }

    workflow = CommitWorkflow(payload=payload, method=method)
    success = workflow.run()
    sys.exit(0 if success else 1)
```

### Migration steps

1. **Update `register_commit_parser`** — replace the positional `payload` arg with named flags.
2. **Update `handle_commit_command`** — construct the payload dict from args instead of `json.loads`.
3. **Update skill SKILL.md files** — change the agent instructions from JSON to flags.
4. **Update `sase_git_commit` bash wrapper** — adjust how it forwards args to `sase commit`.
5. **Update tests** — update any tests that construct JSON payloads.

### Optional follow-up improvements

These are not required for the initial migration but could be done later:

- **Typed dataclass**: Replace the `dict` payload with a `CommitPayload` dataclass inside `CommitWorkflow` and the VCS
  provider interface. This eliminates the `.get()` calls and internal `_` fields.
- **Subcommands**: If the three methods diverge further, consider splitting into subcommands later.
- **JSON Schema**: Generate a JSON Schema from the dataclass for external tooling.

### What NOT to change

- The `SASE_COMMIT_METHOD` env var — it's the right mechanism for xprompt workflow signaling.
- The VCS provider hookspec signatures — changing `payload: dict` to kwargs is a separate, larger refactor that should
  be done after the CLI migration.
- The `CommitWorkflow` internal logic — it can keep mutating the dict internally for now.

## Appendix: Example skill instructions after migration

````markdown
## Instructions

1. Examine uncommitted changes via `git status` and `git diff`.
2. Pick a conventional commit tag: `feat`, `fix`, `ref`, or `chore`.
3. Compose a concise commit message. Never mention "Claude" or "Claude Code".
4. Check for bead association: `sase bead list --status=in_progress`
5. Run the commit:

   ```bash
   sase commit -m "<tag>: <description>" -f file1.py -f file2.py --bead-id sase-42
   ```
````

- `-m`: Full commit message (required). Use quotes for messages with spaces.
- `-f`: Files to stage (repeat for multiple). Omit to stage all changes.
- `--bead-id`: Include if there's an in-progress bead for your changes.
- `--name`: Branch name (only needed for create_pull_request method).

## Example

```bash
sase commit -m "feat: Add user authentication" -f src/auth.py -f src/login.py --bead-id sase-42
```

```

```
