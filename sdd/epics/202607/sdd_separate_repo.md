---
create_time: 2026-07-07 23:22:04
bead_id: sase-5j
tier: epic
status: done
prompt: sdd/prompts/202607/sdd_separate_repo.md
---
# Plan: Separate SDD Repository — Provider-Level Opt-In for VCS Workflows

## Product Context

SASE stores prompt snapshots, plans, research notes, and bead state under `sdd/` in the main code repository when
`sdd.version_controlled: true`, and in a local standalone git repo at `<primary>/.sase/sdd` otherwise. The goal: let VCS
xprompt workflows (the `#gh`, `#git`, … workflow providers) **opt in** to a third storage mode where SDD artifacts live
in a **separate companion repository** hosted alongside the code repo (for GitHub: `<owner>/<repo>-sdd`, e.g.
`sase-org/sase-sdd`), cloned locally into `<primary>/.sase/sdd`. BareGit keeps its current in-tree behavior. Providers
that don't opt in see zero change.

Design source: `sdd/research/202607/github_sdd_repo_consolidated.md`. This plan adopts its core recommendation
(companion repo cloned into `.sase/sdd`, policy enum + resolved store, provider-declared opt-in, materialization hook)
and deliberately deviates from it in a few places (see "Deviations from the research" below).

## Verified Current State (2026-07-07 reconnaissance)

**The two-mode seam is small and centralized:**

- `get_sdd_dir(workspace_dir, workspace_num, version_controlled)` exists in **two duplicate copies**:
  `src/sase/sdd/_paths.py:108` and `src/sase/sdd/files.py:76` (the facade re-implements instead of delegating).
- `get_effective_sdd_config()` (`src/sase/sdd/beads.py:18`) returns a **bool**: config `sdd.version_controlled` true →
  VC; else `detect_vcs(cwd) == "bare_git"` forces VC; else local. This is the only provider-specific special case.
- `commit_sdd_files()` (`src/sase/sdd/_commit.py:180`) commits inside the SDD root when it has a `.git`; it never
  pushes. `init_beads()` (`src/sase/sdd/beads.py:36`) already git-inits `.sase/sdd`, writes `.gitignore`, creates beads,
  and commits.
- Bead push posture already exists and survives push failure: `push_bead_work_launch` / `push_bead_work_launch_async`
  (`src/sase/bead/sync.py:248,292`), config precedent `bead.push_after_commit: true|false|async`
  (`src/sase/default_config.yml:386-398`).

**Bool consumers** (all route through the two helpers above): plan accept/archive trio
(`src/sase/plan_approval_actions.py:328-331`, `src/sase/axe/run_agent_exec_plan_accept.py:292-355`,
`src/sase/ace/tui/actions/agents/_notification_modals.py:307-315`), commit hook
(`src/sase/workflows/commit/precommit_hooks.py:177,199`), bead store resolution (`src/sase/bead/cli_common.py:35`,
`src/sase/bead/workspace.py:197-201`, `src/sase/main/bead_fast_path.py:94-121`, `src/sase/sdd/beads.py:92`), and a
display-only site (`src/sase/bead/cli_query.py:142`).

**Rust core is location-agnostic (verified in sase-core).** Every `sase_core_rs` bead/plan API takes fully-resolved
paths: `bead_cli_execute` takes `read_beads_dirs`/`write_beads_dir`, `plan_search` takes
`repo_sdd_root`/`local_plans_dir` (`crates/sase_core_py/src/lib.rs`). No Rust code reads `sase.yml`, knows
`version_controlled`, or picks `sdd/beads` vs `.sase/sdd/beads` — a grep for `version_controlled` across all `.rs`
production code returns zero hits. Python resolves the path once and hands Rust the final directory. **Because the new
mode reuses the exact `.sase/sdd` path and layout of the existing local mode, no sase-core changes are needed.** This
respects the Rust-core boundary as built: path _policy_ has always been Python glue; Rust owns the domain logic on
resolved paths.

