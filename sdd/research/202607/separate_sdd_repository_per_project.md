---
create_time: 2026-07-07
updated_time: 2026-07-07
status: research
---

# Storing SDD Docs in a Separate Per-Project Repository

## Problem statement

Today, plans, prompts, research markdown, and bead state all live under `sdd/`
**inside the main code repo** and are committed to its git history. This repo
sets `sdd.version_controlled: true` (`sase.yml:5`), so every plan approval and
bead mutation lands a `chore:`-style commit next to the real feature/fix
commits.

The clutter is measurable: **76 of the last 200 commits on `master` (38%)** are
SDD/bead housekeeping — e.g. `chore: Add SDD prompt and plan for …`,
`chore(beads): close sase-5i.5`, `chore: Mark SDD plan done`. These interleave
with `feat(...)`/`fix(...)` commits and dominate `git log`.

**Goal.** Move a project's SDD docs into a *separate* GitHub repo, discovered in
the same GitHub org under the name `sdd` or `<project>-sdd` (e.g.
`sase-org/sase-sdd`). The behavior must be **opt-in per VCS type**: the GitHub
VCS opts in; BareGit repos keep today's behavior unchanged; other/unknown VCS
types are unaffected.

## TL;DR recommendation

**The "separate SDD repo" is ~80% already built.** SASE's *non*-version-controlled
SDD mode already materializes `.sase/sdd/` as a **standalone git repo** (`git
init`, its own `.gitignore`, its own auto-commit path via `commit_sdd_files`).
It is simply **local-only** — it has no remote, so nothing is ever pushed or
shared.

The cleanest path is therefore **not** a new subsystem but a **third SDD storage
mode** layered on that existing standalone-repo machinery:

1. Turn the current boolean SDD mode (`get_effective_sdd_config`) into a
   **three-way policy** — `in_tree` / `local` / `separate_repo` — where the
   default is **declared by each workspace plugin** as a `WorkflowMetadata`
   capability (BareGit → `in_tree`, GitHub → `separate_repo`), read through a
   `get_*_by_vcs` lookup like the existing `get_display_name_by_vcs`. This
   replaces the current hard-coded `detect_vcs(...) == "bare_git"` seam and its
   scattered duplicates, and is the literal "each VCS type opts in" mechanism.
2. Add a **VCS-provider materialization hook** that resolves the remote SDD repo:
   the GitHub plugin discovers `<org>/<project>-sdd` or `<org>/sdd` (using the
   `gh repo list` machinery it already has), clones it into `.sase/sdd`, and
   wires push; BareGit returns `None` → falls back to today's `in_tree`
   behavior.
3. Reuse the existing standalone-repo commit path (`commit_sdd_files`) plus the
   existing bead push machinery (`push_bead_work_launch*`) to commit **and now
   push** to the SDD remote.

This satisfies "opt-in per VCS type," reuses proven code, and leaves BareGit
untouched. Details, alternatives, and the open decisions are below.

---

## 1. How SDD storage works today

### 1.1 Two modes, one switch

Everything hinges on the `sdd.version_controlled` config flag
(`src/sase/config/sase.schema.json` → `sdd.version_controlled`, default `false`
at `src/sase/default_config.yml:373`):

| Mode | `version_controlled` | SDD root | Committed to | Has remote? |
|---|---|---|---|---|
| **VC / in-tree** | `true` | `<workspace>/sdd/` | the **main repo** | via main repo |
| **non-VC / local** | `false` (default) | `<primary>/.sase/sdd/` | a **standalone `.sase/sdd/.git`** | **no** (local only) |

- Resolver: `get_sdd_dir(workspace_dir, workspace_num, version_controlled)` at
  `src/sase/sdd/_paths.py:108` (facade re-export `src/sase/sdd/files.py:76`).
- Decision function: `get_effective_sdd_config()` at `src/sase/sdd/beads.py:18`.

### 1.2 The mode is already resolved per VCS provider

`get_effective_sdd_config` is **not** a pure config read — it already forces
`bare_git` to VC mode regardless of config (`src/sase/sdd/beads.py:29-33`):

