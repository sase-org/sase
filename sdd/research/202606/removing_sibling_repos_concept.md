---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Removing the "Sibling Repos" Concept: Consequences, Feasibility, and Recommendation

## Research Request

> "I've been thinking about removing the concept of sibling repos from SASE. Help me understand the consequences of this
> decision. Is it feasible without losing functionality? Is it advisable? End with a recommended solution."

## Bottom Line (TL;DR)

- **Removal is mechanically feasible** — the feature is young (~1 month old), self-contained, Python-only, and touches a
  bounded set of ~14 source files and ~16 test files. There is no Rust-core entanglement to unwind.
- **But wholesale removal *does* lose real, currently-used functionality.** Three capabilities disappear:
  1. **Per-workspace isolation of related repos** (agent in `sase_10` edits `sase-core_10`, not the shared
     `../sase-core`), which prevents concurrent agents from colliding on one checkout.
  2. **Cross-repo commit finalization** (the finalizer detects and prompts to commit dirty sibling checkouts).
  3. **A stable env/memory contract** that the **Justfile build itself depends on**
     (`SASE_SIBLING_REPO_SASE_CORE_DIR` selects the workspace-matched `sase-core` for building `sase-core-rs`).
  This repo's own `sase.yml` configures four siblings (`sase-core`, `sase-github`, `sase-telegram`, `sase-nvim`), so the
  feature is in active use here.
- **It is *not* advisable to delete the capability outright.** The genuine problems with "sibling repos" are a **naming
  collision** (an unrelated "agent siblings" concept) and **modest surface-area sprawl**, not the capability itself.
- **Recommended solution: keep the capability, retire the "sibling" framing.** Rename to `linked_repos` (or
  `companion_repos`), collapse the two workspace strategies if `none` is unused, and treat the underlying mechanism as
  "number-aligned linked projects." This kills the confusion that is most likely driving the urge to remove it, while
  preserving the multi-repo workflow SASE relies on. A clean full-removal path is documented below as the fallback if you
  decide the functionality isn't worth its weight.

---

## 0. Critical disambiguation: two unrelated "sibling" concepts

The single most important finding. The word "sibling" names **two completely different things** in this codebase, and
this conflation is itself a strong argument *for doing something*, but a weak argument for *deleting the repo feature*:

| Concept | What it is | Representative files |
| --- | --- | --- |
| **Sibling repositories** (in scope) | Configured external repos (`sase-core`, `sase-github`, …) exposed to agents | `sibling_repos.py`, `commit_finalizer_state.py`, `init_memory/roots.py`, `workspace_handler_context.py` |
| **Agent siblings** (NOT in scope) | Sibling *agents* in an agent family (TUI rows, `~name` query filter) | `agent_siblings.py`, `agent_sibling_modal.py`, `actions/agents/_siblings.py`, `status_state_machine/siblings.py`, `query/matchers.py` |

Of the ~1,500 raw "sibling" hits in the tree, the large majority are the **agent-sibling** concept and are irrelevant to
this decision. The repo-sibling feature is much smaller than the raw grep count suggests. Throughout this document,
"siblings" means **sibling repositories** unless stated otherwise.

> Implication: if the motivation to "remove sibling repos" is partly *"the term is overloaded and confusing,"* then a
> **rename** solves that problem directly and at a fraction of the cost of removing the capability.

---

## 1. What the feature actually is

### 1.1 Configuration surface

Declared under the `sibling_repos` key in user config (`~/.config/sase/sase.yml`) and/or a project-local `sase.yml`,
merged with list-concatenation. Default is `[]` (`src/sase/default_config.yml:5`). Schema lives at
`config/sase.schema.json:729-768`; documented in `docs/configuration.md` ("### sibling_repos").

This repo's `sase.yml`:

```yaml
sibling_repos:
  - name: sase-core
    path: ../sase-core
    description: Shared Rust core backend for SASE domain behavior and cross-frontend APIs.
  - name: sase-github
    path: ../sase-github
    description: GitHub VCS and workspace provider plugin for repository, issue, and PR workflows.
  - name: sase-telegram
    path: ../sase-telegram
    description: Telegram integration plugin for chat-driven SASE workflows and notifications.
  - name: sase-nvim
    path: ../sase-nvim
    description: Neovim integration plugin for SASE syntax, completion, and editor support.
```

