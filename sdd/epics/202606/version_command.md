---
create_time: 2026-06-08 15:26:21
status: done
prompt: sdd/prompts/202606/version_command.md
bead_id: sase-4h
tier: epic
---
# `sase version` Runtime Inventory Plan

## Objective

Add a top-level `sase version` command that reports the exact SASE runtime the user is currently executing:

- the `sase` host package,
- the required Rust core distribution, `sase-core-rs`,
- every installed SASE plugin package, including entry-point plugins such as `sase-github` and script-only plugins such
  as `sase-telegram`,
- each package's effective version and the directory containing the Python or Rust code being used by this `sase`
  process.

The command should be intuitive for humans, stable for scripts, and honest in development/editable installs where
distribution metadata can lag behind the source tree.

## Current Context

The recent `sase-4e` epic established the release policy that matters here:

- repositories use `vX.Y.Z` tags,
- released versions are SemVer-compatible while still following zero-ver behavior,
- `sase` is currently released through Release Please,
- `sase-core-rs` is the Python distribution for the Rust core and gets its version from the Cargo workspace,
- `sase-github` and `sase-telegram` are Python plugin packages.

The current checkout shows `sase` source version `0.1.2`, tags `v0.1.0`, `v0.1.1`, and `v0.1.2`, and HEAD is ahead of
`v0.1.2`. The installed `sase` command on PATH is an editable uv tool install that imports code from
`/home/bryan/projects/github/sase-org/sase/src/sase`, but its installed distribution metadata still reports `0.1.0`.
That is the key reliability trap: `sase version` cannot blindly trust `importlib.metadata.version()` for editable
installs.

Existing command patterns:

- top-level CLI commands are registered through `src/sase/main/parser.py` and dispatched in `src/sase/main/entry.py`,
  kept alphabetically sorted,
- human plugin diagnostics already use Rich tables and panels,
- JSON modes use `schema_version` and stable dictionaries,
- `sase core health` already reports Rust extension path/version health, but it is a health probe, not a complete
  runtime/package inventory.

## Product Design

Primary command:

```bash
sase version
sase version --json
sase version --verbose
```

Human output should be a compact Rich panel plus a table:

```text
SASE Runtime
Executable  /home/bryan/.local/bin/sase
Python      /home/bryan/.local/share/uv/tools/sase/bin/python 3.14.3

Package        Role    Version                     Code directory
sase           host    0.1.2+4.g26c39e004          /home/bryan/projects/github/sase-org/sase/src/sase
sase-core-rs   core    0.1.1+untagged.g74f5e97     /home/bryan/projects/github/sase-org/sase-core
sase-github    plugin  0.1.0+70.g1448b2d           /home/bryan/projects/github/sase-org/sase-github/src/sase_github
sase-telegram  plugin  0.1.0+untagged.g0efad96     /home/bryan/projects/github/sase-org/sase-telegram/src/sase_telegram
```

`--verbose` should add the audit fields that are useful but too noisy for the default table:

- install type: editable, wheel, unknown,
- distribution metadata version,
- source metadata version,
- git root, tag, distance, commit, dirty state,
- entry point and console script signals that caused a package to be classified as a plugin,
- import module/path when different from the source root.

`--json` should emit a stable object with `schema_version: 1`, runtime fields, and a `packages` array. JSON should
include all default and verbose fields so scripts do not need a separate verbose flag.

The command should exit `0` even when optional plugin records are incomplete. Missing paths, unresolved import modules,
or git failures should appear as warnings on the affected record. The command should not import plugin provider classes
or execute plugin code just to display versions.

Out of scope: querying PyPI, GitHub releases, or "latest available" versions. This command reports the local runtime
that `sase` is actually using.

## Version Semantics

Use PEP 440-compatible local version syntax for development checkouts:

- clean checkout exactly at `v0.2.3`: `0.2.3`,
- two commits after `v0.2.3`: `0.2.3+2.g<sha>`,
- dirty checkout two commits after `v0.2.3`: `0.2.3+2.g<sha>.dirty`,
- dirty checkout exactly at `v0.2.3`: `0.2.3+0.g<sha>.dirty`,
- no reachable `vX.Y.Z` tag: `<source-or-dist-version>+untagged.g<sha>` with optional `.dirty`.

For editable installs, prefer source metadata over installed distribution metadata:

- Python packages: read `[project].version` from the source `pyproject.toml` when present.
- Rust core: read `[workspace.package].version` from the nearest Cargo workspace for `sase-core-rs` when the source root
  is available.
- Keep the installed distribution metadata version in verbose/JSON fields so stale editable metadata is visible.

For wheels or non-git installs, display the installed distribution version and the import/package directory.

## Discovery Model

Create an internal runtime inventory collector that produces immutable records. Each record should include:

- package name and role: `host`, `core`, or `plugin`,
- display version,
- installed distribution metadata version,
- source metadata version when discoverable,
- import module, import path, code directory, source root, and distribution location,
- install type from `direct_url.json` when available,
- plugin signals: SASE entry points, SASE console scripts, and/or SASE package-name convention,
- optional git metadata and warnings.

Package inclusion rules:

- Always include `sase` if the command is running.
- Always include `sase-core-rs`; if metadata or import resolution fails, include a degraded core row with warnings.
- Include installed distributions that contribute entry points in SASE groups.
- Include installed distributions whose console scripts start with `sase_chop_` or otherwise expose SASE plugin
  commands.
- Include installed distributions named `sase-*`, excluding `sase-core-rs` from the plugin role because it is the core.

Code directory rules:

- For editable Python packages, prefer the imported package directory, for example `.../src/sase_github`.
- For editable Rust core, prefer the git/workspace root that contains the Rust code, and also keep the Python extension
  import path in JSON.
