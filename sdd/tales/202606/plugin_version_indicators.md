---
create_time: 2026-06-26 07:11:53
status: wip
prompt: sdd/prompts/202606/plugin_version_indicators.md
---
# Plan: installed-vs-latest version indicators for `sase plugin list` / `sase plugin show`

## Goal

Make `sase plugin list` and `sase plugin show` show, for each plugin, **the installed version (if any)** and **the
latest available version**, with a **beautiful, unmissable indicator when an update is available** (installed version ≠
latest). The bar is the existing `sase plugin` output: intuitive, reliable, and beautiful, with glyphs that carry
meaning even with color stripped.

Today both commands already render the _installed_ version (`InstalledInfo.version`, glyph `●`/`○`). They have **no
concept of "latest available"** — the entire `src/sase/plugins/` + `src/sase/uv_tool/` subsystem only ever reads the
_local_ environment. This feature adds the missing "what's the newest version out there, and am I behind?" half.

## Investigation that reshapes the design (read first)

I mapped the existing plumbing before designing. The facts that drive every decision below:

1. **There is no latest-version capability anywhere.** Installed versions come from `importlib.metadata` (local).
   "Latest available" must be fetched from somewhere new. We are adding the first network lookup of package versions.

2. **Plugins are installed from the package index (PyPI), and that is what an update actually pulls.**
   `sase plugin install <name>` / `sase plugin update <name>` run `uv tool install … --with <dist>` /
   `uv tool upgrade --upgrade-package <dist>`, which resolve from the configured index (PyPI by default). So the **only
   honest source of "latest available"** — the version an update would actually install — is **the package index**, not
   GitHub release tags. (Catalog entries are discovered via the GitHub `sase-plugin` topic, but a repo's latest _git
   tag_ can lag or lead what is published on PyPI; using it would make the indicator lie.) **Decision: latest = PyPI's
   `info.version`.**

3. **Some installs have no comparable "version".** A plugin can be installed **editable** (a dev checkout — the sase
   workspace itself is one) or from **git**. For those, comparing the local version string against a PyPI version would
   produce a _false_ "update available". We must detect those installs and **not** show an upgrade prompt for them. PEP
   610 `direct_url.json` (read via `importlib.metadata`, stdlib, uv-independent) tells us editable-vs-git-vs-index
   **without** needing the uv receipt — so this works even from a dev checkout where the receipt probe would fail.

4. **`packaging` is not yet a dependency, and the repo does no version comparison at all.** Correct ordering needs PEP
   440 semantics (`1.10.0 > 1.9.0`, pre-release handling). Hand-rolled tuple comparison is wrong for real versions.

5. **The two commands are read-only and must stay instant.** The catalog is already cache-first
   (`~/.sase/plugins/catalog_cache.json`, never auto-fetches on a cache hit). A naive per-plugin PyPI call on every
   invocation would make `list` slow and flaky. We need caching + concurrency + graceful offline behavior, mirroring the
   catalog's "predictable latency beats surprise slowness" ethos.

6. **`urllib.request` is the established HTTP precedent** (the `telemetry/` modules); there is no shared HTTP helper. We
   follow that pattern (Request + `urlopen(timeout=…)` + tight try/except), with the call injected for hermetic tests.

## Pivotal design decisions (I am leading these)

- **D1 — Latest available = the package index (PyPI) `info.version`.** This is the version an actual
  `sase plugin update` would install, so the indicator never lies. A plugin not published to PyPI (git-only catalog
  entry → HTTP 404) honestly renders as "not on the index" rather than inventing a version. _(Rejected: GitHub release
  tags — they diverge from what uv installs.)_

- **D2 — Source-aware honesty: only index installs get a version comparison.** Per PEP 610 `direct_url.json` we classify
  each _installed_ plugin as `index` / `git` / `editable`. **Only `index` installs** are compared against PyPI and can
  show "update available". `editable` and `git` installs render a **source label** (`editable`, `git`) and **never** a
  false upgrade prompt. This is what keeps the feature reliable instead of noisy — and correct in the dev workspace.

