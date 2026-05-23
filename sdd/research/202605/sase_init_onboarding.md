# `sase init` Onboarding Research

Date: 2026-05-23

## Goal

Make bare `sase init` launch an onboarding experience:

- If all initialization work is already up to date, print a useful message and make no changes.
- Otherwise, detect each initialization subcommand that would produce changes.
- Prompt the user for each needed subcommand before running it.
- Keep existing explicit subcommands (`sase init memory`, `sase init sdd`, `sase init skills`) working as direct
  non-onboarding entry points.

## Current State

`sase init` is currently an argparse command group whose subparser is required. `src/sase/main/parser_init.py` registers
`init_subcommand` with `required=True`, so bare `sase init` fails in argparse before `src/sase/main/entry.py` can
dispatch an onboarding handler.

Current init subcommands:

| Subcommand | Handler | Current write behavior | Current dry-run/check quality |
| ---------- | ------- | ---------------------- | ----------------------------- |
| `memory` | `src/sase/main/init_memory_handler.py` | Generates project memory, home memory, provider shims, validates references, then commits/pushes project changes by default and deploys chezmoi home changes when enabled. | No dry-run mode. Helpers know which files changed but only after writing. `_write_text_if_changed()` and `MemoryRootResult.written_paths` already encode "what was different"; planning can reuse that comparison without touching disk. |
| `sdd` | `src/sase/main/sdd_handler.py` -> `sase.sdd.files.write_sdd_readme` | Writes the top-level SDD README, the per-directory READMEs from `SDD_DIRECTORY_README_CONTENT`, and copies the binary `sdd-directory-map.png` asset from `sase.sdd` package resources every time. Idempotent in content, but does not report whether bytes changed. | No dry-run/check mode. The asset is binary (PNG) so plan-time comparison must hash bytes, not compare text. |
| `skills` | `src/sase/main/init_skills_handler.py` | Renders skill files for provider targets, prompts for overwrites unless `--force`, then optionally commits/pushes/applies chezmoi changes. Already has an in-handler "unchanged, skipping" branch inside `_prompt_overwrite()` for the interactive path. | Has `--dry-run`, but it prints target paths for all matching skills. It does not compare rendered output with existing target content, so it cannot answer "would produce changes". |

Related existing research:

- `sdd/research/202604/init_skills_command.md` explains the original skill generation design.
- `sdd/research/202605/sase_init_hooks.md` recommends reusing the `init skills` CLI shape for future hook
  initialization. It is not currently wired into `sase init`.
- `sdd/epics/202605/init_memory.md` and `sdd/tales/202605/init_memory_auto_commit.md` document why `init memory` now
  has side effects beyond file writes, especially project auto-commit/push.
- `sdd/tales/202605/init_sdd_alias.md` documents `sase init sdd` as a parser-level alias for `sase sdd init`.

## Important Findings

### Bare `sase init` Needs Parser Support First

Change `register_init_parser()` so the init subparser is not required:

```python
init_subparsers = init_parser.add_subparsers(
    dest="init_subcommand",
    help="Initialization subcommands",
    required=False,
)
```

Then `entry.py` can dispatch `args.init_subcommand is None` to a new onboarding handler. This keeps all explicit
subcommands unchanged while giving bare `sase init` a real path.

Note: making the subparser non-required does not change `sase init --help` output — argparse still prints the subcommand
list, which is what we want. Confirm with a parser unit test that `["init", "--help"]` still exits 0 and lists
`memory|sdd|skills`. Bare `sase init` should also fall back to printing this help block if there are zero registered
init subcommands at runtime (a safety net for plugin-discovered registries; see "Plugin-discovered init subcommands"
below).

### Existing Handlers Call `sys.exit()` Mid-Flow

Both `handle_init_memory_command` and `handle_init_skills_command` call `sys.exit(exit_code)` themselves, and
`handle_sdd_command` calls `sys.exit(0)` after `_handle_init`. An onboarding coordinator that imports these handlers
directly will be terminated by the first subcommand that runs. Two options:

1. Refactor each handler so the public CLI entry is a thin wrapper that calls `sys.exit()` around a pure
   `run_*()` function returning an `int` exit code. The onboarding coordinator calls the pure functions and aggregates
   exit codes itself. This is the recommended split because it also makes unit testing trivial.
2. Wrap onboarding subcommand calls in a `try/except SystemExit` and read `.code`. Workable but obscures intent and is
   easy to regress when handler internals change.

Option 1 also unblocks the plan/apply split below: the planner becomes a third pure function (`plan_*()`) alongside
`run_*()`.

### Do Not Shell Out To Subcommands For Detection

The onboarding flow should not detect work by spawning `sase init <subcommand> --dry-run`:

- `memory` has no dry-run mode and currently commits/pushes by default.
- `sdd` has no dry-run mode.
- `skills --dry-run` over-reports because it lists target paths without checking whether content differs.
- Shelling out would duplicate config loading, prompt behavior, and exit handling.

The better architecture is to factor each initializer into a small planning API that both the explicit command and the
onboarding command can call.

### The Core Missing Abstraction Is An Init Plan

Introduce a lightweight shared model, probably in a new module such as `src/sase/main/init_plan.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

@dataclass(frozen=True)
class InitAction:
    path: Path
    operation: str  # "create", "update", "overwrite", "deploy", "validate"
    detail: str = ""

@dataclass(frozen=True)
class InitPlan:
    command: str
    label: str
    summary: str
    actions: tuple[InitAction, ...]
    warnings: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.actions)
```

Each init module should expose a `plan_*()` function that returns `InitPlan`, plus an apply function used by the current
handler. The onboarding handler can then:

1. Build plans for all registered init subcommands.
2. Print "SASE is already initialized" when no plan has changes.
3. For each plan with changes, prompt whether to run the corresponding subcommand.
4. Run the same apply path as the explicit subcommand, not a copy of it.

### Planning Must Be Read-Only

The plan functions should not create directories, write files, stage commits, or invoke chezmoi. They should calculate
expected content and compare it to the filesystem.

Specific traps to avoid in the planner:

- `initialize_memory_root()` currently `.mkdir(parents=True, exist_ok=True)` on `memory/short/` and `memory/long/`
  **before** any write check. The planner must not do this — directory creation is itself a filesystem mutation that
  changes git status. Move the `mkdir` calls into the apply path, or have the planner enumerate would-be paths from
  pure values.
- `write_sdd_readme()` copies a binary PNG asset (`sdd-directory-map.png`) from `sase.sdd` package resources. Plan-time
  comparison must hash bytes (e.g. `hashlib.sha256`) — a text compare will misreport or crash on the binary content.
  Reuse `resources.as_file(...)` to read the canonical bytes once and cache the hash.
- `_render_skill()` runs Jinja2 + prettier (via `format_with_prettier`). If prettier is missing the renderer falls back
  to unformatted output and warns once. The planner must invoke the exact same render+format path so plan and apply
  agree on bytes. Planner that bypasses prettier will mis-report drift for users who have prettier installed.
