---
create_time: 2026-07-01 08:31:56
status: done
prompt: sdd/prompts/202607/github_enterprise_setup_docs.md
---
# Plan: GitHub Enterprise Setup Documentation (install routes + end-to-end walkthrough)

## Problem & Product Context

The `sase-github` plugin now supports GitHub Enterprise Server / self-hosted GitHub hosts via the `github_hosts` config
key (feature already implemented and committed in the `sase-github` plugin repo as
`feat: support GitHub Enterprise hosts`). The **code** works, but a corporate Enterprise user still cannot confidently
configure SASE end-to-end from the docs. The configuration half (`github_hosts`, `gh auth`, workspace layout) is now
reasonably covered, but the **installation** half is both wrong and incomplete, and there is no single ordered
walkthrough tying the whole setup together.

This is a **documentation-only** follow-up. No code, config schema, or behavior changes.

### What an Enterprise user actually needs to do (target end-state the docs must convey)

1. **Install SASE + the `sase-github` plugin.** GitHub PR support is not in core `sase`; the plugin is a separate
   package injected into the same `uv tool` environment as `sase`.
2. **Install and authenticate the `gh` CLI to their host:** `gh auth login --hostname github.mycompany.com` (`gh`
   auto-detects the host from the git remote for repo-scoped PR commands).
3. **Configure the host** in `~/.config/sase/sase.yml` via `github_hosts` (first entry = default host for bare
   `#gh(owner/repo)` refs; `github.com` is implicit).
4. **(Optional) SSH clones** via `github_orgs` + an SSH key registered on the Enterprise host; otherwise HTTPS.
5. **Verify** with `sase doctor -C plugins.github`, then drive a repo with `#gh(owner/repo)`.

### Concrete documentation gaps

1. **Installation instructions are wrong for a managed SASE and omit the two routes we want to recommend.** The plugin
   `README.md` "Installation" section tells users to run `pip install sase-github` / `uv pip install sase-github`. That
   is the wrong mechanism for a `uv tool`-managed SASE — the canonical install path that `sase update` and
   `sase plugin *` require — and installing the plugin into a foreign environment leaves its entry points undiscovered
   by the `sase` tool. It mentions **neither** the Admin Center Updates tab **nor** the single-command
   `uv tool install sase --with sase-github`.

2. **The core `sase` repo contains a now-incorrect classifier statement.** `docs/vcs.md` (the canonical VCS provider
   reference — exactly where an Enterprise user checks whether SASE supports them) still states at the
   `vcs_classify_repo` entry that the `sase-github` plugin "claims repos with `github.com` URLs (returning `"github"`)."
   After the Enterprise change this is factually wrong: the plugin now claims repos whose remote **host** is in the
   configured host set (github.com plus any configured `github_hosts`).

3. **The core `sase` repo's own plugin-install snippet is inconsistent with its canonical path.** `docs/plugins.md`
   opens its "Installation" section with `pip install sase` / `pip install sase-github`, yet the same document's
   `sase update` / `sase plugin install` sections state that **the install method is required to be
   `uv tool install sase`**. The quick-start snippet contradicts the rest of the page.

4. **There is no consolidated, discoverable "GitHub Enterprise setup" walkthrough.** The facts an Enterprise user needs
   are scattered across the plugin README "Requirements" note and four separate sections of the plugin
   `docs/configuration.md`, with no ordered checklist. The core `sase` docs — the published reference a user reads first
   — never mention Enterprise or `github_hosts` at all, so there is no signpost from "I use Enterprise GitHub" to "here
   is what to configure."

> **Supersedes a stale draft.** An earlier untracked draft, `sase_plan_github_enterprise_docs.md`, addresses gaps 2 and
> 4 but predates the install-route requirement: it still recommends `pip install sase-github` and never mentions the
> Admin Center Updates tab or `uv tool install --with`. This plan folds in that draft's valid findings (the
> `docs/vcs.md` correctness fix and the consolidated walkthrough) and corrects its install guidance. The stale draft
> should be deleted in favor of this one.

## Goals

1. Make plugin installation guidance correct and complete: recommend installing `sase-github` from the **Admin Center
   Updates tab** in the `sase ace` TUI, and provide the single-command `uv tool install sase --with sase-github`
   alternative that installs SASE and the plugin together. Stop presenting `pip install sase-github` as the path for a
   managed SASE.