- **D3 — Correct comparison via `packaging` (new dependency), behind a safe wrapper.** Add `packaging` to
  `pyproject.toml`. A single `is_newer(latest, installed) -> bool` helper uses `packaging.version.Version`, and returns
  `False` on any `InvalidVersion` — so a weird version string degrades to "no update shown" rather than a crash or a
  false positive. _(packaging is pure-Python, ubiquitous, and the canonical tool; declaring it explicitly is cleaner
  than a vendored comparator.)_

- **D4 — A separate enrichment step; the catalog loader stays network-free for install/update.** `load_plugin_catalog()`
  is shared by `install`/`update` and must **not** start hitting PyPI. Latest-version resolution is a **distinct
  enrichment** — `enrich_with_latest(catalog, …) -> PluginCatalog` — invoked **only** by `cli_list` and `cli_show`. It
  returns a new catalog whose entries carry a populated `LatestInfo` (via `dataclasses.replace`). Network cost is
  isolated to the two read commands; `install`/`update` are untouched.

- **D5 — Fast and reliable by construction.** Enrichment is: **cache-first** (a new short-TTL on-disk cache,
  `~/.sase/plugins/latest_cache.json`, mapping normalized dist name → version + fetch time), then
  **bounded-concurrency** network for cache misses (`ThreadPoolExecutor`, small worker pool, short per-request timeout),
  with **graceful degradation** — any timeout/DNS/404/parse failure yields `LatestInfo(checked=True, version=None, …)`
  rendered as a dim "unknown", **never** an error and **always** exit 0 on the read path. `-r|--refresh` bypasses the
  latest cache (it already bypasses the catalog cache); a new `-o|--offline` flag uses cache only and makes **zero**
  network calls.

- **D6 — Stays in Python (boundary check).** Per `rust_core_backend_boundary.md`: the whole plugin catalog + uv-tool
  install/update subsystem already lives in `src/sase/` with **no** `sase-core` counterpart, and this change is
  presentation plus a thin PyPI lookup adapter. No web/editor frontend needs to mirror "ask PyPI for the latest plugin
  version" to match the TUI. **No `sase-core` (Rust) changes.** (Called out so a reviewer can confirm with eyes open.)

- **D7 — Dependency-injected seams, hermetic tests.** The PyPI fetch (`urlopen_fn`), the clock, and the cache read/write
  are injected exactly like the existing `fetch_fn` / `run_fn` / `now` seams. **No unit test touches the real network**;
  comparison, source detection, caching, enrichment, rendering, and JSON are all tested with fakes.

## The visual design (the "beautiful" half — this is the point)

Color enhances but never carries meaning alone; every state has a distinct glyph + explicit label, matching the existing
renderer's grammar (`● ○ ✓ ✗ · → ⚠ ★`). New glyph: **`↑`** = update available.

**`sase plugin list`** — the installed-version column becomes version-transition aware:

```
SASE Plugins
 ● github         v0.3.2 → v0.4.0  ↑   sase_vcs            GitHub VCS & workspace provider
 ● telegram       v0.1.0               sase_config         Telegram chat-driven workflows
 ● devkit         editable             sase_xprompts       (local dev checkout)
 ○ someplugin     latest v2.1.0        —                   A community plugin (not installed)

 ● installed  ○ available  ↑ update available
 3 built-in · 4 community · 3 installed · 1 update available
 ↑ 1 update available · run `sase plugin update --all`
 Cached 2h ago · run `sase plugin list --refresh` to update
```

- **Installed + update available** → `v0.3.2 → v0.4.0` (old dim, new green/cyan) + a trailing `↑`. Pops without
  shouting; reuses the exact `old → new` idiom already in the install/update result renderer.
