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

The verification recipes cache their setup-validation verdicts inside the active virtual environment. The cache is
fingerprinted from `pyproject.toml`, `uv.lock`, the validator implementations, the local `sase-core` version, and the
installed environment metadata, so dependency or environment changes revalidate automatically. Set
`SASE_TEST_SETUP_FORCE_REVALIDATE=1` on any `just` invocation to bypass the cache while diagnosing setup problems.

## Verification Commands

```bash
just install       # Install with dev deps
just fmt           # Auto-format code and Markdown
just lint          # Run ruff, mypy, pyscripts, symvision, toobig, and keep-sorted
just test          # Fast parallel test run, excluding slow and PNG visual snapshot tests
just test-slow     # Slow pytest subset only
just test-visual   # ACE PNG visual regression snapshots only; the sole visual execution
just test-terminal-smoke  # Optional real-terminal ACE smoke test
just test-cov      # Parallel test run with coverage + 50% gate, excluding visual snapshots
just check         # CI-style checks: formatting, lint, SDD validation, tests
just test-tox      # Test across Python 3.12, 3.13, 3.14
just clean         # Remove build artifacts
just build         # Build wheel and sdist
```

SASE places a pytest safety boundary around its telemetry mutations and common axe state/log writers when they target
the OS account's real `~/.sase` tree. Telemetry flushes and deletions fail with an actionable error; guarded best-effort
daemon writes are suppressed and warn once per target and category; and axe start, stop, and restart requests are
refused unless their test-only override is set. The pytest harness also publishes `SASE_PYTEST_SANDBOX_DIR`; while that
marker is present, bead-store writes through the Python mutation facade or Rust CLI fast path are refused unless the
target store is at or below the sandbox root. `SASE_ALLOW_UNSANDBOXED_BEAD_WRITES=1` is the deliberate test-only escape
hatch for a genuine exception. SASE preserves pytest's isolation marker when it starts runner and daemon subprocesses.
These guards are not a substitute for isolation: tests that exercise persistence should point `SASE_HOME` at a per-test
temporary directory and create bead stores under `tmp_path` or another path inside the published sandbox. Run
`just test-bead-store-soak` when changing bead resolution or mutation paths; it runs the default suite and verifies the
legacy production plans sidecar's `beads/issues.jsonl` digest, bead-state git status, and git HEAD are unchanged. The
current guard still targets `SASE_SDD_PLANS_DIR/beads` and never resolves the dedicated beads role. On a cleaned
schema-3 project it exits with a missing-file error instead of running the suite; if a legacy `beads/` copy remains
under `--plans`, the helper guards that stale copy rather than the active `--beads` store. If an older test run already
polluted the telemetry store, preview the exact-label cleanup with `sase telemetry cleanup-test-data --dry-run` before
deciding whether to rerun it with `--yes`.

`just test`, `just test-slow`, `just test-visual`, and `just test-cov` share a host-global pytest-xdist worker-token
pool with every other checkout owned by the same UID. An automatic run waits until it can lease a small floor, then
greedily grows to its per-run ceiling using whatever capacity is currently free. On the standard development host, a
solo run can receive 28 workers from the 32-token pool while leaving four tokens for another run; concurrent runs scale
down to their actual grants instead of each independently oversubscribing the host. The granted count is the value
passed to `pytest -n`.

The default host budget reserves `max(1, cpu_count // 8)` CPUs and 8 GiB of available memory, allows 950 MiB per worker,
and never exceeds 32 tokens (the prior safe aggregate ceiling). The CPU reserve is proportional rather than a flat
count, so a small host (e.g. a 4-vCPU CI runner) still gets real parallelism instead of collapsing to a single worker.
The memory allowance was calibrated from live worker RSS sampled across concurrent sibling workspaces, which ranges from
0.74 to 0.85 GiB; 950 MiB keeps headroom over the top of that range. Missing memory information falls back to a
conservative four-token limit, and small hosts clamp to at least one token. These capacity safeguards are independent of
xdist scheduling and individual test cost.

The runner defaults to pytest-xdist's `worksteal` scheduler. Workers begin with evenly divided queues and can reclaim
pending tests from a worker with a long queue, avoiding the idle-worker tail caused by keeping an entire heavy test file
on one worker. The fallback is a one-variable change:

```bash
SASE_PYTEST_DIST=loadfile just test
```

`SASE_PYTEST_DIST` accepts only `worksteal` and `loadfile`; unsupported values fail with a pytest usage error before the
runner leases worker tokens. Inline-snapshot update and review modes remain serial and omit both `-n` and `--dist`
regardless of this setting. Test selectors and other pytest options continue to pass through normally.

A post-change comparison on 2026-07-20 used the same 19,883-item fast-suite selection, refreshed dependencies, and an
exact governed grant of 28 workers. Aggregate CPU is reported as the mean utilized cores divided by the 28-worker grant;
the tail is wall time from the first 99% progress report through completion.

| Scheduler   | Pytest time | Wall time | Grant utilization | 99%-finish tail |
| ----------- | ----------- | --------- | ----------------- | --------------- |
| `loadfile`  | 109.68s     | 111.93s   | 59.1%             | 41s             |
| `worksteal` | 102.34s     | 104.66s   | 61.8%             | 39s             |

