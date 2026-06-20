---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Sibling Repos via `sase workspace open` + Open-Tracking (Alternative to Config-Driven Sibling Repos)

## Research Request

> Re: `sibling_repos_removal_consolidated.md` — what if we just tell agents they can use `sase workspace open`
> on any sase project they know about? Then we could add the sibling / linked repo descriptions to the appropriate
> `AGENTS.md` / memory files manually and track which agents run the `sase workspace open` command and use that data
> to implement the commit finalizer / diff tracking. Is this feasible? What am I missing, and what open questions
> would be hard to answer alone when making this migration?

This document evaluates that specific alternative. It builds on, and is meant to be read alongside,
[`sibling_repos_removal_consolidated.md`](sibling_repos_removal_consolidated.md), whose recommendation was the
*opposite* direction (keep the capability, rename the model to `linked_repositories`). This proposal is more radical:
delete the declarative `sibling_repos` layer entirely and replace its two jobs — generated guidance and finalizer
input — with manual docs and runtime open-tracking.

## Verdict (Executive Summary)

**The proposal is partially feasible and is the strongest "actually remove it" option so far — but it cannot be a
pure documentation change.** It quietly requires three pieces of plumbing to survive, and it trades a declarative,
self-validating feature for a convention-plus-runtime-signal feature with a few sharp edges.

The proposal has three pillars. Their feasibility differs sharply:

1. **"Agents can `sase workspace open` any project they know about."** *Mostly already true — but not for the four
   current siblings.* `sase workspace open -p <project> <num>` works today for any project with a registered
   ProjectSpec that has a `WORKSPACE_DIR:` header — it does **not** consult `sibling_repos` config on that path. The
   catch: the four siblings (`sase-core`, `sase-github`, `sase-telegram`, `sase-nvim`) are **not** registered
   projects. They have no standalone ProjectSpec; they are *lazily materialized* from `sibling_repos` config on first
   open. Delete the config and `sase workspace open -p sase-core <num>` breaks on any machine where the spec was never
   materialized (e.g. a fresh `~/.sase`). **A registration step is mandatory, not optional.**

2. **"Add the descriptions to `AGENTS.md` / memory manually."** *Feasible, but the generation code must be removed,
   not just bypassed.* `memory/sase.md` is a **generated and git-committed** file; `sase validate` / `sase memory init`
   diff actual-vs-expected and will flag any hand edit as stale. Going manual means deleting the rendering path, not
   editing the output. And manual text **cannot** carry the one thing config injection gives the build:
   the `SASE_SIBLING_REPO_*` / `SASE_CORE_DIR` env vars the `Justfile` relies on.

3. **"Track `sase workspace open` invocations and feed that to the finalizer."** *Feasible and arguably cleaner — the
   tracking file already exists.* `opened_siblings.json` is already a per-run marker that records the opened
   workspace path. It just needs to (a) drop its "only for configured siblings" gate, and (b) record one extra bit
   per entry — the blocking-vs-advisory classification — because that bit is **not recoverable from a filesystem
   path**. With those two changes the finalizer can iterate over opened workspaces directly.

Bottom line: this is a real, coherent design and it genuinely simplifies several subsystems. But "manual docs + open
tracking" is shorthand for "register the related repos as real projects, delete the generation + env-injection +
materialization code, generalize the open-marker, and accept some behavioral regressions." It is a *migration*, not a
deletion.

## The Proposal, Restated as Three Pillars

| Pillar | Replaces | Mechanism today | Mechanism proposed |
| --- | --- | --- | --- |
| P1. Open any known project | Config-gated sibling resolution + lazy ProjectSpec materialization | `sibling_repos` config → `_materialize_sibling_project_context` writes a hidden `PROJECT_STATE: sibling` spec | Each related repo is a registered project; `sase workspace open` resolves it via its own `WORKSPACE_DIR` |
| P2. Manual descriptions | Generated `## Sibling Repositories` memory section | `roots.py` renders from `config["sibling_repos"]` | Hand-written `AGENTS.md` / memory prose |
| P3. Open-tracking finalizer | Config/env-driven dirty-sibling detection | Finalizer reads `SASE_SIBLING_REPOS_JSON` (from config at launch) + `opened_siblings.json` name filter | Finalizer iterates over *all* opened workspaces recorded this run |

