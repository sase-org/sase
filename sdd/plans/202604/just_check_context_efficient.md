---
create_time: 2026-04-17 23:58:05
status: done
prompt: sdd/prompts/202604/just_check_context_efficient.md
---

# Context-Efficient `just check` for Agents

## Problem

`just check` (the "did I break anything?" gate agents run repeatedly) dumps **many hundreds of lines** on a passing run.
Per `pyproject.toml:140`, pytest is configured with `-v` (verbose) and prints a line per test collected, plus a coverage
table via `--cov-report=term-missing:skip-covered`. On top of that, `Justfile` prints its own box header via `_header`
and `---------- Running X ----------` separators for every sub-step of `lint`, `fmt-check`, and `test`.

A successful `just check` therefore consumes roughly **2–3% of Claude's 200k context window per invocation** for output
that conveys one bit of information: "everything passed." Agents run `just check` multiple times per task (after every
nontrivial edit, before replying). The waste compounds.

HumanLayer's "Context-Efficient Backpressure" blog (`.sase/home/org/lib/blogs/context_efficient_backpressure.txt`)
articulates the fix: **swallow all successful output and emit one ✓ per stage; on failure, dump the full captured output
for only the failing stage.** The model never sees "PASS test_foo.py" — only "✗ lint (mypy)" followed by the mypy errors
it needs to fix.

## Goal

