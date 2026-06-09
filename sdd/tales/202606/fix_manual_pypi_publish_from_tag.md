---
create_time: 2026-06-09 14:12:24
status: wip
prompt: sdd/prompts/202606/fix_manual_pypi_publish_from_tag.md
---
# Plan: Fix the failing manual PyPI publish for `sase-core-rs` 0.1.1

## Problem

The guarded manual publish run of `sase-org/sase-core`'s `release-plz.yml` failed at the `Guard manual PyPI publish`
step:

```
HEAD aad7963d030c4934453583486277ecc6f696fdbc does not match v0.1.1 ac1be9ee3a16391c1bc42213678a9ad687200c3c
Error: Process completed with exit code 1.
```

The guard never reached `pypa/gh-action-pypi-publish`, so nothing was uploaded and PyPI is still 404 for `sase-core-rs`
(verified). This is a workflow-design bug, not a PyPI account problem.

## Root Cause

Two coupled problems, both stemming from the same wrong assumption baked into the guard: that the workflow would be
dispatched on a `master` whose HEAD still equals the `v0.1.1` tag.

1. **Guard mismatch (the immediate failure).** The manual publish path must be dispatched on `master`, because (a) the
   guarded manual path only exists in the `release-plz.yml` on `master` — the `v0.1.1` tag predates it — and (b) the
   GitHub `pypi` environment used by the publish job is branch-restricted to `master`. But the guard requires
   `HEAD == v${expected_version}^{commit}`. Master HEAD is now `41e925f`, which is **3 commits ahead** of the `v0.1.1`
   tag (`ac1be9e`):

   ```
   41e925f feat: preserve prompt previews in agent group archive wire
   aad7963 fix: expose agent template namespaces from core
   8483583 chore: add guarded manual PyPI publish workflow   <- the workflow commit itself
   ac1be9e fix: inherit versioned sase_core dependency        <- v0.1.1 tag target
   ```

   Committing the workflow (and subsequent unrelated work) advanced `master` past the tag, so `HEAD == tag` can never
   hold on a `master` dispatch. The guard is structurally unsatisfiable.

2. **Latent provenance bug (would corrupt the release even if the guard passed).** Every build job (`linux`, `macos`,
   `windows`, `sdist`) and the publish-guard checkout use a bare `actions/checkout@v4` with no `ref:`, so they check out
   the _dispatched ref_ — master HEAD — not the tag. Master has diverged from `v0.1.1` by **106 lines of real source**
   under `crates/` (`agent_group_archive`, `agent_name_template`, `sase_core_py/src/lib.rs`). Because the workspace
   version is still `0.1.1` (no release-plz bump has landed), building from master HEAD would produce wheels/sdist
   **labeled `0.1.1` but containing unreleased code**. PyPI `0.1.1` would then not match GitHub release `v0.1.1`
   (`ac1be9e`). PyPI files are immutable, so this would be permanent.

The correct invariant is: **dispatch on `master` (for the workflow file + `pypi` environment), but build and publish the
artifacts from the `v${expected_version}` tag's source.** The current design conflates "where the workflow runs" with
"what source we package," and the `HEAD == tag` guard is the wrong tool for enforcing provenance in that split.

## Proposed Fix

All changes are in `sase-core`'s `.github/workflows/release-plz.yml` (edit in the `sase-core_11` sibling workspace,
commit via the SASE commit wrapper). No package/source code changes.

### 1. Build the artifacts from the tag, not the dispatched HEAD

Add an explicit checkout `ref` to the four build jobs (`linux`, `macos`, `windows`, `sdist`) so that manual dispatch
builds from the requested tag, while the automatic release path keeps its current behavior:

```yaml
- uses: actions/checkout@v4
  with:
    ref:
      ${{ (github.event_name == 'workflow_dispatch' && inputs.expected_version != '') && format('v{0}',
      inputs.expected_version) || '' }}
```

- Manual dispatch with `expected_version=0.1.1` → checks out `v0.1.1` (`ac1be9e`) → artifacts are the real release
  source.
- `push` events (automatic release) and dispatches without `expected_version` → `ref: ''` → `actions/checkout` uses its
  default (the triggering commit), preserving today's behavior.
- This also makes the dry-run validation build (`build_wheels=true, publish_pypi=false`) build from the tag, so the dry
  run is representative of what the real publish will upload.

### 2. Replace the unsatisfiable `HEAD == tag` guard with a provenance-appropriate check

In the `Guard manual PyPI publish` step, keep the safety checks that still make sense and drop the one that fights the
dispatch-on-master design:

- **Keep**: `GITHUB_REF == refs/heads/master` (ensures the `pypi` environment routing / trusted workflow file is the
  master one).
- **Keep**: `expected_version` non-empty.
- **Keep**: the artifact metadata sweep — every file in `dist/` must report `Name: sase-core-rs` and
  `Version: ${expected_version}`. Combined with step 1 (build-from-tag), this is now the real provenance gate.
