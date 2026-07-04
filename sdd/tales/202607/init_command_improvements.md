---
create_time: 2026-07-04 06:32:35
status: wip
prompt: sdd/prompts/202607/init_command_improvements.md
---
# Plan: Fix bugs and objective UX gaps in `sase init`

## Context

`sase init` is the onboarding entrypoint for new SASE users, so it must be safe, predictable, and quiet when nothing is
wrong. A review of the command family (bare `sase init`, `sase init memory|sdd|skills`, and the canonical
`sase memory init` / `sase sdd init` / `sase skill init` commands) found four genuine bugs and two objective
improvements. All are "clear win" fixes: each one either makes a documented promise true, removes a crash/traceback, or
removes provably wrong output. None change intended behavior in a way anyone would want to keep.

All work is CLI/presentation-layer Python in this repo (no shared domain behavior), so nothing crosses the Rust core
backend boundary.

## Findings and fixes (ordered by severity)

### 1. BUG: `sase init --check skills` ignores `--check` and mutates files

The parent `init` parser accepts `-c/--check` before a subcommand ("Report initialization drift without writing files or
running initializers"), and `tests/main/test_init_onboarding_parser.py` explicitly exercises the
`sase init --check <subcommand>` form. The memory and sdd handlers honor it (`run_init_memory` and `run_sdd_init` both
route to `run_init_check` when `args.check` is set), but `run_init_skills` in `src/sase/main/init_skills_handler.py`
never reads `args.check`. As a result, `sase init --check skills`:

- creates any missing skill files unconditionally,
- prompts to overwrite drifted files (TTY) or emits skip warnings (non-TTY), and
- can trigger a chezmoi git commit/push/apply —

all under a flag documented as read-only. Additionally, `--check` cannot be spelled after the subcommand
(`sase init skills --check` and `sase skill init --check` are argparse errors), even though both sibling commands
support exactly that (`sase memory init --check`, `sase sdd init --check`).

**Fix:**

- In `run_init_skills`, honor `args.check` by delegating to `run_init_check` with the skills `InitCommandSpec` — the
  identical pattern already used by `run_init_memory` (`src/sase/main/init_memory_handler.py`) and `run_sdd_init`
  (`src/sase/main/sdd_handler.py`). `plan_init_skills` already exists, so this is pure wiring.
- Add `-c/--check` (with `default=argparse.SUPPRESS`, matching the memory subparser pattern) to
  `add_skills_init_arguments` in `src/sase/main/parser_init.py`, so both `sase skill init --check` and
  `sase init skills --check` parse. `-c` is free in that flag set (`-C` is `--no-commit`).

**Tests:** parser test for the new flag positions; handler test that `check=True` performs no writes and returns the
drift-based exit code (mirror `test_init_check_memory_alias_does_not_apply` in
`tests/main/test_init_onboarding_entry.py`).

### 2. BUG: `sase skill init` treats up-to-date files as drift outside the interactive path

`run_init_skills` only compares existing file content against the rendered content inside the interactive
`_prompt_overwrite` path. The non-TTY path and the `--force` path never check content:

- Non-TTY on a fully initialized machine (verified live): `sase skill init` prints one
  `Warning: ... exists, skipping (not a TTY; use -f to force)` line **per target** (60 warnings on the current provider
  set) and ends with `Written: 0, Skipped: 60` — while `sase init --check` on the same machine correctly reports "SASE
  is initialized". A brand-new user scripting or piping this command sees a wall of warnings when nothing is wrong.
- With `--force`, every target is rewritten and reported as written even when byte-identical, and a chezmoi deploy is
  attempted for files with no real change. Bare `sase init --yes` onboarding passes `force=True` internally
  (`_apply_args` in `src/sase/main/init_onboarding.py`), so the onboarding flow reports dozens of "written" files when
  the plan only showed one drifted target.

The planner (`_planned_skill_operation`) already implements the correct semantics: identical content means "no action".

**Fix:** in the `run_init_skills` write loop, check content equality first, before the exists/force/TTY branching.
Identical targets produce no warning, no prompt, and no write; count them separately and report
`Written: N, Skipped: M, Unchanged: K` (the interactive path's "(unchanged, skipping)" message already establishes this
concept). This makes `sase skill init` idempotent, makes its output truthful, and stops no-op chezmoi deploy attempts.
Apply the same content check to `--dry-run` so it lists only paths that would actually change (with their
create/overwrite operation), matching what `plan_init_skills` reports.

**Tests:** update/extend `tests/main/test_init_skills_handler.py` and `tests/main/test_init_skills_deploy.py`: unchanged
targets emit no warning and no write in non-TTY, `--force` rewrites only drifted targets, summary line counts unchanged
targets, dry-run lists only real changes, and no chezmoi deploy happens when everything is current.

### 3. BUG: Ctrl-D / Ctrl-C at the bare `sase init` confirmation prompt raises a traceback

`_prompt_for_plan` in `src/sase/main/init_onboarding.py` calls `input_func(...)` with no guard. During interactive
onboarding — the first thing a new user runs — pressing Ctrl-D (EOF) or Ctrl-C at the `Run \`sase init memory\` now?
[y/N]`prompt dumps a raw Python traceback. Both sibling prompts in this same command family already handle this correctly:`_prompt_overwrite`in`init_skills_handler.py`catches`(EOFError,
KeyboardInterrupt)`, and `_resolve_fold_commit_message`in`init_memory_handler.py` catches each with a clean abort
message.

**Fix:** catch `EOFError` and `KeyboardInterrupt` around the prompt in the onboarding loop. EOF answers "no" for the
current prompt cycle consistent with the `[y/N]` default; Ctrl-C prints a short "aborted" line and exits with a non-zero
code, without running further initializers (the deferred-chezmoi context manager already unwinds safely).

**Tests:** onboarding-flow tests where `input_func` raises `EOFError` / `KeyboardInterrupt`, asserting no spec runs, no
traceback, and the documented exit code (`tests/main/test_init_onboarding_flow.py`).

### 4. BUG: memory init reports failure on repos with no upstream, after succeeding locally

`_deploy_to_project_repo` in `src/sase/main/init_memory_handler.py` unconditionally runs `git pull --rebase` and
`git push` after committing. On a fresh local-only repository — a very plausible first `sase init` environment — the
commit succeeds, then pull fails ("There is no tracking information for the current branch"), the command exits 1, and
bare `sase init` reports `init memory failed with exit code 1` even though every local step succeeded. The same gap
exists in the shared `deploy_to_chezmoi` pull/push path (`src/sase/main/_init_chezmoi_deploy.py`) used by skill init.

**Fix:** add a small shared helper (in `_init_chezmoi_deploy.py`, since both callers live in this command family) that
detects whether the current branch has an upstream (`git rev-parse --abbrev-ref --symbolic-full-name @{u}`). When there
is no upstream, skip pull/push with one informational line (e.g.
`init memory: no upstream configured; skipping pull/push`) and exit 0. Failures on repos that _do_ have an upstream keep
today's error behavior.

**Tests:** extend `tests/main/test_init_memory_commit.py` (and the chezmoi deploy tests) with a no-remote repo fixture
asserting exit 0, the informational message, and that the commit still lands.

### 5. Improvement: derive `--provider` validation from the plugin registry

`add_skills_init_arguments` hardcodes `choices=["claude", "agy", "codex", "opencode", "qwen"]`, while the actual
provider set comes from the `sase_llm` plugin registry (`sase.llm_provider.registry.iter_plugins`; the two happen to
match today). Providers are pluggable, so any newly installed provider plugin is impossible to target with `-p`, and a
removed plugin leaves a dead choice that silently deploys nothing. This also conflicts with the project convention that
all agent runtimes are treated uniformly.

**Fix:** drop the static `choices` list (keep a `PROVIDER` metavar and mention "a registered provider" in help), and
validate the value at handler time in `run_init_skills` / `plan_init_skills` against `iter_plugins()`, erroring with the
list of registered names on a miss. Runtime validation is deliberate: computing choices at parser-build time would load
plugin entry points on every CLI invocation, which startup-performance rules here forbid.

**Tests:** unknown provider errors with the registered-name list; a registered provider filters targets as before
(extend `tests/main/test_init_skills_handler.py`).

### 6. Polish: reject the contradictory `sase init --check --yes`

On bare `sase init`, `-c/--check` (read-only) and `-y/--yes` (apply everything) are opposites, but argparse accepts both
and `--yes` is silently ignored. Put the two flags in an argparse mutually-exclusive group in `register_init_parser`
(`src/sase/main/parser_init.py`) so the conflict is a clear usage error instead of a silent surprise.

**Tests:** parser test asserting `sase init -c -y` exits with a usage error while each flag alone still parses (extend
`tests/main/test_init_onboarding_parser.py`).

## Implementation order

Each finding is independently shippable; implement in the order above (severity order). Items 1 and 2 touch the same
file (`init_skills_handler.py`) and should be done together to avoid churn.

1. Skills `--check` wiring (items 1, 6 — both touch `parser_init.py`).
2. Skills idempotency / unchanged-target handling (item 2).
3. Onboarding prompt interrupt handling (item 3).
4. No-upstream pull/push skip (item 4).
5. Registry-driven provider validation (item 5).

## Affected files

- `src/sase/main/parser_init.py` — add `-c/--check` to skills init flags; mutually exclusive `-c`/`-y` on bare init;
  drop hardcoded provider choices.
- `src/sase/main/init_skills_handler.py` — honor `check`; content-equality check before exists/force/TTY branching;
  truthful written/skipped/unchanged reporting; provider validation.
- `src/sase/main/init_onboarding.py` — guard `_prompt_for_plan` against EOF/interrupt.
- `src/sase/main/init_memory_handler.py` — skip pull/push when no upstream.
- `src/sase/main/_init_chezmoi_deploy.py` — shared upstream-detection helper; use it in `deploy_to_chezmoi`.
- `tests/main/` — new/updated tests per finding, following the existing helper/fixture patterns in
  `init_onboarding_helpers.py` and `init_skills_handler_helpers.py`.

## Verification

- `just install && just check` (lint + mypy + full test suite).
- Manual smoke pass: `sase init --check`, `sase init --check skills` (must not write), `sase skill init` piped non-TTY
  on an up-to-date machine (must be quiet), Ctrl-D and Ctrl-C at the bare `sase init` prompt (clean exit), and
  `sase memory init` in a throwaway no-remote repo (commit succeeds, exit 0).

## Explicitly out of scope

Anything disputable was left out: exit-code semantics of `--check` (drift = 1 is intentional and tested), re-planning
between onboarding steps, output wording/styling changes beyond the truthful counts above, and any redesign of the
onboarding prompt flow.
