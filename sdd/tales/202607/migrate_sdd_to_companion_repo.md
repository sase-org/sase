---
create_time: 2026-07-08 03:02:17
status: wip
prompt: sdd/prompts/202607/migrate_sdd_to_companion_repo.md
---
# Plan: Migrate sase-org/sase SDD Files to the `sase-org/sdd` Companion Repo

## Product Context

The GitHub VCS provider now supports storing SDD artifacts (prompts, plans, research, tales, epics, legends, myths, bead
state) in a **separate companion repository** cloned locally into `<primary>/.sase/sdd`, instead of in-tree under
`sdd/`. That feature (storage policy enum, resolved `SddStore`, provider materialization/creation hooks,
`sase sdd migrate`, doctor storage checks) already shipped via the earlier "Separate SDD Repository" work — but the
**sase project itself was never migrated**, and the provider cannot yet target the desired repo name without a config
override.

This plan finishes the migration for the `sase-org/sase` project so that:

1. A companion repo **`sase-org/sdd`** exists and is initialized.
2. `sase-org/sdd` is the store for **all future** SDD commits for this project.
3. The SDD files that currently live in-tree under `sdd/` are copied to the companion repo and **removed** from the main
   repo.
4. `sase-org/sdd` becomes a **built-in default** companion-repo candidate for the GitHub provider — no `sdd.repo.name`
   override required (per the user's explicit direction).

### Confirmed decisions

- **Repo name:** `sase-org/sdd` (not the provider default `sase-org/sase-sdd`).
- **Remove in-tree:** yes — copy to the companion repo, then delete the tracked `sdd/` tree in a separate commit
  (`sase sdd migrate --remove-in-tree`).
- **No config override:** do **not** rely on a project-local or global `sdd.repo.name: sdd` override. Instead change the
  provider so `<org>/sdd` is always one of the default candidate repos checked for SDD files.

## Verified Current State

- Neither `sase-org/sdd` nor the provider-default `sase-org/sase-sdd` exists on GitHub. **Nothing has been migrated.**
- The project's root `sase.yml` has `sdd: {version_controlled: true}` — the **deprecated in-tree** storage mode.
- All SDD content still lives in-tree at `sdd/`: `assets/`, `beads/` (`beads.db`, `issues.jsonl`, `events/`,
  `config.json`, `metadata.json`), `epics/`, `legends/`, `myths/`, `prompts/`, `research/`, `tales/`, `README.md`.
- No `sdd-store.json` store record exists for the project (confirming no materialized companion store).
- `gh` is authenticated with `repo` scope, so it can create the private companion repo.

### Where the relevant behavior lives

This work spans **two repos**.

**Main repo `sase-org/sase` (SDD engine — no functional change expected, referenced for correctness):**

- `src/sase/sdd/migrate.py` — `migrate_sdd_to_separate_repo(...)` orchestrates: resolve the remote record via the
  provider's `create_sdd_remote`, copy in-tree `sdd/` → `<primary>/.sase/sdd`, `git init`, add `origin`, write the store
  record, ensure SDD scaffolding + bead store, commit, push, rewrite config to `sdd.storage: separate_repo`, and
  (optionally) `git rm -r sdd` in a separate commit.
- `src/sase/main/sdd_handler.py` — `_run_sdd_migrate` is the `sase sdd migrate` CLI entry (`--create`,
  `--remove-in-tree`).
- `src/sase/main/sdd_init_config.py` — `write_sdd_init_config(root, storage="separate_repo")` rewrites the project `sdd`
  block to `storage: separate_repo` and drops the deprecated `version_controlled` key (verified clean rewrite).
- `src/sase/default_config.yml` — documents `sdd.storage`, `sdd.repo.name`, `sdd.push_after_commit`; the `sdd.repo.name`
  comment currently states the provider convention is `<repo>-sdd`.

**Linked repo `sase-github` (GitHub provider plugin — the companion-repo naming lives ONLY here):**

- `src/sase_github/workspace_plugin.py`:
  - `_companion_sdd_repo(owner, repo)` — resolves a **single** `(owner, name)` tuple: an `sdd.repo.name` override if
    set, else the default `(owner, f"{repo}-sdd")`. **This is the piece that must change.**
  - `ws_materialize_sdd_store(...)` — discovers/clones the companion repo at workspace setup: calls
    `_companion_sdd_repo` once, probes **one** repo via `_probe_github_repo` (`gh repo view`), and either adopts an
    existing local clone, refuses to clobber existing local content, or clones.
  - `ws_create_sdd_remote(...)` — verifies or creates the companion repo: probes **one** repo; when `probe == not_found`
    and `options.create` is set, creates it via `_create_github_sdd_repo` (`gh repo create <full> --private`).
- `src/sase_github/config.py` — `get_sdd_repo_name_override()` reads `sdd.repo.name` from merged config. Keep as an
  explicit escape hatch.
- Tests: `tests/test_workspace_plugin.py` (companion discovery/create/adopt/override cases,
  `test_materializes_sdd_store_after_checkout`) and `tests/test_config.py` (override parsing) currently assume the
  single `<repo>-sdd` default and must be updated for multi-candidate probing.

**Boundary note:** companion-repo naming is GitHub-provider-specific glue that already lives in the sase-github plugin —
not shared domain logic — so this change stays in sase-github and does **not** belong in `sase-core`.

## Design

### Workstream A — Make `<org>/sdd` a default companion candidate (sase-github)

Replace the single-name resolver with a **priority-ordered candidate list**, so the provider always checks `<org>/sdd`
while still honoring the historical `<repo>-sdd` convention and the explicit override.

- Introduce `_companion_sdd_candidates(owner, repo) -> list[tuple[str, str]]`:
  - If an `sdd.repo.name` override is set → a single parsed candidate (the override still wins outright).
  - Otherwise, default candidates in priority order:
    1. `(owner, "sdd")` — the new always-checked default (**primary / create target**).
    2. `(owner, f"{repo}-sdd")` — the existing provider convention, kept as a fallback for repos that already use it.
  - The **primary** candidate (index 0) is the create target and the repo recorded when nothing is found.
- Keep `_companion_sdd_repo` as a thin wrapper returning the primary candidate, or inline it — whichever keeps the diff
  small; all call sites move to the list.
- `ws_materialize_sdd_store`: probe candidates in priority order and adopt the **first** that probes `found`
  (clone/adopt against it). If none are found, build the `not_found` / clone-target record from the **primary**
  candidate. Preserve the existing behaviors: adopt a matching existing local clone, and never clobber existing local
  `.sase/sdd` content (print the adoption notice and return a `not_found` record instead).
- `ws_create_sdd_remote`: probe candidates in order; return the first `found`; else, if `options.create` is set, create
  the **primary** (`<owner>/sdd`) and return a `found` record for it; else return a `not_found` record for the primary.
- Documentation: update the `sdd.repo.name` comment in `default_config.yml` (and any docs referencing the `<repo>-sdd`
  convention) to describe the new default order — `<org>/sdd`, falling back to `<repo>-sdd`, override wins.
- Tests (sase-github): update existing cases for multi-candidate probing and the new primary; add coverage for (a)
  `<org>/sdd` preferred when it exists, (b) fallback to `<repo>-sdd` when `<org>/sdd` is absent but `<repo>-sdd` exists,
  (c) create targets `<org>/sdd` when neither exists, (d) an explicit `sdd.repo.name` override still wins. Watch for the
  extra `gh repo view` probe call that multi-candidate discovery introduces in the common path and assert the probe
  order.

### Workstream B — Perform the migration (depends on A)

Run the existing migration command against the sase project **after** Workstream A has landed, so the create target
resolves to `sase-org/sdd` with no override:

```
sase sdd migrate --create --remove-in-tree
```

This single command will:

1. Create the private `sase-org/sdd` repo via `gh repo create`.
2. Copy the in-tree `sdd/` tree → `<primary>/.sase/sdd`, `git init`, add `origin`, and write the store record.
3. Ensure SDD scaffolding (README/dir-map) and the bead store (`.gitignore` for `beads/beads.db`) — the existing
   `beads/` directory is copied as-is, so `issues.jsonl` / `events/` history is preserved (init only runs when `beads/`
   is absent).
4. Commit and push the companion repo.
5. Rewrite the project `sase.yml` to `sdd: {storage: separate_repo}`, dropping the deprecated `version_controlled` key.
6. `git rm -r sdd` in a **separate** commit removing the migrated in-tree files.

The resulting `sase.yml` change and the in-tree `sdd/` removal commit must be landed on `master` through the normal sase
commit / PR flow.

### Verification (after B)

- `gh repo view sase-org/sdd` succeeds and the repo is populated.
- `sase doctor` reports `config.sdd` OK — no `separate-repo-not-materialized`, `orphaned-store-record`, or
  deprecated-`version_controlled` warnings.
- `sase sdd path` resolves to `.sase/sdd`.
- The companion repo contains all migrated content (`prompts/`, `tales/`, `research/`, `epics/`, `legends/`, `myths/`,
  `assets/`, `README.md`) and the bead store (`issues.jsonl`, `events/`), with `beads/beads.db` gitignored (not
  committed).
- A subsequent SDD-producing action (e.g. accepting a plan or a bead mutation) commits into the companion repo, not
  in-tree.
- The main repo no longer tracks `sdd/`.

## Sequencing

1. **Workstream A** (sase-github provider change + tests + docs) lands first.
2. **Workstream B** (run `sase sdd migrate --create --remove-in-tree`; land the config + removal commits) follows.

Rationale: with A in place, the migration's create target is `sase-org/sdd` with **no override**, exactly matching the
confirmed decisions. (A fallback path — run B first behind a temporary `sdd.repo.name: sdd` override, then land A and
remove the override — is possible but rejected, because the user does not want to rely on an override at any point.)

## Risks & Open Considerations

- **Shared-repo semantics / collision (most important).** Making `<org>/sdd` the always-checked, highest-priority
  default means that once `sase-org/sdd` exists, **any other `sase-org` project** on `auto` storage with no materialized
  record and no explicit config will also discover and adopt `sase-org/sdd`, cloning it into its own `.sase/sdd`. If
  multiple projects share one companion repo, their `prompts/`, `tales/`, `beads/`, etc. would collide in a single tree.
  Only the sase project is being migrated now, but this is an inherent consequence of the requested default. **Decision
  needed:** is `sase-org/sdd` intended as a single shared org-level SDD repo, or should the default probe order prefer
  the per-repo `<repo>-sdd` first and fall back to `<org>/sdd` (which would, however, make the create target
  `<repo>-sdd` and reintroduce the need to special-case `sdd` as the primary)? The design above chooses
  `<org>/sdd`-first to satisfy the naming decision; flag this trade-off for confirmation.
- **Bead history integrity.** Confirm the copied `beads/` retains `issues.jsonl` and `events/` in the companion repo and
  that `beads.db` is gitignored (kept local, not committed).
- **Extra probe cost.** Multi-candidate discovery adds a `gh repo view` call in the common path (probe `<org>/sdd`, then
  `<repo>-sdd`). Acceptable, but keep probing lazy (stop at the first `found`).
- **Landing the removal commit.** The in-tree `sdd/` removal is created directly by the migration (not through the
  interactive commit UI); ensure it and the `sase.yml` edit reach `master` via the normal flow and that CI passes. Note
  that `sase.yml` is a normal source edit (subject to `just check`), even though the `sdd/` file deletions themselves
  are SDD content.
- **Idempotency / partial runs.** If the companion repo gets created but a later step fails, re-running
  `sase sdd migrate` should adopt the existing repo rather than error; verify the not-found/adopt paths behave on a
  second run.