- **Keep**: the PyPI-absence check for `sase-core-rs==${expected_version}` (blocks duplicate/overwrite of an immutable
  release).
- **Replace** `HEAD == v${expected_version}^{commit}` with a **tag-existence** assertion: fetch tags and fail unless
  `v${expected_version}^{commit}` resolves. This still refuses to publish a version that has no release tag, without
  requiring the master checkout to equal the tag.

Leave `skip_existing: false` on the publish action (unchanged); a partial upload should surface, not be silently
swallowed.

### 3. Validate locally before pushing

In `sase-core_11`:

- `actionlint .github/workflows/release-plz.yml` (or careful manual YAML/expression review if not installed).
- Confirm the build-job `ref` expression yields `v0.1.1` for the manual-publish inputs and `''` for a `push` (reason
  through the expression; it gates on `github.event_name == 'workflow_dispatch'`).
- Sanity-check that `v0.1.1` builds a `0.1.1` sdist whose manifest carries the versioned workspace dependency (already
  verified previously from `ac1be9e`; re-confirm if convenient).

Commit the workflow change to `master` with the SASE commit wrapper (single workflow file).

### 4. Confirm the PyPI pending trusted publisher (user / account action)

The previous run failed before the publish action, so the trusted publisher has never actually been exercised. Before
dispatching the real publish, ensure a **pending** trusted publisher exists on PyPI (project is still 404, so it must be
pending), with exactly:

- PyPI project name: `sase-core-rs`
- Publisher: GitHub Actions
- Owner / organization: `sase-org`
- Repository: `sase-core`
- Workflow filename: `release-plz.yml`
- Environment: `pypi`

### 5. Dry run, then publish 0.1.1

After the workflow fix is on `master` and the pending publisher is confirmed:

Dry-run validation (builds from the tag, publish skipped):

```bash
gh workflow run release-plz.yml --repo sase-org/sase-core --ref master \
  -f dry_run=true -f build_wheels=true -f publish_pypi=false -f expected_version=0.1.1
```

Confirm the wheel matrix + sdist + `twine check` pass and `publish to PyPI` is skipped.

Real publish (builds from the tag, guard passes, uploads):

```bash
gh workflow run release-plz.yml --repo sase-org/sase-core --ref master \
  -f dry_run=false -f build_wheels=true -f publish_pypi=true -f expected_version=0.1.1
```

### 6. Post-publish validation

- `https://pypi.org/project/sase-core-rs/` returns 200 showing `0.1.1`.
- `https://pypi.org/pypi/sase-core-rs/0.1.1/json` lists one sdist + the four wheels (manylinux x86_64, manylinux
  aarch64, macOS universal2, Windows amd64).
- Smoke test from PyPI in a clean venv:

  ```bash
  python3 -m venv /tmp/sase-core-rs-pypi-smoke
  /tmp/sase-core-rs-pypi-smoke/bin/pip install --upgrade pip
  /tmp/sase-core-rs-pypi-smoke/bin/pip install --only-binary=:all: sase-core-rs==0.1.1
  /tmp/sase-core-rs-pypi-smoke/bin/python -c "import sase_core_rs; print(sase_core_rs.parse_query('status:Ready'))"
  ```

- Confirm the PyPI pending publisher converted to a normal trusted publisher, and `v0.1.1` still targets `ac1be9e`.

## Alternatives Considered (rejected)

- **Move the `v0.1.1` tag to master HEAD and rerun.** Rejected: it ships the 106 lines of unreleased `crates/` code as
  `0.1.1`, contradicting the approved publish plan's non-goals ("do not move the tag", "rebuild from `ac1be9e`"), and
  PyPI immutability would make it permanent.
- **Dispatch the workflow on the `v0.1.1` tag ref.** Rejected: the tag's `release-plz.yml` predates the manual publish
  path, and the `pypi` environment is branch-restricted to `master`, so the publish job would be blocked.
- **Just relax the guard but keep building from master HEAD.** Rejected: fixes the symptom (guard failure) but leaves
  the provenance bug — it would publish unreleased code as `0.1.1`.

## Risks and Mitigations

- **Wrong-source upload.** Mitigated by building from the tag (step 1) + metadata `Name`/`Version` gate (step 2). PyPI
  immutability means this gate matters; dry-run first.
- **Empty/duplicate publish.** Mitigated by `expected_version` required, tag-existence check, and the PyPI-absence
  check; `skip_existing: false`.
- **Account access.** The pending trusted publisher (step 4) may need org/account permissions the agent lacks; publish
  is blocked until the user confirms it.

## Non-Goals

- No package/source changes; no version bump beyond `0.1.1`.
- Do not move the `v0.1.1` tag.
- Do not replace Trusted Publishing with a long-lived API token.
- Do not alter the automatic release path's behavior for future real releases.
