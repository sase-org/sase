---
create_time: 2026-05-22 21:58:04
status: done
prompt: sdd/prompts/202605/sase_init_onboarding.md
bead_id: sase-3y
tier: epic
---
# `sase init` Onboarding Implementation Plan

## Objective

Implement bare `sase init` as a polished onboarding/check command inspired by
`sdd/research/202605/sase_init_onboarding.md`.

The final behavior:

- `sase init` with no subcommand runs a read-only initialization check first.
- If everything is current, it prints a concise, useful "already initialized" message and writes nothing.
- If work is needed, it shows a clear grouped summary by subcommand and prompts once per needed subcommand.
- `sase init --yes` runs every needed initializer without prompting.
- `sase init --check` reports drift without writing and exits non-zero when any initializer would change files.
- Existing explicit subcommands continue to work: `sase init memory`, `sase init sdd`, and `sase init skills`.

The command should feel deliberate and well-designed. Use Rich for restrained terminal structure: a compact header,
stable aligned sections, subdued colors, and readable action summaries. Avoid noisy decoration, emoji, nested prompts,
or huge walls of paths by default.

## Design Principles

- Planning is read-only. No planner may create directories, write files, stage git changes, commit, push, or run
  `chezmoi`.
- Apply paths remain the source of truth for writing. Bare onboarding calls the same apply functions as explicit
  subcommands, with only prompt/deploy policy adjusted.
- Each handler should expose a pure `run_*()` function returning an exit code. The existing `handle_*()` wrappers may
  keep calling `sys.exit()` for CLI compatibility.
- Do not detect drift by shelling out to `sase init <subcommand> --dry-run`. Current dry-run coverage is incomplete and
  would duplicate config and prompt behavior.
- Keep v1 deploy behavior conservative. Do not introduce coordinated multi-command git/chezmoi deploy in the first
  implementation unless a later phase explicitly scopes it. Sequential explicit apply behavior is easier to verify and
  preserves existing side effects.
- Keep advanced flags off bare `sase init` for v1 except `--yes` and `--check`. `--no-commit`, `--no-push`, and
  `--no-apply` have different meanings across subcommands today.

## Proposed Shared Model

Add `src/sase/main/init_plan.py`:

```python
@dataclass(frozen=True)
class InitAction:
    path: Path
    operation: Literal["create", "update", "overwrite", "validate", "deploy"]
    detail: str = ""


@dataclass(frozen=True)
class InitPlan:
    command: str
    label: str
    summary: str
    actions: tuple[InitAction, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool: ...

    @property
    def runnable(self) -> bool: ...
```

Add `src/sase/main/init_registry.py`:

```python
@dataclass(frozen=True)
class InitCommandSpec:
    name: str
    label: str
    plan: Callable[[argparse.Namespace], InitPlan]
    run: Callable[[argparse.Namespace], int]
```

The registry order is:

1. `memory`
2. `sdd`
3. `skills`

## User Experience

Target interactive output shape:

```text
SASE initialization check

Up to date:
  ok  init sdd

Needs attention:
  run init memory  update 2 memory files and 4 provider shims
  run init skills  write 5 provider skill files

Run `sase init memory` now? This may commit and push generated project memory changes. [y/N]
Run `sase init skills --force` now? [y/N]
```

Target no-op output:

```text
SASE is initialized. No init subcommands need to run.
Checked: memory, sdd, skills.
```

Target non-TTY drift output:

```text
SASE initialization check

Needs attention:
  run init memory  update 2 memory files

Run `sase init --yes` to apply these changes.
```

Exit code policy:

- `0`: no changes needed, or all selected/automatic applies succeed.
- `1`: `--check` found drift, non-TTY found drift without `--yes`, a planner blocker exists, or an apply fails.

## Phase 1: Foundation And Onboarding Shell

Owner: one agent.

Write scope:

- `src/sase/main/parser_init.py`
- `src/sase/main/entry.py`
- New `src/sase/main/init_plan.py`
- New `src/sase/main/init_registry.py`
- New `src/sase/main/init_onboarding.py`
- Focused parser/onboarding tests, preferably `tests/main/test_init_onboarding.py`

Implementation:

- Make the init subparser optional in `register_init_parser()`.
- Add bare-init flags:
  - `-y`, `--yes`
  - `--check`