**Because separate_repo physically reuses `.sase/sdd`, most literal-path code keeps working unchanged:** the
`.sase/sdd/` vs `sdd/` prefix branches (`src/sase/sdd/_write.py:12-19` `sdd_link_path`, `src/sase/sdd/links.py:338-362`,
`src/sase/axe/run_agent_exec_plan_sdd.py` ref builders, `src/sase/workflows/commit/plan_paths.py:18`), the bead-path
suffix matchers (`src/sase/agent/bead_display.py:163-195`, `src/sase/integrations/_mobile_helper_beads.py:251-416`), and
prompt search roots (`src/sase/prompt/search/sources.py:92-97`) all already handle `.sase/sdd`. The new mode inherits
local-mode behavior for all of them.

**Provider plugin surface:**

- `WorkflowMetadata` (`src/sase/workspace_provider/_hookspec.py:88-111`) is the per-provider declaration record;
  `ws_get_workflow_metadata` is the only collect-all hook. Registry lookups by `vcs_provider_name` exist
  (`get_display_name_by_vcs`, `src/sase/workspace_provider/_registry.py:82`).
- BareGit declares metadata at `src/sase/workspace_provider/plugins/bare_git_workspace.py:78-87` and materializes SDD on
  checkout at `:143-162` (plus `bare_git_init.py:284-296`).
- The GitHub plugin (sase-github repo) registers `sase_vcs` + `sase_workspace` entry points; it has **no** SDD
  references today, **no** `ws_setup_workflow` (workspace setup runs through the `#gh` xprompt's setup step →
  `src/sase_github/scripts/gh_setup.py:24-43` → `resolve_ref` + `ensure_workspace_checkout`), **no** origin-URL →
  owner/repo parser (`normalize_github_host`, `src/sase_github/config.py:12-32`, extracts host only), and **no** repo
  creation logic. It shells to `gh` with `GH_HOST` (`workspace_plugin.py:483-495`) and clones with plain git, SSH then
  HTTPS (`_clone_gh_repo`, `workspace_plugin.py:392-434`). Compat with sase is a version pin (`sase>=0.11.0`).

**Config:** `sdd.version_controlled` is defined at `src/sase/default_config.yml:372-373` and
`src/sase/config/sase.schema.json` (`sdd` object, `additionalProperties: false`). `sase sdd init` writes
`sdd.version_controlled: true` into project `sase.yml` via `src/sase/main/sdd_init_config.py`. The `sase sdd` CLI group
exists (`src/sase/main/parser_sdd.py`: init/validate/links/list/repair-links).

**Known gaps the new mode inherits from local mode (fixed in Phase 6):** plan search's repo corpus only looks at the
in-tree `sdd/` root (`src/sase/plan_search/facade.py:40,54` — local `.sase/sdd` plans are not indexed today); TUI bead
watchers hard-code `Path.cwd()/"sdd"/"beads"` (`src/sase/ace/tui/actions/_startup_watchers.py:53`,
`src/sase/ace/tui/event_refresh/_watcher.py:86`, `_artifact_delta.py:38`); `sase prompt export` writes to
`Path.cwd()/"sdd"/"prompts"` only in VC mode (`src/sase/prompt/cli_export.py:173`).

## Design

### Storage policy model

```python
SddStorage = Literal["in_tree", "local", "separate_repo"]

@dataclass(frozen=True)
class SddStore:
    storage: SddStorage
    sdd_dir: Path              # contains prompts/, tales/, research/, beads/, ...
    repo_root: Path            # git root to commit/push (v1: always == sdd_dir for local/separate_repo)
    provider: str | None = None      # e.g. "github" (separate_repo only)
    remote_url: str | None = None    # separate_repo only
```

Two resolvers, split by cost:

- `resolve_sdd_dir(workspace_dir, workspace_num)` — **dir-only, hot-path-safe.** Pure function of config + provider
  metadata (no store-record read, no network, no subprocess beyond the existing cached `detect_vcs`). Because local and
  separate_repo share the same physical dir, in-tree vs not is decidable without knowing which of the two non-tree modes
  is active. This is what bead fast paths, watchers, and display code use.