2. Correct the stale `github.com`-only classifier description in the core `sase` repo.
3. Provide a single, ordered "GitHub Enterprise setup" walkthrough an Enterprise user can follow top-to-bottom, and make
   it discoverable from the core `sase` docs.
4. Keep the core `sase` docs internally consistent (canonical `uv tool` install path everywhere).

## Non-Goals

- No code, config-schema, or default-config changes. The feature is already implemented.
- No new config keys, ref syntax, or behavior.
- Do not relocate the full `github_hosts` / `github_orgs` reference into the core repo. Core intentionally defers
  plugin-specific config keys to the plugin's own docs; core gets a pointer, not a copy.

## Affected Repositories

Two repos are involved.

- **Linked `sase-github` plugin repo** (canonical, version-locked source of truth): `README.md`, `docs/configuration.md`
  (and a spot-check of `docs/architecture.md`, which the feature commit already corrected). The implementer must open
  the linked plugin repo with `sase workspace open -p sase-github -r "<reason>" <workspace_num>` and edit only the path
  that command prints. `<workspace_num>` is the number of the primary workspace the implementer is running in.
- **Core `sase` repo** (this repo): `docs/vcs.md`, `docs/plugins.md`, `docs/configuration.md`.

## Proposed Design

### 1. Linked `sase-github` repo — rewrite the README "Installation" section

Replace the current `pip install sase-github` / `uv pip install sase-github` block with two clearly labeled routes,
recommended-first:

- **Recommended — install from the SASE Admin Center Updates tab (TUI).** In `sase ace`, press `#` to open the SASE
  Admin Center, jump to the **Updates** tab (press `5`, or `[` / `]` to cycle), highlight `sase-github` in the plugin
  list (`j` / `k`, or `/` to filter), press `i` to install, and confirm the preview modal (which shows the exact `uv`
  command and resolved package set). The install runs as a tracked background task and the plugin's entry points are
  discovered on the next `sase` run. Note the prerequisite: this route (like all Admin Center install/update actions)
  requires SASE to have been installed via `uv tool install sase`.
- **Alternative — one-command `uv tool install`.** To install SASE and the plugin together in a single command:

  ```bash
  uv tool install sase --python 3.12 --with sase-github
  ```

  Repeat `--with` for additional plugins (e.g. `--with sase-github --with sase-telegram`). Add `--force` to replace an
  existing tool install.

