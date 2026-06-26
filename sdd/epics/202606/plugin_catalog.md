---
create_time: 2026-06-25 18:35:15
bead_id: sase-57
tier: epic
status: done
prompt: sdd/prompts/202606/plugin_catalog.md
---
# Plan: `sase plugin list` & `sase plugin show`

## Goal

Introduce a first-class `sase plugin` command surface that lets a user **discover every SASE plugin that exists** — not
just the ones installed locally — by treating the GitHub `sase-plugin` repository topic as the canonical registry. Two
subcommands ship:

- `sase plugin list` — a beautiful, scannable catalog of all known SASE plugins, clearly distinguishing **built-in**
  (published under the canonical `sase-org` GitHub org) from **community** plugins (anyone else, shown with a warning),
  and clearly marking which are **installed** in the current environment.
- `sase plugin show <plugin_name>` — a detailed view of a single plugin.

The catalog is fetched from GitHub once and **cached** so the command is instant on repeat runs; a `--refresh` flag
bypasses the cache and rewrites it with fresh data.

The bar for this feature is: **intuitive, reliable, and beautiful.** The design below optimizes for all three.

---

## Product Context & UX Vision

Today there is _no_ `sase plugin` command — `docs/plugins.md` and `src/sase/plugins/inventory.py` both explicitly say
the namespace is "reserved for a future pluggy-focused rewrite." This feature claims that namespace.

SASE plugins are distributed as separate GitHub repos that carry the `sase-plugin` topic (e.g. `sase-org/sase-github`,
`sase-org/sase-telegram`). Some are built-in (the `sase-org` org); others may be community-authored. A user needs to
answer, at a glance:

1. **What plugins exist?** (the whole ecosystem, not just what I've installed)
2. **Which are official vs. community?** (and a clear warning on community ones)
3. **Which do I have installed, and at what version?**
4. **What does each one do?** (a short description)
5. **What topics does each carry?**

### `sase plugin list` — example output (human view)

```
╭─ SASE Plugins ───────────────────────────────────────────────────────────────────╮
│                                                                                    │
│  BUILT-IN  ·  sase-org (official)                                                   │
│   ●  github      v0.4.1   sase-vcs, sase-workspace   GitHub VCS & PR workflows      │
│   ○  telegram    —        —                          Telegram chat integration      │
│                                                                                    │
│  COMMUNITY  ·  ⚠ third-party, not maintained by sase-org — review before installing │
│   ○  acme-jira   —        —                          Jira sync for SASE (acme-corp)  │
│                                                                                    │
│  ● installed   ○ available    2 built-in · 1 community · 1 installed                │
│  Cached 2h ago · run `sase plugin list --refresh` to update                        │
╰────────────────────────────────────────────────────────────────────────────────────╯
```

Design principles for the rendering:

- **Two clearly-labeled sections**: built-in first, community second. The community header is itself the warning, so the
  distinction is impossible to miss — exactly the requirement.
- **Glyph + text, never color alone.** `●`/`○` for installed/available, plus an explicit legend, so the output is fully
  legible when copied into an agent chat or a no-color terminal (consistent with the repo's existing Rich-output
  conventions). Color (green = built-in/installed, yellow = community/warning, dim = secondary) _enhances_ but is never
  load-bearing.
- **Columns**: installed glyph · short name (bold) · installed version · contributed entry-point groups · description.
  `--verbose` adds stars, last-updated, and the full topic list.
- **A footer** showing counts and **cache age + the exact refresh command**, so the freshness story is always visible
  and the refresh affordance is discoverable.

### `sase plugin show <plugin_name>` — example output (human view)

```
╭─ github · sase-org/sase-github ──────────────────────────────────────────────────╮
│  BUILT-IN (official)                                                               │
│                                                                                    │
│  GitHub VCS and workspace support, including GitHub CLI (gh) PR operations.        │
│                                                                                    │
│  Installed    ✓  v0.4.1   (sase_vcs:github, sase_workspace:github, sase_config…)    │
│  Repository   https://github.com/sase-org/sase-github                              │
│  Homepage     https://sase.dev/plugins/github                                      │
│  Topics       sase-plugin · github · vcs · pull-requests                           │
│  Stars        12      Updated  2026-06-20      License  MIT                         │
╰────────────────────────────────────────────────────────────────────────────────────╯
  Cached 2h ago · run `sase plugin show github --refresh` to update
```

For a **community** plugin, `show` leads with a prominent warning panel:

```
╭─ ⚠  COMMUNITY PLUGIN ────────────────────────────────────────────────────────────╮
│  This plugin is published by `acme-corp`, not the official `sase-org` org.         │
│  It is third-party software. Review its source before installing.                  │
╰────────────────────────────────────────────────────────────────────────────────────╯
```

When `<plugin_name>` doesn't match, `show` prints a "did you mean…?" suggestion list from the catalog and exits
non-zero.

Both subcommands support `-j|--json` for stable machine output and `-r|--refresh` to rewrite the cache.

---

## Key Design Decisions (with rationale)

### 1. This feature lives in Python (`src/sase/plugins/`), not the Rust core

The repo's Rust-core boundary rule says shared domain behavior belongs in `sase-core`. This feature is the **exception
that proves the rule's litmus test**, for three concrete reasons:

- **The relevant domain logic already lives in Python here.** Plugin _inventory_ and _classification_
  (`src/sase/plugins/inventory.py`, `src/sase/version/_plugins.py`, `src/sase/doctor/checks_plugins.py`) are all Python
  in this repo, not in `sase-core`. The plugin _catalog_ is the same domain; splitting it across the Rust boundary would
  make plugins half-Rust/half-Python and _less_ consistent.
- **The data source is `gh`.** By design, `sase-core` does not shell out to external CLIs; GitHub interaction happens in
  Python (the `sase-github` plugin, and `sase doctor`'s `gh auth status` probe already lives in core Python at
  `src/sase/doctor/checks_plugins.py`). A read-only `gh` topic search belongs in the same place.
- **Reliability.** Keeping the whole feature in one repo avoids a cross-repo wire/binding/version-bump dance for the
  first cut, which is the right call for a user-facing discovery command.

This is an explicit, documented decision so the implementing agents do not try to push catalog logic into `sase-core`.
(If a future `sase web` plugin browser needs the same catalog, the Python module is the shared source of truth,
mirroring how `inventory.py` is shared today.)

### 2. GitHub source: a single authenticated `gh api` search call, topics included

Fetch with:

```
gh api --paginate -X GET "search/repositories?q=topic:sase-plugin&per_page=100"
```

and read `.items[]`. The REST search endpoint returns **topics inline** (`topics`, `full_name`, `name`, `owner.login`,
`description`, `html_url`, `homepage`, `stargazers_count`, `archived`, `license.spdx_id`, `pushed_at`, `updated_at`) —
so we get every field we need, including the per-plugin topic list, in **one call with no N+1 per-repo lookups**.
`q=topic:sase-plugin` (no org filter) returns both internal and community repos, which is exactly the requirement.
(`gh search repos --topic sase-plugin --json …` is the documented fallback, but it does not return topics, so the
`gh api` form is primary.)

Graceful degradation, mirroring `checks_plugins.py`:

- `gh` not on PATH → clear error with the same install/`gh auth login` hint the doctor uses.
- `gh` present but the call fails/unauthenticated → fall back to the existing cache if present (with a loud "showing
  stale cached data" warning); otherwise an actionable error. Subprocess runs with a timeout.

### 3. Built-in vs. community classification

A single constant, `SASE_PLUGIN_ORG = "sase-org"`, defines the canonical org. `owner.login == SASE_PLUGIN_ORG`
(case-insensitive) ⇒ **built-in**; anything else ⇒ **community** (rendered with the warning). The constant may later be
over/extended via config, but starts as a module constant for simplicity and reliability. Archived repos are surfaced
with an "archived" marker rather than hidden.

### 4. Installed detection by merging with the live inventory

The catalog (what _exists_) is merged with `collect_plugin_inventory()` (what's _installed_) to mark installed status,
version, and contributed entry-point groups. A catalog repo (`sase-github`) maps to an installed distribution via
`normalize_distribution_name` from `src/sase/version/_plugins.py`. Console-script-only plugins (e.g. `sase-telegram`)
are detected through the same module's console-script signal helpers. Plugins that are _not_ pip-installable (e.g. a
Neovim-only integration) correctly show as "not installed (n/a)" — the merge is robust to repos that carry the topic but
contribute no Python entry points.

### 5. Caching: fast by default, explicit refresh, never a surprise network call

- Location: `~/.sase/plugins/catalog_cache.json` via `ensure_sase_directory("plugins")` (the standard `sase_home()`
  convention).
- Envelope: `{"schema_version": 1, "fetched_at": <epoch>, "query": "...", "entries": [ … ]}`, written atomically (temp
  file + rename).
- Behavior: **first run** (no cache) fetches and writes. **Subsequent runs** use the cache and never touch the network
  unless `--refresh` is passed. The footer always shows cache age and the refresh command. If the cache is older than a
  soft staleness threshold (e.g. 7 days) the footer warns more loudly — but we still never auto-fetch, because
  predictable latency beats surprise slowness.

### 6. CLI conventions (per `memory/cli_rules.md`)

- `sase plugin` (bare) delegates to `sase plugin list` automatically via the central `_default_list_subcommands`
  mechanism (just define an exact `list` child; the delegation notice is wired for free). Documented in the group help.
- Every public long option gets a short alias: `-j|--json`, `-r|--refresh`, `-v|--verbose`.
- Subcommands and options listed alphabetically; `-h|--help` made excellent.
- Beautiful colored output preferred over plain.

---

## Data Model

A small, frozen-dataclass model in `src/sase/plugins/catalog.py`:

- `PluginCatalogEntry`: `name` (short, e.g. `github`), `repo` (`sase-github`), `full_name` (`sase-org/sase-github`),
  `owner`, `description`, `url`, `homepage`, `topics: tuple[str, …]`, `stars`, `archived`, `license`, `updated_at`, and
  a derived `kind: Literal["builtin", "community"]`.
- `InstalledInfo` (derived at merge time): `installed: bool`, `version: str | None`, `entry_point_groups`.
- `PluginCatalog`: `fetched_at`, `entries: tuple[PluginCatalogEntry, …]`, plus cache-age helpers; the public loader
  returns entries already merged with installed info.
- Public API: `load_plugin_catalog(*, refresh: bool) -> PluginCatalog` and
  `find_plugin(catalog, query) -> PluginCatalogEntry | None` (name matching + suggestions).

Name matching (`show`): case-insensitive against short name (`github`), repo (`sase-github`), and full name
(`sase-org/sase-github`); on miss, return ranked suggestions.

---

## Phases

Four phases, each completed by a **distinct agent instance**, each self-contained and each leaving the tree green
(`just check` passes). Every phase begins with `just install` (ephemeral-workspace requirement) and ends with
`just check`. Note: there are ~8 **pre-existing** `llm_provider` `invoke_agent` failures in this dev env caused by
`default_effort: xhigh` — these are _not_ regressions from this work and should be ignored.

### Phase 1 — Catalog engine (library only, no CLI)

**Goal:** the reliable foundation — fetch, classify, cache, and merge — with zero CLI surface.

**Build:**

- `src/sase/plugins/catalog.py` — data model + `load_plugin_catalog(refresh=…)` orchestration + `find_plugin`.
- `src/sase/plugins/github_source.py` — the `gh api` subprocess call + JSON parsing into `PluginCatalogEntry`, with
  `gh`-missing / unauth / timeout handling.
- `src/sase/plugins/cache.py` — read/write the `~/.sase/plugins/catalog_cache.json` envelope (atomic write), cache-age
  computation, staleness threshold.
- Installed-merge helper (in `catalog.py` or a small `installed.py`) reusing `collect_plugin_inventory()` and
  `version/_plugins` normalizers.

**Tests** (`tests/test_plugin_catalog*.py`): parse a fixture `gh api` payload into entries; built-in vs. community
classification; installed-merge (distribution match + console-script match + not-installed); cache write→read round-trip
and age; `--refresh` vs. cache-hit path; `gh` missing / failed-call fallback to cache and the actionable-error path (all
with mocked subprocess + tmp `SASE_HOME`).

**Handoff:** Phases 2 & 3 consume only `load_plugin_catalog`, `find_plugin`, and the model — no GitHub or cache details
leak into the CLI layer.

### Phase 2 — `sase plugin list` command + rendering

**Goal:** wire the command into the CLI and render the beautiful list.

**Build:**

- `src/sase/main/parser_plugin.py` (`register_plugin_parser`) with a `list` subparser and flags `-j|--json`,
  `-r|--refresh`, `-v|--verbose`; register it alphabetically in `src/sase/main/parser.py` (import +
  `register_plugin_parser(top_level_subparsers)` between `parser_path`/`parser_project`).
- `src/sase/main/plugin_handler.py` (`handle_plugin_command`) dispatching the `list` subcommand; dispatch from
  `src/sase/main/entry.py` in sorted order.
- `src/sase/plugins/cli_list.py` + `src/sase/plugins/render.py` — Rich two-section (built-in/community) table in a
  titled panel, legend + counts + cache-age footer, and the stable `-j|--json` payload (`schema_version`, entries with
  installed + cache metadata).
- Update the "namespace is reserved" wording in `src/sase/plugins/inventory.py` docstring so the repo is internally
  consistent now that the command exists.

**Tests** (`tests/test_plugin_cli_list.py`): parser accepts `sase plugin`, `sase plugin list`, and each flag; bare
`sase plugin` triggers the delegation notice; JSON shape is stable; rendered output contains the built-in/community
section labels and the community warning; `--refresh` is threaded to the loader (mock Phase 1).

### Phase 3 — `sase plugin show <plugin_name>` command + rendering

**Goal:** the detailed single-plugin view.

**Build:**

- Add a `show` subparser (positional `<plugin_name>`, `-j|--json`, `-r|--refresh`) to `parser_plugin.py`; dispatch in
  `plugin_handler.py`.
- `src/sase/plugins/cli_show.py` + a detail renderer in `render.py` — the detail panel, the prominent community warning
  panel, installed/entry-point/repo/homepage/topics/stars/updated/license rows, install hint when not installed, and the
  JSON payload. Not-found → ranked "did you mean…?" suggestions, non-zero exit.

**Tests** (`tests/test_plugin_cli_show.py`): found (built-in & community), not-found-with-suggestions, JSON shape,
community-warning presence, installed vs. not-installed rendering, name matching across short/repo/full forms.

### Phase 4 — Polish, docs, and contract sync

**Goal:** make it production-grade and consistent across the repo.

**Build:**

- `-h|--help` excellence for the group and both subcommands (clear, alphabetical, examples).
- Docs: rewrite the "There is no `sase plugin` command" section of `docs/plugins.md` into a "Plugin Catalog
  (`sase plugin list` / `sase plugin show`)" section; add the `sase plugin` rows to the `docs/cli.md` command table.
- Verify no CLI-surface snapshot/contract test needs regenerating; update if so. Confirm whether any generated skill
  (`src/sase/xprompts/skills/`) references the plugin command surface — none is expected (this feature does not change
  `sase commit`), but confirm and run `sase skill init --force` only if a source actually changed.
- Final `just install && just check`; run `just test-visual` only if any ACE PNG snapshot is affected (not expected,
  since this is a CLI command, not a TUI change).

**Note:** the stray, untracked `sase_plan_plugin_command.md` at repo root described a _different_ (list + doctor,
installed-only) design and is superseded by this plan; leave it untouched.

---

## Out of Scope / Future Work

- `sase plugin add/remove/sync` (install mutation) — needs an install-profile model; deliberately deferred.
- Config-izing `SASE_PLUGIN_ORG` and the cache staleness threshold (start as module constants).
- A `sase-plugin-manifest`-driven richer metadata source (the topic + repo metadata is sufficient now).
- Moving any of this into `sase-core` (see Decision #1).

## Risks & Mitigations

- **`gh` unauthenticated / rate-limited.** Mitigated by cache-first behavior, the stale-cache fallback, and doctor-style
  actionable errors.
- **Topic not yet applied to a repo.** The catalog is purely data-driven off the live topic search, so it always
  reflects reality; repos gain/lose the topic with no code change. (User has already tagged `sase-github` and
  `sase-telegram`.)
- **Repo→distribution name mismatch for installed detection.** Mitigated by reusing the existing `version/_plugins`
  normalizers and console-script signal detection rather than re-inventing matching.
