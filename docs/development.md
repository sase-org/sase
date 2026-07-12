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
just lint          # Run ruff, mypy, pyscripts, pyvision, toolong, and keep-sorted
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
goldens. Run them normally first:

```bash
just test-visual
```

When a visual test fails, inspect the artifacts under `.pytest_cache/sase-visual/<node>/<snapshot>/`. Each failure
directory contains the actual PNG capture and, when a golden exists, the expected PNG plus a diff PNG, a human-readable
`summary.txt`, and a structured `failure.json` sidecar. The sidecar carries the test source location, repo-relative
golden path, and pixel-diff stats so tooling can map a failure back to the test and the committed golden. Accept
intentional visual changes only by rerunning the relevant test with the explicit update flag:

```bash
just test-visual -- --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots.py
```

Review changed PNG files as normal test data. Do not pass `--sase-update-visual-snapshots` to `just check`, `just fmt`,
or broad CI-style commands.

Committed goldens are canonical to the pinned renderer. Rasterization goes through resvg (`resvg_py==0.3.3`), a
pure-Rust SVG renderer that carries its own font database restricted to the bundled Fira Code
(`tests/ace/tui/visual/fonts/`) with `skip_system_fonts=True`. No host font-config or graphics stack participates, so
rendering is stable and host-font-independent everywhere.

Rasterization is not perfectly byte-identical across host operating systems, though: resvg anti-aliases a small, fixed
set of pixels differently on macOS arm64 than on CI's Linux x86_64 — a drift of ~0.1-0.3% of pixels. Every lane (local
`just test-visual`, the broad `just test` / `just test-cov` runs, `just check`, and CI, which all run through the
`justfile`) therefore allows a small ratio-only drift tolerance by default: `SASE_VISUAL_PNG_MAX_DIFF_RATIO` is exported
from the `justfile` at `0.01` (1%). That band absorbs cross-host anti-aliasing drift with headroom while still catching
real regressions, which change orders of magnitude more pixels. Goldens are consequently regenerable on any host —
accept intentional changes with the local one-liner above, review the changed PNGs as ordinary test data, then commit;
no CI-artifact adoption ritual and no host-specific font setup is required.

The renderer version is pinned exactly because it _defines_ the golden corpus. Bumping `resvg_py` is a deliberate
regenerate-and-review event: change the pin, regenerate every golden, spot-check the diff, and commit the corpus churn
in the same change.

Override the default tolerance per run with `SASE_VISUAL_PNG_MAX_DIFF_RATIO=<ratio>` (use `0` to demand exact pixel
equality, or a larger cap while measuring drift scale during a renderer bump) or per assertion with a `max_diff_pixels`
/ `max_diff_ratio` kwarg.

One accepted fidelity caveat: Fira Code ships no italic face and resvg does not synthesize oblique, so
`font-style: italic` renders upright. This is uniform across every screen and host. Restoring visible italics would mean
switching the bundled font family, taken as a separate follow-up if it becomes necessary.

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
| `src/sase/telemetry/`          | Prometheus metrics, health, dashboard, and monitoring export support.                                  |
| `src/sase/version/`            | Runtime inventory collection and rendering for the `sase version` CLI command.                         |
| `src/sase/integrations/`       | Public helper APIs consumed by external plugins and editors.                                           |
| `src/sase/scripts/`            | Packaged utility scripts used by axe chops and support commands.                                       |
| `tests/`                       | Python test suite, with subdirectories mirroring major `src/sase/` areas.                              |
| `docs/`                        | MkDocs Material site source.                                                                           |
| `sdd/`                         | Project-local prompt, tale, epic, research, and bead artifacts.                                        |
| `xprompts/`                    | Repository-local xprompts and workflows for SASE maintenance agents.                                   |
| `tools/`                       | Development scripts used by `just` targets and CI checks.                                              |
| `memory/`                      | SASE memory files used by repository agents.                                                           |

Detailed subsystem pages often include narrower source-layout tables. Use this page for initial orientation, then jump
to the specific reference for the area you are changing.

## Repository XPrompts

The checkout's top-level `xprompts/` directory is project-local to the `sase` repository. When SASE resolves prompts
from this project checkout, those entries are namespaced as `sase/<name>` so they do not collide with user or packaged
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
