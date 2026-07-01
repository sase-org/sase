---
create_time: 2026-07-01 07:03:07
status: done
prompt: sdd/prompts/202607/init_skip_non_project_dirs.md
---
# Plan: `sase init` should not scaffold project files in non-project directories

## Problem

`sase init` (and its `--check` variant) treats the current working directory as a project root unconditionally. When run
from a directory that is not a version-controlled project — most commonly the user's home directory (`~`) — it proposes
to scaffold project-only resources into that directory:

- **SDD**: creates `sase.yml` with `sdd.version_controlled: true` and a full `sdd/` tree (`sdd/README.md`,
  `sdd/tales/README.md`, `sdd/epics/…`, the directory-map PNG, etc.).
- **Memory**: writes a _project_ memory root at the cwd — `./AGENTS.md`, `./CLAUDE.md` provider shim,
  `./memory/sase.md`, and provider instruction shims — as if the home directory were a checked-out project, and then
  tries to `git commit`/`push` those files.

Observed today from `~`:

```
Needs attention:
  run  init memory  refresh 6 memory files and provider shims
    - update    memory/sase.md  generated SASE memory
    - overwrite AGENTS.md  managed AGENTS.md
    - overwrite CLAUDE.md  provider instruction shim
    ... 3 more actions
  run  init sdd     enable version-controlled SDD and create SDD README files and directory map
    - create    sase.yml  enable sdd.version_controlled
    - create    sdd/README.md  top-level README
    - create    sdd/tales/README.md  directory README
    ... 5 more actions
```

None of these belong in a non-project directory.

## Desired behavior

Decide whether the current directory is a **project directory** by looking for VCS indicators (walking up from cwd for
`.git`/`.hg`, etc.). Then:

- **In a project directory** (VCS found): behavior is unchanged from today.
- **Outside a project directory** (no VCS): `sase init` should _only_ initialize the user's **home directory**
  resources. Concretely:
  - **SDD init is skipped entirely** — never create `sase.yml`/`sdd/` in a non-project dir.
  - **Memory init runs the home root only** — it initializes the home-level managed files (via chezmoi source when
    `use_chezmoi`, else directly under `~`) and does **not** create or commit a project memory root at the cwd.
  - **Skills init runs as usual** — skill deployment targets global/managed locations and is not tied to a project
    directory.

The `--check` output should reflect this: from `~`, SDD no longer appears, and memory only reports genuine
home-directory drift.

## Behavior matrix

| Step   | Project directory (VCS found)           | Non-project directory (no VCS)                              |
| ------ | --------------------------------------- | ----------------------------------------------------------- |
| memory | project root (cwd) **+** home root      | home root **only** (no project root, no project git commit) |
| sdd    | scaffold `sase.yml` + `sdd/` at project | **skipped** (not applicable)                                |
| skills | deploy managed skills                   | deploy managed skills (unchanged)                           |

## Design

### 1. Project-directory detection (reuse existing VCS provider)

A canonical detector already exists and is the right abstraction:

- `src/sase/vcs_provider/_registry.py`
  - `detect_vcs(cwd) -> str | None` — walks up from `cwd` for plugin VCS markers, then `.git`; returns `"github"` /
    `"bare_git"` / `"hg"` / `None`.
  - `detect_vcs_family(cwd) -> str | None` — collapses git variants; returns `"git"` / `"hg"` / `None`.

Add a small predicate (e.g. `is_project_directory(cwd: Path | str | None = None) -> bool`) that returns
`detect_vcs_family(cwd) is not None`, defaulting `cwd` to `Path.cwd()`. This becomes the single source of truth for the
gating and keeps the "look for VCS indicators" policy in one place. Place it where the init handlers can share it (e.g.
a new `src/sase/main/init_project_scope.py`, or alongside the memory-init config helpers).

Rationale for reusing `vcs_provider`: it already handles the `.git`-as-a-file case (submodules/worktrees),
plugin-provided VCS types (e.g. `.hg`), and the walk-up. We avoid a second, divergent notion of "is this a repo."

### 2. Gate the SDD step

SDD is inherently project-scoped (a version-controlled SDD tree tied to a repo). Make it "not applicable" outside a
project directory in **both** entry points so bare `sase init` and explicit `sase init sdd` / `sase sdd init` behave
consistently:

- **Bare `sase init` / `sase init --check`** (`init_onboarding.py` / `init_registry.py`): filter the SDD spec out of the
  active spec list when `not is_project_directory()`. The cleanest seam is where `iter_init_command_specs()` results are
  consumed by `run_init_onboarding` / `run_init_check` — build the spec list, then drop `sdd` when not in a project
  directory. This keeps SDD from showing up under "Needs attention" at all, rather than appearing as a misleading "up to
  date" or "blocker" row.
