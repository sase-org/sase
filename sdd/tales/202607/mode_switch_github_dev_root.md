---
create_time: 2026-07-05 06:21:22
status: wip
prompt: sdd/prompts/202607/mode_switch_github_dev_root.md
---
# Plan: Clone mode-switch dev checkouts into `~/projects/github/` using SSH remotes

## Problem

Switching from the PyPI install of sase to the dev (editable) install — via the `m` ("Switch mode") keymap on the
"Updates" tab of the SASE Admin Center panel, or via the equivalent `sase update` CLI path — clones the GitHub source
repos with two undesirable defaults:

1. **Wrong directory**: clones land in `~/projects/git/<repo>` (e.g. `~/projects/git/sase`). `~/projects/git/` is the
   bare-git workspace provider's home (`docs/workspace.md`, `src/sase/workspace_provider/plugins/bare_git_init.py`),
   while GitHub-provider projects canonically live at `~/projects/github/<owner>/<repo>` (`docs/project_spec.md`,
   `resolve_known_project_ref()` in `src/sase/xprompt/_parsing_vcs_refs.py`).
2. **HTTPS remotes**: clones use `https://github.com/<owner>/<repo>` instead of the SSH form
   `git@github.com:<owner>/<repo>.git`, so pushes from these checkouts prompt for credentials instead of using the
   user's SSH key.

## Current behavior (code map)

The whole flow is side-effect-free planning + execution in `src/sase/mode_switch/`:

- `src/sase/mode_switch/repos.py`
  - `DEFAULT_DEV_ROOT = "~/projects/git"` — the default for the `update.dev_root` config key.
  - `config_dev_root()` — resolves `update.dev_root` from merged config, falling back to the default.
  - `repo_for_package()` / `_repo()` — build a `RepoSpec(full_name, url, checkout_name)`. URLs are built as
    `https://github.com/{full_name}`, or taken from the plugin-catalog entry's `url` (a GitHub `html_url`, also HTTPS).
- `src/sase/mode_switch/plan.py`
  - `_plan_to_dev()` computes each checkout path as `dev_root / spec.checkout_name` (flat layout, no owner segment) for
    the host (`sase`), core (`sase-core`), and each plugin repo.
  - `_dev_package_row()` emits `("git", "clone", spec.url, str(checkout_path))` when the checkout does not exist, or a
    `git fetch` when it does (reuse).
- `src/sase/default_config.yml` — mirrors the default: `update.dev_root: "~/projects/git"`.
- Consumers that only display/pass through these values (no logic changes needed): `src/sase/mode_switch/render.py`,
  `src/sase/mode_switch/execute.py`, `src/sase/main/update_handler.py`, and the Admin Center TUI
  (`src/sase/ace/tui/modals/plugins_browser_loading.py` shows `config_dev_root(...)`; `plugins_browser_mode_switch.py`
  runs the plan).

## Design

### 1. New default dev root: `~/projects/github`

- Change `DEFAULT_DEV_ROOT` in `src/sase/mode_switch/repos.py` to `"~/projects/github"`.
- Update `update.dev_root` in `src/sase/default_config.yml` to match.
- `update.dev_root` remains fully user-configurable; only the default changes.

### 2. Owner-nested checkout layout: `<dev_root>/<owner>/<repo>`

Rather than dropping clones flat into the new root (`~/projects/github/sase`), nest them under the repo owner:
`~/projects/github/sase-org/sase`. Rationale:

- This is the established GitHub-provider convention (`~/projects/github/<owner>/<repo>`), so mode-switch clones become
  recognizable as known-project workspaces (e.g. `#gh:sase-org/sase` refs resolve to them).
- Existing checkouts that already follow the convention are **reused** instead of re-cloned (the existing
  exists→fetch/reuse logic in `_dev_package_row()` handles this automatically once the path is right).
- A flat `~/projects/github/sase` would sit ambiguously next to owner directories.