- Add shared plan/spec dataclasses.
- Add onboarding orchestration that accepts an injectable tuple of `InitCommandSpec` objects for tests.
- Add a Rich-backed renderer with deterministic non-color text under captured pytest output.
- Add prompt handling that asks once per runnable changed plan and skips nested prompts by passing force-like args only
  where a later phase wires that behavior.
- Add entry dispatch for `args.init_subcommand is None`.
- Preserve the existing explicit subcommand dispatch for now.

Tests:

- Parser accepts `["init"]`, `["init", "--yes"]`, and `["init", "--check"]`.
- `["init", "--help"]` still exits 0 and lists `memory`, `sdd`, and `skills`.
- Stub all planners as empty: no apply calls, no-op message printed, exit 0.
- Stub two changed plans and answer yes/no: only confirmed run function is called.
- Stub changed plan in non-TTY without `--yes`: summary prints, no prompt, exit 1.
- Stub changed plan with `--check`: no run calls, exit 1.
- Stub blocker: blocker prints and exit 1.

Acceptance:

- The foundation can be tested without real memory/sdd/skills planners.
- Existing explicit subcommand tests still pass.
- No real filesystem initialization happens in foundation tests.

## Phase 2: SDD Plan/Apply Split

Owner: one agent.

Write scope:

- `src/sase/sdd/files.py`
- `src/sase/main/sdd_handler.py`
- `src/sase/main/init_registry.py`
- SDD planner tests in `tests/test_sdd_paths.py` or a new `tests/main/test_init_sdd_plan.py`
- Any affected `tests/main/test_sdd_handler.py` expectations

Implementation:

- Add pure SDD expected-output helpers:
  - top-level `sdd/README.md` path and text
  - directory README path/text pairs
  - `assets/sdd-directory-map.png` path and canonical bytes
- Add `plan_sdd_init(args) -> InitPlan` that compares text and bytes without creating directories.
- Refactor `write_sdd_readme()` to use the same expected-output helpers for apply.
- Add `run_sdd_init(args) -> int` and keep `_handle_init()` as a `sys.exit(run_sdd_init(args))` wrapper.
- Register SDD in the onboarding registry.

Tests:

- Missing SDD tree reports create actions and does not create `sdd/`.
- Stale README and directory README report update actions.
- Corrupt PNG reports an update action using byte comparison.
- Identical README/directory README/PNG produces an empty plan.
- Existing `sase sdd init` and `sase init sdd` behavior remains unchanged.

Acceptance:

- Bare `sase init --check` can accurately report SDD drift when only the SDD planner is real.
- Running explicit SDD init remains idempotent.

## Phase 3: Memory Plan/Apply Split

Owner: one agent.

Write scope:

- `src/sase/main/init_memory/roots.py`
- `src/sase/main/init_memory/inventory.py`
- `src/sase/main/init_memory/models.py`
- `src/sase/main/init_memory_handler.py`
- `src/sase/main/init_registry.py`
- Focused memory planner tests, likely extending `tests/main/test_init_memory_handler.py`

Implementation:

- Split memory root logic into:
  - render expected files
  - compare expected files against disk
  - apply expected files
- Planning must not create `memory/short/`, `memory/long/`, `AGENTS.md`, or provider shim files.
- Add an overlay-aware validation path so generated memory files can be treated as present for
  `unreferenced_memory_files()` without writing them first.
- Add `plan_init_memory(args) -> InitPlan`.
- Add `run_init_memory(args) -> int`; keep `handle_init_memory_command()` as a wrapper.
- Preserve existing project commit/push behavior for explicit `sase init memory`.
- For onboarding, the prompt text must mention that applying memory may commit and push generated project memory.
- Register memory in the onboarding registry.

Tests:

- Missing memory tree reports create actions without creating directories.
- Identical generated memory produces an empty plan.
- Stale provider shim reports update/overwrite.
- Existing user `AGENTS.md` is not overwritten and is not reported as an update.
- Missing `AGENTS.md` reports create.
- Invalid sibling config returns blockers and writes nothing.
- Unreferenced-memory validation works against rendered overlay.
- `run_init_memory()` returns int and existing wrapper still raises `SystemExit` in legacy tests.

Acceptance:

- The memory planner is read-only on a fresh tree.
- Existing memory init behavior and commit-path tests keep passing.

## Phase 4: Skills Plan/Apply Split