- `resolve_sdd_store(workspace_dir, workspace_num)` — **full store.** Additionally reads the persisted store record
  (mtime-cached). Used by commit/push, materialization, doctor, migrate, and status surfaces — none of which are
  keystroke paths.

### Config: `sdd.storage` enum with a compatibility alias

- New key `sdd.storage: auto | in_tree | local | separate_repo`, default `auto`.
- `sdd.version_controlled` becomes a deprecated alias: `true → in_tree`, `false → auto`. If both keys are set, `storage`
  wins; `sase doctor` warns about the alias. Removal is out of scope.
- Later phases add `sdd.push_after_commit: true|false|async` (default `async`; mirrors `bead.push_after_commit`) and
  `sdd.repo.name` (explicit companion repo override, `name` or `owner/name`). No `discover`/`create_if_missing` config
  knobs — discovery policy is fixed (below) and creation is CLI-flag-only.

### Resolution precedence

1. Explicit `sdd.storage` (non-`auto`) wins.
2. Under `auto`: a materialized store record ⇒ `separate_repo`.
3. Else the provider's declared policy via new `WorkflowMetadata.sdd_storage_policy` field (`""` = no opinion,
   `"in_tree"`, `"separate_repo"`): BareGit declares `in_tree` (replacing the hard-coded `detect_vcs == "bare_git"`
   check with a metadata lookup); a provider declaring `separate_repo` means _eligible — materialize at setup_, and
   resolves to `local` until a record exists.
4. Else `local` (current default).

Equivalence with today under `auto` + no record: config true → in_tree; bare_git → in_tree; else local. Exactly current
behavior.

### Store record

`<primary>/.sase/sdd-store.json` (deliberately _next to_, not inside, the store so it never lands in the companion
repo): `{schema_version, storage, provider, host, repo, remote_url, discovery: "found"|"not_found", probed_at}`. Written
only by materialization/migration. A negative record (`discovery: "not_found"`) caches a failed probe so routine
workflow setups never re-probe; `sase sdd init` / `sase sdd migrate` explicitly re-probe.

### Provider opt-in surface (the actual "opt in" mechanism)

Two additions to the `sase_workspace` hook surface:

- `WorkflowMetadata.sdd_storage_policy: str = ""` — cheap, static declaration (backward compatible: existing plugins
  construct the frozen dataclass without the field).
- `ws_materialize_sdd_store(primary_workspace_dir, workspace_dir, options) -> dict | None` (firstresult) — the
  network-capable hook. Called from a host-side `materialize_sdd_store()` orchestrator at _setup-shaped_ moments only
  (workflow setup scripts, `ensure_beads_initialized`, `sase sdd init`) — never on TUI keystroke or render paths. Must
  be cheap when a record already exists (no network; optional async fetch).
- Later (Phase 4): `ws_create_sdd_remote(...)` for explicit `--create` in `sase sdd migrate`.

A provider that implements neither sees zero behavior change — that is the opt-in.

### GitHub materialization (sase-github)

- Derive `(host, owner, repo)` from the primary workspace's `remote.origin.url` (new parser generalizing
  `normalize_github_host`) so GitHub Enterprise and non-default hosts work; fall back to the project ref.
- Companion repo name: explicit `sdd.repo.name` if set, else `<repo>-sdd` by convention. **Auto-probe only
  `<owner>/<repo>-sdd`** (one `gh repo view` with `GH_HOST=<origin host>`); the org-level `sdd` repo is reachable only
  via explicit `sdd.repo.name` and is treated as dedicated to the project (shared multi-project layout is a v1
  non-goal).
- Found ⇒ clone into `<primary>/.sase/sdd` (reuse the SSH-then-HTTPS pattern of `_clone_gh_repo`), run
  `ensure_sdd_initialized` + bead init inside it, write a positive record. Not found ⇒ negative record, keep local mode,
  no error.
- Adoption safety: if `.sase/sdd` already exists with local content and its remote doesn't match the companion, do
  **not** clobber — write a negative record and print a notice pointing at `sase sdd migrate`. If its remote already
  matches, adopt and write a positive record.