Per-entry fields: `name` (required, → env-var alias), `path` (required, relative to primary workspace), `description`
(required, → generated memory), and optional `workspace.strategy` ∈ {`suffix` (default), `none`}.

### 1.2 The load-bearing mechanic: workspace-number parity

The core value is **alignment by workspace number**. SASE runs agents from ephemeral `sase_<N>` clones. For a `suffix`
sibling, an agent in workspace `N` is handed `sase-core_<N>` (materialized through the same `workspace.root` policy as
the primary). Workspace numbers `0`/`1` use the primary checkout; `none`-strategy siblings always use the primary
checkout (e.g. a shared `~/.local/share/chezmoi`). Core logic: `sibling_repos.py:resolve_sibling_repos_for_project()` /
`_resolve_workspace_dir()` (`src/sase/sibling_repos.py:185-405`).

### 1.3 The env/metadata contract

`SiblingRepoResolution.to_env()` (`sibling_repos.py:59-68`) emits, for each resolved sibling:

- `SASE_SIBLING_REPOS_JSON` — canonical JSON array of all resolved siblings (name, dirs, workspace_num, strategy)
- `SASE_SIBLING_REPO_<NAME>_DIR` — workspace-matched checkout
- `SASE_SIBLING_REPO_<NAME>_PRIMARY_DIR` — primary checkout

Injected at agent launch (`agent/launch_spawn.py:172-234`, scrub-then-apply), recomputed after deferred-workspace claims
(`axe/run_agent_phases.py:124-136`, `axe/run_agent_runner_setup.py:218-245`), and written into `agent_meta.json`
(`axe/run_agent_directives.py:239-241`).

### 1.4 The `sase workspace open -p <sibling> <num>` path

`sase workspace open -p <sibling> <num>` (`main/parser_workspace.py`, `main/workspace_handler_list.py:152-200`) lazily
materializes the sibling as a regular project with `PROJECT_STATE: sibling`
(`main/workspace_handler_context.py:95-259`) and records it in `opened_siblings.json` via `record_opened_sibling()`.

> Architectural note: a sibling is, under the hood, **already a normal SASE project** — just one that is auto-registered
> and number-aligned with the primary. This is important for the recommendation (§6): "sibling repos" is largely sugar
> over the existing project/workspace machinery.

### 1.5 Generated memory / AGENTS.md instructions