- The `init memory` flow validates "unreferenced memory files" *after* writing. To predict validation results without
  writing, the planner can build an in-memory overlay: render the expected `memory/short/sase.md`, `memory/README.md`,
  and provider shim contents, then run `unreferenced_memory_files()` against an overlay view (e.g. a temporary copy
  layered with the rendered content, or a small refactor of `_reachable_memory_files` to accept a "synthetic file
  contents" map).

Suggested per-subcommand plan changes:

| Subcommand | Planning approach |
| ---------- | ----------------- |
| `memory` | Refactor `initialize_memory_root()` into `render()` (returns `dict[Path, str]`), `plan()` (compares rendered output against disk), and `apply()` (mkdirs + writes). The current `_write_text_if_changed()` logic is close but planning must inspect expected paths without writing or creating directories. Run unreferenced-memory validation read-only against the current tree plus rendered generated files; report validation blockers as plan-level warnings before prompting. |
| `sdd` | Add helpers that return the expected README path/content, directory README path/content pairs, and the canonical asset bytes (with their hash). Compare text/bytes before writing. Refactor `write_sdd_readme()` to apply the plan. `_resolve_sdd_readme_path()` is already pure and can be reused as-is. |
| `skills` | Split rendering/target resolution from writing. For each generated target, render through the same Jinja2 + prettier pipeline and compare to existing content. Treat missing files and differing files as actions. Existing overwrite prompts can remain for explicit `init skills`; onboarding should invoke skills with `--force` semantics only after the user confirms the whole subcommand. |

## Recommended UX

For interactive TTY:

```text
SASE initialization check

Up to date:
  - init sdd

Needs attention:
  - init memory: update 2 project/home memory files
  - init skills: write 5 provider skill files

Run `sase init memory` now? [y/N]
Run `sase init skills --force` now? [y/N]
```

For already-initialized state:

```text
SASE is initialized. No init subcommands need to run.
Checked: memory, sdd, skills.
```

For non-TTY:

- Do not prompt.
- Print the same status summary.
- Exit `0` if nothing needs to run.
- Exit non-zero if there are needed actions and no explicit `--yes` was supplied, or provide a `--check` mode that
  exits non-zero on drift.

Useful flags for bare `sase init`:

| Flag | Recommendation |
| ---- | -------------- |
| `-y`, `--yes` | Run every needed initializer without prompting. This is useful for scripts and tests. |
| `--check` | Report needed init work and exit non-zero if anything would change. Do not prompt or write. |
| `--only {memory,sdd,skills}` | Optional, repeatable. Useful if the registry grows. Not required for the first version. |
| `--no-commit`, `--no-push`, `--no-apply` | Consider forwarding only to subcommands that support them. Be careful: `memory --no-commit` and `skills --no-commit` have different scopes today. |

## Coordinated Git / Chezmoi Deploys

Running `memory`, `sdd`, and `skills` back-to-back today produces redundant deploy work because each handler owns its
own commit/push/apply sequence:

- `init memory` commits/pushes to the **project repo** and (when `use_chezmoi`) commits to the chezmoi repo and runs
  `chezmoi apply --force`.
- `init skills` commits/pushes to the chezmoi repo and runs `chezmoi apply`.
- `init sdd` does not commit at all (the asset/README write is unstaged).

If onboarding invokes all three sequentially, the user sees two separate chezmoi commit + push + apply cycles, with
the second one potentially blocked behind the first finishing a remote push. The onboarding coordinator should:

1. Extract the chezmoi deploy block (already duplicated between `init_memory_handler._deploy_to_chezmoi` and
   `init_skills_handler._deploy_to_chezmoi`) into a shared helper, e.g. `src/sase/main/_init_chezmoi_deploy.py`. Both
   `init_skills` and the proposed `init hooks` already plan to share this code (see
   `sdd/research/202605/sase_init_hooks.md`); folding `init memory` in at the same time avoids re-extracting later.
2. In onboarding, run each subcommand's `apply()` with `no_commit=True, no_push=True, no_apply=True` (or an equivalent
   "defer deploy" flag), accumulate the set of changed paths per repo, then run one project-repo commit/push and one
   chezmoi commit/push/apply at the end.
3. Project-repo handling has a wrinkle: only `init memory` currently writes inside the project repo, so the
   "coordinated deploy" really matters for the chezmoi side. Keep the project commit local to `init memory`'s apply for
   v1 unless `init sdd` or `init skills` start writing to the project repo too.

For the explicit subcommands, behavior should not change — only the onboarding coordinator should pass deploy-deferral
flags.

## Argument Forwarding And Flag Collisions

`init memory` and `init skills` both use `-C / --no-commit` for repo-shaped meaning, but the repos are different:

- `init memory --no-commit` skips the **project** repo commit/push and is silent about chezmoi.
- `init skills --no-commit` skips the **chezmoi** repo commit/push/apply sequence entirely.

