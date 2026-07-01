---
create_time: 2026-07-01 08:06:25
status: done
prompt: sdd/prompts/202607/github_enterprise_support.md
---
# Plan: GitHub Enterprise / Custom Root URL Support for the sase-github Plugin

## Problem & Product Context

Today the `sase-github` plugin only works against public/SaaS **github.com**. Users on a **GitHub Enterprise Server**
(or any self-hosted GitHub instance, e.g. `github.mycompany.com`) cannot use the plugin's PR workflows. There is **no
configuration option** to point sase at a different GitHub root URL. The only related setting, `github_orgs`, merely
toggles SSH vs HTTPS clone URLs — it does not change the host.

This matters because most corporate SASE users are on Enterprise GitHub, not github.com. Without this, the entire `#gh`
workflow (resolve → clone → commit → mail → PR → submit) is unavailable to them.

### Why it breaks today

The host `github.com` is hard-coded in several places. The single most damaging one is repo **classification**:

- `sase_github/plugin.py` → `vcs_classify_repo()` claims a repo only if the origin URL contains the literal substring
  `"github.com"`. For an Enterprise remote it returns `None`, so sase core
  (`sase/vcs_provider/_registry.py::_classify_by_url`) falls the repo back to **`bare_git`**. The `bare_git` provider
  has no concept of PRs, so PR creation, PR-merge-on-submit, and PR URL/number retrieval all silently degrade or fail.
- This also produces an **internal inconsistency**: the workspace layer
  (`sase_github/workspace_plugin.py::ws_detect_workflow_type`) already treats _any_ non-local hosted remote as workflow
  type `"gh"`, while the VCS layer refuses to classify Enterprise repos as `"github"`. The two layers disagree about
  what an Enterprise repo is.

Other hard-coded spots that must change for full compatibility:

- `workspace_plugin.py::_clone_gh_repo()` — builds clone URLs as `git@github.com:...` / `https://github.com/...`, so
  `#gh(owner/repo)` bootstrap always clones from github.com.
- `workspace_plugin.py::ws_extract_change_identifier()` — regex `https?://github\.com/.+/pull/(\d+)`.
- `workspace_plugin.py::ws_supports_reviewer_comments()` — regex `https?://github\.com/`.
- `workspace_plugin.py::_extract_pr_number()` — regex `https?://github\.com/.+/pull/(\d+)`.

Out of scope / verified fine:

- The **`gh` CLI** already supports Enterprise Server. For repo-scoped commands (`gh pr view/create/merge`) it
  auto-detects the host from the git remote, so no command-construction changes are needed — only that the user has
  authenticated to their host (`gh auth login --hostname github.mycompany.com`). This is a **documentation** item.
- **Rust `sase-core`** is host-agnostic (its git-URL parsing derives `owner/repo` from any host). No changes needed
  there.
- Core `sase/workspace_provider/store.py::_derive_project_key` special-cases `github.com` for a prettier project-key,
  but the non-github.com branch is already functional (it produces a host-qualified slug). This is cosmetic and
  **explicitly out of scope** unless we want naming parity (see "Optional polish").

## Goals

1. Let users configure one or more GitHub hosts so Enterprise repos are recognized and driven through the full PR
   workflow, identically to github.com.
2. Keep github.com working with zero configuration (backward compatible).
3. Treat all configured hosts uniformly — Enterprise gets the same capabilities as github.com (per the "Uniform Agent
   Runtimes" spirit: no second-class host).

## Non-Goals

- Multi-host disambiguation heuristics beyond an explicit default. We will not try to guess which host a bare
  `owner/repo` belongs to.
- Any change to the `gh` CLI auth flow (user-managed).
- GitLab/Bitbucket or other providers.

## Proposed Design

### 1. New configuration: `github_hosts`

Add a list-valued config key, mirroring the existing `github_orgs` shape and its reader in `sase_github/config.py`:

```yaml
# ~/.config/sase/sase.yml
github_hosts:
  - github.mycompany.com # first entry is the default host for `#gh(owner/repo)` clones
  - github.com
```

Semantics:

- **Effective host set** = the configured `github_hosts` **plus** an implicit `github.com` (so github.com always works
  even when a user lists only their Enterprise host). De-duplicate.
- **Default host** (for constructing clone URLs from a bare `owner/repo`) = the first entry of `github_hosts` if set,
  else `github.com`.
- Add `get_github_hosts()` and a `get_default_github_host()` helper to `sase_github/config.py`, reading via
  `load_merged_config()` exactly like `get_github_orgs()`. Normalize entries (strip, lowercase, drop scheme/`https://`
  prefixes and trailing slashes if a user pastes a URL).

