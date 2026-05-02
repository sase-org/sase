---
status: done
create_time: 2026-03-27 16:56:59
prompt: sdd/prompts/202603/message_file_migration.md
---

# Plan: Migrate `--message` to `--message-file`

## Motivation

Currently, agents pass commit messages (and PR descriptions) as inline CLI strings via `sase commit -m "..."`. This is
problematic for `create_pull_request` workflows where the PR description benefits from rich markdown formatting -
multi-line content with headers, bullet points, and code blocks is awkward to pass as a quoted shell argument. Migrating
to a file-based approach lets agents write proper markdown files and pass the path, avoiding shell quoting issues and
enabling richer descriptions.

## Design

- **Replace** `--message` / `-m` with `--message-file` / `-m` (reuse the short flag for muscle memory)
- `sase commit` reads the file content into `payload["message"]` (so the downstream workflow is unchanged)
- `sase commit` deletes the file after reading (it's ephemeral, created per-invocation)
- The workflow layer (`CommitWorkflow`) needs **no changes** - it still operates on `payload["message"]`
- VCS providers need **no changes** - they still receive `payload["message"]`
- SKILL.md files are updated to instruct agents to write a markdown file before committing

### File lifecycle

```
Agent writes commit_message.md  -->  sase commit -m commit_message.md  -->  handler reads file  -->  handler deletes file  -->  workflow runs with payload["message"]
```

### Error handling

- If the file path doesn't exist: print error and exit 1 (before any VCS operations)
- If the file is empty: proceed with empty string (existing validation catches missing message for
  create_commit/create_proposal)

## Changes

### Phase 1: CLI and handler (sase_102 repo)

**`src/sase/main/parser_commands.py`** (lines 32-36)

- Rename `--message` to `--message-file`, keep `-m` as short form
- Update help text: `"Path to file containing the commit message / PR description"`
- The argparse `dest` will become `message_file` (auto-converted from `--message-file`)

**`src/sase/main/cl_handler.py`** (lines 12-44)

- At the top of `handle_commit_command()`:
  - Read `args.message_file` as a file path
  - If the path is provided but doesn't exist, print error and `sys.exit(1)`
  - Read file content, strip trailing whitespace
  - Delete the file (best-effort, don't fail if deletion fails)
  - Set `payload["message"]` to the file content (or `""` if no file provided)
- Rest of the function is unchanged

### Phase 2: Tests (sase_102 repo)

**`tests/test_commit_cli.py`**

- Update `_parse_commit_args` usage: all tests that pass `-m "msg"` now need to write a temp file and pass `-m path`
- Add a pytest fixture that creates a temp message file and returns its path
- Update all test cases in `TestCommitCLI`:
  - `test_basic_commit`: write "fix: bug" to temp file, pass `-m <path>`
  - `test_multiple_files`: same pattern
  - `test_no_files_stages_all`: same pattern
  - `test_bead_id`, `test_pr_name`, `test_checkout_target`, etc.: same pattern
- Add new tests:
  - `test_message_file_not_found`: verify error exit when path doesn't exist
  - `test_message_file_deleted_after_read`: verify file is deleted after handler runs
  - `test_message_file_multiline`: verify multi-line markdown content is preserved

**`tests/test_commit_workflow.py`**

- No changes needed - workflow tests construct `payload` dicts directly with `"message"` keys, not via CLI parsing

### Phase 3: Skill files (chezmoi repo + ~/.claude/)

All SKILL.md files need the same conceptual update: instruct agents to write a markdown file instead of passing an
inline string.

**Files to update (6 total):**

1. `~/.claude/skills/sase_git_commit/SKILL.md` (active Claude skill)
2. `~/.claude/skills/sase_hg_commit/SKILL.md` (active Claude skill)
3. `~/.local/share/chezmoi/home/dot_claude/skills/sase_git_commit/SKILL.md`
4. `~/.local/share/chezmoi/home/dot_gemini/skills/sase_git_commit/SKILL.md`
5. `~/.local/share/chezmoi/home/dot_codex/skills/sase_git_commit/SKILL.md`
6. `~/.local/share/chezmoi/home/dot_gemini/skills/sase_hg_commit/SKILL.md`

**Updated instruction flow for git skills:**

1. Examine uncommitted changes (unchanged)
2. Determine the commit tag (unchanged)
3. **Write a commit message file** - Create a markdown file (e.g., `commit_message.md`) with the commit message. For
   `create_pull_request`, write a detailed PR description with a summary, test plan, etc. For
   `create_commit`/`create_proposal`, a single-line `<tag>: <description>` is sufficient.
4. Check for bead association (unchanged)
5. Run the commit with `-m commit_message.md` instead of `-m "inline message"`

**Updated instruction flow for hg skills:**

- Same pattern: write file, pass path via `-m`
- Remove the JSON payload approach from the Claude hg skill (it's already using `-m` flags in the Gemini version)

### Files that do NOT need changes

- **`src/sase/workflows/commit/workflow.py`** - operates on `payload["message"]`, unchanged
- **`src/sase/vcs_provider/`** - receives `payload["message"]`, unchanged
- **`src/sase/scripts/sase_git_commit`** - forwards `"$@"` to `sase commit`, unchanged
- **`src/sase/scripts/sase_commit_stop_hook.py`** - doesn't reference `-m` flag, unchanged
- **`../sase-github/`** - receives `payload["message"]` and `payload["_pr_body"]`, unchanged

## Verification

1. `just check` passes in sase_102 repo
2. All existing tests pass with the new file-based interface
3. New tests verify file reading, deletion, and error handling
4. SKILL.md files are consistent across all runtimes (Claude, Gemini, Codex)
5. `chezmoi apply` after committing chezmoi changes
