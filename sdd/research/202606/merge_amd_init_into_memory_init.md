# Research: Merging `sase amd init` into `sase memory init`

**Date:** 2026-06-26
**Question:** Should the functionality of `sase amd init` be folded into `sase memory init`?
**Recommendation (TL;DR):** **No — do not merge / delete `amd init`.** The two commands already share their
lower-level engine (`memory init` reuses the `sase.amd` package), so the practical duplication users worry about is
mostly cosmetic. A hard merge would force `memory init` to absorb three AMD-only concerns it does *not* currently handle
(managed **home/chezmoi** `AGENTS.md` generation, legacy single-file **migration**, and standalone **shim repair**),
turning a memory command into a misnamed catch-all. If the real goal is "one command to rule them all," that already
exists: bare **`sase init`** orchestrates AMD → memory → SDD → skills. A lighter-touch consolidation (have `memory init`
delegate the *whole* project-root AGENTS.md/shim concern to AMD instead of partially reimplementing the sync) is the
better target if you want to reduce surface area. Details and alternatives below.

---

## 1. What "AMD" is and what `sase amd init` does

**AMD = Agent Markdown Documents.** It is the initialization surface for agent instruction files: the root `AGENTS.md`
plus the provider shims `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md` (and their `*.md.tmpl` chezmoi variants).

**Where it lives (all Python; no Rust core):**

- CLI parser: `src/sase/main/parser_amd.py` (`amd init`, lines ~36-69; flags lines 8-33)
- Handler: `src/sase/main/amd_handler.py` (`_handle_amd_init_command`, also `handle_init_amd_command` for the
  `sase init amd` alias)
- Facade: `src/sase/amd/cli.py` → `run_amd_init`
- Engine: `src/sase/amd/_runner.py`, `_planner.py`, `_memory.py`, `_config.py`, `_shared.py`, `constants.py`
- Docs: `docs/init.md` §"Agent Markdown Documents" (lines 96-133)
- Tests: `tests/main/test_amd_init.py` (631 lines), `tests/main/test_amd_init_commit.py` (425 lines)
- Origin: bead **sase-44** "sase amd and Project-Managed AGENTS.md" (closed), phases sase-44.2 (Init Engine),
  sase-44.4 (`sase amd list`)

**Behavior:**

1. **Managed `AGENTS.md`** — When the selected root's *own* `./sase.yml` sets `amd_h1_title`, AMD writes a managed
   `AGENTS.md` with marker-delimited short-memory (Tier 1) and long-memory (Tier 2) sections derived from `memory/`.
2. **Provider shims** — Always creates/repairs `CLAUDE.md`/`GEMINI.md`/`QWEN.md`/`OPENCODE.md`. Project roots get
   `@AGENTS.md`; live-home roots get an absolute `@/home/<user>/AGENTS.md`; chezmoi source roots get
   `*.md.tmpl` files containing `@{{ .chezmoi.homeDir }}/AGENTS.md`.
3. **Legacy migration** — When `AGENTS.md` is missing and no title is configured, AMD can migrate exactly **one**
   custom provider instruction file into `AGENTS.md`. Multiple custom files **block** so content is never guessed.
4. **Multi-root / chezmoi** — Plans against the current directory unless `use_chezmoi: true` adds or redirects to the
   chezmoi home source root. It can generate the **home** `AGENTS.md` from `~/.config/sase/sase.yml` (or the chezmoi
   `dot_config/sase/sase.yml`) — a value `memory init` deliberately ignores (see §4).
5. **Git** — Commits **locally only**, grouped by git repo root, message `chore: run sase init amd`
   (`AMD_COMMIT_MESSAGE`, `src/sase/amd/constants.py:14`). **No pull/rebase, no push, no chezmoi apply.**
6. **Flags:** `-c/--check` (drift report, no writes), `-C/--no-commit` (skip the local commit).

---

## 2. What `sase memory init` does

**Where it lives (all Python; reuses `sase.amd`; no Rust core):**

- CLI parser: `src/sase/main/parser_memory.py` (`init`, lines 37-57); alias `sase init memory` in `parser_init.py`
- Handler: `src/sase/main/memory_handler.py` → `init_memory_handler.py` (`handle_memory_init_command`,
  `run_init_memory`, `plan_init_memory`)
- Engine: `src/sase/main/init_memory/roots.py`, `config.py`, `constants.py`
- Docs: `docs/init.md` §"Memory Initialization" (lines 135-171)
- Tests: `tests/main/test_init_memory_handler.py` (679 lines), `test_init_memory_plan.py` (451 lines),
  `test_init_memory_commit.py`, `test_init_onboarding_flow.py`

