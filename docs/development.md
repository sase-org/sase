# Development

This page orients contributors working in the `sase` repository. It covers local setup, verification, source layout, and
documentation publishing paths.

## Setup

Requirements:

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- [`just`](https://github.com/casey/just)

```bash
uv venv .venv
source .venv/bin/activate
just install
sase --help
```

`just install` installs the package in editable mode with development dependencies. When a sibling `../sase-core`
checkout is present and `cargo` is available, it also builds and installs the local `sase_core_rs` extension before
resolving Python dependencies.

## Verification Commands

```bash
just install       # Install with dev deps
just fmt           # Auto-format code and Markdown
just lint          # Run ruff, mypy, pyscripts, symvision, toobig, and keep-sorted
just test          # Fast parallel test run, including PNG visual snapshots
just test-slow     # Slow pytest subset only
just test-visual   # ACE PNG visual regression snapshots only
just test-terminal-smoke  # Optional real-terminal ACE smoke test
just test-cov      # Parallel test run with coverage + 50% gate, including visual snapshots
just check         # CI-style checks: formatting, lint, SDD validation, tests
just test-tox      # Test across Python 3.12, 3.13, 3.14
just clean         # Remove build artifacts
just build         # Build wheel and sdist
```

`just test`, `just test-slow`, `just test-visual`, and `just test-cov` size the pytest-xdist worker pool from local CPU
count, capped at 16. Set `SASE_PYTEST_WORKERS=<N>` to override that value. Test selectors are normalized from the
directory where `just` was invoked, so this works the same from the repository root or a subdirectory:

```bash
just test tests/main/test_parser.py::test_example
```

`just lint` and `just fix-keep-sorted` bootstrap a project-local `keep-sorted` executable into `.venv/bin/` from `PATH`,
or by running `go install github.com/google/keep-sorted@v0.8.0` when Go is available. If neither `keep-sorted` nor Go is
installed, those recipes fail with a setup error before linting YAML keep-sorted blocks.

Default test runs exclude `slow` and `terminal_smoke` markers but include the ACE PNG snapshot regression tests. Use
`just test-visual` for focused visual-snapshot work; both recipes install the optional PNG rasterizer dependencies when
they are missing. Direct `pytest` runs still inherit the repository `pyproject.toml` default marker expression, which
excludes `slow`, `terminal_smoke`, and `visual` unless you pass your own `-m` selector.

Use `just test-terminal-smoke` only when you need to verify the ACE startup path through a real PTY. It installs
`pexpect` and `pyte`, runs the optional `terminal_smoke` marker, and stays out of default tests and CI until that path
has proved stable.

## Visual Snapshot Workflow

ACE visual tests live under `tests/ace/tui/visual/` and compare deterministic Textual screenshots against committed PNG
goldens. The renderer stack is exact-pinned in the `visual` optional-dependency group in `pyproject.toml`, and
`tests/ace/tui/visual/renderer_env.json` records those package versions plus hashes of the bundled fonts. A
session-scoped fixture checks that fingerprint before any snapshot runs, so a skewed environment fails once with an
installation or upgrade instruction instead of producing a wall of misleading pixel diffs.

The visual fixtures also pin the process environment that affects rendering: `TERM=xterm-256color` and
`COLORTERM=truecolor` select Rich's truecolor path, `FORCE_COLOR` and `NO_COLOR` are removed, and `TZ=UTC` is applied
with the process timezone cache refreshed. Neither a contributor's terminal settings, local timezone, nor CI's process
environment participates in the golden corpus.

Run the focused suite normally first:

```bash
just test-visual
```

When a visual test fails, inspect the artifacts under `.pytest_cache/sase-visual/<node>/<snapshot>/`. Each failure
directory contains the actual PNG capture and, when a golden exists, the expected PNG plus a diff PNG, a human-readable
`summary.txt`, and a structured `failure.json` sidecar. The sidecar carries the test source location, repo-relative
golden path, and pixel-diff stats so tooling can map a failure back to the test and the committed golden.

To accept an intentional change to the full golden corpus on Linux, use the guarded regeneration recipe:

```bash
just update-visual-snapshots
```

For a targeted UI change, the underlying pytest option still accepts a selector:

```bash
just test-visual -- --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots.py
```

Both forms refuse to write if the renderer fingerprint is skewed or the host is not Linux. Review changed PNG files as
normal test data. Do not pass `--sase-update-visual-snapshots` to `just check`, `just fmt`, or broad CI-style commands.

Committed goldens are canonical to the pinned renderer. Rasterization goes through resvg (`resvg_py==0.3.3`), a
pure-Rust SVG renderer that carries its own font database restricted to the bundled Fira Code
(`tests/ace/tui/visual/fonts/`) with `skip_system_fonts=True`. No host font-config or graphics stack participates, so
rendering is stable and host-font-independent on the canonical Linux x86_64 platform. PNG comparison is byte-exact by
default locally and in every visual-bearing CI lane; together with the fixture-level terminal and timezone pins, a
mismatch is a real rendering change or an unpinned environment defect to investigate.

Rasterization can still differ by a small, bounded amount on macOS arm64. The tolerance environment variables remain
available only as explicit escape hatches for local iteration and renderer investigations. For the known macOS drift,
use:

```bash
SASE_VISUAL_PNG_MAX_DIFF_RATIO=0.01 \
SASE_VISUAL_PNG_MATERIAL_DIFF_THRESHOLD=8 \
SASE_VISUAL_PNG_MAX_MATERIAL_DIFF_PIXELS=0 \
just test-visual
```

The ratio caps the changed image area. The material threshold measures the maximum visible channel distance after
alpha-aware compositing over black and white, and the material-pixel cap still rejects any change above that threshold.
These overrides never update or implicitly accept a golden, and they do not bypass the Linux-only regeneration gate.
Per-assertion equivalents are `max_diff_pixels`, `max_diff_ratio`, `max_material_diff_pixels`, and
`material_diff_threshold`.

Mismatch assertions, `summary.txt`, and `failure.json` report `material_diff_pixels`, `material_diff_ratio`, and
`material_diff_threshold` alongside the active area and material limits. Inspect those fields to distinguish broad,
low-amplitude renderer drift from a small material UI change before using any override.

One accepted fidelity caveat: Fira Code ships no italic face and resvg does not synthesize oblique, so
`font-style: italic` renders upright. This is uniform across every screen and host. Restoring visible italics would mean
switching the bundled font family, taken as a separate follow-up if it becomes necessary.

### Intentional Renderer Upgrades

The pinned versions and font bytes define the golden corpus. Upgrade Textual, Rich, resvg, a syntax grammar, Pillow, or
another package in that stack as one reviewed change:

1. Update the exact pins in the `visual` optional-dependency group in `pyproject.toml`.
2. Run `uv lock`, then `just install-visual` so the working environment matches the new pins.
3. Refresh the matching package versions in `tests/ace/tui/visual/renderer_env.json`. If bundled fonts changed, update
   their SHA-256 hashes too; the Python and platform fields are diagnostic only.
4. On Linux, run `just update-visual-snapshots`, then run `just test-visual` once more without update mode.
5. Review the complete PNG diff for unexpected content or layout changes and commit the pins, `uv.lock`, fingerprint,
   and regenerated goldens together.

Non-Linux contributors should use CI as the canonical renderer. Push the branch, let the Linux `visual-test` job produce
`ace-visual-artifacts`, and download that artifact from the Actions run. Each failure directory contains an `actual.png`
and a `failure.json`; the sidecar's `expected_repo_path` identifies the golden that the actual image should replace
after review. The same fingerprint checks still require pins, lockfile, and manifest to agree before CI will render the
replacement corpus.

### CI Visual Lanes

The Python 3.12 matrix leg keeps visual tests in `just test-cov`, preserving their contribution to the coverage gate.
The 3.13 and 3.14 legs set `SASE_PYTEST_EXCLUDE_VISUAL=true`, so they exercise the shipped Python surface without
duplicating the canonical renderer signal. The dedicated Linux Python 3.12 `visual-test` job remains focused on the
complete visual suite and uploads failure reports and raw artifacts. This keeps one broad coverage lane plus one
diagnostic lane authoritative for snapshots while preventing a future Python-specific rendering change from reddening
two unrelated matrix legs.

### Visual Failure Report

`tools/render_visual_snapshot_failure_report` consumes the `failure.json` sidecars and writes
`.pytest_cache/sase-visual-report/`:

- `visual-failure-report.html` - self-contained HTML with PNG/SVG embedded as data URIs, one anchored section per
  failure.
- `summary.md` - compact table for `$GITHUB_STEP_SUMMARY` with links into the report and to the committed golden.
- `annotations.sh` - escaped `::error file=...,line=...` workflow commands.
- `manifest.jsonl` - aggregate of every loaded `failure.json` for ad-hoc inspection.

Run it locally against a failed run with
`tools/render_visual_snapshot_failure_report --repo <owner/repo> --sha <commit>` and open the HTML file directly. The
script is safe to run when there are no failures; it exits 0 without writing artifacts.

In GitHub Actions the `visual-test` job invokes the renderer twice on failure: once to build the report before upload,
then again after upload with `--report-url "$VISUAL_REPORT_URL"` so the summary and annotations point at the freshly
uploaded artifact. The HTML is uploaded via `actions/upload-artifact@v7` with `archive: false`, which is what makes the
per-failure anchors browsable directly from the Actions UI. Expected links point at the immutable
`https://github.com/<repo>/blob/<sha>/<expected_repo_path>` URL; actual/diff links point at the report artifact rather
than a public PNG URL because the raw PNGs are only uploaded as a zipped `ace-visual-artifacts` bundle and have no
stable per-file URL.

Add a visual test when the risk is layout, styling, focus highlighting, modal composition, or a regression that is hard
to express as state. Prefer a plain state/widget test when the behavior can be asserted through model state, rendered
text, selection identity, key handling, or a small widget contract.

## Required Rust Core

Ported `sase.core` operations are served by the required Rust extension `sase_core_rs`, distributed as the
`sase-core-rs` package and built from the sibling `../sase-core` repo during source development. Normal installs pull a
prebuilt wheel; local source installs can build the extension with `just install` or `just rust-install`.

There is no pure-Python fallback for ported operations. Use the health check after install changes:

```bash
sase core health
```

See the [Rust backend reference](rust_backend.md) for the Python/Rust boundary, shipped Rust-backed operations, source
build path, and benchmark expectations.

## Source Map

The repository is organized around the CLI entry point, operational subsystems, provider boundaries, and docs/tests:

| Path                           | Purpose                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `src/sase/main/`               | CLI parser registration and subcommand handlers.                                                       |
| `src/sase/ace/`                | ACE TUI, ChangeSpec rendering, query integration, actions, widgets, and TUI state.                     |
| `src/sase/agent/`              | Agent launch, detached spawn, prompt fan-out, running-agent metadata, artifact lookup, and naming.     |
| `src/sase/axe/`                | Axe orchestrator, lumberjacks, chop execution, scheduled jobs, maintenance mode, and automation state. |
| `src/sase/xprompt/`            | XPrompt expansion, directives, workflow loading, execution, tracing, explaining, and graphing.         |
| `src/sase/xprompts/`           | Bundled xprompt templates, workflows, and schemas shipped with the package.                            |
| `src/sase/workflows/`          | Change lifecycle workflows for commit, mentor, CRS, accept, and rewind operations.                     |
| `src/sase/memory/`             | Memory inventory, audited read logs, and proposal write/review flows.                                  |
| `src/sase/core/`               | Python facade and stable wire records for operations served by `sase_core_rs`.                         |
| `src/sase/bead/`               | Python host layer for bead storage discovery, CLI integration, and epic launch flow.                   |
| `src/sase/sdd/`                | Spec-driven development file and bead integration helpers.                                             |
| `src/sase/llm_provider/`       | Built-in LLM providers and provider registry.                                                          |
| `src/sase/vcs_provider/`       | VCS provider hook specs, plugin registry, and built-in git provider.                                   |
| `src/sase/workspace_provider/` | Workspace provider hook specs, plugin registry, and bare-git workspace support.                        |
| `src/sase/running_field/`      | Workspace claim and slot-management helpers.                                                           |
| `src/sase/notifications/`      | Notification delivery and storage integration.                                                         |
| `src/sase/telemetry/`          | Local debugging metric accumulation, store queries, health checks, and shared numeric render helpers.  |
| `src/sase/version/`            | Runtime inventory collection and rendering for the `sase version` CLI command.                         |
| `src/sase/integrations/`       | Public helper APIs consumed by external plugins and editors.                                           |
| `src/sase/scripts/`            | Packaged utility scripts used by axe chops and support commands.                                       |
| `tests/`                       | Python test suite, with subdirectories mirroring major `src/sase/` areas.                              |
| `docs/`                        | MkDocs Material site source.                                                                           |
| `sase/sase.yml`                | Repository-local SASE configuration.                                                                   |
| `sase/xprompts/`               | Repository-local xprompts and workflows for SASE maintenance agents.                                   |
| `sase/memory/`                 | SASE memory files used by repository agents.                                                           |
| `sase/repos/`                  | Runtime-only linked, sidecar, and external repository checkouts.                                       |
| `tools/`                       | Development scripts used by `just` targets and CI checks.                                              |

Detailed subsystem pages often include narrower source-layout tables. Use this page for initial orientation, then jump
to the specific reference for the area you are changing.

## Repository XPrompts

The checkout's `sase/xprompts/` directory is project-local to the `sase` repository. When SASE resolves prompts from
this project checkout, those entries are namespaced as `sase/<name>` so they do not collide with user or packaged
prompts. Use the catalog's `insertion` value to know whether an entry should be invoked with `#` or `#!`.

Useful visible entries include:

| Reference      | Purpose                                                                                                          |
| -------------- | ---------------------------------------------------------------------------------------------------------------- |
| `#!sase/reads` | Fan out a reading-recommendation request across Antigravity, Claude, and Codex, then consolidate the final list. |
| `#sase/sync`   | Sync the primary SASE workspace and restart axe.                                                                 |

`#!sase/reads` accepts a required `topic` and an optional `reference_query`. By default, the workflow passes this
Dataview query to the research agents:

```dataview
LIST WITHOUT ID title + " (" + url + ")"
FROM "ref"
WHERE
  source_path AND url AND (
    parent = [[ai_ref]]
    OR parent.parent = [[ai_ref]]
    OR parent.parent.parent = [[ai_ref]]
    OR parent.parent.parent.parent = [[ai_ref]]
    OR parent.parent.parent.parent.parent = [[ai_ref]]
  )
SORT title
```

Each research agent is expected to use `/bob_query` to run that query against Bryan's Bob vault, treat every returned
title and URL entry as already-known, and only then search for new reading candidates. A normal invocation can rely on
the default query:

```text
#!sase/reads(agent memory systems)
```

Some repository workflows are marked `hidden: true` because they are automation helpers, such as docs refresh, recent
bug/improvement audits, and Python line-limit splitting. That flag hides workflow run rows in ACE; it does not mean the
workflow is unavailable. Use `sase xprompt list` or the ACE xprompt browser from a source checkout when you need the
exact current catalog.

## Documentation Workflow

The docs site is a MkDocs Material project:

| Path             | Purpose                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| `mkdocs.yml`     | Main docs site configuration, strict build, navigation, blog, RSS, and theme settings.            |
| `mkdocs-pdf.yml` | PDF handbook build configuration, inheriting the main site config.                                |
| `docs/`          | Markdown, images, stylesheets, JavaScript, redirects, headers, and PDF templates.                 |
| `site/`          | Generated site output. It is rebuilt by docs commands and deployed as the static asset directory. |

Run the strict site build after changing docs navigation, links, images, or Markdown pages:

```bash
just docs-check
```

Run SASE validation when a change can affect generated initialization files or SDD frontmatter links. It is deliberately
separate from source linting because it can report user/home initialization drift and independently managed SDD state:

```bash
sase validate
```

Run the handbook build and validation when a change materially affects the public handbook, PDF styling, navigation, or
generated-site assets:

```bash
just docs-pdf-check
```

`just docs-check` installs only MkDocs tooling, then runs `mkdocs build --strict`. `just docs-pdf-check` installs the
PDF tooling, installs Chromium for Playwright, builds `mkdocs-pdf.yml` in an isolated temporary site directory,
post-processes and validates the handbook there, and copies only `downloads/sase-handbook.pdf` back into `site/`.

## Docs Deployment

Production docs are deployed by `.github/workflows/docs-deploy.yml`, not by a Cloudflare dashboard build command. The
workflow:

1. Checks out the repo and installs `uv`, `just`, and Python 3.12.
2. Runs `just docs-check`.
3. Runs `just docs-pdf-check`.
4. Verifies `site/index.html`, `site/_headers`, the blog and series pages, and `site/downloads/sase-handbook.pdf`.
5. Deploys the prebuilt `site/` directory through `wrangler.jsonc`.
6. Smoke-tests the deployed handbook PDF from the deployment URL and `https://sase.sh/`.

The GitHub repository must provide a `CLOUDFLARE_API_TOKEN` Actions secret with permission to deploy the `sase`
Cloudflare Worker. Keep dashboard-managed Git builds disabled or unused for production so they cannot race the checked
in workflow's prebuilt artifact deploy.