- Explicit `sdd.storage: separate_repo` with no discoverable/materializable repo ⇒ **loud, actionable error** on write
  paths (never a silent fall-back to in-tree or local writes); dir-only reads keep working offline against an existing
  clone.

### Commit/push posture

- `commit_sdd_files()` stays the single commit entry point (v1 keeps `repo_root == sdd_dir`, so it needs only a
  store-aware wrapper, not a layout generalization).
- After a successful SDD commit in a `separate_repo` store: push per `sdd.push_after_commit` (`true|false|async`,
  default `async`), reusing the bead sync push helpers. Local commit always survives push failure (bead posture). The
  TUI plan-archive path must never block the event loop — detached/async push only there (per `memory/tui_perf.md`
  rules).
- Fetch/pull: fast-forward-only fetch at materialization points, bounded by the existing `SASE_SDD_GIT_NETWORK_TIMEOUT`;
  never on hot paths. Divergence is surfaced by doctor, not auto-resolved.
- Code commits keep carrying only logical `PLAN=` references; SDD files are never staged into code-repo commits in
  non-in-tree modes (current behavior, pinned by tests).

### Deviations from the research (deliberate)

1. **No `logical_prefix` machinery in v1.** The research proposes teaching `sdd/...` references to resolve into the
   physical `.sase/sdd/...` store. Since separate_repo reuses the local-mode path, every existing reference builder and
   resolver (`sdd_link_path`, `links.py`, plan-ref builders) already produces/consumes `.sase/sdd/...` refs that work
   end-to-end. v1 keeps that convention; logical `sdd/` aliasing is deferred (agent-facing discovery is instead solved
   by `sase sdd path` + `SASE_SDD_DIR`, Phase 5). This removes the riskiest cross-cutting change from v1.
2. **No `sdd.repo.discover` / `sdd.repo.create_if_missing` config.** Discovery is a fixed, cheap, cached-once policy;
   creation is an explicit `sase sdd migrate --create` action. Fewer knobs, same capabilities.
3. **No `<owner>/sdd` auto-probe.** A bare org-level `sdd` repo auto-claimed by every project in the org is a foot-gun
   without namespacing; explicit config covers the dedicated case.
4. **No sase-core changes.** Verified location-agnostic (see Current State); adding a storage enum to Rust would be new
   API with no consumer.

## Decisions called out for review

1. **Auto-discovery is on by default for opted-in providers** (probe once at setup, cached in the record). Creating
   `<owner>/<repo>-sdd` and running one workflow setup (or `sase sdd init`) activates the mode — no per-project config
   required. Alternative: require explicit `sdd.storage: separate_repo` per project; say so and Phases 3–4 shrink.
2. **`sdd.push_after_commit` defaults to `async`** (bead default is sync `true`). Rationale: SDD writes happen inside
   plan-approval UX and TUI actions where sync network latency is unacceptable; detached push with logged failures is
   the proven bead pattern.
3. **`sase sdd migrate` writes `sdd.storage: separate_repo` into the project `sase.yml`** (mirroring how `sase sdd init`
   writes config today), making migrated projects explicit rather than record-dependent.
4. **New-repo default visibility on `--create` is `--private`.**
5. **This repo's own migration to `sase-org/sase-sdd` is an operational follow-up**, not a phase: Phase 4 delivers the
   command; actually running it against the sase repo (and removing the tracked `sdd/` tree) is a separate user
   decision.

## Non-goals (v1)

- Multi-project shared SDD repo with per-project namespaces.
- Submodules, symlinks, or a companion checkout containing a top-level `sdd/` (i.e. `repo_root != sdd_dir` layouts) —
  `SddStore.repo_root` exists so this can come later without another refactor.
- Moving SDD storage policy into sase-core.
- Mercurial/other-provider opt-ins (the seam supports them; nothing ships).
- Removing `sdd.version_controlled` (alias + warning only).

## Phasing Overview

Six phases. Each is completed by a distinct agent instance, is independently landable (green `just check`, committed),
and leaves every existing project's behavior unchanged until Phase 3 activates GitHub. Every phase agent must run
`just install` before other `just` commands (ephemeral workspaces) and `just check` before finishing. Agents needing
linked-repo access must use `sase workspace open -p <repo> -r "<reason>" <workspace_num>` (their own primary-repo
workspace number) — never sibling paths.

