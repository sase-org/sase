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
| `memory` | `src/sase/main/init_memory_handler.py` | Generates project memory, home memory, provider shims, validates references, then commits/pushes project changes by default and deploys chezmoi home changes when enabled. | No dry-run mode. Low-level helpers know which files changed, but only after writing. |
| `sdd` | `src/sase/main/sdd_handler.py` -> `sase.sdd.files.write_sdd_readme` | Writes SDD README files and directory map asset every time. Idempotent in content, but it does not report whether bytes changed. | No dry-run/check mode. |
| `skills` | `src/sase/main/init_skills_handler.py` | Renders skill files for provider targets, prompts for overwrites unless `--force`, then optionally commits/pushes/applies chezmoi changes. | Has `--dry-run`, but it prints target paths for all matching skills. It does not compare rendered output with existing target content, so it cannot answer "would produce changes". |

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

Suggested per-subcommand plan changes:

| Subcommand | Planning approach |
| ---------- | ----------------- |
| `memory` | Refactor `initialize_memory_root()` into render/plan/apply steps. The current `_write_text_if_changed()` logic is close, but planning must inspect expected paths without writing. Also plan missing directories as part of creating the files rather than as standalone actions. Run unreferenced-memory validation read-only against the current tree plus expected generated files if practical; otherwise report validation blockers before prompting. |
| `sdd` | Add helpers that return the expected README path/content, directory README path/content pairs, and asset bytes. Compare text/bytes before writing. Refactor `write_sdd_readme()` to apply the plan. |
| `skills` | Split rendering/target resolution from writing. For each generated target, compare rendered content to existing content. Treat missing files and differing files as actions. Existing overwrite prompts can remain for explicit `init skills`; onboarding should likely invoke with an apply mode equivalent to `--force` only after the user confirms the whole subcommand. |

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

## Testing Strategy

Add focused tests before broad end-to-end tests:

- Parser test: `parser.parse_args(["init"])` returns `command == "init"` and `init_subcommand is None`.
- Already-initialized onboarding test: stub all planners to return empty plans, assert useful message and no apply
  calls.
- Prompt test: two plans need changes; answer yes/no via patched `input()`, assert only selected apply functions run.
- Non-TTY test: needed plan actions cause a summary without blocking on `input()`.
- `--yes` test: all needed apply functions run in registry order.
- Plan tests for each subcommand:
  - `memory`: missing/generated/different files are reported without writing.
  - `sdd`: stale README/asset/directory README content is reported; identical content is not.
  - `skills`: existing identical rendered output is not reported; missing or differing target output is reported.

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

## Recommendation

Implement bare `sase init` as a thin onboarding coordinator over read-only per-subcommand plans. Do not add special
onboarding-only detection logic that shells out or approximates file changes. The implementation work should start by
factoring `memory`, `sdd`, and `skills` into reusable plan/apply layers, then add the bare `init` parser dispatch and
interactive coordinator.

This makes the up-to-date case reliable, avoids accidental writes during detection, and gives future init subcommands a
clear contract: "tell onboarding what you would change, then apply exactly that."