## What I Verified About Current Behavior

These are the load-bearing facts the proposal hinges on, grounded in the source.

### `sase workspace open` does not need sibling config — *if* the project is registered

`resolve_project_context` (`src/sase/main/workspace_handler_context.py:34-92`) reads the target project's own
`WORKSPACE_DIR:` header via `parse_workspace_dir` (`src/sase/workspace_provider/utils.py:64-90`) and builds a
`WorkspaceStore` on the fly. `-p/--project` is a free-form string with no `choices=` restriction
(`src/sase/main/parser_workspace.py:52-79`). The **only** hard requirement is a ProjectSpec at
`~/.sase/projects/<name>/<name>.sase` with a non-empty `WORKSPACE_DIR`. No registry entry, no pre-existing store, no
sibling config.

### …but the four siblings are not registered — they're lazily materialized from config

When `WORKSPACE_DIR` is absent, `resolve_project_context` falls into `_materialize_sibling_project_context`
(`workspace_handler_context.py:95-161`), which looks the name up in `resolve_sibling_repos_for_project(...)`. If the
name is **not** in `sibling_repos` config, it returns `None` and the command exits 2 with
`"Project '<name>' has no WORKSPACE_DIR in <file>."`. If it *is* configured, it writes a hidden ProjectSpec with
`PROJECT_STATE: sibling` and `WORKSPACE_DIR = <sibling primary dir>` (`_ensure_sibling_project_spec`, `:227-259`). So
the config is the seed for the spec. The four siblings in `sase.yml:14-26` rely on this seeding.

### Agents have no workspace-number env var — they parse it from cwd