| Phase | Deliverable                                                              | Repo(s)             | Depends on |
| ----- | ------------------------------------------------------------------------ | ------------------- | ---------- |
| 1     | `SddStore` model, `sdd.storage` config, resolvers, call-site conversion  | sase                | —          |
| 2     | Materialization framework, store record, SDD commit→push plumbing        | sase                | 1          |
| 3     | GitHub opt-in: discovery, clone/adopt, record write                      | sase-github (+sase) | 2          |
| 4     | `sase sdd migrate` (+`--create`), doctor checks, `sase sdd init` storage | sase (+sase-github) | 3          |
| 5     | Agent-facing paths: `sase sdd path`, `SASE_SDD_DIR`, README/skills, docs | sase                | 1          |
| 6     | Store-aware consumers: plan search, TUI bead watchers, prompt export     | sase                | 1          |

Phases 5 and 6 may run in parallel with 2–4.

---

## Phase 1 — Storage policy model, config, and call-site conversion (pure equivalence)

**Goal:** replace the boolean seam with the enum + `SddStore` model so every caller consumes one resolver. Zero behavior
change, proven by tests.

**Scope:**

1. New module (e.g. `src/sase/sdd/store.py`): `SddStorage`, `SddStore`, `resolve_sdd_dir()`, `resolve_sdd_store()`,
   store-record reader (mtime-cached; nothing writes records yet), and the precedence logic from the Design section.
2. Config: add `sdd.storage` to `src/sase/default_config.yml` and `src/sase/config/sase.schema.json`; implement the
   `version_controlled` alias mapping (`storage` wins when both set). Keep `src/sase/main/sdd_init_config.py` write-side
   behavior unchanged for now (Phase 4 teaches it the enum).
3. `WorkflowMetadata.sdd_storage_policy: str = ""` (`src/sase/workspace_provider/_hookspec.py`) + registry lookup by
   `vcs_provider_name` (pattern of `get_display_name_by_vcs`, `_registry.py:82`); BareGit declares `"in_tree"`
   (`bare_git_workspace.py:78-87`), and the resolver uses metadata instead of the hard-coded
   `detect_vcs(cwd) == "bare_git"` check in `get_effective_sdd_config` (preserve its best-effort/non-fatal posture
   outside repos).
4. Deduplicate `get_sdd_dir` (make `src/sase/sdd/files.py:76` delegate to `_paths.py`); keep `get_sdd_dir` /
   `get_effective_sdd_config` as thin compatibility wrappers over the resolvers.
5. Convert the bool call sites to the storage-aware API: the plan accept/archive trio, `precommit_hooks.py:177`,
   `bead/cli_common.py`, `bead/workspace.py`, `main/bead_fast_path.py`, `sdd/beads.py` (`ensure_beads_initialized`),
   `bead/cli_query.py:142`. Semantics: `in_tree` behaves exactly like today's `True`; `local` and `separate_repo` behave
   exactly like today's `False` (only later phases make separate_repo differ, and only in commit/push flows).
6. Tests: an equivalence matrix (config value × alias × detected VCS → storage, sdd_dir, beads dir) covering bare-git
   invariance; record-precedence unit tests; alias-conflict behavior; and pinning that bead fast-path dirs and
   plan-write dirs are byte-identical to pre-change behavior.

**Non-scope:** no record writes, no hooks, no push, no CLI changes, no provider activation.

**Acceptance:** `just check` green; no test outside the new suites needed a behavioral update (test-support/plumbing
edits are fine); grep shows no remaining direct consumers of `sdd.version_controlled` besides the alias mapping and
`sdd_init_config.py`.

---

## Phase 2 — Materialization framework and SDD push plumbing (inert until a provider opts in)

**Goal:** the host-side machinery a provider needs: the materialization hook, record persistence, and push-after-commit
for stores with remotes. Ships with no opted-in provider, so real behavior is unchanged; framework is proven with a fake
plugin in tests.