If bare `sase init` forwards a single `--no-commit` flag to both, the resulting behavior is non-obvious. Recommended
v1 behavior:

- Do not expose `--no-commit` / `--no-push` / `--no-apply` on bare `sase init`. Users who want fine control should run
  the explicit subcommand.
- The onboarding coordinator implements coordinated deploy (above), so a single `--no-deploy` flag (or absence of
  `--yes`) can suppress all post-write side effects uniformly.
- Document the divergence in `sase init --help` epilog text.

## Plugin-discovered init subcommands

Today `entry.py` hard-codes the three init subcommands in an `if` chain. Future additions (`init hooks`, `init core`,
`init telegram`) could each need their own onboarding plug-in point. Two options:

1. **Module-level registry.** Each init module exposes `INIT_COMMAND_SPEC = InitCommandSpec(...)`, and `parser_init.py`
   + the onboarding coordinator import a known list of modules. Simple and easy to reason about for the in-repo case.
2. **Pluggy hook.** Add a `sase_init` hookspec that returns one or more `InitCommandSpec` entries. Provider plugins
   (and sibling repos like `sase-github`) can then register their own init subcommands without editing this repo. This
   matches the existing `sase_llm` plugin pattern from `iter_plugins()`.

For v1, option 1 is sufficient — there are only three subcommands and no external plugin currently registers init
work. The `InitCommandSpec` shape below is identical either way, so picking option 1 first does not block migrating to
pluggy later.

## Command Registry Shape

Avoid hard-coding onboarding order inside a long `if` chain in `entry.py`. A small registry keeps future additions such
as `init hooks` straightforward:

```python
@dataclass(frozen=True)
class InitCommandSpec:
    name: str
    label: str
    plan: Callable[[argparse.Namespace], InitPlan]
    apply: Callable[[argparse.Namespace], int]
```

Recommended order for the current commands:

1. `memory`
2. `sdd`
3. `skills`

Rationale: `memory` establishes agent/project context, `sdd` establishes durable docs scaffolding, and `skills` affects
provider home/chezmoi files. There is no hard dependency between them today, but this order matches user setup flow.

## Interaction With Existing Prompting

`init skills` already prompts per target when an existing file differs and `--force` is not set. Bare `sase init` should
not produce nested prompts like:

1. "Run init skills?"
2. "Overwrite this skill?"
3. "Overwrite that skill?"

Once onboarding has shown a clear plan and the user confirms the subcommand, the apply path should be deterministic.
The simplest implementation is for onboarding to run skills with force semantics after confirmation. The plan summary
must therefore show enough detail to justify that overwrite.

`init memory` currently auto-commits/pushes by default. The onboarding prompt should mention this when the memory plan
has actions:

```text
Run `sase init memory` now? This may commit and push generated project memory changes. [y/N]
```

## Prior Art

Common conventions from comparable interactive setup commands:

- **`pre-commit install`** is silent on a no-op repeat. `pre-commit install --install-hooks` prints "Pre-commit
  installed" only on first run. Onboarding should match this: a fully-initialized workspace produces one short line of
  output, not an empty one.
- **`cargo init`** errors out hard if the directory already has a `Cargo.toml`, rather than offering an
  interactive merge. SASE onboarding sits between these two extremes: per-subcommand prompts let the user opt in to
  each change without forcing an all-or-nothing decision.
- **`gh auth setup-git`** detects current state, prints what it will change, and asks one Y/N prompt per resource. That
  is the closest UX analog and what the per-subcommand prompt loop in this proposal mirrors.
- **`npm init` / `yarn init`** prompt for missing values rather than detecting drift. Not a good model for SASE
  onboarding because nothing in `init memory|sdd|skills` is value-driven — every input is filesystem-derived.
- **Ansible playbook --check mode** distinguishes "would change", "ok", "skipped". The `--check` flag in this proposal
  intentionally borrows that exit-non-zero-on-drift behavior for CI use.

The plan/apply split itself is an Ansible/Terraform pattern; we are not inventing it, just porting it to a CLI that
currently entangles the two.

