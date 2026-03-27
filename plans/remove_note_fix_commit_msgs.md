---
create_time: 2026-03-27 17:32:33
status: done
---

# Plan: Remove `--note` option and fix commit message scope

## Problem

Two related issues with the `sase commit` workflow:

1. **`--note` is redundant.** The commit message file (`-m`) already carries the same information. The workflow parses
   the first line of the message as the COMMITS note anyway. The separate `--note` flag adds complexity for no benefit —
   agents never use it, and the message-file approach is strictly more capable (supports multi-line body).

2. **Agents redescribe the entire PR on every commit.** The skills currently say "for `create_commit`, a single-line
   `<tag>: <description>` is sufficient" but don't clarify that the description should cover _only this commit's
   changes_. In practice, agents write a commit message summarizing all PR work, not just their delta. This produces
   noisy COMMITS entries and redundant git history.

## Changes

### Phase 1: Remove `--note` from CLI and workflow

#### 1a. `src/sase/main/parser_commands.py`

Remove the `-N, --note` argument (lines 61-65):

```python
# DELETE these lines:
commit_parser.add_argument(
    "-N",
    "--note",
    help="COMMITS note (used by Mercurial create_commit)",
)
```

#### 1b. `src/sase/main/cl_handler.py`

Remove the note passthrough (lines 46-47):

```python
# DELETE these lines:
if args.note:
    payload["note"] = args.note
```

#### 1c. `src/sase/workflows/commit/workflow.py` (lines 453-467)

Remove the `explicit_note` branch. Always derive note+body from the message:

```python
# BEFORE:
explicit_note = self._payload.get("note")
if explicit_note:
    note = explicit_note
    body: list[str] | None = None
else:
    message = self._payload.get("message", "")
    parts = message.split("\n\n", 1)
    note = (parts[0].split("\n")[0]) or "Manual changes"
    if len(parts) > 1 and parts[1].strip():
        body = parts[1].splitlines()
    else:
        body = None

# AFTER:
message = self._payload.get("message", "")
parts = message.split("\n\n", 1)
note = (parts[0].split("\n")[0]) or "Manual changes"
body: list[str] | None = None
if len(parts) > 1 and parts[1].strip():
    body = parts[1].splitlines()
```

#### 1d. Tests

- `tests/test_commit_cli.py`: Remove `test_note` (lines 90-93).
- `tests/workflows/test_commit_workflow.py`: Remove `test_append_commits_entry_human_cli_uses_note` (lines 294-309).
  Remove the `note` parameter from `_make_commit_workflow` helper. Rename
  `test_append_commits_entry_human_cli_falls_back_to_message` to `test_append_commits_entry_uses_message_first_line`
  (it's no longer a "fallback").

#### 1e. Documentation

- `docs/commit_workflows.md`: No change needed — payload format section already doesn't mention `note`.
- `docs/configuration.md` line 647: That `--note` is for `sase init`, not `sase commit` — no change needed.

### Phase 2: Update skill files to scope commit messages correctly

All 5 commit skill files need the same conceptual change: clarify that `create_commit`/`create_proposal` messages should
describe **only the changes in this commit**, not the overall PR.

#### Files (all in chezmoi — `~/.local/share/chezmoi/home/`):

1. `dot_claude/skills/sase_git_commit/SKILL.md`
2. `dot_claude/skills/sase_hg_commit/SKILL.md`
3. `dot_gemini/skills/sase_git_commit/SKILL.md`
4. `dot_gemini/skills/sase_hg_commit/SKILL.md`
5. `dot_codex/skills/sase_git_commit/SKILL.md`

#### Changes for git_commit skills (Claude, Gemini, Codex):

**Step 3** (write commit message file) — replace with:

> 3. **Write a commit message file** — Create a file (e.g., `commit_message.md`) containing the commit message. **NEVER
>    mention "Claude" or "Claude Code"** — write as if a human authored the commit.
>    - For `create_pull_request`: Write a detailed PR description with a summary, test plan, etc.
>    - For `create_commit` / `create_proposal`: Write a single-line `<tag>: <description>` that describes **only the
>      changes you made in this commit** — not the overall PR or prior commits. The first line becomes the COMMITS entry
>      note.

#### Changes for hg_commit skills (Claude, Gemini):

**Step 2** (determine commit message) — tighten the `create_commit` guidance:

> - For `create_commit`: Describe **only the changes you made in this commit** — not the overall CL or prior commits.

**Step 3** (write commit message file) — add the same scoping note:

> For `create_commit`/`create_proposal`, a concise summary of **this commit's changes only** is sufficient. The first
> line becomes the COMMITS entry note.

**Step 5 flags** — remove the `--note` flag from the list and example:

Remove:

```
- `--note`: Optional note for COMMITS entry (used by `create_commit`).
```

Update example:

```bash
sase commit -m commit_message.md -f auth.py -f login.py --bead-id sase-42
```

### Phase 3: Apply chezmoi and run checks

After committing the chezmoi changes:

```bash
chezmoi apply
```

After committing the sase_101 changes:

```bash
just install && just check
```

## Sequencing

Phase 1 and Phase 2 are independent and can be done as separate commits. Phase 3 is the verification step after each.