**Behavior:**

1. **Memory content** — Generates `memory/sase.md` (workspace naming + linked-repo summary, with
   `type: short` / `parent: AGENTS.md` frontmatter) and `memory/README.md`, for **both** the project root and the
   home root (`~/memory/` or the chezmoi home tree under `use_chezmoi: true`).
2. **`AGENTS.md`** — Two paths (`src/sase/main/init_memory/roots.py:161-210`):
   - If the **project** `./sase.yml` sets `amd_h1_title`, it calls **`plan_amd_memory_sync()`** (from
     `sase.amd.init`) to write the *managed* `AGENTS.md` and to add missing long-memory `description` frontmatter,
     then validates reachability against that content.
   - Otherwise it writes a **minimal** `AGENTS.md` with `write_policy="create_if_missing"` (never overwrites).
3. **Provider shims** — Uses **`provider_shim_plan()`** (also from `sase.amd`) — *the same engine `amd init` uses*.
4. **Reachability validation** — Every Markdown file under `memory/` must be reachable from `AGENTS.md` via transitive
   `@memory/...` / `memory/...` references; unreferenced files **fail** the command.
5. **Linked-repo validation** — Every `linked_repos` (or deprecated `sibling_repos`) entry must have a non-empty
   `description` or init fails.
6. **Git + deploy** — Runs precommit, stages generated files, commits `chore: run sase init memory`
   (`PROJECT_COMMIT_MESSAGE`, `init_memory/constants.py:6`), then **`git pull --rebase` + `git push`**
   (`init_memory_handler.py:206-234`), and **`chezmoi apply`** for home deployment when configured.
7. **Flags:** `-c/--check`, `-C/--no-commit` (skips only the *project* commit/push; home/chezmoi deploy still runs).

---

## 3. The key finding: they are already coupled, not independent

`memory init` does **not** reimplement AMD — it **depends on the `sase.amd` package**:

```text
src/sase/main/init_memory/roots.py:9   from sase.amd.init import AmdMemorySyncPlan, plan_amd_memory_sync
src/sase/main/init_memory/roots.py:13  from sase.amd...        import provider_shim_plan
src/sase/main/init_memory/constants.py:3  from sase.amd.constants import PROVIDER_SHIM_FILES
```

So for the **project root**, `memory init` is effectively a **superset** of `amd init`: it writes the managed
`AGENTS.md` (via the AMD planner), writes the provider shims (via the AMD plan), *and* layers on memory content,
reachability validation, home memory, and push/deploy.

The clean dependency direction today is **`memory` → `amd`** (memory is the higher-level workflow; AMD is the
lower-level primitive). The bare coordinator makes the relationship explicit: **`sase init` runs AMD *before* memory**
"so memory validation can see the `AGENTS.md` that AMD would create" (`docs/init.md:13`, 131). That ordering dependency
is the architectural reason they are separate steps.

---

## 4. What a hard merge would *cost* (AMD-only capabilities memory init does NOT replicate)

These are the gaps that make "just delete `amd init`" lossy:

| AMD-only capability | Status in `memory init` today | Why it matters |
|---|---|---|
| **Managed home / chezmoi `AGENTS.md`** generation from user/global config | **Not done.** `_amd_sync_plan` enables AMD sync for the **project root only** (`roots.py:213-219`, with an explicit comment that the onboarding title fallback is "scoped to the project and never the home root"). Home gets only a *minimal* `AGENTS.md`. | The only way to produce a *managed* `~/AGENTS.md` (or chezmoi-source `AGENTS.md.tmpl`) with a configured title is `amd init`. |
| **Legacy single-file migration** (`CLAUDE.md` → `AGENTS.md` when no title) | **Not done.** | One-time repair for repos predating AMD; a memory command is the wrong home for it. |
| **Standalone shim repair without touching memory** | **Not available.** `memory init` always writes memory files, validates reachability, and pushes. | AMD is usable in roots that have **no `memory/` directory at all** (pure dotfiles/home). Folding it into memory couples shim repair to memory existence + reachability rules. |
| **Local-commit-only semantics** | `memory init` commits **and pull/rebase/pushes** + chezmoi-applies. | A merge forces one commit policy. AMD's deliberate "local commit, no push" would be lost or would have to become a new flag. |

In short: the names describe genuinely different scopes. AMD = *agent-instruction plumbing* (provider-agnostic shims,
titles across project/home/chezmoi, migration). Memory = *memory content + reachability + linked repos*. They touch the
same `AGENTS.md`, but that overlap is already factored cleanly via reuse.

---

## 5. Options