## Testing Strategy

Add focused tests before broad end-to-end tests:

- Parser test: `parser.parse_args(["init"])` returns `command == "init"` and `init_subcommand is None`.
- Already-initialized onboarding test: stub all planners to return empty plans, assert useful message and no apply
  calls.
- Prompt test: two plans need changes; answer yes/no via patched `input()`, assert only selected apply functions run.
- Non-TTY test: needed plan actions cause a summary without blocking on `input()`.
- `--yes` test: all needed apply functions run in registry order.
- Plan tests for each subcommand:
  - `memory`: missing/generated/different files are reported without writing. Verify the planner does **not** create
    `memory/short/` or `memory/long/` directories on a fresh tree. Verify `unreferenced_memory_files` validation runs
    against the rendered overlay, not the un-touched filesystem.
  - `sdd`: stale README/asset/directory README content is reported; identical content is not. Use a hash-based
    comparison test for the binary `sdd-directory-map.png` (corrupt the asset by one byte and assert the planner flags
    it).
  - `skills`: existing identical rendered output is not reported; missing or differing target output is reported.
    Cover both prettier-available and prettier-missing paths so plan and apply agree on bytes either way.
- Handler-boundary tests:
  - `run_init_memory()`, `run_init_sdd()`, `run_init_skills()` return `int` exit codes (no `sys.exit`).
  - Onboarding coordinator with all three sub-applies in deploy-deferred mode invokes the shared chezmoi deploy helper
    exactly once.
- Snapshot test: golden output of the "needs attention" report for a tree missing all three resources, to lock in the
  user-visible format.

## Risks And Open Questions

- `memory` validation is the trickiest piece because generated files and reachability checks interact. A robust planner
  may need an in-memory overlay for generated file contents so it can predict post-apply validation without writing.
- Forwarding commit/deploy flags through bare `sase init` can be confusing because `memory` and `skills` use similar
  flag names for different repos. The first version can keep forwarding minimal and document explicit subcommands for
  advanced control.
- `skills` rendering may call Prettier. Planning should render exactly the same bytes as apply, including the same
  fallback warning when Prettier is missing, or planner/apply drift will cause confusing onboarding output.
- If future `init hooks` lands, it should plug into the same registry with a real plan function rather than relying on
  its own dry-run output.
- `_load_skill_xprompts()` builds its catalog by calling `get_all_xprompts(project="")`. That call traverses user
  config overlays and can be measurably slow on machines with many xprompts. Onboarding builds plans for every
  registered subcommand on every invocation, so the no-op `sase init` path will pay this cost even when nothing needs
  to change. Consider a cheap "is anything obviously missing?" pre-check (e.g. existence of
  `~/.{provider}/skills/`) before invoking the full skills planner. The same applies to memory's reachability
  validation on large memory trees.
- Concurrency: the explicit subcommands already race on chezmoi when two agents run in parallel (see
  `sdd/research/202605/sase_init_hooks.md` "Concurrency and Atomicity"). Bare `sase init` does not make this worse, but
  the shared chezmoi deploy helper should add `fcntl.flock` around its commit/apply path before being relied on by
  onboarding-from-multiple-agents.
- `sase init` is also a likely first-command-after-clone target. The coordinator should not assume a `git remote` is
  configured — `_deploy_to_project_repo()` will fail on `git push` for a fresh local-only clone. Either degrade
  gracefully (skip push, print a hint) or require `--no-deploy` for that case.

## Recommendation

Implement bare `sase init` as a thin onboarding coordinator over read-only per-subcommand plans. Do not add special
onboarding-only detection logic that shells out or approximates file changes. The implementation work should start by
factoring `memory`, `sdd`, and `skills` into reusable plan/apply layers, then add the bare `init` parser dispatch and
interactive coordinator.

This makes the up-to-date case reliable, avoids accidental writes during detection, and gives future init subcommands a
clear contract: "tell onboarding what you would change, then apply exactly that."