```python
configured = get_sdd_config()          # config["sdd"]["version_controlled"]
if configured:
    return True
cwd = ... workspace_dir ...
return detect_vcs(str(cwd)) == "bare_git"   # bare_git ⇒ always in-tree
```

**This is exactly the opt-in seam the user is asking for.** "BareGit keeps the
old behavior; GitHub opts into the new behavior" is a natural extension of a
function that *already* branches on `detect_vcs(...)`.

### 1.3 The non-VC mode already builds a standalone repo

The most important existing fact for this project: non-VC mode isn't just "a
folder outside the tree" — it is a **real git repo** that SASE creates and
auto-commits to:

- `init_beads()` (`src/sase/sdd/beads.py:36-82`) creates `.sase/sdd/`, runs
  `git init`, writes a `.gitignore` (`beads/beads.db`), initializes beads, and
  calls `commit_sdd_files(...)`.
- `commit_sdd_files(sdd_dir, message, …)` (`src/sase/sdd/_commit.py:180-226`)
  does `git add` + `git commit` **inside `.sase/sdd/.git`**, no-op if it isn't a
  git repo. Docstring: *"Auto-commit SDD files in a local `.sase/sdd/` git
  repo."*
- The only thing missing versus a "separate GitHub repo" is a **remote** — no
  `git remote add`, no clone-from-remote, no push. `commit_sdd_files` never
  pushes.

### 1.4 What writes and commits SDD content

Write side (all funnel through `get_sdd_dir` / `get_effective_sdd_config`):

- **Plans/prompts** land on plan approval — `write_sdd_files(sdd_dir, …)`
  (`src/sase/sdd/_write.py:43`) writes `…/prompts/YYYYMM/<name>.md` and
  `…/<kind>/YYYYMM/<name>.md`; driven from
  `src/sase/axe/run_agent_exec_plan_accept.py:276-355` and
  `src/sase/plan_approval_actions.py:306-349`.
- **Beads** — `find_beads_location()` (`src/sase/bead/cli_common.py:15-53`)
  returns `(root, "sdd/beads")` in VC mode or `(primary/.sase/sdd, "beads")` in
  non-VC mode. Bead data is written by an **in-process Rust extension**
  (`sase.core.bead_*_facade`), not a `bd` subprocess. `beads.db` is gitignored
  (`.gitignore:62`); `issues.jsonl`, `config.json`, `metadata.json`, `events/**`
  are tracked.

Commit side — **three distinct paths**, selected by mode:

1. **VC plan/prompt** → `commit_sdd_files_for_exec_plan()`
   (`src/sase/axe/run_agent_exec_plan_sdd.py:14-70`) shells out to
   **`sase commit -M <msg> -f <prompt> -f <plan>`** in the main repo. This is
   the source of the `chore: Add SDD prompt and plan for <name>` commits.
2. **non-VC plan/prompt** → `commit_sdd_files()` inside `.sase/sdd/.git`
   (`src/sase/sdd/_commit.py:180`).
3. **init/scaffold** → `ensure_bare_git_sdd_initialized()` /
   `commit_bare_git_sdd_init_paths()` (`src/sase/sdd/_commit.py:229,318`).

Beads have their own commit + **push** machinery already:
`commit_bead_work_launch()` and `push_bead_work_launch*()`
(`src/sase/bead/sync.py:49,248,292`), gated on a configured remote
(`push_bead_work_launch` returns `skipped_no_remote` when `git remote` is empty,
`sync.py:259-267`) and on `bead.push_after_commit` config
(`src/sase/bead/cli_work_commit.py:27`). **Push infra already tolerates
"no remote configured" gracefully** — it just becomes active once `.sase/sdd`
has one.

### 1.5 Plan references are mode-aware (a subtlety to preserve)

Downstream agents are handed a *path reference* to the plan/prompt, and that
reference already differs by mode: `build_sdd_plan_ref()` /
`build_saved_plan_ref()` (`src/sase/axe/run_agent_exec_plan_sdd.py:73-107,
255-277`) emit `sdd/<kind>/…` in VC mode but `.sase/sdd/<kind>/…` in non-VC
mode. A third mode needs a defined reference scheme (see Open Questions §6).