- **Installed + current** → `v0.1.0` (green), no arrow — calm.
- **Installed editable/git** → the source label (`editable` / `git`), no version math, no `↑`.
- **Not installed** → `latest v2.1.0` (dim) when known; `○ available` unchanged.
- **Latest unknown (offline / not on PyPI)** → installed version alone, or a dim `—` / `latest unknown`.
- **Footer** gains an `updates_available` count and, when > 0, an actionable CTA line; the legend gains the `↑` entry.

**`sase plugin show <name>`** — add a dedicated **Latest** row beneath **Installed**:

```
 Installed   ✓  v0.3.2   (sase_vcs)
 Latest      v0.4.0   ↑ update available — run `sase plugin update github`
```

- Up to date → `Latest  v0.3.2   ✓ up to date`.
- Not installed → `Latest  v0.4.0` + the existing `sase plugin install <name>` hint.
- Editable/git install → `Installed  ✓ editable (local checkout)` and a Latest row that explains no comparison is made.
- Offline/unknown → `Latest  unknown` (dim) with a hint to drop `-o|--offline` or run `-r|--refresh`.

## New / changed modules

**New (`src/sase/plugins/`):**

- **`pypi_source.py`** — `fetch_latest_version(dist_name, *, urlopen_fn=…, timeout=…) -> str | None`. GETs
  `https://pypi.org/pypi/<dist>/json`, returns `info.version`; `None` on 404 (not on index), timeout, or parse error.
  `urllib.request` per the telemetry precedent; `urlopen_fn` injected for tests.
- **`latest_cache.py`** — short-TTL on-disk cache (`~/.sase/plugins/latest_cache.json`) of
  `dist name → {version, fetched_at}`, mirroring `cache.py`'s atomic temp-file + `os.replace` write, schema-versioned,
  with a `LATEST_TTL` constant. `read`/`write`/`is_fresh` helpers.
- **`latest.py`** — the model + orchestration:
  - `LatestInfo` (frozen): `checked: bool`, `version: str | None`,
    `source: Literal["index","git","editable","unknown"]`, `error: str | None`, plus an `.unknown()` constructor
    (parallels `InstalledInfo.not_installed()`).
  - `installed_source(dist) -> "index"|"git"|"editable"` via PEP 610 `direct_url.json`
    (`dist.read_text("direct_url.json")`), defaulting to `index`.
  - `is_newer(latest, installed) -> bool` (the `packaging` wrapper, safe on `InvalidVersion`).
  - `enrich_with_latest(catalog, *, offline=False, refresh=False, fetch_fn=…, cache fns=…, clock=…) -> PluginCatalog`:
    cache-first, bounded-concurrency fetch for misses, attaches `LatestInfo` to every entry, fully injected.

**Edited:**

- **`catalog.py`** — add `latest: LatestInfo = field(default_factory=LatestInfo.unknown)` to `PluginCatalogEntry`; add
  an `update_available` property (installed **and** `source == "index"` **and** `latest.version` known **and**
  `is_newer(latest, installed)`); add `updates_available` count to `PluginCatalog`. Loader logic unchanged (D4).
- **`render.py`** — version-transition cell + `↑` glyph + footer CTA/legend in `render_catalog_list`; a `Latest` row +
  indicator + action hint in `render_catalog_show`. New glyph/style constants; reuse `_humanize_age`.
- **`json_payload.py`** — extend `plugin_entry_json` with a `latest` object:
  `{checked, version, source, update_available, error}`.
- **`cli_list.py`** / **`cli_show.py`** — call `enrich_with_latest` after `load_plugin_catalog` (honoring `--offline`
  /`--refresh`) so **both** text and `--json` reflect latest; bump `LIST_JSON_SCHEMA_VERSION` /
  `SHOW_JSON_SCHEMA_VERSION` to `2`; add `counts.updates_available` to the list payload.
