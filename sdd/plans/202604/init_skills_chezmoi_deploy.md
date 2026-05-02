---
create_time: 2026-04-17 23:21:56
status: done
prompt: sdd/prompts/202604/init_skills_chezmoi_deploy.md
---

# Plan: Auto-deploy chezmoi skill changes from `sase init-skills`

## Problem

When `sase init-skills` runs with `use_chezmoi: true`, it renders skill templates from `src/sase/xprompts/skills/` and
writes them into the chezmoi source tree (under `~/.local/share/chezmoi/home/dot_<provider>/skills/...`). That is only
_half_ the deploy: the user then has to manually commit the chezmoi repo, push it, and run `chezmoi apply` to copy the
generated files to their live locations (`~/.claude/...`, `~/.gemini/...`, etc.).

This is an error-prone ritual. The chezmoi memory (`long-external-repos.md`) even codifies it as a standing rule, which
is a strong signal the tool should just do it.

## Goal

When `sase init-skills` finishes writing files and `use_chezmoi: true`, the command should automatically:

1. `git commit` in the chezmoi repo, staging _only_ the skill files it wrote this run
2. `git pull --rebase` then `git push` to the chezmoi remote
3. `chezmoi apply`

…so a single `sase init-skills` invocation end-to-end regenerates, versions, syncs, and deploys the skills.

## Non-goals

- Does NOT run the sequence when `use_chezmoi: false` — in that mode files land directly in `~/.claude/...` etc. and
  there is no chezmoi repo to commit.
- Does NOT commit unrelated dirty state in the chezmoi repo. Staging is explicit per-file.
- Does NOT extract a shared `git_ops` module. The TUI (`xprompt_browser_actions.py`) already has its own version of this
  sequence, and pulling them both into one helper is worth doing but is separate cleanup — noted in Follow-ups.
- Does NOT change behavior for the `--dry-run` mode (no side effects, as today).

## Current behavior (baseline)

- `src/sase/main/init_skills_handler.py::handle_init_skills_command` iterates skill sources, renders them, writes each
  target via `target.write_text(...)`, tracks `written`/`skipped` counts, prints a summary, exits 0.
- `CHEZMOI_HOME` is `~/.local/share/chezmoi/home`; target paths are under that tree when `use_chezmoi: true`.
- `xprompt_browser_actions.py::_offer_git_commit` and `_run_chezmoi_apply` already implement the exact sequence we want,
  driven by a TUI confirm modal. Key implementation details to mirror:
  - `subprocess.run(["git", "-C", git_root, "add", "--", file_path], ...)` — stage by explicit path
  - `commit -m <msg>`, then `pull --rebase`, then `push`
  - Run `chezmoi apply` only after a successful push
  - `FileNotFoundError` handled for missing `chezmoi` binary
  - Each step's failure short-circuits the next

## Proposed design

### Trigger conditions

The deploy sequence runs iff **all** of these hold:

- `use_chezmoi` is true
- Not in `--dry-run`
- `written > 0` (at least one file was actually written or overwritten; if every target was "unchanged" or user-skipped,
  nothing to commit)

Otherwise the handler behaves exactly as today.

### Step 1 — Commit

- `git_root` is the parent of `CHEZMOI_HOME` (i.e. `~/.local/share/chezmoi`). Verify it is a git working tree; if it is
  not, print a warning and skip the remaining git/apply steps (but still exit 0 — the files are written).
- Stage only the set of target paths that were actually written this run. The handler already knows these — we extend
  the main loop to collect them into a list.
- If `git diff --cached --quiet` returns 0 (nothing staged, e.g. files we wrote were byte-identical to what was already
  tracked), skip commit/push/apply with an informational message. This prevents empty commits.
- Commit message: `chore: regenerate skills via sase init-skills`. If `--provider` was passed, include it:
  `chore: regenerate <provider> skills via sase init-skills`.

### Step 2 — Pull & Push

- `git pull --rebase` first (matches the TUI pattern; chezmoi repos are typically synced across machines, so stale local
  state is common).
- If pull fails (merge conflicts, detached HEAD, no upstream), print stderr and stop — do NOT push, do NOT apply. Exit
  with a non-zero status so the user sees the failure loud and clear. The commit is still in place locally.
- Then `git push`. On failure: same treatment (print stderr, skip apply, non-zero exit).

### Step 3 — chezmoi apply

- Only runs after a successful push.
- Catch `FileNotFoundError` for a missing `chezmoi` binary → print a warning (`chezmoi not found on PATH`) and exit 0,
  since the commit/push part did succeed.
- On a non-zero `chezmoi apply` exit, print stderr and exit non-zero.

### CLI flags

Three opt-outs, all defaulting to "do the thing":