- **Success path**: `just check` prints ~8 lines — one `✓ <stage>` per atomic step — and exits 0.
- **Failure path**: prior stages still show `✓`, the failing stage shows `✗ <stage>` immediately followed by its full
  captured stdout+stderr, and no later stages run (just's default fail-fast gives us this for free).
- **No loss of information on failure**. Everything an agent would have seen from the raw tool output is preserved,
  verbatim, when there is a problem.
- **Zero impact on `just test`, `just lint`, `just fmt-check` run directly**. Humans debugging interactively keep the
  current verbose behavior. Only the `check` aggregation path changes.

## Non-Goals

- Not changing pytest's `-v` / coverage config globally. That affects anyone who runs `just test` directly; the wrapper
  approach doesn't require it.
- Not adding pytest `-x` / fail-fast. Agents sometimes want to see all failures; the humanlayer blog argues for `-x` but
  that's a separate debate and a one-line follow-up if we decide we want it.
- Not touching tools vendored via `pyvendor` (e.g. `tools/pyvision-260225`, `tools/pyscripts-260314`). Their own stdout
  is arbitrary — we capture it, not modify it.
- Not touching other recipes (`all`, `fix`, `build`, `pylimit`, `clean`, `dev-shell`). Scope is strictly `check` and the
  recipes it depends on.

## Design

### 1. `tools/run_silent` — the core wrapper

Add a new standalone bash script at `tools/run_silent`. Contract:

```
Usage: tools/run_silent <description> <cmd> [args...]

  Runs <cmd> with combined stdout+stderr captured to a tempfile.
  On success (exit 0): prints "✓ <description>" and deletes the tempfile.
  On failure (nonzero): prints "✗ <description>", dumps the captured output,
                        and exits with the same code.
```

Key properties:

- **Passes the command via `"$@"`**, not `eval` / `bash -c` on a single string. Avoids shell-quoting foot-guns and is
  safe with paths containing spaces. For recipes that genuinely need a shell (pipes, `xargs`), callers wrap with
  `bash -c "..."` explicitly.
- **`trap 'rm -f "$tmp_file"' EXIT`** so the tempfile is cleaned up even if the process is interrupted.
- **`set -uo pipefail`** (not `-e`, because we need to observe the subcommand's exit code and keep running to dump the
  log).
- Lives in `tools/` alongside `sase_bead` etc. It is not a vendored script (no `-YYmmdd` suffix), so agents may edit it
  directly in this repo.

### 2. Justfile: split `lint` into atomic private recipes

`lint` currently has five sequential steps in one recipe body. To wrap each individually under `run_silent`, extract
each step as a private recipe so `check` can call them one at a time:

| New private recipe | Current source                              |
| ------------------ | ------------------------------------------- |
| `_lint-ruff`       | `ruff check src/ tests/`                    |
| `_lint-mypy`       | `mypy`                                      |
| `_lint-pyscripts`  | `python tools/pyscripts-260314`             |
| `_lint-pyvision`   | the long `BD_COMMAND=... pyvision ...` line |

`lint-keep-sorted` already exists as its own recipe. `fmt-py-check` and `fmt-md-check` already exist.

The public `lint` recipe is kept (it still chains the four private recipes plus `lint-keep-sorted`) for humans who run
`just lint` interactively — they get the existing verbose, separator-decorated output unchanged.

### 3. Justfile: rewrite `check`

Replace:

```
check: fmt-check lint test
```

with a body that calls `run_silent` for each atomic stage:

```
check: _setup
    @tools/run_silent "fmt (python)"        just fmt-py-check
    @tools/run_silent "fmt (markdown)"      just fmt-md-check
    @tools/run_silent "lint (keep-sorted)"  just lint-keep-sorted
    @tools/run_silent "lint (ruff)"         just _lint-ruff
    @tools/run_silent "lint (mypy)"         just _lint-mypy
    @tools/run_silent "lint (pyscripts)"    just _lint-pyscripts
    @tools/run_silent "lint (pyvision)"     just _lint-pyvision
    @tools/run_silent "test"                just test
```

Notes:

- `@` prefix suppresses just's own "echoing the command" behavior, so the only output comes from `run_silent`.
- Each `run_silent` call re-invokes `just <recipe>` rather than inlining the tool command. Benefit: the single source of
  truth for how each stage is invoked stays in one place (the recipe). Cost: slight overhead from re-parsing the
  Justfile. Acceptable.
- `_setup` stays as an explicit dep so the first-run install noise (uv pip install…) happens exactly once, above the ✓
  stream. (Alternative: wrap `_setup` in `run_silent` too. Minor, probably not worth it since `_setup` is near-silent
  after the first run.)
- Just's default fail-fast behavior (stop on first non-zero exit) gives us the right behavior automatically: the first
  `run_silent` that exits nonzero halts the recipe, so later stages never run.

### 4. Expected success output

```
✓ fmt (python)
✓ fmt (markdown)
✓ lint (keep-sorted)
✓ lint (ruff)
✓ lint (mypy)
✓ lint (pyscripts)
✓ lint (pyvision)
✓ test
```

Eight lines. Roughly 50 tokens. Versus the current ~1000+ lines for the same outcome.

### 5. Expected failure output (e.g. mypy fails)

```
✓ fmt (python)
✓ fmt (markdown)
✓ lint (keep-sorted)
✓ lint (ruff)
✗ lint (mypy)
src/sase/foo.py:42: error: Incompatible return value type ...
Found 1 error in 1 file (checked 250 source files)
error: Recipe `check` failed on line N with exit code 1
```

The agent sees exactly the failure it needs to fix, plus breadcrumbs about what did pass. `lint (pyscripts)`,
`lint (pyvision)`, and `test` are not run — their output cannot waste context because it never existed.

## Alternatives Considered

1. **Inline `run_silent` as a `bash`-snippet inside each recipe line.** More indirection per recipe, and the same
   wrapper logic gets duplicated in prose form across many lines. Rejected in favor of a single reusable script.

2. **Add a second recipe, e.g. `just check-agent`, and leave `just check` verbose.** Safer (fully additive, no surprise
   for existing workflows) but every agent and every CLAUDE.md / AGENTS.md reference already says `just check`. Changing
   two-dozen references is worse than changing one recipe. Humans who want verbose output can still run `just lint` /
   `just test` directly — nothing is lost.

3. **Silence at the tool-flag level instead** (pytest `-q`, mypy `--no- pretty`, ruff `--quiet`, etc.). The blog
   explicitly warns against this: every tool has different quiet flags, some don't have them, and you're trusting the
   tool's author to know what matters. The deterministic "capture everything, dump on failure" pattern is provably
   lossless and works uniformly across every tool we happen to wire into `check` now or later.

4. **Pytest `-x` / fail-fast.** The blog recommends it. Valid future tuning once the base pattern is in place; not part
   of this change.

## Files Touched

- **New**: `tools/run_silent` (shell script, ~25 lines, chmod +x).
- **Modified**: `Justfile`:
  - Add four private recipes: `_lint-ruff`, `_lint-mypy`, `_lint-pyscripts`, `_lint-pyvision` (bodies copy-pasted from
    existing `lint` recipe).
  - Rewrite `lint` recipe body to call the four private recipes + existing `lint-keep-sorted` (preserves current verbose
    UX for `just lint`).
  - Rewrite `check` recipe to call `tools/run_silent` per stage.

No other files touched. No changes to pyproject.toml, no changes to tool configs, no changes to vendored scripts.

## Validation Plan

After implementing, verify by running:

1. `just check` on a clean tree — expect 8 `✓` lines, exit 0.
2. Intentionally break something minor (add an unused import) and run `just check` — expect ✗ at the right stage with
   ruff's actual error, and no output from later stages.
3. `just lint` directly — expect current verbose behavior unchanged.
4. `just test -k some_test` — expect current verbose behavior unchanged (test recipe itself untouched beyond what
   `check` wraps it with).

## Open Questions

- Should `_setup`'s first-run uv-install output also be routed through `run_silent`? Nearly always a no-op, but a
  first-run on a fresh checkout dumps ~100 lines of pip-install output above the ✓ stream. Minor; can be a follow-up.
- Do we want `run_silent` to emit the ✗/✓ to stderr vs stdout? Blog uses stdout; I'd match that for parity and
  simplicity.