Owner: one agent.

Write scope:

- `src/sase/main/init_skills_handler.py`
- `src/sase/main/init_registry.py`
- Existing init skills tests and new planner tests under `tests/main/`

Implementation:

- Extract a shared skill target renderer that yields target path plus exact output bytes/text for every selected
  provider/skill target.
- The planner must use the same Jinja2 and Prettier formatting path as apply.
- Add `plan_init_skills(args) -> InitPlan`:
  - missing target = create
  - existing different target = overwrite/update
  - existing identical target = no action
- Add `run_init_skills(args) -> int`; keep `handle_init_skills_command()` as a wrapper.
- Keep explicit `--dry-run` behavior for backward compatibility unless tests intentionally expand it.
- In onboarding apply, force overwrites after the user confirms `init skills` to avoid nested per-file prompts.
- Register skills in the onboarding registry.

Tests:

- Missing target reports create.
- Identical rendered target reports no action.
- Differing target reports overwrite/update.
- Provider filtering is honored by the planner.
- Prettier-present and prettier-missing cases keep plan/apply bytes aligned.
- Non-TTY explicit `init skills` still skips existing files without `--force`.
- Onboarding-confirmed skills run uses force semantics and does not prompt per file.

Acceptance:

- `sase init --check` no longer over-reports skills that are already byte-identical.
- Existing `init skills` deploy and formatting tests pass after wrapper refactor.

## Phase 5: End-To-End Polish And Integration

Owner: one agent.

Write scope:

- `src/sase/main/init_onboarding.py`
- `src/sase/main/init_registry.py`
- `src/sase/main/parser_init.py`
- Integration and output snapshot tests under `tests/main/`
- Help/docs snippets if the repo already has a concise CLI docs location

Implementation:

- Wire the full registry: memory, sdd, skills.
- Finalize Rich output:
  - compact title
  - "Up to date" and "Needs attention" groups
  - concise summary line per command
  - path detail capped by default, with counts making the result clear
  - warnings/blockers visibly separated from normal work
- Ensure captured output has stable plain text for pytest.
- Ensure non-TTY behavior never blocks.
- Ensure `--yes` applies in registry order and stops/returns non-zero if a prior apply fails.
- Ensure `--check` never calls apply functions.
- Keep `sase init --help` clear that advanced deploy controls live on explicit subcommands.

Tests:

- Full no-op path with all real planners stubbed or fixture-backed.
- Full drift path with all three plans changed, including prompt order.
- `--yes` runs memory, sdd, skills in order.
- Apply failure stops or reports failure deterministically.
- Golden output snapshot for the "needs attention" summary.
- CLI-level `main()` test for bare `sase init`.

Acceptance:

- Bare `sase init` is enabled for all three current subcommands.
- The command output is polished and readable in both terminal and captured/plain output.
- `just check` passes.

## Phase 6: Optional Deploy Consolidation Follow-Up

Owner: separate follow-up agent only after v1 lands.

Write scope:

- Shared deploy helper module, likely `src/sase/main/_init_chezmoi_deploy.py`
- `src/sase/main/init_memory_handler.py`
- `src/sase/main/init_skills_handler.py`
- Additional onboarding integration tests

Implementation:

- Extract duplicated chezmoi git/push/apply behavior.
- Add an internal deploy-deferral mode so onboarding can write all selected home/chezmoi files first and deploy once.
- Keep explicit subcommands behavior unchanged.
- Consider a single bare-init `--no-deploy` only after behavior is coherent across memory and skills.

Acceptance:

- The user sees at most one chezmoi commit/push/apply cycle during `sase init --yes`.
- No explicit subcommand regressions.

## Verification For Every Implementation Phase

- Run `just install` before repo checks if the workspace has not already been installed.
- Run targeted pytest for changed areas first.
- Run `just check` before completing any phase with code changes.
- Do not modify files under `memory/` unless the user explicitly approves it.
- Do not commit unless explicitly asked or a SASE post-completion commit hook requires it.

## Suggested Agent Handoff Order

1. Foundation/onboarding shell.
2. SDD planner.
3. Memory planner.
4. Skills planner.
5. Full integration and output polish.
6. Optional deploy consolidation.

This order keeps early work low-risk, lets each later agent own one initializer, and leaves the visible command polish
until all real plan data is available.