- **Also available (equivalent CLI):** `sase plugin install github` adds the plugin to an existing managed SASE install
  (documented in the core repo's `docs/plugins.md`).

Cross-link the recommended route to the core repo's Updates-tab documentation (`docs/configuration.md#updates-tab`) and
`docs/plugins.md`. Keep `pip install` only as an explicit escape hatch for non-`uv tool` / library-style installs, if
retained at all — it must not be the headline instruction. Update the "Requirements" area and add a one-line pointer
from the README to the new "GitHub Enterprise setup" walkthrough (Section 2) for discovery.

### 2. Linked `sase-github` repo — consolidated "GitHub Enterprise setup" walkthrough (docs/configuration.md)

Add a dedicated, ordered **"GitHub Enterprise setup"** section near the top of the plugin's `docs/configuration.md`
(before the individual `github_hosts` / `github_orgs` reference sections, which remain as detailed reference). It
consolidates the currently-scattered facts into one numbered checklist an Enterprise user follows top-to-bottom:

1. **Install SASE + the plugin.** Point at the two routes from Section 1 (Admin Center Updates tab recommended;
   `uv tool install sase --with sase-github` for a fresh single-command install). Do not duplicate the full instructions
   — link to the README install section and the core `docs/plugins.md`.
2. **Authenticate `gh` to the Enterprise host:** `gh auth login --hostname github.mycompany.com`, noting `gh`
   auto-detects the host from the remote for repo-scoped PR commands.
3. **Set `github_hosts`** in `~/.config/sase/sase.yml`, with an **emphasized ordering pitfall**: the first entry is the
   default host for bare `#gh(owner/repo)` refs, so an Enterprise user should list their Enterprise host **first** or
   bare refs will default to github.com. Note github.com is implicit. Cross-link the existing `github_hosts` reference
   section rather than repeating it.
4. **(Optional) SSH clones** via `github_orgs` + an SSH key registered on the Enterprise host; otherwise HTTPS.
   Cross-link the existing `github_orgs` section.
5. **Verify and locate repos:** `sase doctor -C plugins.github` confirms the GitHub provider and `gh auth` are ready;
   then resolve a repo with `#gh(owner/repo)`. Point at the existing "Workspace Layout" section so users know Enterprise
   repos land under `~/projects/github/<host>/<user>/<project>/`.

### 3. Core `sase` repo — fix correctness in docs/vcs.md

- **Primary fix:** Rewrite the `vcs_classify_repo` description (the sentence stating the plugin "claims repos with
  `github.com` URLs (returning `"github"`)", at `docs/vcs.md:554-555`) so it states the plugin claims repos whose remote
  **host** is in the configured GitHub host set — github.com by default, plus any hosts listed in `github_hosts` — while
  unclaimed repos fall through to `bare_git`.
- **Secondary consistency pass:** Review the other GitHub-flavored phrasings in the same file (the auto-detection bullet
  and the provider-selection notes around lines 60-61 and 316). Adjust wording only if it still implies
  github.com-exclusivity; do not over-edit accurate text.
- **Discoverability signpost:** Add a short **"GitHub Enterprise"** note in the GitHub-relevant area (e.g. near the
  GitHub plugin scope / PR integration region, or Troubleshooting). It should say plainly that Enterprise / self-hosted
  GitHub is supported, that the user must `gh auth login --hostname <host>` and set `github_hosts`, and link to the
  plugin's configuration docs (the Section 2 walkthrough) as the source of truth. A few sentences — a signpost, not a
  duplicate.

### 4. Core `sase` repo — fix the docs/plugins.md install snippet

Update the "Installation" quick snippet (currently `pip install sase` / `pip install sase-github`) to lead with the
canonical managed path, matching the rest of the page:

```bash
# Core SASE (installs the sase tool)
uv tool install sase --python 3.12

# Core SASE + GitHub PR support in one command
uv tool install sase --python 3.12 --with sase-github
```

Reference `sase plugin install github` and the Admin Center Updates tab as the ways to add the plugin to an existing
install. This removes the internal contradiction with the document's own "install method is required:
`uv tool install sase`" rule. Keep the change minimal and consistent with `docs/plugins.md`'s existing tone.

### 5. Core `sase` repo — discoverability pointer in docs/configuration.md

Add a one-line pointer (in the `vcs_provider` area and/or the table of contents) noting that GitHub host configuration
(`github_hosts`) for Enterprise lives in the `sase-github` plugin docs, with a link to the Section 2 walkthrough. This
mirrors how core already treats plugin-owned config without importing the full key reference.

## Testing / Validation

- **Linked `sase-github` repo:** open it via `sase workspace open -p sase-github -r "<reason>" <workspace_num>`, run
  `just install` then `just check` (repo policy). Confirm no broken internal doc links.
- **Core `sase` repo:** run `just install` then `just check` (the `docs/` markdown edits are not in the `sdd/research/`
  exception). Confirm no broken internal doc links.
- **Manual review:** read the new walkthrough top-to-bottom as a first-time Enterprise user and confirm the five steps
  are self-sufficient, that the install-route recommendation (Admin Center Updates tab) and the one-command
  `uv tool install sase --with sase-github` alternative are both present and correct, and that the `github_hosts`
  ordering pitfall is unmissable. Grep both repos for any remaining `github.com`-only classifier phrasing and any
  remaining `pip install sase-github`-as-primary instruction.

## Rollout / Risk

- Docs-only; no runtime risk. The main risk is doc drift between the two repos and between the core install snippets —
  mitigated by keeping the full config/host reference in the plugin repo and using pointers (not copies) from core, and
  by standardizing every install snippet on the single canonical `uv tool install sase` path.

## Out of Scope / Possible Follow-ups

- Delete the superseded untracked draft `sase_plan_github_enterprise_docs.md` (this plan replaces it).
- Publishing the plugin `docs/` to the sase.sh docs site (if not already) to strengthen discoverability beyond a
  GitHub-rendered markdown file.
- `#gh(host/owner/repo)` 3-segment ref syntax (already noted as a code follow-up in the original feature plan) — not a
  docs task.