There is no `SASE_WORKSPACE_NUM` delivered to plain agents. The runner receives the number only as argv[5]
(`src/sase/axe/run_agent_runner.py:176`) and never re-exports it. (`SASE_AGENT_WORKSPACE_NUM` is referenced in the
finalizer's lookup list at `commit_finalizer_state.py:25` but **is never set** — dead.) The number is recovered by
parsing the cwd basename against `<primary_basename>_<digits>` (`_workspace_num_for_project_file`,
`commit_finalizer_state.py:202-230`). Generated memory already instructs the agent to do exactly this
(`roots.py:90-99`, the "check what directory you were started in" line). **This means the agent can self-serve the
number it needs to pass to `sase workspace open` — that part of the proposal is sound.**

### The open-tracking file already exists and already stores the path

`record_opened_sibling` (`src/sase/sibling_repos.py:114-145`) writes
`$SASE_ARTIFACTS_DIR/opened_siblings.json`, keyed by name, storing `{name, workspace_dir}`. It is per-run (scoped by
the run's artifact dir), atomic, union-by-name, and needs no cleanup (each run gets a fresh artifact dir). It is
called from exactly one place — `handle_open_clean` (`workspace_handler_list.py:194-197`) — and is double-gated:
`ctx.is_sibling` must be true, and `SASE_ARTIFACTS_DIR` must be set (so interactive opens record nothing). **The
finalizer currently ignores the stored `workspace_dir` and re-derives paths from config/env**, using
`opened_sibling_names` only as a name filter (`commit_finalizer_state.py:51, 118`).

### The finalizer's one irreducible config dependency: blocking vs advisory

`_dirty_configured_sibling_repos_for_strategy` (`commit_finalizer_state.py:108-131`) branches on
`workspace_strategy`: `suffix` siblings **block** finalization when dirty *and opened*; `none` (static singleton)
siblings are **advisory only** and bypass the open-marker check entirely. This `suffix`/`none` bit comes only from
config/env (`SASE_SIBLING_REPOS_JSON` or `sibling_repos.workspace.strategy`). It is **not** stored in
`opened_siblings.json` and **cannot be inferred from a path** — a `suffix` clone and a `none` checkout are both just
git directories. This is the single datum an open-tracking-only finalizer would lose.

## Feasibility, Pillar by Pillar

### P1 — Open any known project: feasible *with a registration step*

The mechanism is already there for registered projects. The work is making the four siblings into registered
projects with correct `WORKSPACE_DIR` values. Options:

- **Keep a thin declarative shim** that registers related repos as projects at setup time (essentially: run the
  existing lazy materialization eagerly, driven by *something*). This is barely distinguishable from keeping a small
  config block — which is why the consolidated doc recommended renaming rather than removing.
- **A real `sase project add <name> <path>`-style registration**, run once per related repo per machine. This makes
  the repos first-class projects (they appear in launch pickers, project lists, doctor, etc.). See the "noise"
  gotcha below.

Either way, **something declarative survives** — the question is only whether it lives in `sibling_repos` config or in
per-project ProjectSpec state. (The consolidated doc's Option 4, "store links in ProjectSpec," is essentially this.)

### P2 — Manual descriptions: feasible, but it's a code deletion + an env-injection hole

Three sub-points:

1. **`memory/sase.md` is generated and committed**, and `sase validate` compares it against the rendered expectation
   (`init_memory/roots.py` `_extend_sibling_repository_section:62-103`, `_compare_expected_memory_files:218`). To make
   the section hand-maintained you must delete the rendering path and the `sibling_entries_from_config` reader
   (`init_memory/config.py:177-246`), or `validate` will flag every manual edit as stale. So "do it manually" = "remove
   the generator." That is fine, just not free.
2. **Manual text cannot set environment variables.** The `Justfile` build resolves
   `SASE_CORE_DIR` → `SASE_SIBLING_REPO_SASE_CORE_DIR` → `../sase-core` (`Justfile:11-16`). Today a SASE-launched
   agent in `sase_11` builds Rust against its **workspace-matched** `sase-core_11` only because launch injects
   `SASE_SIBLING_REPO_SASE_CORE_DIR`. Under the default `xdg-state` root policy, `../sase-core` does **not** resolve to
   the matched checkout (cwd is `.../sase-org/sase/sase_11`, so `../sase-core` is `.../sase-org/sase/sase-core`, which
   does not exist). CI is safe (it sets `SASE_CORE_DIR` explicitly, `.github/workflows/ci.yml:13`), but an agent doing
   a local Rust build would lose workspace matching. A manual doc cannot fix this; the agent would have to
   `export SASE_CORE_DIR=$(sase workspace open -p sase-core <N>)` itself — fragile and easy to forget.
3. **Onboarding/product story regresses.** For SASE-as-a-product, `sibling_repos` is a declarative feature: a user
   declares related repos once and gets guidance + finalizer safety automatically. Manual prose pushes that work onto
   every user for every repo. If `sibling_repos` is meant to be a user-facing feature (not just this repo's internal
   plumbing), P2 is a meaningful downgrade. **This is an open question — see below.**

### P3 — Open-tracking finalizer: feasible and arguably cleaner

This is the most attractive pillar. Concretely:

- **Generalize the marker.** Drop the `ctx.is_sibling` gate at `workspace_handler_list.py:194-197` so *every*
  `sase workspace open` from within a run is recorded. The marker is already per-run and path-carrying.
- **Record the classification.** At record time, store a blocking-vs-advisory flag (today's `workspace_strategy`)
  alongside `{name, workspace_dir}`. `handle_open_clean` has the `ctx` in scope, so it can resolve and persist this.
- **Have the finalizer iterate the marker directly.** Use the stored `workspace_dir` (currently discarded) instead of
  re-deriving paths from config/env. This *deletes* code: `_sibling_targets_from_env`, `_sibling_targets_from_config`,
  `_resolve_workspace_dir`, the `workspace_num`/`primary_dir` machinery, and the env-injection at launch all become
  unnecessary for finalization. `git_changed_files` already tolerates non-git paths (returns empty), so iterating over
  arbitrary opened paths is safe.

Net effect on the finalizer: simpler, path-direct, and no longer dependent on the launch-time env contract. The
*only* thing that must be carried forward explicitly is the blocking/advisory bit.

## What You're Missing (Gotchas)

1. **The four siblings aren't projects — the premise's "any project they know about" excludes them today.** This is
   the biggest gap. Without a registration step, the proposal breaks the exact repos it's meant to serve. (P1 above.)

2. **The workspace-number-parity guarantee is currently config-enforced and would become convention-only.** Today the
   config path and the registered-project path are kept aligned because the lazy materializer seeds the registered
   spec's `WORKSPACE_DIR` from config. The config resolution merges the *sibling's own* `sase.yml`
   (`sibling_repos.py:298-301`), while `sase workspace open -p sase-core` resolves from the *registered* project file +
   the *invoking* project's merged config. These can produce **different directories** for `sase-core_10` if
   project_key or `workspace.root` differ between the two paths (`WorkspaceStore._resolve_root`,
   `src/sase/workspace_provider/store.py:207-244`). On this machine they agree (default `xdg-state`, per-repo
   project_key) only because of the config-seeded bootstrap. Remove the config and you remove the alignment guarantee.
   Migration must pin each registered related project's `WORKSPACE_DIR`/`workspace.*` so `sase-core_<N>` keeps landing
   where it does today.

3. **Manual memory cannot replace env injection.** The `SASE_SIBLING_REPO_*` / `SASE_CORE_DIR` contract that powers
   workspace-matched Rust builds has no manual-doc equivalent. (P2.2.) If matched local builds matter, *some*
   launch-time path injection must survive — which again means *something* declarative survives.

4. **Static-singleton (`workspace.strategy: none`) support is lost unless you record the classification.** The
   advisory-only behavior for shared/non-cloneable repos (e.g. dotfiles) cannot be recovered from a path. If you still
   want static singletons, the open-marker must carry the blocking/advisory bit (P3) — meaning the "purely runtime, no
   declaration" ideal is unreachable for that case.

5. **Generalized tracking widens the finalizer's blast radius.** Today only *configured, opened* siblings can block.
   If you track *all* opens, an agent that opens an unrelated project merely to read it now has that repo dirty-checked.
   If it's clean, it's ignored (harmless); but the semantic shifts from "opened a declared relationship" to "opened
   anything." You likely want to (a) exclude opens of the primary project's own other workspaces, and (b) decide
   whether non-declared opens should block or only advise.

6. **Promoting siblings to normal projects adds UI/list noise.** `PROJECT_STATE: sibling` exists partly to keep these
   out of launch pickers and project lists. Registered `active` projects show up in the launch picker, `sase` project
   lists, doctor (`doctor/checks_project.py:20`), and the TUI project-management modal
   (`project_management_modal.py:41-46`). The migration needs a deliberate answer for what lifecycle state the related
   repos should have (`active` / `inactive` / keep `sibling`).

7. **`agent_meta["sibling_repos"]` has no production reader** (only a test reads it back,
   `tests/test_run_agent_runner_setup.py:200`), so losing it from metadata is low-impact — but worth noting it was
   never load-bearing in the first place.

## Open Questions (Hard to Answer Alone)

These are the decisions I could not resolve from the code and that most affect the migration's shape:

1. **Is `sibling_repos` a user-facing product feature, or just this repo's internal plumbing?** If product, the
   manual-docs pillar (P2) is a real onboarding regression and a thin declarative layer is probably worth keeping
   (favoring the consolidated doc's "rename, don't remove"). If internal-only, manual docs are acceptable and the
   simplification wins. *This is the pivotal question.*

2. **Do agents actually rely on workspace-matched local Rust builds?** If matched builds via
   `SASE_SIBLING_REPO_SASE_CORE_DIR` are commonly used, gotcha #3 is a blocker and env injection must survive. If
   builds almost always go through CI (`SASE_CORE_DIR`) or the shared `../sase-core`, the loss is acceptable.

3. **Is static-singleton (`none`) support still needed?** If any current or planned related repo is a shared/static
   checkout (dotfiles-style), the open-marker must carry the blocking/advisory bit and the "no declaration" ideal is
   out. If every related repo is a per-workspace git clone, you can drop the distinction and the marker stays simple.

4. **What should the registration step be, and where do related-project links live?** A one-time
   `sase project add`-style command? Eager materialization at memory-init time? ProjectSpec metadata (consolidated
   doc's Option 4)? Each choice changes how parity (#2) is guaranteed and whether links are per-machine or committed.

5. **Should generalized open-tracking block on non-declared opens, or only on opens of declared relationships?** This
   determines whether you can drop the declaration entirely (block on any open) or still need a list of "repos that
   should block" (back to a declaration). The answer interacts directly with #1 and #3.

6. **What is the desired lifecycle state for related repos** if they become registered projects (gotcha #6)? This
   affects launch-picker UX, doctor, and the project-management modal.

## How This Compares to the Consolidated Recommendation

The consolidated research recommended **keep the capability, rename `sibling_repos` → `linked_repositories`, migrate
behind compatibility aliases.** This proposal pushes further: remove the declarative layer and lean on
`sase workspace open` + runtime open-tracking.

The honest synthesis is that **the two converge.** Each gotcha above ("register the repos," "keep env injection,"
"record the blocking bit," "decide lifecycle state") reintroduces a small piece of declaration. By the time the
proposal is safe, you have: registered related-project specs (a declaration), possibly surviving path injection (a
declaration), and a per-open blocking/advisory flag (a declaration). That is `linked_repositories` wearing different
clothes — *but* with one genuinely better idea grafted on: **drive finalization from what the run actually opened
(P3), not from static config.** That is a real improvement over today's env+config discovery and is worth adopting
regardless of which naming/storage path you pick.

### Recommended path if you pursue this

1. **Adopt P3 first, independently.** Generalize `opened_siblings.json` (drop the `is_sibling` gate, add the
   blocking/advisory bit, make the finalizer iterate the marker's stored paths). This is a self-contained,
   low-risk simplification that improves correctness (finalization tracks intent precisely) and can land before any
   decision about config removal.
2. **Decide Open Question #1.** It gates everything else.
3. **If you still want to remove config:** add a real registration step for related repos (answering #4 and #6),
   pin their `WORKSPACE_DIR`/`workspace.*` to preserve parity (#2), and decide whether *any* path injection must
   survive for builds (#2/gotcha #3).
4. **Only then** delete the generation path, env injection, and lazy materializer.

Doing P3 first de-risks the whole effort: it delivers the proposal's most compelling benefit immediately and reveals,
in practice, how much the finalizer still needs from the declarative layer.

## Appendix: Touch-Point Map

Primary references (file:line) for a migration:

- **CLI / open path:** `src/sase/main/parser_workspace.py:52-79`, `src/sase/main/workspace_handler.py:109-178`,
  `src/sase/main/workspace_handler_list.py:106-200`,
  `src/sase/main/workspace_handler_context.py:34-161, 227-259`.
- **Sibling core module:** `src/sase/sibling_repos.py` (env names `:15-17`; `to_env` `:59-68`; resolution
  `:185-275`; `_resolve_workspace_dir` `:381-405`; `record_opened_sibling`/`opened_sibling_names` `:114-153`).
- **Launch env injection / refresh:** `src/sase/agent/launch_spawn.py:172-234`,
  `src/sase/axe/run_agent_phases.py:30-138`, `src/sase/axe/run_agent_runner_setup.py:218-245`,
  `src/sase/axe/run_agent_directives.py:239-310`.
- **Commit finalizer:** `src/sase/llm_provider/commit_finalizer_state.py:31-230` (targets `:134-193`; dirty branch
  `:108-131`; cwd-number parse `:202-230`), `commit_finalizer.py:180-289`, `commit_finalizer_prompting.py:20-88`,
  `commit_finalizer_types.py:52-61`, `commit_finalizer_git.py:35-58`.
- **Generated memory:** `src/sase/main/init_memory/roots.py:62-103, 218`,
  `src/sase/main/init_memory/config.py:177-246`, `src/sase/main/init_memory_handler.py:99-102`; output at
  `memory/sase.md` (`## Sibling Repositories`).
- **Build / CI:** `Justfile:11-16` (and Rust targets), `.github/workflows/ci.yml:13, 21-24`,
  `tests/test_justfile_sase_core_dir.py`.
- **Config / schema:** `sase.yml:14-26`, `src/sase/default_config.yml:5`, `config/sase.schema.json:729-768`.
- **Lifecycle / UI coupling:** `src/sase/core/project_lifecycle_wire.py:15`,
  `src/sase/doctor/checks_project.py:20`, `src/sase/ace/.../project_management_modal.py:41-46`,
  `project_management_rendering.py:25, 46, 147`.
- **Tests to rewrite/remove:** `tests/llm_provider/test_commit_finalizer_siblings.py`, `tests/test_sibling_repos.py`,
  `tests/test_justfile_sase_core_dir.py`, `tests/test_runtime_workspace_managed_roots.py`,
  `tests/test_cd_spawn_env.py`, `tests/ace/test_project_spec_migration.py`,
  `tests/test_run_agent_runner_setup.py:200`.
