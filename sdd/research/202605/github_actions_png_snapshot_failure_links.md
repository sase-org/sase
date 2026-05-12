---
create_time: 2026-05-12
status: research
---

# GitHub Actions Links for PNG Snapshot Failures

## Question

When an ACE PNG snapshot fails in GitHub Actions, how should CI expose the expected and actual images so a maintainer
can quickly understand the visual regression?

## Recommendation

Implement this in two layers:

1. Keep the existing `.pytest_cache/sase-visual` failure artifact directory, but make the pytest helper write a
   machine-readable manifest next to the images.
2. Add a CI post-processing step that turns the manifest into a GitHub job summary plus error annotations. Each failed
   snapshot should get a compact row with links for `expected`, `actual`, and `diff`.

For the first implementation, the best UX/cost tradeoff is:

- Link `expected` to the committed golden in the repository at the run SHA.
- Link `actual` and `diff` to a generated `visual-failure-report.html` artifact uploaded with
  `actions/upload-artifact@v7` and `archive: false`; the report can embed the PNGs directly as base64 data URIs and
  expose stable anchors per snapshot.
- Continue uploading the raw `.pytest_cache/sase-visual` directory as a bulk debug artifact.

If we later decide that `actual` must be a direct PNG URL rather than a report anchor, add a small local JavaScript
action around GitHub's artifact toolkit and upload each `actual.png` / `expected.png` / `diff.png` as its own unzipped
single-file artifact. That is more plumbing and more artifacts, so it should not be the default first move.

Two caveats that materially shape the design and are worth stating up front:

- GitHub artifact URLs require an authenticated GitHub login **even for public repositories**. Anonymous viewers (the
  natural audience for an open-source SASE failure on a PR check) cannot open `artifact-url` links directly. This is
  not a Markdown rendering bug; it is GitHub's access policy. The recommendation below works around it for the SASE
  audience (maintainers are logged in), but if SASE later needs links to be publicly viewable, prefer a GitHub Pages
  publishing path (see Option G).
- GitHub job summaries (`$GITHUB_STEP_SUMMARY`) sanitize HTML and strip embedded image data URIs. Inline visual
  comparison in the summary itself is essentially blocked; the summary should link out, not embed.

## Current SASE State

SASE already has most of the local failure data:

- `.github/workflows/ci.yml` defines a dedicated `visual-test` job.
- The visual job runs `just test-visual`.
- It uploads `.pytest_cache/sase-visual` through `actions/upload-artifact@v4` as `ace-visual-artifacts` with
  `if: always()`.
- `tests/ace/tui/visual/png_diff.py` writes `actual.png`, `expected.png`, `diff.png`, `actual.svg`, and `summary.txt`
  under `.pytest_cache/sase-visual/<test-node>/<snapshot-name>/` via `_write_failure_artifacts()`.
- The assertion message in `assert_png_matches()` prints local runner paths, which are useful in a local shell but
  not enough in GitHub Actions.
- Both the missing-golden and pixel-mismatch paths already produce structured artifact records; adding manifest
  emission is a localized change inside `_write_failure_artifacts()`.

The missing piece is not image generation. It is a stable CI-facing index that maps a failed pytest node/snapshot to
clickable GitHub UI links.

## GitHub Actions Capabilities

### Artifact URLs

`actions/upload-artifact` exposes `artifact-url`, `artifact-id`, and `artifact-digest` outputs. The URL is valid until
the artifact, run, repository, or retention window disappears.