- **Explicit `sase init sdd` / `sase sdd init`** (`sdd_handler.py::run_sdd_init` / `plan_sdd_init`): short-circuit with
  a clear, non-scaffolding outcome when not in a project directory — print a message like
  `sase init sdd: not a project directory (no VCS found); skipping SDD initialization` and return non-zero (so scripting
  notices), without writing `sase.yml` or `sdd/`.

### 3. Gate the memory step (home-only mode)

In `init_memory_handler.py`, thread the project-directory status into memory planning and execution so that, when not in
a project directory, only the home root is planned/applied and no project git commit is attempted:

- `_load_memory_inputs()` / `_MemoryInitInputs`: record `is_project_dir` (from the new predicate against
  `project_root = Path.cwd()`).
- `_memory_root_plans()`: return only the home-root plan when `not is_project_dir` (skip the `project_root` plan). Today
  it always returns `(project_plan, home_plan)`.
- `run_init_memory()`:
  - skip `_initialize_memory_root(project_root, …)` when not a project dir;
  - skip `_capture_pre_init_git_state()` and `_deploy_to_project_repo(...)` (there is no project repo to commit to —
    today this path errors with "not a git repo");
  - keep the home-root initialization and the chezmoi deploy of home-root paths.
- `plan_init_memory()`: unchanged apart from consuming the filtered `_memory_root_plans()`.

Note on the non-chezmoi case: when `use_chezmoi` is false and cwd is `~`, the home root is `Path.home()` (== cwd), so
home-only mode still initializes the home directory's `AGENTS.md`/`CLAUDE.md`/`memory/sase.md` directly — exactly the
"just initialize the home directory" intent — while no longer duplicating them via a separate "project" root.

### 4. Skills step

No change. Skills deployment is global/managed and already independent of a project directory (it is reported "up to
date" in the example).

## Files likely to change

- `src/sase/vcs_provider/_registry.py` — (optionally) expose/`__all__` the family detector, or leave as-is and import
  directly.
- `src/sase/main/init_project_scope.py` _(new)_ — `is_project_directory()` predicate.
- `src/sase/main/init_registry.py` and/or `src/sase/main/init_onboarding.py` — filter the SDD spec out when not in a
  project directory.
- `src/sase/main/sdd_handler.py` — short-circuit `run_sdd_init` / `plan_sdd_init` outside a project directory (covers
  explicit `sase init sdd` and `sase sdd init`).
- `src/sase/main/init_memory_handler.py` — home-only memory mode outside a project dir.

## Edge cases & decisions

- **Home directory that is itself a git repo.** If `~` (or an ancestor) is a git working tree, `detect_vcs` returns
  non-`None` and the directory is treated as a project — matching the user's stated "look for VCS indicators" policy.
  Flagging this as a known consequence; if undesired, a follow-up could special-case `Path.home()`, but that is
  intentionally out of scope here.
- **Running in a subdirectory of a repo.** `detect_vcs` walks up, so any dir inside a repo counts as a project
  directory. This preserves today's behavior (init anchors on cwd, not the repo root). Re-anchoring init to the VCS root
  is a separate concern and **out of scope**.
- **Exit codes.** Bare `sase init --check` from a non-project dir should return `0` when the home directory is up to
  date (SDD no longer contributes drift). Explicit `sase init sdd` from a non-project dir returns non-zero with a clear
  "skipping" message.
- **Rust core boundary.** VCS detection already lives in the Python `vcs_provider` package (not `sase-core`); the new
  predicate is a thin wrapper over it, and the gating is CLI/ onboarding orchestration — presentation-layer glue that
  the boundary explicitly allows to stay in Python. No `sase-core` wire/API/binding change is required.

## Testing

Extend `tests/main/test_init_*.py`:

- **SDD**: `plan_sdd_init` / `run_sdd_init` in a `tmp_path` **without** `.git` → no `sase.yml`/`sdd/` written, clear
  "skipping" message, non-zero from the explicit runner; **with** a `.git` marker → unchanged scaffolding behavior.
- **Onboarding**: bare `sase init --check` (via `run_init_check`) in a non-project `tmp_path` → SDD spec absent from the
  rendered plans; in a project `tmp_path` → SDD present.
- **Memory**: `plan_init_memory` / `run_init_memory` in a non-project `tmp_path` → only the home root is planned/applied
  and no project git commit is attempted; in a project `tmp_path` (with `.git`) → project + home roots as today.
- Prefer injecting the VCS status via a `.git` marker in `tmp_path` (matches how `detect_vcs` probes) so tests exercise
  the real detector rather than mocking it.

Run `just check` (after `just install`) before wrapping up.

## Out of scope / possible follow-ups

- Re-anchoring `sase init` to the VCS root when run from a repo subdirectory.
- Special-casing a home directory that is itself under version control.
- Moving VCS/project detection into `sase-core` (currently Python-only by existing design).