**Scope:**

1. `ws_materialize_sdd_store` hookspec (firstresult) + registry dispatch, and a host orchestrator
   `materialize_sdd_store(workspace_dir, workspace_num)` that: short-circuits fast when a record exists (no network),
   consults `sdd_storage_policy` to decide whether to invoke the hook, validates/writes the store record
   (`<primary>/.sase/sdd-store.json`, schema-versioned, write side of the Phase 1 reader), and runs
   `ensure_sdd_initialized` + bead init inside a newly materialized store (reusing `init_beads`-shaped logic).
2. Wire the orchestrator into setup-shaped call sites: `ensure_beads_initialized` (`src/sase/sdd/beads.py:85`) and the
   `sase sdd init` handler (`src/sase/main/sdd_handler.py`). Keep it off TUI render/keystroke paths.
3. Push-after-commit: `sdd.push_after_commit` config (`true|false|async`, default `async`; schema + default_config.yml)
   consumed by a store-aware wrapper around `commit_sdd_files()` — push only when the resolved store is `separate_repo`
   and a remote exists, reusing/parameterizing the bead push helpers (`src/sase/bead/sync.py:248,292`). Convert the SDD
   commit call sites (plan accept, bead init, TUI archive) to the wrapper. TUI paths use async/detached push only (see
   `memory/tui_perf.md` — agents touching TUI actions must read it via `sase memory read`).
4. Explicit-config guard: `sdd.storage: separate_repo` with no record and no provider hook result ⇒ actionable error on
   materialization and on SDD write paths (message names the expected repo and points at `sase sdd migrate`).
5. FF-only fetch of an existing clone during materialization (bounded by `SASE_SDD_GIT_NETWORK_TIMEOUT`), failure
   non-fatal.
6. Tests: fake workspace plugin registering the hook (pattern: existing plugin-manager tests); record round-trip; push
   matrix (`true|false|async` × remote/no-remote × push-failure-survives); no-op guarantees when no provider opts in;
   explicit-config error paths.

**Acceptance:** `just check` green; with no plugins implementing the hook, an end-to-end run over all three storage
configs is behaviorally identical to Phase 1.

---

## Phase 3 — GitHub provider opt-in (sase-github, plus small sase-side integration)

**Goal:** the first real opt-in. GitHub-backed projects with a `<owner>/<repo>-sdd` companion repo start using it
automatically at workflow setup; everyone else stays on local mode with a cached negative probe.

**Repos:** primarily `sase-github` (open via `sase workspace open -p sase-github -r "<reason>" <workspace_num>`); a
small `sase` change only if the setup-script seam needs it.

**Scope:**

1. Origin parsing: extend `src/sase_github/config.py` with a `remote.origin.url` → `(host, owner, repo)` parser
   (generalizing `normalize_github_host`, `config.py:12-32`; handle scp/ssh/https forms and ports).
2. Metadata: `GitHubWorkspacePlugin.ws_get_workflow_metadata` declares `sdd_storage_policy="separate_repo"`
   (`workspace_plugin.py:57-66`). Bump the `sase>=` pin in `pyproject.toml` to the release carrying Phases 1–2 (old sase
   would reject the new `WorkflowMetadata` kwarg).
3. `ws_materialize_sdd_store` implementation: record exists ⇒ verify clone + optional async fetch, return. No record ⇒
   resolve companion name (`sdd.repo.name` override, else `<repo>-sdd`), probe once via `gh repo view` with
   `GH_HOST=<origin host>` and the non-interactive env helpers (`workspace_plugin.py:483-495`), clone SSH-then-HTTPS
   into `<primary>/.sase/sdd` (pattern of `_clone_gh_repo`, `:392-434`), or write a negative record. Implement the
   adoption rules from the Design section (never clobber a divergent local store; adopt a matching remote).
4. Trigger materialization from the `#gh` workflow setup step (`src/sase_github/scripts/gh_setup.py:24-43`) after
   `ensure_workspace_checkout`, so setup — the moment that already does network work — is where discovery happens.