Source: [`actions/upload-artifact` README](https://github.com/actions/upload-artifact#outputs).

`actions/upload-artifact@v7` (released April 10, 2026) supports `archive: false` for single-file artifacts. With
`archive: false`, only one file may be uploaded per step (the artifact `name` parameter is ignored — the file name is
used), and a browser visiting the artifact URL renders the file inline when the content type is browser-friendly
(images, HTML, plain text). v7 also enforces a per-job limit of 500 artifacts. Storage quota still applies to the
workflow run independently.

Source: [`actions/upload-artifact` README — non-zipped artifacts](https://github.com/actions/upload-artifact).

Important auth caveat (gap in the previous version of this note): per long-standing
[issue actions/upload-artifact#51](https://github.com/actions/upload-artifact/issues/51) and the related
[issue #144](https://github.com/actions/upload-artifact/issues/144), the artifact URL requires the visitor to be a
logged-in GitHub user with read access to the repo, even when the repo is public. Sharing the URL with an
anonymous reader will return a 404 / "not found" rather than the file. This is GitHub policy, not a per-action quirk;
the REST artifacts API is similarly authenticated. Internal SASE maintainers will not hit this, but contributors on
forks or external reviewers will, so the report layer should not assume the URL is broadly shareable.

Sources:

- [GitHub REST API: Actions artifacts](https://docs.github.com/en/rest/actions/artifacts)
- [Issue: artifact URL 404s for guests](https://github.com/actions/upload-artifact/issues/51)
- [Issue: public-repo artifact downloads still require auth](https://github.com/actions/upload-artifact/issues/144)
- [GitHub blog: artifact v4 immediate URL availability](https://github.blog/news-insights/product-news/get-started-with-v4-of-github-actions-artifacts/)

Important constraints to plan around:

- `archive: false` only supports a single file per upload.
- The official action is a workflow step, not a shell command; dynamic "upload N files and collect N URLs" is awkward
  in plain YAML.
- The current `@v4` directory artifact is still useful for bulk download, but it does not give clean direct links to
  individual images.
- `${{ steps.<id>.outputs.artifact-url }}` is only available **after** the upload step has run; any summary or
  annotation that needs to embed the URL must be a later step (this is the ordering pitfall to watch in CI YAML).

### Job Summaries

GitHub job summaries are Markdown written to `$GITHUB_STEP_SUMMARY`. They are designed for custom run summaries,
reports, and test output independent of raw logs. GitHub documents a 1 MiB limit per step summary; exceeding it
fails the step's summary upload and creates an error annotation.

Sources:

- [GitHub blog: job summaries](https://github.blog/news-insights/product-news/supercharging-github-actions-with-job-summaries/)
- [GitHub workflow commands: job summaries](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary)

Summary sanitization rules to plan around (gap in the previous note):

- Job summaries support GitHub-flavored Markdown but apply HTML sanitization equivalent to GitHub README rendering.
  Arbitrary HTML is escaped or stripped, including most `<script>`, `<iframe>`, `style`/event attributes, etc.
- `<img>` tags survive in some forms but `src="data:image/png;base64,..."` is filtered out by GitHub's image proxy
  (Camo), which is the same path that strips data URIs in normal Markdown rendering. See
  [github/markup#270](https://github.com/github/markup/issues/270). The practical effect: do not try to inline
  expected/actual/diff PNGs as base64 in the summary itself. Link out instead.
- `<details>`/`<summary>` collapsibles **do** render and are useful for keeping the summary scannable when there are
  many failures.

This is the best place for a table like:

| Test | Snapshot | Expected | Actual | Diff |
| --- | --- | --- | --- | --- |
| `tests/ace/tui/visual/test_ace_png_snapshots.py::test_agent_list_png_snapshot` | `agent_list_120x40` | expected | actual | diff |

Wrap noisy per-snapshot detail in `<details>` blocks to keep the top of the summary skimmable.

### Error Annotations

GitHub workflow commands can emit `::error file=<path>,line=<n>,title=<title>::<message>` annotations. The `file` and
`line` parameters anchor the annotation to a real source location in the check UI, which means a snapshot failure can
surface under the relevant test file rather than as an unsourced floating message. Use the same `::warning` and
`::notice` commands for non-fatal signals (e.g. "snapshot golden was missing — accepted automatically because
`--sase-update-visual-snapshots` was set").

Source:
[GitHub workflow commands: error annotations](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-error-message).

Annotations should be secondary to the job summary because annotation rendering is optimized for source locations,
not rich visual comparison. They are still useful because they surface in the failed check without digging into logs.

A useful UX pattern: wrap noisy diagnostic output in `::group::Visual failure: <name>` / `::endgroup::` workflow
commands so per-snapshot diagnostic lines collapse in the raw log view.

## Options

### Option A: Only Improve The Assertion Message

Make `png_diff.py` include more path text in the assertion failure.

Pros:

- Tiny code change.
- Helps local debugging.

Cons:

- Still points at runner-local paths in CI.
- Does not solve the user's main problem.

Verdict: insufficient.

### Option B: Upload One Directory Artifact And Link To It

Keep the existing `ace-visual-artifacts` upload and add one job-summary link to the artifact.

Pros:

- Almost no implementation work.
- Already close to what CI does today.

Cons:

- Still makes the maintainer download or browse a bundle and map paths manually.
- Does not give per-failure expected/actual links.

Verdict: useful fallback, not enough by itself.

### Option C: Manifest Plus HTML Report Artifact

Have `png_diff.py` write a JSONL manifest record whenever it writes failure artifacts:

```json
{
  "node_id": "tests/ace/tui/visual/test_ace_png_snapshots.py::test_agent_list_png_snapshot",
  "snapshot": "agent_list_120x40.png",
  "expected_repo_path": "tests/ace/tui/visual/snapshots/png/agent_list_120x40.png",
  "actual_path": ".pytest_cache/sase-visual/.../actual.png",
  "expected_path": ".pytest_cache/sase-visual/.../expected.png",
  "diff_path": ".pytest_cache/sase-visual/.../diff.png",
  "summary_path": ".pytest_cache/sase-visual/.../summary.txt",
  "test_file": "tests/ace/tui/visual/test_ace_png_snapshots.py",
  "test_line": 42,
  "changed_pixels": 137,
  "total_pixels": 4800,
  "changed_ratio": 0.0285
}
```

Then a CI script renders:

- `visual-failure-report.html`, embedding expected/actual/diff images as inline `data:image/png;base64,...` URIs
  inside the HTML (not the Markdown summary).
- `$GITHUB_STEP_SUMMARY`, linking each row to report anchors and the bulk artifact.
- `::error file=...,line=...,title=...::` annotations for each row, anchored to the test file.

Pros:

- Works with any number of failures.
- No third-party service.
- One unzipped HTML artifact can be directly viewed in the browser with `upload-artifact@v7 archive:false`.
- Keeps the current raw artifact upload.
- Lets SASE control the comparison layout, labels, and diff metadata.

Cons:

- `actual` links initially point to a report anchor, not a standalone PNG URL.
- Needs a small manifest/report script.
- Report URL is still authenticated; it works for SASE maintainers but not for unauthenticated reviewers.

Verdict: recommended first implementation.

### Option D: Upload Every PNG As Its Own Unzipped Artifact

Upload each failed snapshot image as a separate `archive:false` artifact and use each action output URL directly.

Pros:

- Gives the literal direct expected/actual image links requested.
- Browser can render PNG artifacts directly.

Cons:

- Plain workflow YAML cannot loop over dynamic files with `uses: actions/upload-artifact`.
- A local JavaScript action using GitHub's artifact toolkit would be needed for clean dynamic uploads.
- Creates 2-3 artifacts per failed snapshot, which can get noisy.
- `upload-artifact` has a 500-artifact-per-job cap, so a mass snapshot failure (e.g. a CSS-wide change) could hit it.
- Authentication caveat still applies — the per-image URLs are still GitHub-authenticated, not public.

Verdict: best literal interpretation, but only worth doing after Option C proves insufficient.

### Option E: Post PR Comments With Images

Post a pull request comment with linked or embedded image results.

Pros:

- Highly visible during review.
- Image links in PR comment Markdown are pre-rendered (Camo-cached), so a public image host works without login.

Cons:

- Requires fork/permission handling (forked PR workflows do not get `GITHUB_TOKEN` write).
- Needs comment deduplication/editing.
- Produces noise on repeated pushes.
- Still needs hosted image URLs or artifacts.

Verdict: defer. Job summaries and annotations are cleaner for CI diagnostics. Useful as a v2 surface once the
manifest/report exists.

### Option F: Reuse `pytest-textual-snapshot`'s Built-In Report

If SASE adopts `pytest-textual-snapshot` (a parallel option recommended in
`tui_pixel_snapshot_testing.md`), the plugin already writes a `snapshot_report.html` next to the test session that
shows side-by-side expected/actual with a "Show Difference" toggle. CI can upload that file directly with
`upload-artifact@v7 archive: false` and link it from the job summary, skipping most of the custom rendering work.

Pros:

- Almost no custom rendering code to maintain.
- Same UX Textual maintainers already use to triage their own failures.
- Co-evolves with the upstream plugin.

Cons:

- Only meaningful if/when SASE switches the visual suite to the official plugin (today the SVG→PNG comparison runs
  through SASE-owned `png_diff.py`).
- Would not cover SASE-owned PNG diffs unless those are migrated to the plugin's snapshot machinery.
- Report layout is fixed; SASE-specific metadata (changed-pixel counts, test node IDs) has to fit the plugin's
  format.

Verdict: keep on the table — it is the cheapest path if SASE adopts the official plugin later. Until then, Option C
ships sooner.

### Option G: Publish The Report To GitHub Pages

Generate the same `visual-failure-report.html` as Option C, but publish it to GitHub Pages (e.g. under
`gh-pages/visual-failures/<PR-or-SHA>/`) using `actions/upload-pages-artifact` + `actions/deploy-pages`, or
`peaceiris/actions-gh-pages`.

Pros:

- Yields a **public, login-free** URL, which is the only way to make the report shareable with anonymous reviewers
  and on the open SASE web surface.
- The report can be linked from PR comments and external dashboards.
- Plays well with the existing `docs-build` and `docs-deploy` jobs in `.github/workflows/`.

Cons:

- Publishing failure artifacts to a public URL exposes any test data that the report includes — generally fine for
  SASE TUI screenshots, but should be reviewed before turning on broadly.
- More moving parts than a one-shot artifact upload.
- Requires write permission to a `gh-pages` branch (or the Pages deployment environment).

Verdict: defer unless link sharing with non-maintainers becomes important; revisit if SASE wants to surface visual
failure reports on the public SASE site or in mobile/blog automation.

### Option H: Hosted Visual-Regression Service (Argos, reg-suit, etc.)

Use a third-party visual-regression service that already has a "upload screenshots, get a PR check with side-by-side
diffs and approval flow" product. The two most relevant candidates today:

- [Argos CI](https://argos-ci.com/) — managed service, GitHub App, free tier for OSS. Workflow: run tests, run
  `npx argos upload ./screenshots`, get a PR check whose details page shows side-by-side expected/actual/diff with
  approval buttons. Approving a change "promotes" the actual image to the new baseline. Argos is framework-agnostic
  — it accepts any directory of PNGs, so it does not require Playwright/Cypress, and our pytest pipeline already
  produces the right PNG files.
- [reg-suit](https://github.com/reg-viz/reg-suit) + [reg-actions](https://github.com/reg-viz/reg-actions) — OSS,
  self-hosted. Generates an HTML report and posts it as a PR comment / workflow summary. reg-suit historically uses
  S3/GCS for baselines; `reg-actions` is the variant that uses workflow artifacts instead so no cloud storage is
  needed.

Pros:

- Production-quality side-by-side UI without writing or maintaining one.
- Approval/baselining flow is a first-class feature, which solves the "is this an intentional change?" question
  in-PR instead of in a `--sase-update-visual-snapshots` re-run.
- Public per-build URLs (Argos) or PR comments (reg-suit) bypass the GitHub artifact auth problem entirely.

Cons:

- Argos is hosted: adds external trust, retention, account, and token-management questions; OSS free tier exists but
  is bounded.
- reg-suit/reg-actions is OSS but adds a Node-based CI dependency to a Python project and another tool to
  understand.
- Either choice means coupling SASE's visual baseline workflow to an external project's cadence.

Verdict: not the first move, but worth a follow-up evaluation once Option C is in place. Argos is the easier win if
SASE is willing to take a managed dependency; reg-actions is the self-hosted equivalent.

### Option I: Switch The Visual-Test Artifact Upload To Failure-Only

The current `visual-test` job uploads `.pytest_cache/sase-visual` with `if: always()`. On a green run that directory
typically contains only stale local-dev junk or is empty; uploading on success is wasted storage and clouds the
artifact list.

Change `if: always()` → `if: failure()` (or `if: ${{ failure() && hashFiles('.pytest_cache/sase-visual/**') != '' }}`)
once the manifest layer exists, so failure artifacts are the only ones present.

Verdict: small CI hygiene change, do it alongside Option C.

## Proposed Implementation Shape

### Pytest Helper

Extend `_FailureArtifacts` / `_write_failure_artifacts()` in `tests/ace/tui/visual/png_diff.py` to append one JSONL
record per failure under:

```text
.pytest_cache/sase-visual/manifest.jsonl
```

Include:

- `node_id`
- `snapshot`
- `expected_repo_path`
- `actual_path`
- `expected_path`
- `diff_path`
- `source_svg_path`
- `summary_path`
- `test_file` and `test_line` (so annotations can anchor to the right source location)
- diff metrics when available (`changed_pixels`, `total_pixels`, `changed_ratio`)
- `kind` (e.g. `"mismatch"` vs `"missing_golden"`)

Use relative paths from the workspace where possible. Keep the human-readable assertion message, but add one line
saying that CI will publish a visual failure report when `GITHUB_ACTIONS=true`.

Optional smaller change: in parallel, switch to (or add) `pytest-json-report` to produce a structured pytest result
file. The report script can then cross-reference pytest's structured node info with `manifest.jsonl` instead of
re-parsing assertion text. This is not required for Option C — the manifest is sufficient — but it removes
brittleness if the manifest ever drifts from pytest's view of what failed.

### Report Script

Add a small script, for example:

```text
tools/render_visual_snapshot_failure_report
```

Inputs:

- `.pytest_cache/sase-visual/manifest.jsonl`
- `GITHUB_REPOSITORY`
- `GITHUB_SHA`
- optional artifact/report URL from the upload step

Outputs:

- `.pytest_cache/sase-visual-report/visual-failure-report.html`
- `.pytest_cache/sase-visual-report/summary.md`
- `.pytest_cache/sase-visual-report/annotations.sh`

The HTML report should embed image bytes as data URIs. That makes it self-contained, so `archive:false` can upload
one HTML file and browser viewing does not need relative asset paths. (Note: embedding data URIs is only allowed in
the HTML report, not in `summary.md` — the job summary sanitizer strips them.)

Reasonable layout per failure inside the HTML report:

1. heading and stable anchor (`#<slug>`),
2. one row of three images: `diff` (primary), `expected`, `actual`,
3. a small metadata table (changed pixels, ratio, test node id, golden path),
4. a "raw SVG" `<details>` block with the captured `actual.svg`.

### Workflow

Keep raw artifacts (and tighten to failure-only once the rest is wired):

```yaml
- name: Upload visual failure artifacts
  if: failure()
  uses: actions/upload-artifact@v4
  with:
    name: ace-visual-artifacts
    path: .pytest_cache/sase-visual
    if-no-files-found: ignore
```

Add a report generation and unzipped upload path. In practice this should bump the visual upload action to `@v7` for
the report artifact:

```yaml
- name: Build visual failure report
  if: failure()
  run: tools/render_visual_snapshot_failure_report

- name: Upload visual failure report
  id: visual_failure_report
  if: failure()
  uses: actions/upload-artifact@v7
  with:
    path: .pytest_cache/sase-visual-report/visual-failure-report.html
    archive: false
    if-no-files-found: ignore

- name: Publish visual failure summary
  if: failure()
  env:
    VISUAL_REPORT_URL: ${{ steps.visual_failure_report.outputs.artifact-url }}
  run: |
    tools/render_visual_snapshot_failure_report --finalize \
      --report-url "$VISUAL_REPORT_URL"
    cat .pytest_cache/sase-visual-report/summary.md >> "$GITHUB_STEP_SUMMARY"
    bash .pytest_cache/sase-visual-report/annotations.sh
```

The report script needs the uploaded report URL to write final links. The two-pass split above (build → upload →
finalize) keeps the dependency one-directional. Alternatively the script can pass `--report-url` on a single
invocation that runs after the upload, and the build step just writes raw images and a `manifest.jsonl`. Either is
fine — the constraint is that `${{ steps.<id>.outputs.artifact-url }}` is only resolvable after the upload step.

## Link Strategy

For each snapshot:

- Expected link:
  `https://github.com/${GITHUB_REPOSITORY}/blob/${GITHUB_SHA}/tests/ace/tui/visual/snapshots/png/<name>.png`
  — publicly viewable, no auth required, immutable per SHA. Use `?raw=true` if a direct image URL is preferred.
- Actual link:
  `${VISUAL_REPORT_URL}#<stable-actual-anchor>` (authenticated; in-browser inline view via `archive:false`).
- Diff link:
  `${VISUAL_REPORT_URL}#<stable-diff-anchor>` (authenticated).
- Raw bundle link:
  use the existing `ace-visual-artifacts` artifact URL if the upload step has an output, or let the summary point
  users to the artifact section as a fallback.

This is not as pure as individual direct public PNG URLs, but it gives one-click inspection from the check summary
and does not require downloading a zip. The "expected" link is genuinely public because it points at the committed
golden in the repo; only "actual" and "diff" require login.

Annotation example to surface failures directly under the test file in the check UI:

```text
::error file=tests/ace/tui/visual/test_ace_png_snapshots.py,line=42,title=ACE PNG snapshot mismatch::
agent_list_120x40 changed 137/4800 pixels (2.85%) — see job summary for diff/expected/actual.
```

## Decision Notes

- Use GitHub job summaries for the primary UX because they are explicit, scannable, and designed for run-level
  reports.
- Use annotations as a notification surface, anchored with `file=`/`line=`/`title=` to the failing test.
- Prefer a self-contained HTML report over many single-file artifacts for v1 because it handles any number of
  failures with one upload step and stays under the per-job artifact cap.
- Do not try to inline expected/actual/diff PNGs in `$GITHUB_STEP_SUMMARY` — GitHub's Markdown sanitizer strips
  `data:` image URIs and most arbitrary HTML. Use `<details>` for collapsibles, but link out for images.
- Upgrade only the report upload to `actions/upload-artifact@v7` initially. Leave the existing raw artifact upload
  in place until the report is proven, then tighten to `if: failure()`.
- Anchor SASE's internal expectations to the reality that artifact URLs are auth-walled even for public repos. If
  link-sharing with anonymous reviewers becomes important, escalate to Option G (Pages) or Option H (Argos).
- Do not post PR comments yet; the permissions/noise tradeoff is worse than the benefit for v1, and fork PRs would
  need separate handling.

## Open Questions

- Does GitHub preserve URL fragments after clicking an `artifact-url` for an unzipped HTML artifact? If not, the
  report should still land at the top with a table of contents and use in-page links after load.
- Should the report include `diff.png` as the primary first image? For snapshot debugging, the best order is
  probably `diff`, then `expected`, then `actual`.
- Should missing-golden failures link only to `actual`, or should the expected link point to the intended golden
  path in the repo even though it does not exist at that SHA?
- Is there appetite to evaluate Argos CI (Option H) as a v2 follow-up once Option C is in place? It would replace
  the bespoke report and add an approval-in-PR workflow, but couples SASE to a managed service.
- If SASE later adopts `pytest-textual-snapshot` (per `tui_pixel_snapshot_testing.md` Milestone 1), should
  `snapshot_report.html` from that plugin replace or coexist with the SASE-owned PNG report?

## Sources

- [`actions/upload-artifact` README and outputs](https://github.com/actions/upload-artifact)
- [GitHub blog: artifact v4 immediate URL availability](https://github.blog/news-insights/product-news/get-started-with-v4-of-github-actions-artifacts/)
- [GitHub workflow commands (job summaries, annotations, groups)](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands)
- [GitHub blog: job summaries](https://github.blog/news-insights/product-news/supercharging-github-actions-with-job-summaries/)
- [GitHub REST API: Actions artifacts](https://docs.github.com/en/rest/actions/artifacts)
- [`actions/upload-artifact` issue #51 — artifact URLs require login even on public repos](https://github.com/actions/upload-artifact/issues/51)
- [`actions/upload-artifact` issue #144 — public-repo artifact downloads still require auth](https://github.com/actions/upload-artifact/issues/144)
- [`github/markup` issue #270 — base64 / data URI images are not rendered in GitHub Markdown](https://github.com/github/markup/issues/270)
- [Argos CI documentation and GitHub integration](https://argos-ci.com/docs/github)
- [reg-suit — OSS visual regression report tool](https://github.com/reg-viz/reg-suit)
- [reg-actions — reg-suit variant that uses GitHub Actions workflow artifacts](https://github.com/reg-viz/reg-actions)
- [`pytest-textual-snapshot` plugin](https://github.com/Textualize/pytest-textual-snapshot)
- [`pytest-json-report` plugin](https://github.com/numirias/pytest-json-report)
- [`peaceiris/actions-gh-pages` (publishing static reports to GitHub Pages)](https://github.com/peaceiris/actions-gh-pages)
- [`actions/upload-pages-artifact`](https://github.com/actions/upload-pages-artifact)
- Related SASE research: `sdd/research/202605/tui_pixel_snapshot_testing.md`
- Related SASE research: `sdd/research/202605/markdown_to_html_rich_artifacts.md`