---

## 2. The plugin architecture (where "opt-in per VCS type" lives)

SASE has **two** pluggy plugin systems, both entry-point discovered, both
implemented by the GitHub plugin package (`sase-github`, a numbered-workspace
linked repo):

- **`sase_vcs`** (`src/sase/vcs_provider/`, hookspec `_hookspec.py`) — commit /
  mail / classify. Entry point `github = sase_github.plugin:GitHubPlugin`
  (`sase-github/pyproject.toml:24`). `bare_git` lives in
  `src/sase/vcs_provider/plugins/bare_git.py`.
- **`sase_workspace`** (`src/sase/workspace_provider/`, hookspec `_hookspec.py`)
  — ref/workspace resolution, repo completion, submit. Entry point
  `github = sase_github.workspace_plugin:GitHubWorkspacePlugin`
  (`sase-github/pyproject.toml:27`). `bare_git` lives in
  `src/sase/workspace_provider/plugins/bare_git_*.py`.

VCS type (`"github"` / `"bare_git"` / `"hg"`) is resolved by `detect_vcs(cwd)`
(`src/sase/vcs_provider/_registry.py:112`): plugins classify via
`vcs_classify_repo` (GitHub claims repos whose `remote.origin.url` host is a
configured GitHub host — `sase_github/plugin.py:19-41`), falling back to
`bare_git` for any other resolvable remote.

### 2.1 GitHub already knows how to find & clone org repos

The exact primitive the feature needs already exists in the GitHub workspace
plugin:

- **Org repo discovery:** `_list_github_repo_candidates(namespace)`
  (`sase_github/workspace_plugin.py:480`) runs
  `gh repo list <namespace> --json name,description,visibility,…`. The org list
  comes from `get_github_orgs()` (`sase_github/config.py:55`, reads
  `github_orgs` config).
- **Clone:** `_clone_gh_repo(user, project, target_dir, host=…)`
  (`sase_github/workspace_plugin.py:392`) tries SSH then HTTPS.
- **Workspace path convention:** primary clones live at
  `~/projects/github/<owner>/<project>/` (`_github_workspace_dir`,
  `workspace_plugin.py:639`).
- Gap: there is **no `gh repo create`** anywhere in `sase-github` — so
  "repo doesn't exist yet" needs a decision (§6).

So GitHub-side "search the org for `sdd` / `<project>-sdd`, then clone it" is a
small composition of functions that already exist; BareGit has no equivalent and
should simply decline.

### 2.2 `WorkflowMetadata` is the idiomatic place to *declare* the opt-in

Each workspace plugin already publishes a `WorkflowMetadata` record via
`ws_get_workflow_metadata` (`src/sase/workspace_provider/_hookspec.py:88-111`),
aggregated and cached by `get_all_workflow_metadata()`
(`src/sase/workspace_provider/_registry.py:44-47`). It already carries
`vcs_provider_name` — **the exact join key `detect_vcs()` returns** — and the
repo already has the lookup template `get_display_name_by_vcs(vcs_name)`
(`_registry.py:82-95`), which finds the metadata whose `vcs_provider_name`
matches and falls back to family.

This means the "opt-in per VCS type" the user wants is idiomatically a
**plugin-declared capability field on `WorkflowMetadata`**, not another
hard-coded string check. The GitHub plugin (external `sase-github`) can then
opt itself in, and BareGit (built-in) declares the old behavior — no core code
needs to special-case provider names.

Today the per-VCS SDD decision is instead **hard-coded to
`detect_vcs(...) == "bare_git"`** and duplicated across several files (see §5),
which is the pattern to replace.

---

## 3. Design options considered

### Option A — Third SDD storage mode built on the standalone-repo machinery ✅ (recommended)

Extend the existing `.sase/sdd` standalone-repo mode with a remote.