Implementation shape: give `RepoSpec` a relative checkout path (e.g. a `checkout_relpath` property or field returning
`Path(owner) / checkout_name`, with the owner taken from `full_name`), and switch the three
`dev_root / spec.checkout_name` join sites in `_plan_to_dev()` to use it. Keep `checkout_name` semantics for display
where needed. Note `git clone` creates intermediate parent directories itself, so no explicit mkdir is required;
optionally, `_cleanup_failed_clone()` in `execute.py` may also remove a now-empty owner directory after a failed clone.

### 3. SSH-style clone URLs

- `_repo()` in `repos.py`: build `url` as `git@github.com:{full_name}.git`.
- Catalog-backed plugin specs: the catalog entry's `url` is a GitHub `html_url`. Since the catalog branch already
  requires `entry.full_name`, derive the SSH URL from `full_name` via a small shared helper (e.g.
  `_ssh_url(full_name)`); only fall back to `entry.url` verbatim if it is a non-`github.com` URL (defensive; today the
  catalog is GitHub-only).
- The URL flows unchanged into the `git clone` command, the plan table (`repo_url` column), and `sase update --json`
  output — all pick up the SSH form automatically.

### 4. Legacy checkout handling: warn, don't migrate

Users who previously switched to dev mode with the old default have checkouts at `~/projects/git/<repo>`. Do **not**
silently reuse or migrate them (that would freeze the old layout in place). Instead, when planning a clone for a repo
whose new-layout path does not exist but the old default-location path (`~/projects/git/<checkout_name>`) does, append a
plan warning such as:

> `sase: existing checkout at ~/projects/git/sase is no longer used (new location: ~/projects/github/sase-org/sase)`

This uses the existing `SwitchPlan.warnings` surface, which both the CLI renderer and the Admin Center confirmation
modal already display. Existing checkouts are never touched. Reused checkouts (already at the new path) keep whatever
remote URL they have — we do not rewrite remotes.

## Implementation steps

1. **`src/sase/mode_switch/repos.py`**
   - `DEFAULT_DEV_ROOT = "~/projects/github"`.
   - SSH URL construction for both `_repo()` and the catalog branch (shared helper).
   - Add owner-aware relative checkout path to `RepoSpec`.
2. **`src/sase/mode_switch/plan.py`**
   - Use the new relative checkout path at the three join sites in `_plan_to_dev()`.
   - Add the legacy-location warning described in Design §4.
3. **`src/sase/default_config.yml`** — update `update.dev_root` default.
4. **Tests**
   - `tests/mode_switch/test_plan.py`: update path expectations from `dev/<repo>` to `dev/sase-org/<repo>`; add
     assertions that `git_clone` commands use `git@github.com:sase-org/<repo>.git`; add a test for the legacy-checkout
     warning.
   - `tests/main/test_update_command_mode_switch.py`: same path expectation updates.
   - New `tests/mode_switch/test_repos.py`: default dev root, SSH URL for known packages, catalog-entry HTTPS→SSH
     derivation, non-GitHub catalog URL passthrough, and the `RepoSpec` relative checkout path.
5. **Verification** — `just install && just check` (lint, mypy, full test suite).

## Non-goals / out of scope

- **Plugin pip installs** (`sase plugin install --git`, `src/sase/plugins/operations.py`): those use `git+<html_url>`
  for pip, not mode-switch clones; switching them to SSH is a separate decision.
- **Rewriting remotes of existing checkouts** from HTTPS to SSH.
- **Bare-git provider paths**: `~/projects/git/<name>` remains the bare-git provider's primary-checkout home; those docs
  and code are untouched.
- **Rust core (`sase-core`)**: mode switching is host-machine uv-tool orchestration implemented entirely in this repo's
  Python; no cross-frontend domain behavior moves, so no `sase-core` changes are needed.

## Risks

- Users with a customized `update.dev_root` will see the new owner-nested layout under their configured root (previously
  flat). Their existing flat checkouts stop being reused and a fresh nested clone occurs; the legacy warning in Design
  §4 can be extended to cover the flat `dev_root/<repo>` location as well to make this visible.
- Machines without a GitHub SSH key configured will fail to clone over SSH. This is accepted per the request (dev-mode
  switchers are expected to have push-capable SSH setups); the clone failure message plus the existing restore-hint path
  (`execute.py::_with_restore_hint`) keeps failures recoverable.