- **`parser_plugin.py`** — add `-o|--offline` to `list` and `show` (use cache only, no network); refresh the
  descriptions/epilogs to mention the update indicator and offline mode. Keep options **alphabetical**, every long
  option short-aliased.
- **`pyproject.toml`** — add `packaging` to `dependencies` (then `just install`).
- **Docs** — `docs/plugins.md` (catalog section: latest/update indicators, offline flag, the new cache) and
  `docs/cli.md` (plugin rows reference the indicator).

## CLI-rules compliance

- `-h|--help` stays excellent and scannable; new `-o|--offline` is documented with examples; options remain alphabetical
  and short-aliased. The bare-`sase plugin` → `list` default (central `_default_list_subcommands`) is untouched.
- New flags affect only `list`/`show`; `install`/`update`/`sase update` are not changed.

## CLI / skill contract

The CLI/skill-sync rule in `generated_skills.md` is scoped to `sase commit`. As a guard I'll grep
`src/sase/xprompts/skills/` for any `sase plugin list`/`show` usage; if a skill demonstrates these flags, regenerate via
`sase skill init --force` (+ `chezmoi apply`). Expectation: no skill change needed.

## Testing (mirrors existing patterns; no real network)

- **`pypi_source`** — `info.version` parsed; 404 / timeout / malformed JSON → `None`; injected `urlopen_fn`.
- **`latest_cache`** — round-trip, atomic (no temp leftovers), TTL freshness, schema-version guard.
- **source detection** — `index` / `git` / `editable` from synthetic `direct_url.json`; default `index` when absent.
- **`is_newer`** — `1.10 > 1.9`, equal, downgrade, pre-release, and `InvalidVersion → False`.
- **`enrich_with_latest`** — cache hit avoids network; miss fetches once; `--offline` makes zero calls; one failure
  doesn't sink the batch; `--refresh` bypasses cache.
- **render** (Console→`StringIO`, `no_color`, substring asserts as in `test_plugin_cli_list.py`/`_show.py`) — list:
  update available (`→` + `↑` + footer CTA), all current, not-on-index, editable source, offline; show: update
  available, up to date, not-installed-with-latest, editable/git, offline.
- **JSON** — new `latest` block present and stable; `counts.updates_available` correct; `schema_version == 2` (update
  the stable-shape tests).
- **handlers** — `-o|--offline` skips fetch (assert injected fetch not called); default enriches; `--refresh` bypasses
  the latest cache; exit code stays 0 on enrichment failure.

## Out of scope (possible follow-ups)

- A standalone `sase plugin outdated` summary command (the data now exists; a focused report is a natural next step).
- Respecting a plugin's pinned version specifier from the uv receipt when deciding "update available" (edge case: most
  installs are unpinned; v1 compares against PyPI latest and labels non-index sources instead).
- Index configuration awareness (private/extra indexes via uv/pip config) — v1 assumes the default public PyPI, matching
  how the community catalog is published.
- Surfacing the indicator in the ACE TUI or any editor/web frontend — none; this is the two CLI read commands only.

## Suggested phasing (each independently shippable; `just check` green at every phase)

1. **Latest-version engine** — `pypi_source.py`, `latest_cache.py`, `latest.py` (`LatestInfo`, source detection,
   `is_newer`, `enrich_with_latest`), the `packaging` dependency, and `PluginCatalogEntry.latest` / `update_available` /
   `updates_available`. Exhaustive unit tests. No user-facing change yet.
2. **Wire into `list` + `show`** — `-o|--offline` parser flag; enrichment in `cli_list`/`cli_show`; the list + show
   renderer states; `json_payload` + schema bumps + `updates_available` count. Render/JSON/handler tests.
3. **Polish, docs, verification** — beauty + `-h` sweep across both commands; edge-case pass (offline, not-on-PyPI,
   editable/git, pre-release); `docs/plugins.md` + `docs/cli.md`; skill-contract grep; `just install && just check`
   green; then **close the tracking bead** as the final step.