`init_memory/roots.py:_extend_sibling_repository_section()` (`62-104`) renders the `## Sibling Repositories` block into
`memory/sase.md` (the very block visible in this repo's memory). For numbered siblings it emits the
`sase workspace open -p <sibling_repo> <workspace_num>` instruction; for `none` siblings it prints the static path and
omits that instruction. (Project-local vs. home config drive project vs. home memory respectively.)

### 1.6 Cross-repo commit finalization

The provider-neutral commit finalizer (`llm_provider/commit_finalizer*.py`) discovers configured siblings (env first,
config fallback — `commit_finalizer_state.py:134-160`), intersects with `opened_siblings.json`
(`commit_finalizer_state.py:51`), and for **opened, dirty, numbered** siblings emits follow-up prompts telling the agent
to `cd <sibling workspace>` and run `/sase_git_commit` (`commit_finalizer_prompting.py:66-84`). `none` siblings are
**advisory** (reported, never blocking). Recent hardening (`db79196c8`, 2026-06-19) gates this on the
sibling having been *opened*, to avoid false positives.

---

## 2. Footprint (what removal would touch)

**Source (14 files):** `sibling_repos.py` (core, ~420 LoC), `agent/launch_spawn.py`, `axe/run_agent_directives.py`,
`axe/run_agent_phases.py`, `axe/run_agent_runner.py`, `axe/run_agent_runner_setup.py`,
`llm_provider/commit_finalizer.py`, `commit_finalizer_state.py`, `commit_finalizer_prompting.py`,
`main/init_memory/config.py`, `main/init_memory/roots.py`, `main/workspace_handler_context.py`,
`main/workspace_handler_list.py`, `default_config.yml`.

**Tests (~16 files):** incl. `test_sibling_repos.py`, `test_cd_spawn_env.py`,
`test_axe_run_agent_runner_deferred_workspace.py`, `llm_provider/test_commit_finalizer_siblings.py`,
`main/test_init_memory_*`, `test_justfile_sase_core_dir.py`, `test_config_schema.py`.

**Other surfaces:** `config/sase.schema.json`, `docs/configuration.md`, `docs/commit_workflows.md`, `README.md`, the
generated `memory/sase.md` block, and **`Justfile`** (build-time consumer — see §3).

**Maturity signals:** Introduced `3653d728d` (2026-05-21); only 4 commits ever touch the core module; last change
2026-06-19. So: young, low-churn, but still being actively refined — i.e. not yet "settled," which cuts both ways.

**Rust core:** *No* sibling-repo logic exists in `sase-core`. The feature is 100% Python. (Relevant to §5.)

---

## 3. What would be LOST on wholesale removal

1. **Concurrent-agent isolation on related repos.** Without workspace-matched checkouts, every agent touching
   `sase-core` shares `../sase-core`. Two agents in `sase_10` and `sase_20` editing the Rust core would stomp on each
   other's working tree. This is the feature's reason for existing, and it matters specifically for *this* project, which
   is developed across five number-aligned repos.

2. **Cross-repo commit safety.** The finalizer would no longer detect or prompt for dirty sibling checkouts. An agent
   that edits both the primary and `sase-core` would get the primary committed and **silently leave the core change
   uncommitted** (or the user commits it by hand, out of band from the ChangeSpec workflow).

3. **The build's workspace-matched core selection.** `Justfile:16` resolves
   `SASE_CORE_DIR → SASE_SIBLING_REPO_SASE_CORE_DIR → SASE_SIBLING_REPO_CORE_DIR → ../sase-core`. Remove the feature and
   the build falls back to the shared `../sase-core`. That still *builds*, but loses per-workspace isolation of the
   `sase-core-rs` source build — a subtle correctness hazard when concurrent workspaces are on different core revisions.

4. **The documented agent affordance.** The generated-memory instructions that teach agents *how* to read/edit related
   repos vanish. Agents would fall back to ad-hoc relative paths (`../sase-core`), reintroducing the very collision
   problem above and removing the audit trail (`opened_siblings.json`).

5. **The `none`/static advisory workflow** (e.g. chezmoi dotfiles surfaced to agents and reported as advisory).

**Net:** removal is *not* "feasible without losing functionality." It is feasible **only if you accept** the loss of
multi-repo isolation + cross-repo commit + workspace-matched builds, and replace them with manual discipline.

---

## 4. Is it feasible? (Yes — and here's the clean removal path, if chosen)

Mechanically straightforward because the feature is Python-only and funnels through one module:

1. Delete `src/sase/sibling_repos.py` and its dedicated tests.
2. Strip the resolve/scrub/apply calls from `launch_spawn.py`, `run_agent_phases.py`, `run_agent_runner_setup.py`,
   `run_agent_directives.py` (drop `sibling_repos` from `agent_meta.json`).
3. Remove the sibling branch from the commit finalizer (`commit_finalizer_state.py` discovery,
   `commit_finalizer_prompting.py` prompts) and `opened_siblings.json` plumbing in `workspace_handler_list.py`.
4. Remove the sibling memory section from `init_memory/roots.py` + `config.py` (and regenerate `memory/sase.md`).
5. Drop `sibling_repos` from `default_config.yml` and `config/sase.schema.json`; prune `docs/configuration.md`,
   `docs/commit_workflows.md`, `README.md`.
6. Decide the `Justfile` fallback: keep `SASE_CORE_DIR` override + `../sase-core` default (recommended) so local Rust
   builds still work without the feature.
7. Remove the `sase workspace open -p <sibling>` materialization (or keep `-p` for genuine cross-project opens and only
   drop the *auto-registration* of configured siblings).

No database/wire migration, no Rust changes, no cross-frontend contract to renegotiate. Estimated as a 1–2 day change
including test cleanup.

---

## 5. Is it advisable? (No, not as deletion — but the concern is legitimate)

**Arguments the urge to remove is pointing at something real:**

- **Naming collision** with "agent siblings" is a genuine, recurring source of confusion (this research had to fight it
  on every file).
- **Surface sprawl:** 14 source + 16 test files for what is, conceptually, "expose some related checkouts."
- **Boundary tension:** `memory/rust_core_backend_boundary.md` says shared backend/domain behavior belongs in
  `sase-core`. Sibling resolution arguably *is* backend logic (a future web UI / CLI would want the same resolution), yet
  it lives entirely in Python. So the feature is either (a) mis-located and should partly move to Rust, or (b) genuinely
  orchestration glue that's fine in Python. Either way it's worth a deliberate call, not silent drift.
- **Strategy proliferation:** two strategies (`suffix`/`none`) with only one `none` example (chezmoi) in the wild.

**Arguments against deletion:**

- The capability is **used by this project today** (4 configured siblings, Justfile dependency, live memory block).
- It encodes a **non-trivial invariant** (workspace-number parity) that is annoying to re-derive by hand and easy to get
  wrong, exactly when concurrency makes mistakes most costly.
- Removing cross-repo commit finalization shifts safety-critical work (committing the right change in the right repo)
  from the tool back onto the human.

**Conclusion:** the *concept* is sound; the *packaging and naming* are the warts. Delete the warts, not the capability.

---

## 6. Recommended solution

**Keep the capability. Retire the "sibling" framing. Trim the edges.** Concretely, in priority order:

1. **Rename `sibling_repos` → `linked_repos`** (or `companion_repos`). Rename env vars to `SASE_LINKED_REPO_*` and the
   memory section to "## Linked Repositories." Keep `sibling_repos` as a deprecated config alias for one release.
   *Payoff:* eliminates the agent-sibling collision — the single biggest conceptual cost — for a low, mechanical price.
   This alone likely resolves most of the "I want this gone" feeling.

2. **Reframe the mental model as "number-aligned linked projects," not a separate subsystem.** A sibling is already a
   `PROJECT_STATE: sibling` project (§1.4). Lean into that: document it as "configured projects whose workspaces stay
   aligned with the primary's number," which makes the feature feel like a small policy over existing project/workspace
   machinery rather than a bespoke concept to carry.

3. **Collapse the strategy split if `none` is unused.** If you don't actually rely on static siblings (chezmoi), drop
   `workspace.strategy` entirely and keep only number-aligned behavior. That deletes a conditional branch from
   resolution, memory rendering, **and** the finalizer's advisory path — real surface reduction without losing the load-
   bearing behavior. (If chezmoi-style static exposure *is* wanted, keep `none` but document it as the one exception.)

4. **Keep, unchanged:** workspace-number parity, the env contract the Justfile depends on, and cross-repo commit
   finalization. These are the parts that earn their keep.

5. **Optional, longer-term:** if the boundary concern (§5) bites, move the *pure resolution* (config → workspace-matched
   paths) into `sase-core` so a future non-TUI frontend gets it for free, leaving only env injection + memory rendering
   in Python.

**If you nonetheless decide the functionality isn't worth it:** follow §4, and explicitly accept (and document for
agents) that related repos are now edited in the shared `../<repo>` checkout, committed manually, and not isolated across
concurrent workspaces. Keep the `Justfile` `SASE_CORE_DIR` override so the Rust build still works.