`worksteal` reduced wall time by 7.27s (6.5%) while running the same assertions. The slowest calls remained the two
tests in `test_agents_zoom_panel_search.py` (roughly 16-20s each), so the improvement reflects better pending-work
distribution rather than removed test cost. Three complete `worksteal` runs at governed grants of 11, 16, and 28 workers
passed while auditing for within-file order and shared-state assumptions.

### Final combined-suite verification

The completed optimization was measured on athena on 2026-07-20 with the current 19,921-item fast-suite selection. A
crash-safe reservation held the measured 29-token host pool across three consecutive samples so unrelated queued suites
could not enter between runs; each `just test` used 25 workers, the automatic ceiling for that capacity after reserving
the four-worker floor. Aggregate CPU is GNU time's mean utilized cores, and grant utilization divides it by 25.

| Sample | Pytest time | Recipe wall | Workers | Aggregate CPU | Grant utilization |
| ------ | ----------- | ----------- | ------- | ------------- | ----------------- |
| 1      | 90.71s      | 93.14s      | 25      | 1809%         | 72.4%             |
| 2      | 90.84s      | 93.08s      | 25      | 1776%         | 71.0%             |
| 3      | 89.63s      | 92.05s      | 25      | 1803%         | 72.1%             |
| Mean   | 90.39s      | 92.76s      | 25      | 1796%         | 71.8%             |

Against the pre-optimization 4:04 recipe / 194s pytest / 14-worker / ~780% CPU baseline, the mean recipe is **2.63x
faster** and the pytest segment is **2.15x faster**. Non-pytest recipe overhead fell from roughly 50s to 2.37s. The
selection grew from 19,744 to 19,921 items while the work landed; no existing test was removed, skipped, or moved out of
the fast lane.

Coverage parity used the same 19,921-item selection with `just test-cov`: 19,915 tests passed, 7 were skipped, total
branch coverage was 80.07%, and the unchanged 50% gate passed. The coverage recipe still uses the same `not slow`
selection and includes the visual regression tests.

Sustained real-host demand also exercised the pool while these measurements were prepared. With memory sizing the active
budget at 20 tokens, three full suites progressed simultaneously with grants of 12, 4, and 4 workers. Their sum never
exceeded 20; available memory stayed healthy and swap remained at 2.3 GiB throughout the observation. The process-level
regression in `tests/test_suite_gate_integration.py` makes the same guarantees deterministic in a temporary three-token
pool: three one-worker suites reach test execution together, a fourth waits, killing one holder admits the waiter, and
active grants remain exactly bounded before and after the handoff.

Set `SASE_PYTEST_WORKERS=<N>` to request exactly that many governed workers; the request must fit the shared capacity.
Direct parallel `pytest -n ...` controllers use the same pool and lease their resolved numeric, `auto`, or `logical`
worker count exactly. Lock descriptors survive the runner's exec and are released by the kernel even after `SIGKILL`.
Nested pytest processes inherit the disabled marker so they cannot deadlock on the parent's tokens.

For deliberate diagnostics, `SASE_TEST_GATE_DISABLED=1` bypasses accounting. `SASE_TEST_GATE_SLOTS` overrides host-wide
token capacity, `SASE_TEST_GATE_TIMEOUT` controls bounded admission waits, and `SASE_TEST_GATE_DIR` selects the shared
pool directory. `SASE_PYTEST_WORKER_FLOOR` and `SASE_PYTEST_WORKER_CEILING` tune automatic grants; invalid or
inconsistent values fail before pytest starts. See [Configuration](configuration.md#general) for the complete contract.

Test selectors are normalized from the directory where `just` was invoked, so this works the same from the repository
root or a subdirectory:

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
has proved stable. The recipe uses the shared pytest runner's private disk-backed temp root and leak guard, but it is
always serial and never leases xdist worker tokens; `SASE_PYTEST_DIST` is therefore ignored. Set `SASE_PYTEST_TMPDIR` to
override its scratch root while diagnosing temp-path behavior.

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

## Timestamp Display Convention

User-facing timestamp display must go through `sase.core.time.parse_local` or `sase.core.time.format_local`, so stored
UTC instants, offset-aware values, naive configured-timezone wall times, and epoch values all render in the configured
`timezone`. Naive-model arithmetic keeps using `local_now` and `to_local`; storage and wire contracts keep canonical UTC
unless their owning schema says otherwise.

`tests/test_timezone_display_consistency.py` has the focused `tz_divergence` fixture coverage and the
`test_no_system_clock_display_sites` AST guard. A new bare `datetime.now()`, argument-less `.astimezone()`, or tz-less
`datetime.fromtimestamp()` under `src/sase/` should normally be fixed by routing through the time helpers instead of
adding another guard allowlist entry.

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

The default lane (`just test`, `just test-cov`, and every leg of the Python matrix) excludes visual tests. The dedicated
Linux Python 3.12 `visual-test` job is the sole visual execution: it runs the complete visual suite and uploads failure
reports and raw artifacts. This keeps one broad lane plus one diagnostic lane authoritative for snapshots while
preventing a future Python-specific rendering change from reddening the whole matrix.

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

Run SASE validation when a change can affect generated initialization files or SDD artifact links. It is deliberately
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
