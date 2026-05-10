---
create_time: 2026-04-09 15:22:54
status: done
prompt: sdd/prompts/202604/rename_commit_type_flag.md
---

# Plan: Rename `sase commit -M|--method` to `-t|--type`

## Context

The `sase commit` command currently uses `-M|--method` to select the commit dispatch method (`create_commit`,
`create_proposal`, or `create_pull_request`). The user wants to rename this to `-t|--type` for brevity and clarity.

**Note:** The current flag is `-M|--method` (not `--method-type` as described in the request). The `-t` short flag is
free on the commit subparser; it's used on other subparsers (`telemetry list`, `xprompt expand`) but argparse namespaces
are per-subparser so there's no conflict.

## Design Decision: Internal Variable Name

The CLI flag changes to `--type`, but argparse will derive `args.type` as the attribute name. Since `type` is a Python
builtin, I'll add `dest="method"` so all internal code continues using `args.method`, `method=`, etc. unchanged. This
keeps the diff minimal and avoids builtin shadowing.

## Changes

### Phase 1: Core CLI (sase repo)

1. **`src/sase/main/parser_commands.py:68-72`** — Change `-M`/`--method` to `-t`/`--type`, add `dest="method"` to
   preserve `args.method` attribute name.

2. **`tests/test_commit_cli.py:92`** — Update `--method` to `--type` in the test that passes the flag explicitly.

3. **`docs/commit_workflows.md:28,31,43`** — Update the CLI docs table and prose references from `-M`/`--method` to
   `-t`/`--type`.

### Phase 2: Skill SKILL.md Files (chezmoi repo)

All four skill files reference `--method` in their "Do NOT pass `--method` unless..." guidance line. Update each to say
`--type`:

4. **`~/.local/share/chezmoi/home/dot_claude/skills/sase_git_commit/SKILL.md:43`**
5. **`~/.local/share/chezmoi/home/dot_codex/skills/sase_git_commit/SKILL.md:41`**
6. **`~/.local/share/chezmoi/home/dot_gemini/skills/sase_git_commit/SKILL.md:41`**
7. **`~/.local/share/chezmoi/home/dot_gemini/skills/sase_hg_commit/SKILL.md:33`**

### Phase 3: Plugin Repo (retired Mercurial plugin)

8. **`../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/split_executor.md:36`** — Change `-M create_pull_request` to
   `-t create_pull_request`.

### Not Changed (intentionally)

- **`src/sase/main/cl_handler.py`** — No changes needed; `args.method` is preserved via `dest="method"`.
- **`src/sase/scripts/sase_commit_stop_hook.py:132`** — The string "commit method type" describes the concept, not the
  CLI flag. Left as-is.
- **Plan/spec/research files** (`plans/`, `specs/`, `sdd/research/`) — Historical documents; not updated.
- **`$SASE_COMMIT_METHOD` env var** — Not part of this rename.

### Verification

- `just install && just check` in sase repo
- `just check` in retired Mercurial plugin repo
- `just check` in chezmoi repo
- `chezmoi apply` after chezmoi commit
