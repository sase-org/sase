---
create_time: 2026-04-09 15:35:50
status: done
prompt: sdd/prompts/202604/commit_message_flag.md
---

# Plan: Reassign `-m` to `--message` and `-M` to `--message-file` for `sase commit`

## Context

Currently `sase commit -m` is the short option for `--message-file` (path to a file containing the commit message). The
user wants to swap this so that `-m` maps to a new `--message` option (inline string), and `--message-file` gets `-M` as
its short option. This mirrors the common convention where `-m` means "message as a string" (like `git commit -m`).

## Changes

### 1. CLI parser — `src/sase/main/parser_commands.py`

- Change `-m, --message-file` to `-M, --message-file`
- Add new `-m, --message` argument (accepts a string directly)

### 2. Handler — `src/sase/main/cl_handler.py`

- Support both `args.message` (inline string) and `args.message_file` (file path)
- Error if both are provided simultaneously
- Priority: `-m` (inline) takes precedence, `-M` (file) as fallback

### 3. Internal caller — `src/sase/axe/run_agent_exec_plan.py`

- `_commit_sdd_files()` currently writes a tempfile and passes `-m msg_path` — update to use `-M` instead (it uses the
  file-based approach)

### 4. Tests — `tests/test_commit_cli.py`

- Update all existing tests that use `-m` for message files to use `-M`
- Add new tests for `-m` / `--message` with inline strings
- Add test for mutual exclusivity of `-m` and `-M`

### 5. Skill docs — SKILL.md files (3 locations)

- `~/.claude/skills/sase_git_commit/SKILL.md` — update flag docs and examples
- `~/.gemini/skills/sase_hg_commit/SKILL.md` — update flag docs and examples
- `~/.local/share/chezmoi/home/dot_gemini/skills/sase_hg_commit/SKILL.md` — update flag docs and examples

### 6. Hook script — `tools/sase_sibling_commit_stop_hook`

- Line 88 references `--message '<msg>'` in a Gemini instruction — no `-m` flag used, so no change needed

## Out of scope

- The `sase_git_commit` bash wrapper script (`src/sase/scripts/sase_git_commit`) just forwards `"$@"` — no flag
  references to update
- The stop hook script uses `--message` in Gemini runtime instruction text which is not an actual `sase commit` flag
  invocation — verify this doesn't conflict with the new `--message` long option name