**Option A — Full merge (delete `amd init`, absorb everything into `memory init`).**
- *Pros:* one fewer top-level command; removes the surface-level "which one writes AGENTS.md?" confusion.
- *Cons:* `memory init` must grow home/chezmoi managed-`AGENTS.md` generation, migration, no-`memory/` shim repair, and
  a reconciled commit policy. It would run in repos with no memory at all, making the name misleading. Large churn
  across `parser_*`, handlers, two test suites (1000+ lines combined), `docs/init.md`, and the `sase init amd` alias.
  Reverses the clean `memory → amd` layering by collapsing the primitive into the workflow. **Highest cost, lossy.**

**Option B — Keep separate, do nothing (status quo).**
- *Pros:* zero risk; clean layering preserved; bare `sase init` already gives the "do everything in order" UX; narrow
  commands stay available for drift checks and targeted repair.
- *Cons:* two commands still both *appear* to write `AGENTS.md` + shims, which is the original confusion.

**Option C — Consolidate the engine, not the command (recommended middle ground).**
- Make `memory init` delegate the *entire* project-root AGENTS.md/shim concern to the AMD engine (call the full
  `build_amd_init_plan` path) instead of partially reusing `plan_amd_memory_sync` + `provider_shim_plan`. AMD stays the
  single owner of "AGENTS.md + shims + migration"; memory owns "memory content + reachability + push." This removes the
  *real* duplication (two slightly different AGENTS.md write paths) without losing any capability or renaming anything.
- Optionally improve discoverability in help text so users understand `memory init` ⊇ `amd init` for the project root,
  and that bare `sase init` is the combined entry point.

---

## 6. Recommendation

**Do not merge `amd init` into `memory init` (reject Option A).** Prefer **Option B (status quo)** if you want zero
risk, or **Option C** if the motivation is to eliminate the genuine duplication.

Reasoning:

1. **The duplication is already largely solved.** `memory init` reuses the `sase.amd` engine; it is not a parallel
   reimplementation. The remaining overlap is one slightly-divergent AGENTS.md write path — best fixed by *more* reuse
   (Option C), not by deleting the primitive.
2. **A merge is lossy.** AMD owns three things memory deliberately does not: managed **home/chezmoi** `AGENTS.md`,
   legacy **migration**, and **standalone shim repair in memory-less roots**. Folding these into `memory init` expands
   and mis-names it.
3. **The combined UX already exists.** Bare `sase init` orchestrates AMD → memory → SDD → skills with the correct
   ordering and per-initializer commit/push behavior. Users wanting "one command" should reach for that, not a merged
   `memory init`.
4. **Commit semantics conflict.** AMD's intentional local-commit-no-push vs memory's commit+pull+push+chezmoi-apply
   would have to be reconciled, almost certainly by adding flags that re-expose the very separation you removed.

**If you proceed anyway** (e.g., you specifically want to retire the `amd` namespace), the safe sequencing is: first do
Option C so AMD is the single AGENTS.md/shim owner, then port AMD's home/chezmoi + migration paths into the memory
engine behind explicit flags, keep `sase init amd` (and a new `sase memory init --amd-only`) as compatibility shims,
and update both test suites + `docs/init.md` together. That is a multi-phase effort, not a quick fold.

---

## Appendix — quick command comparison

| Aspect | `sase amd init` | `sase memory init` |
|---|---|---|
| Primary artifacts | `AGENTS.md` + provider shims | `memory/sase.md`, `memory/README.md` + `AGENTS.md` + shims |
| AGENTS.md when `amd_h1_title` set | Managed (overwrite) | Managed via `plan_amd_memory_sync` (overwrite) |
| AGENTS.md when title unset | Migrate 1 file, else leave | Minimal, `create_if_missing` |
| Provider shims | `provider_shim_plan` | **same** `provider_shim_plan` |
| Home / chezmoi `AGENTS.md` (managed) | **Yes** (from user/global/chezmoi config) | **No** (project-only AMD sync; home gets minimal) |
| Legacy single-file migration | **Yes** | No |
| Memory reachability validation | No | **Yes** (unreferenced files fail) |
| linked_repos description check | No | **Yes** |
| Git | Local commit only (`chore: run sase init amd`) | Commit + `pull --rebase` + `push` + chezmoi apply (`chore: run sase init memory`) |
| Flags | `-c/--check`, `-C/--no-commit` | `-c/--check`, `-C/--no-commit` |
| Implementation | `src/sase/amd/` (Python) | `src/sase/main/init_memory/` (Python, **imports `sase.amd`**) |
| Combined entry point | `sase init` (AMD first) | `sase init` (memory second) |