- For wheels, use the resolved import package directory or extension package directory in `site-packages`.
- If a package cannot be mapped to an import module, fall back to the distribution location and emit a warning.

Git enrichment should be best-effort, cached per git root, and bounded by short subprocess timeouts. A broken or missing
`git` command should never make `sase version` fail.

## Phase 1: Runtime Version Collector Foundations

Scope: core data model and version derivation for `sase` and `sase-core-rs`; no user-facing CLI yet.

Deliverables:

- Add an internal module for version inventory records and collection helpers.
- Resolve installed distributions with `importlib.metadata`.
- Parse `direct_url.json` to identify editable installs and source roots.
- Resolve import/module paths without loading plugin/provider code.
- Read source versions from Python `pyproject.toml` and Rust `Cargo.toml`.
- Implement the git-to-display-version algorithm described above.
- Add focused unit tests for:
  - wheel-style metadata only,
  - editable Python source with stale distribution metadata,
  - editable Rust core with dynamic Python version and Cargo workspace version,
  - exact tag, ahead-of-tag, dirty, and untagged git states,
  - missing git or missing source metadata fallbacks.

Verification:

- Run the new collector tests directly.
- Run existing `tests/test_core_health.py` to ensure no Rust health behavior regresses.

## Phase 2: Plugin Package Discovery

Scope: complete plugin detection and code-directory mapping for installed SASE plugin packages.

Deliverables:

- Extend the collector to scan installed distributions once and classify plugin packages from:
  - SASE entry point groups,
  - `sase_chop_*` console scripts,
  - `sase-*` distribution names.
- Include script-only plugins such as `sase-telegram`.
- Deduplicate records across multiple signals from the same distribution.
- Preserve entry point/script signal details for verbose and JSON output.
- Avoid `EntryPoint.load()` for provider classes and plugin modules.
- Add tests with fake distributions for:
  - `sase-github`-style entry-point plugin,
  - `sase-telegram`-style console-script plugin,
  - a plugin with both signals,
  - a malformed plugin with no resolvable module path,
  - disabled plugin environment variables, confirming version inventory still reports installed packages because it is
    inventory, not runtime loading.

Verification:

- Run the new version collector/plugin tests.
- Run `tests/main/test_plugin_command.py` to make sure existing plugin diagnostics still behave the same.

## Phase 3: CLI, Rendering, And JSON Contract

Scope: add the actual `sase version` command with polished output.

Deliverables:

- Register `version` as a top-level command in the argparse command tree and dispatcher, preserving alphabetical help
  order.
- Add `--json`/`-j` and `--verbose`/`-v`.
- Add a human renderer using Rich with:
  - a runtime summary panel,
  - a primary package table,
  - restrained color for roles/status,
  - folded paths so long source directories remain readable.
- Add JSON serialization with `schema_version: 1`.
- Keep default human output dense and useful; reserve metadata internals for `--verbose` and JSON.
- Add tests for:
  - parser acceptance,
  - sorted help entries,
  - human output includes package, version, and code directory,
  - JSON schema and representative fields,
  - warning rendering for incomplete package records.

Verification:

- Run the new CLI tests.
- Run `tests/main/test_parser_help.py`.
- Run `sase version` and `sase version --json` from the active runtime and inspect that `sase`, `sase-core-rs`,
  `sase-github`, and `sase-telegram` are represented when installed.

## Phase 4: End-To-End Runtime Hardening

Scope: prove the command behaves correctly in realistic install shapes.

Deliverables:

- Add an end-to-end test harness or documented smoke that covers:
  - editable `sase` with stale installed metadata,
  - editable `sase-core-rs` backed by a sibling Rust checkout,
  - wheel-like package metadata without source roots,
  - plugin packages installed in the same Python environment as the `sase` executable.
- Add short subprocess timeouts and per-root caching for git metadata.
- Ensure the command remains fast enough for interactive use.
- Decide whether to expose a `--no-git` flag if git probing is measurable or flaky; otherwise keep git best-effort and
  invisible.
- Verify that `sase version` does not import plugin code by using sentinel tests that would fail if `EntryPoint.load()`
  is called.

Verification:

- Run the full version-command test suite.
- Run `just test` if the phase touches only Python tests and CLI code.
- Run `just check` before handing off if practical.

## Phase 5: Documentation And Final Polish

Scope: make the feature discoverable and finalize the contract.

Deliverables:

- Document `sase version` in:
  - CLI docs,
  - configuration/command reference if applicable,
  - Rust backend docs where it complements `sase core health`.
- Include a short explanation that `sase version` reports the local runtime, not latest available releases.
- Include examples of developer versions such as `0.1.2+4.g26c39e004`.
- Mention stale editable metadata handling so contributors understand why source and distribution versions may both
  appear in verbose/JSON output.
- Run the same docs formatting/check flow used by the repo.
- Do a final command smoke in the real uv-tool runtime and in the local test environment.

Verification:

- Run docs-related checks if available.
- Run `just check` for the final integrated state.
- Capture final sample outputs for `sase version` and `sase version --json` in the phase notes.

## Acceptance Criteria

- `sase version` lists at least `sase` and `sase-core-rs` in every runnable SASE environment.
- Installed plugin packages are listed whether they use SASE entry points or SASE console scripts.
- Every listed package has a best-effort code directory that points at the Python package directory, Rust source root,
  or installed package directory actually used by the running `sase`.
- Editable installs prefer source versions over stale installed distribution metadata, while still exposing the metadata
  version for auditability.
- Development checkouts use clear PEP 440 local versions such as `0.2.3+2.gabc1234`.
- Human output is compact, readable, and path-friendly.
- JSON output is stable and complete enough for support/debug tooling.
- The command avoids plugin imports and remains robust when optional plugins are broken.