5. `sdd.repo.name` config key (sase schema — small sase-side change in this phase or pre-staged in Phase 2; keep the
   schema's `additionalProperties: false` satisfied).
6. Tests (sase-github conventions: mock `subprocess.run` at `sase_github.workspace_plugin`, on-disk fake `gh` for
   script-level tests; `_home_patches`-style fixtures): probe/clone/adopt/negative-record matrix, enterprise host
   derivation from origin (not the default-host config), offline probe failure (network error ≠ durable "not found" — do
   not write a negative record on transport errors), and gh_setup wiring.

**Acceptance:** both repos' checks green (`just check` in sase; sase-github's own test suite per its README/CI). A
GitHub project with an existing companion repo picks it up on next workflow setup; a project without one behaves exactly
as before with a single cached probe; bare-git and non-GitHub projects are untouched.

---

## Phase 4 — Migration and creation tooling, doctor coverage

**Goal:** a supported path from both existing modes into a companion repo, plus health checks so the new state is
inspectable and misconfigurations are loud.

**Scope:**

1. `sase sdd migrate` subcommand (`src/sase/main/parser_sdd.py` — follow `memory/cli_rules.md`: alphabetized listings,
   short aliases for every long option, excellent help; agents must read it via `sase memory read`):
   - From **local**: the `.sase/sdd` repo already exists — point/verify remote, push, write record + config.
   - From **in_tree**: copy the tracked `sdd/` tree into the materialized store (fresh clone or init+remote), commit,
     push; optional `--remove-in-tree` removes the tracked `sdd/` from the code repo in a clearly-labeled separate
     commit (default off).
   - `--create` creates the missing companion repo via a new optional `ws_create_sdd_remote` hook; GitHub implements it
     with `gh repo create <owner>/<repo>-sdd --private` (first repo-creation logic in sase-github — none exists today).
   - Writes `sdd.storage: separate_repo` into project `sase.yml` (extend `src/sase/main/sdd_init_config.py`, which
     already owns config patching) and re-probes/refreshes the store record.
2. `sase sdd init` learns the enum: a storage option (replacing the implicit "init means in-tree" assumption) and
   record-aware behavior; explicit re-probe of a cached negative record.
3. Doctor (`src/sase/doctor/checks_config_sdd.py`, `checks_beads.py`): record↔config consistency, deprecated
   `version_controlled` alias warning, companion divergence (ahead/behind, offline-tolerant), duplicate-remote collision
   (two projects claiming the same companion repo), orphaned record (record present, clone missing).
4. Tests: migrate from each mode (including idempotent re-run), `--create` hook dispatch with a fake provider,
   `--remove-in-tree` commit isolation (SDD removal commit contains nothing else), doctor check matrix.

**Acceptance:** `just check` green (both repos if sase-github changes); a local-mode project can be migrated end-to-end
against a fake/`gh`-mocked provider in tests; `sase sdd validate`/doctor report coherent status for all three modes.

---

## Phase 5 — Agent-facing path discovery and documentation

**Goal:** agents and prompts stop assuming `sdd/...` is a workspace-relative path. This closes the research file's
biggest practical gap: prompts that say "write under `sdd/research/...`" produce code-repo files in non-in-tree modes.

**Scope:**

1. `sase sdd path [kind]` subcommand: prints the effective SDD root (no args) or `<root>/<kind>` (validated against the
   canonical kinds in `src/sase/sdd/_paths.py:7-15`), using the dir-only resolver. Follow `memory/cli_rules.md` (read
   via `sase memory read`).
2. Export `SASE_SDD_DIR` in launched agents' environment (resolved once at launch alongside the existing agent env
   assembly), so prompt templates and hooks can reference it without shelling out.
3. Generated SDD guidance: update the README/directory-map templates (`src/sase/sdd/_init_files.py:31-77`) so path
   examples are phrased relative to the SDD root and mention `sase sdd path` for non-in-tree modes; refresh CLI
   help/example strings that hard-code `sdd/research/...` (`src/sase/main/parser_memory.py:21,147`).