### Why this beats removal

It addresses the actual pain (overloaded name, sprawl, fuzzy mental model) at a fraction of the cost and risk, while
preserving a multi-repo workflow that SASE — and your own day-to-day work across five aligned repos — currently depends
on. Removal trades a one-time cleanup for a permanent regression in concurrency safety and cross-repo commit hygiene.

---

## Appendix: key file references

| Area | Files |
| --- | --- |
| Core resolution + env | `src/sase/sibling_repos.py:59-405` |
| Launch injection | `src/sase/agent/launch_spawn.py:172-234` |
| Deferred re-resolution | `src/sase/axe/run_agent_phases.py:124-136`, `run_agent_runner_setup.py:218-245` |
| Commit finalizer | `src/sase/llm_provider/commit_finalizer_state.py:31-160`, `commit_finalizer_prompting.py:66-98` |
| Generated memory | `src/sase/main/init_memory/roots.py:62-104`, `init_memory/config.py:177-253` |
| Workspace open / tracking | `src/sase/main/workspace_handler_context.py:95-259`, `workspace_handler_list.py:152-200` |
| Build-time consumer | `Justfile:11-16` (`sase_core_dir` resolution) |
| Config + schema + docs | `default_config.yml:5`, `config/sase.schema.json:729-768`, `docs/configuration.md`, `docs/commit_workflows.md`, `README.md:144-158` |