Register nothing new in entry points; this is plain config read through the existing `sase_config` merge chain.
Optionally seed a documented default in `src/sase_github/default_config.yml`.

### 2. Host-aware classification (`plugin.py`)

Rewrite `vcs_classify_repo()` to claim a repo when its origin URL's **host** matches any host in the effective host set.
Parse the host robustly for all three URL shapes:

- HTTPS: `https://github.mycompany.com/owner/repo.git`
- SSH scp-style: `git@github.mycompany.com:owner/repo.git`
- SSH URL: `ssh://git@github.mycompany.com/owner/repo.git`

Match on host equality (not substring) to avoid false positives (e.g. a path segment named `github.com`). Keep returning
`"github"` on a match, `None` otherwise. This alone fixes the primary blocker and removes the VCS-vs-workspace
inconsistency.

### 3. Host-aware clone URLs (`workspace_plugin.py::_clone_gh_repo`)

Thread the **default host** into the URL builder. Preserve the existing `github_orgs` SSH/HTTPS decision, just with the
configured host substituted:

- org in `github_orgs` → `git@<host>:<user>/<project>.git`
- otherwise → `https://<host>/<user>/<project>.git`

Decide workspace-path layout for non-default hosts to avoid collisions between same-named repos on different hosts
(`_github_workspace_dir`):

- Keep github.com at the **existing** path `~/projects/github/<user>/<project>/` (no migration for current users).
- Namespace other hosts, e.g. `~/projects/github/<host>/<user>/<project>/`.

(If we later add `#gh(host/owner/repo)` ref syntax, `resolve_gh_ref` Mode 1 would parse a 3-segment path; note this as a
possible follow-up, not required for MVP since already-cloned Enterprise repos resolve via Modes 2/3 from the recorded
`WORKSPACE_DIR` and read their host directly from the remote.)

### 4. Host-agnostic PR URL parsing (three regexes)

Replace the `github\.com`-pinned regexes in `ws_extract_change_identifier`, `_extract_pr_number`, and
`ws_supports_reviewer_comments` with host-agnostic matching. Two acceptable approaches; pick one and use it
consistently:

- **Simple & sufficient:** match any host — `https?://[^/]+/.+?/pull/(\d+)` for PR-number extraction and
  `https?://[^/]+/` for the reviewer-comments check. A GitHub PR URL shape (`/pull/<n>`) is distinctive enough that
  broad host matching is safe here.
- **Strict:** match only against the configured effective host set. More precise but couples URL parsing to config
  reads.

Recommendation: use the simple form for `_extract_pr_number` / `ws_extract_change_identifier` (keyed on the `/pull/<n>`
shape) and the simple host-agnostic form for `ws_supports_reviewer_comments`.

### 5. Documentation

- Update `docs/configuration.md`: document `github_hosts`, the default-host rule, the workspace layout for non-default
  hosts, and the **required** `gh auth login --hostname <host>` step for Enterprise.
- Update `docs/architecture.md`: revise the `vcs_classify_repo()` row ("claims repos whose host is in the configured
  GitHub host set, defaulting to github.com").
- Update `README.md` requirements note re: Enterprise auth.

## Testing Strategy

Extend `tests/test_github_plugin.py` and `tests/test_workspace_plugin.py`:

- `vcs_classify_repo`: returns `"github"` for github.com and for a configured Enterprise host across HTTPS / scp-SSH /
  ssh:// URL forms; returns `None` for an unconfigured host; host-equality (no substring false positives).
- `config`: `get_github_hosts()` / `get_default_github_host()` — default when unset, normalization of pasted URLs,
  implicit github.com inclusion, ordering → default host.
- `_clone_gh_repo`: correct SSH vs HTTPS URL for default Enterprise host, honoring `github_orgs`; correct workspace path
  namespacing for non-default hosts and unchanged path for github.com.
- PR-URL parsing: `_extract_pr_number` / `ws_extract_change_identifier` / `ws_supports_reviewer_comments` all work for
  an Enterprise PR URL and still for github.com.

Run `just check` (install first, per repo policy) in the `sase-github` plugin repo.

## Optional Polish (separate, low priority)

- Core `store.py::_derive_project_key`: extend the `github.com`-only pretty-key branch to any configured GitHub host for
  consistent project-key naming across hosts. Cosmetic only.
- `#gh(host/owner/repo)` 3-segment ref syntax in `resolve_gh_ref` Mode 1 for first-time cloning of a specific
  non-default host without relying on the default-host config.

## Rollout / Risk

- Fully backward compatible: with no `github_hosts` set, behavior is identical to today (github.com only, existing
  workspace paths).
- Main risk is the classification broadening — mitigated by **host-equality** matching against an explicit configured
  set (plus github.com), so we never steal repos belonging to a future GitLab/other provider plugin.