- `--no-commit` — skip steps 1–3 entirely
- `--no-push` — do step 1, skip steps 2–3
- `--no-apply` — do steps 1–2, skip step 3

These compose naturally (`--no-commit` implies the others, etc.). Short options per the `gotchas.md` convention:
`-C`/`--no-commit`, `-P`/`--no-push`, `-A`/`--no-apply`. (Avoiding `-c`/`-p` collision with existing lowercase flags on
other subcommands.)

### Output

Print the git/chezmoi output as the handler progresses, e.g.:

```
Written: 12, Skipped: 3

Committing in /home/bryan/.local/share/chezmoi...
  [chezmoi abc1234] chore: regenerate skills via sase init-skills
Pulling...
  Already up to date.
Pushing...
  To github.com:user/chezmoi.git
Applying chezmoi...
  Done.
```

Failures go to stderr with a clear prefix (e.g. `init-skills: push failed: ...`).

## Implementation outline

Changes confined to two files plus tests:

1. **`src/sase/main/init_skills_handler.py`**
   - Collect a `written_paths: list[Path]` in the main loop.
   - After the summary print, call a new private `_deploy_to_chezmoi(written_paths, args)` helper when the trigger
     conditions are met.
   - `_deploy_to_chezmoi` encapsulates: resolve `git_root`, stage paths, commit, pull, push, apply — with early returns
     honoring `--no-commit` / `--no-push` / `--no-apply`, and correct exit codes on failure.
   - `FileNotFoundError` guards around `git` and `chezmoi` subprocess calls.

2. **`src/sase/main/parser_commands.py::register_init_skills_parser`**
   - Add the three new `--no-*` flags with short options.

3. **Tests: `tests/main/test_init_skills_handler.py`** (new file; no existing tests for this handler)
   - `subprocess.run` mocked via `monkeypatch`. Capture the sequence of commands.
   - Test matrix:
     - `use_chezmoi: false` → no git/chezmoi calls
     - `use_chezmoi: true`, `written == 0` → no git/chezmoi calls
     - `use_chezmoi: true`, `written > 0`, happy path → exact command sequence (add → commit → pull → push → apply)
     - `--dry-run` → no git/chezmoi calls even with `use_chezmoi: true`
     - `--no-commit` / `--no-push` / `--no-apply` each honored
     - Commit failure (e.g. `git diff --cached --quiet` exits 0) → no push, no apply, exit 0
     - Push failure → no apply, non-zero exit
     - `chezmoi` binary missing → warning, exit 0
     - `git_root` not a git repo → skipped gracefully

## Edge cases & decisions

- **Partial writes across providers.** If we wrote `claude/sase_plan` but skipped `gemini/sase_plan` interactively, we
  only stage what was written. A future run will stage the remaining file. No special handling needed.
- **Dirty chezmoi repo from other sources.** Because we stage by explicit path, unrelated dirty files in the chezmoi
  repo are not swept into our commit. The user's other in-flight chezmoi work is preserved.
- **Pull conflicts.** We stop rather than attempt to resolve. The user's local commit is intact; they can `git pull`
  manually, resolve, and push. We do not abort the rebase automatically — leave the repo in the state `git pull` left it
  in, so the user sees the real problem.
- **No upstream configured.** `git push` will fail with a clear message; we surface it. Not our job to guess an
  upstream.
- **`-f/--force` interaction.** Orthogonal — `--force` affects whether we overwrite existing skill files; the new flags
  affect what we do after writing.
- **`--provider` interaction.** Narrower invocations still deploy. The commit message mentions the provider so the
  commit log stays readable.

## Testing plan

- Unit tests as listed above — mocked subprocesses, happy path + each failure branch.
- Manual end-to-end: run `sase init-skills -f` on a machine with `use_chezmoi: true`, a real chezmoi repo, a working
  remote, and `chezmoi` installed. Verify commit lands, push succeeds, and generated files appear at their apply
  destinations.
- Manual negative: point `CHEZMOI_HOME` at a non-git directory and confirm graceful skip.
- Run `just check` before finishing.

## Follow-ups (out of scope for this change)

- Factor a shared `sase/git_ops.py` (or similar) with the `stage → commit → pull → push → chezmoi-apply` sequence;
  migrate both `init_skills_handler.py` and `xprompt_browser_actions.py::_offer_git_commit` onto it. Keep the
  TUI-specific `notify(...)` vs CLI-specific `print(...)` as injected I/O callbacks.
- Update `.sase/memory/long-external-repos.md` to note that `sase init-skills` now auto-handles the chezmoi
  commit/push/apply so future agents do not redundantly do it.
- Consider extending this auto-deploy behavior to any other sase command that writes into the chezmoi tree.