- `get_effective_sdd_config` → returns a **policy enum** `in_tree | local |
  separate_repo` instead of a bool. Resolution:
  - `bare_git` → `in_tree` (unchanged old behavior).
  - `github` + feature enabled → `separate_repo`.
  - otherwise → today's default (`local` when config false, `in_tree` when true).
- A new **VCS-provider hook**, e.g. `vcs_resolve_sdd_repo(project, cwd)` (on
  `sase_vcs`) or `ws_resolve_sdd_repo(...)` (on `sase_workspace`), returns an
  `SddRepoResolution { local_path, remote_url } | None`. GitHub implements it
  via discovery+clone into `.sase/sdd`; BareGit returns `None`.
- SDD dir stays `<primary>/.sase/sdd` (so the ~10 hardcoded `.sase/sdd`
  path-tail checks and TUI watchers keep working), but that directory is now a
  clone of the remote SDD repo with `origin` set.
- Commit path is the already-working `commit_sdd_files`; add a push (reusing
  `push_bead_work_launch*` / a sibling `push_sdd_files`) gated on the resolved
  remote and a `sdd.push_after_commit`-style config.

**Pros:** minimal new surface; reuses standalone-repo + push code; the
"separate repo" is literally the shipped non-VC mode + a remote; BareGit
untouched; the per-VCS decision is where it already is.
**Cons:** SDD content moves out of the main repo — plan/prompt path references
handed to agents change (§6); a few hardcoded `Path.cwd()/"sdd"` spots assume
in-tree (§5).

### Option B — Model the SDD repo as a "role: sdd" linked repo

Reuse the mature `linked_repos` mechanism (numbered `<name>_<N>` clones,
independent per-repo commit via the finalizer, env exposure, agent-memory
instructions — `src/sase/linked_repos.py`, `src/sase/workspace_provider/store.py`).

Add an optional `role: sdd` discriminator to a `linkedRepo` entry
(`sase.schema.json` `linkedRepo` def) and teach `get_sdd_dir` to redirect into
that linked repo's resolved workspace dir.

**Pros:** the heavy transport (second numbered clone, independent commits,
revert, env) already exists.
**Cons:** significant impedance mismatch. Linked repos are **path-based** with
**no `url` / no remote clone / no auto-discovery** — they assume a local
checkout already exists at `path` (`src/sase/linked_repos.py:365-370`), so the
org-discovery+clone is still net-new. Linked-repo commits are **agent-driven**
(`cd <path>` then `/sase_git_commit` in the finalizer,
`src/sase/llm_provider/commit_finalizer_prompting.py:66-98`), whereas SDD
commits today are **automatic** (`commit_sdd_files`, bead sync). Bending SDD's
automatic, path-hardcoded flow onto per-`<N>` linked clones is more disruptive
than Option A. Linked repos also reuse the `PROJECT_STATE: sibling` lifecycle
machinery, which would need an SDD discriminator anyway.

### Option C — Keep in-tree, rewrite/split history later

Rejected: doesn't address ongoing clutter, and history surgery is disruptive.

### Option A vs B verdict

Option A wins because SDD's write/commit flow is already **automatic and
centralized** around `.sase/sdd` as a standalone repo. Option B's strengths
(per-`<N>` isolation, agent-driven commits) are things SDD does **not** need —
docs are shared metadata, not per-agent code under edit. Reuse the mechanism
that already matches SDD's shape (the standalone repo), not the one built for
code siblings.

---

## 4. Recommended approach (detail)

**Introduce `separate_repo` as a per-VCS SDD storage mode, backed by the
existing `.sase/sdd` standalone repo plus a GitHub-provided remote.**