4. xprompt skill sources that hard-code `sdd/...` paths (`src/sase/xprompts/skills/sase_beads.md:26-185`, and the plan
   skill source if applicable): teach them the `sase sdd path`/`SASE_SDD_DIR` convention. Generated-skill rules apply —
   agents must read `memory/generated_skills.md` via `sase memory read`; sources are edited in-repo and the user deploys
   with `sase skill init --force` + `chezmoi apply`.
5. Docs (mkdocs): an "SDD storage" page covering the three modes, precedence, the companion-repo convention, migration,
   and offline/push behavior.
6. Tests: `sdd path` output across the three modes; agent-env export presence; template snapshot updates.

**Acceptance:** `just check` green; an agent in a non-in-tree project can locate the research/plans directories using
only documented, generated-into-context surfaces (`sase sdd path` / `SASE_SDD_DIR`).

---

## Phase 6 — Store-aware consumers: plan search, TUI watchers, prompt export

**Goal:** point the remaining hard-coded consumers at the resolved store. These are deliberate small behavior
_improvements_ for non-in-tree modes (they also fix today's local-mode gaps), isolated here so the equivalence phases
stay pure.

**Scope:**

1. Plan search: `src/sase/plan_search/facade.py:40` resolves the repo corpus root through the dir-only resolver instead
   of only the in-tree `sdd/` (Rust `plan_search` already takes the root as an argument — no binding change). Update
   source labels (`src/sase/main/plan_search_render.py:39`) so non-in-tree roots display sensibly.
2. TUI bead watchers: `_startup_watchers.py:53`, `event_refresh/_watcher.py:86`, `_artifact_delta.py:38` watch the
   resolved beads dir (resolved once at startup/mount; dir-only resolver; no event-loop I/O — read `memory/tui_perf.md`
   via `sase memory read` before touching these).
3. `sase prompt export` (`src/sase/prompt/cli_export.py:173`): write SDD snapshots into the resolved store in all modes,
   not just VC.
4. Audit-and-decide (fix or explicitly record as fine): `src/sase/core/health.py:199`,
   `src/sase/doctor/checks_beads.py:105-117` candidate dirs, `src/sase/prompt/search/sources.py:92-97`.
5. Tests: plan search finds plans in a `.sase/sdd` store; watcher targets per mode; export destination per mode. TUI
   changes run `just test-visual` if any snapshot-covered surface changes.

**Acceptance:** `just check` green; in a local or separate_repo project, plan search returns store plans, the TUI bead
watcher fires on store bead changes, and in-tree projects behave identically to before.

---

## Risks / edge cases

- **Equivalence regressions in Phase 1** — the highest-risk phase by blast radius. Mitigation: the matrix tests are the
  acceptance gate; `local`/`separate_repo` are indistinguishable everywhere except commit/push until Phase 2+.
- **Surprise activation** (Decision 1): a pre-existing `<repo>-sdd` repo in an org flips a project to separate_repo at
  next setup. Mitigations: exact-name convention, loud one-time notice on materialization, adoption rules never clobber,
  `sase sdd migrate`/doctor make state inspectable, explicit `sdd.storage: local` opts out permanently.
- **Cross-repo version skew**: new sase-github on old sase fails constructing `WorkflowMetadata` (unknown kwarg) —
  handled by the version pin bump in Phase 3; old sase-github on new sase is safe (defaulted field, unimplemented hooks
  return None).
- **Network on setup paths**: probes/clones/fetches are confined to setup-shaped moments, bounded by
  `SASE_SDD_GIT_NETWORK_TIMEOUT`, and cached; transport errors never write durable negative records.
- **Concurrent materialization** (two workflow setups racing): record writes must be atomic (write-temp + rename) and
  clone-into-temp + rename, so a loser observes the winner's store.
- **Multi-machine divergence** of the companion repo: FF-only fetch + doctor divergence check; no auto-merge. Bead JSONL
  is append-friendly but conflicts still surface as push failures with logged output (bead posture).
- **Agents writing `sdd/...` literally** in non-in-tree projects remains possible until Phase 5 lands (and habits
  persist); Phase 5's generated guidance + env var is the mitigation, and in-tree projects are unaffected.