1. **Config surface.** Add an `sdd` sub-config, e.g.:
   ```yaml
   sdd:
     storage: auto        # auto | in_tree | local | separate_repo
     repo:
       discover: true     # search the org for sdd / <project>-sdd
       name: ""           # explicit override, else auto-discovered
       create_if_missing: false
     push_after_commit: true
   ```
   Keep `version_controlled` working as a deprecated alias
   (`true → in_tree`, `false → auto`) during a compat window, mirroring the
   `linked_repos`/`sibling_repos` alias pattern (`src/sase/linked_repos.py:36`).
   Remember to update `src/sase/config/sase.schema.json` (this repo's #1 gotcha).

2. **Declare the opt-in as a plugin capability (not a string check).** Add a
   capability field to `WorkflowMetadata`
   (`src/sase/workspace_provider/_hookspec.py:88-111`) — e.g.
   `sdd_storage_default: "in_tree" | "separate_repo" | "local"` (or a general
   `capabilities: frozenset[str]`). BareGit declares `in_tree` (in
   `bare_git_workspace.py`'s `ws_get_workflow_metadata`); the external
   `sase-github` plugin declares `separate_repo`. Add a lookup helper next to
   `get_display_name_by_vcs` — e.g. `get_sdd_storage_by_vcs(vcs_name)` in
   `src/sase/workspace_provider/_registry.py:82-95` — keyed on the
   `detect_vcs()` result. This is the true "each VCS type opts in" mechanism:
   the plugin owns the decision.

3. **Policy resolution.** Convert `get_effective_sdd_config`
   (`src/sase/sdd/beads.py:18-33`) into `resolve_sdd_storage(cwd) -> SddStorage`
   (enum), replacing the hard-coded `== "bare_git"` with
   `get_sdd_storage_by_vcs(detect_vcs(cwd))`, still allowing explicit `sdd`
   config to override. Every current caller of `get_effective_sdd_config`
   (~10 sites: `bead/cli_common.py:35`, `bead/workspace.py:198`,
   `main/bead_fast_path.py:101`, `workflows/commit/precommit_hooks.py:177`,
   `axe/run_agent_exec_plan_accept.py:292`, TUI notification modals, …) maps the
   enum back to "does SDD live in-tree?" plus "where is the SDD dir?". Also
   re-point the *other* hard-coded `== "bare_git"` sites (§5) at the same helper.

4. **VCS-provider hook for the remote (materialization).** The metadata field
   declares *policy*; a separate hook does the *network work*. New hook (name
   TBD, e.g. `ws_resolve_sdd_repo(project, cwd)` on `sase_workspace`, or
   `vcs_resolve_sdd_repo` on `sase_vcs`) returning `SddRepoResolution | None`:
   - **GitHub impl** (in `sase-github`): for each org in `github_orgs`, look for
     `<project>-sdd` then `sdd` via the existing `gh repo list` / `gh repo view`
     path; on hit, ensure `.sase/sdd` is a clone of it (clone via
     `_clone_gh_repo`, or `git remote add` + fetch if `.sase/sdd` already
     exists locally). Return `{local_path=.sase/sdd, remote_url}`.
   - **BareGit impl:** return `None` ⇒ caller falls back to `in_tree`.
   This keeps GitHub-specific discovery in the GitHub plugin. (Splitting
   *declaration* from *materialization* keeps the metadata read cheap/cached and
   side-effect-free, since `get_all_workflow_metadata()` is called on hot paths.)

5. **Commit + push.** SDD content still commits via `commit_sdd_files`
   (unchanged). Add a push step (generalize `push_bead_work_launch*` in
   `src/sase/bead/sync.py` or add `push_sdd_files` in `src/sase/sdd/_commit.py`),
   run after commit when a remote is configured and `sdd.push_after_commit` is
   true. The existing "no remote ⇒ skip" guard means this is safe to always
   attempt.

6. **Plan references.** Extend `build_sdd_plan_ref` /
   `build_saved_plan_ref` / `_resolve_sdd_reference_path`
   (`src/sase/axe/run_agent_exec_plan_sdd.py`) to emit the `separate_repo`
   reference form (see §6 for the scheme decision).

7. **Rust core boundary.** Per this repo's boundary rule, the *policy decision*
   ("which SDD mode, where is the SDD root, what remote") is shared backend
   behavior a web/CLI frontend would need to match, so it belongs in
   `../sase-core` (`sase_core`) with a thin Python adapter — while the
   GitHub-specific `gh`-based discovery/clone stays in the `sase-github` plugin.
   Scope this split during design; at minimum keep the mode/path resolution in
   one canonical place rather than re-deriving `.sase/sdd` in callers.

8. **Migration.** Provide `sase sdd migrate` (or extend `sase sdd init`) to:
   create/clone the SDD repo, `git mv`/copy the existing `sdd/**` (or
   `.sase/sdd/**`) content in, push, and (optionally) `git rm -r sdd/` from the
   main repo in one clearly-labeled commit. Existing `sase sdd init` config
   rewriting logic (`src/sase/main/sdd_init_config.py`) is the natural home for
   the config edit.

---

## 5. Places that assume `sdd/` lives in the main working tree

These are the concrete edit sites a `separate_repo` mode must account for
(most already have a `.sase/sdd` counterpart because non-VC mode exists):

- Base resolver: `src/sase/sdd/_paths.py:116-117`, `src/sase/sdd/files.py:80-81`.
- Beads dir constant `sdd/beads`: `src/sase/bead/project.py:39`; duplicated at
  `src/sase/main/bead_fast_path.py:12`.
- Beads location walk-up (VC): `src/sase/bead/cli_common.py:37-40`,
  `src/sase/bead/workspace.py:187-197`.
- VC plan/prompt commit via `sase commit`:
  `src/sase/axe/run_agent_exec_plan_sdd.py:31-62`.
- Precommit plan copy into `cwd/sdd/tales/…`:
  `src/sase/workflows/commit/precommit_hooks.py:199`.
- Finalizer "mark plan done" flip on `sdd/{tales,epics,legends,myths}`:
  `src/sase/llm_provider/commit_finalizer_git.py:14-19,153-154`.
- **TUI watchers hardcode `Path.cwd()/"sdd"/"beads"`** (would miss a relocated
  beads dir): `src/sase/ace/tui/actions/_startup_watchers.py:53`,
  `event_refresh/_artifact_delta.py:38`, `event_refresh/_watcher.py:86`.
- Diff/revert badges: `src/sase/ace/tui/models/_diff_badge.py:16,26`,
  `src/sase/ace/revert_agent_models.py:7`.
- Doctor / mobile / display path-tail checks:
  `src/sase/doctor/checks_beads.py:105,116`,
  `src/sase/integrations/_mobile_helper_beads.py:251,253,414,416`,
  `src/sase/agent/bead_display.py:163,192,195`.
- gitignore: `.gitignore:62` (`sdd/beads/beads.db*`) — the SDD repo needs its own
  `.gitignore` (non-VC mode already writes one, `src/sase/sdd/beads.py:63-66`).

**Scattered hard-coded `detect_vcs(...) == "bare_git"` per-VCS checks** — these
are the current, informal expression of "SDD storage policy per VCS type" and
should be re-pointed at the new `WorkflowMetadata`-backed helper (§4 step 2/3)
so the decision lives in one place:

- `src/sase/sdd/beads.py:31` (`get_effective_sdd_config`) — the primary seam.
- `src/sase/sdd/_commit.py:269-295` (`is_local_bare_git_workspace`).
- `src/sase/commit_instructions.py:162` (`_resolve_commit_skill_name`, picks
  `/sase_<provider>_commit`).
- `src/sase/axe/run_agent_directives.py:53,175`.

---

## 6. Open questions / decisions for design

1. **Repo name precedence & scope.** `<project>-sdd` (dedicated per project) vs
   a single shared `sdd` repo for the whole org. A shared `sdd` repo **must**
   namespace content by project (e.g. `sdd/<project>/tales/…`) to avoid
   collisions between projects; a dedicated `<project>-sdd` repo can use the
   root layout as-is. Recommend: prefer dedicated `<project>-sdd`, treat a bare
   `sdd` repo as a shared/namespaced fallback. Define the search order
   explicitly (and make it configurable).

2. **Repo doesn't exist.** `sase-github` has no `gh repo create`. Options:
   (a) auto-create with `gh repo create <org>/<project>-sdd --private` behind an
   opt-in flag; (b) error with a clear "create it first / run `sase sdd
   migrate`" message; (c) fall back to `local` mode until it exists. Recommend
   (a) behind `sdd.repo.create_if_missing: false` default.

3. **Plan-reference scheme (`separate_repo`).** How do downstream agents locate a
   plan file that now lives in a different repo/checkout? Options: keep the
   `.sase/sdd/<kind>/…` reference (agents already resolve that in non-VC mode via
   `_resolve_sdd_reference_path`), or expose the SDD checkout as an env var
   (mirroring `SASE_LINKED_REPO_<NAME>_DIR`) and reference relative to it. The
   `.sase/sdd` path is simplest since it already works.

4. **First-run latency & offline.** Discovery does a network `gh repo list`/clone
   on first use in a workspace. Must be cached/lazy and degrade gracefully
   offline (fall back to `local`, never block plan approval). Note ephemeral
   `sase_<N>` workspaces share the primary's `.sase/sdd` (it hangs off
   `get_primary_workspace_dir`), so the clone happens once per machine, not per
   workspace — good.

5. **Auth & push.** Reuse the existing non-interactive `gh`/git env
   (`non_interactive_git_env`, `_non_interactive_gh_env`) and the "skip if no
   remote / warn on push failure, never undo the local commit" contract from
   `push_bead_work_launch` (`src/sase/bead/sync.py:248-278`).

6. **BareGit invariance.** Verify `bare_git` truly keeps `in_tree` end to end
   (it does today via `get_effective_sdd_config`) and that the new hook returning
   `None` reproduces byte-for-byte the current behavior. Add a regression test.

7. **Uniform runtimes.** The opt-in is per **VCS provider**, not per **agent
   runtime** — consistent with the repo rule that all agent runtimes (Claude,
   Gemini, Codex, …) are treated uniformly. No runtime branching.

8. **Deprecation of `version_controlled`.** Decide the alias/compat window and
   whether `in_tree` remains selectable for GitHub repos that *want* SDD in the
   main tree.

---

## Appendix — key code references

| Concern | Location |
|---|---|
| SDD mode decision (per-VCS seam) | `src/sase/sdd/beads.py:18-33` |
| SDD dir resolver | `src/sase/sdd/_paths.py:108-120`, `src/sase/sdd/files.py:76-84` |
| Standalone `.sase/sdd` git init + auto-commit | `src/sase/sdd/beads.py:36-82`, `src/sase/sdd/_commit.py:180-226` |
| VC plan/prompt commit (`sase commit`) | `src/sase/axe/run_agent_exec_plan_sdd.py:14-70` |
| Bead location (VC vs non-VC) | `src/sase/bead/cli_common.py:15-53` |
| Bead commit + push machinery | `src/sase/bead/sync.py:49,248,292` |
| Mode-aware plan references | `src/sase/axe/run_agent_exec_plan_sdd.py:73-107,255-277` |
| VCS classify / detect | `src/sase/vcs_provider/_registry.py:112-139`, `sase_github/plugin.py:19-41` |
| `sase_vcs` hookspec | `src/sase/vcs_provider/_hookspec.py` |
| `sase_workspace` hookspec | `src/sase/workspace_provider/_hookspec.py` |
| `WorkflowMetadata` (declare opt-in here) | `src/sase/workspace_provider/_hookspec.py:88-111` |
| Per-VCS metadata lookup template | `src/sase/workspace_provider/_registry.py:44-47,82-95` |
| BareGit metadata declaration | `src/sase/workspace_provider/plugins/bare_git_workspace.py` (`ws_get_workflow_metadata`) |
| Scattered `== "bare_git"` checks to centralize | `sdd/beads.py:31`, `sdd/_commit.py:269-295`, `commit_instructions.py:162`, `axe/run_agent_directives.py:53,175` |
| GitHub org repo discovery | `sase_github/workspace_plugin.py:480-527` |
| GitHub clone | `sase_github/workspace_plugin.py:392-434` |
| GitHub org config | `sase_github/config.py:55-67` |
| Linked-repo mechanism (Option B) | `src/sase/linked_repos.py`, `src/sase/workspace_provider/store.py` |
| Config schema (must stay in sync) | `src/sase/config/sase.schema.json` |
</content>
</invoke>
