---
create_time: 2026-06-09 10:52:42
status: done
prompt: sdd/prompts/202606/publish_sase_core_rs_0_1_1.md
---
# Plan: Publish `sase-core-rs` 0.1.1 to PyPI

## Context

The `https://pypi.org/project/sase-core-rs/` URL still returns 404 because no upload has successfully created the PyPI
project yet. The GitHub release and tag exist, but PyPI publication is a separate workflow path:

- `sase-org/sase-core` release `v0.1.1` exists and now targets `ac1be9e`, the manifest-fix commit.
- The latest `Release-plz` run on `ac1be9e` is green, but `release-plz-release` reported `releases_created: false`; all
  wheel, sdist, metadata, and publish jobs were skipped by design.
- The original release run `27206889681` did create `v0.1.1`, built four wheels plus an sdist, and passed `twine check`.
  Its `publish to PyPI` job failed before upload with PyPI Trusted Publishing `invalid-publisher`.
- The failing OIDC claims were:
  - `sub`: `repo:sase-org/sase-core:environment:pypi`
  - `repository`: `sase-org/sase-core`
  - `workflow_ref`: `sase-org/sase-core/.github/workflows/release-plz.yml@refs/heads/master`
  - `ref`: `refs/heads/master`
  - `environment`: `pypi`
- The GitHub `pypi` environment exists and is branch-restricted to `master`, so GitHub environment routing is not the
  blocker. PyPI refused the OIDC token because PyPI has no matching normal or pending trusted publisher.

The original run's saved artifacts should not be used for the final upload. They were built from the old `ab0a97d`
commit, before the manifest fix. The wheels are probably equivalent at the binary level, but the sdist contains the old
path-only internal dependency shape. Since `v0.1.1` has been intentionally re-anchored to `ac1be9e`, the PyPI artifacts
should be rebuilt from `ac1be9e` as well.

## Root Cause

This is now a PyPI Trusted Publisher recovery problem, not a release-plz manifest problem.

The first release run got far enough to build and validate Python distributions, but PyPI rejected the upload with
`invalid-publisher`. That error means the presented GitHub OIDC token was valid, but it did not match any PyPI trusted
publisher configuration for the project name being uploaded. Because `sase-core-rs` does not exist on PyPI yet, the
right PyPI-side setup is a pending trusted publisher for that project name.

After the tag fix, simply re-running the current `Release-plz` workflow cannot publish, because release-plz now sees no
new release to create and the workflow only publishes when `release-plz-release.outputs.releases_created == 'true'`.

## Proposed Fix

Use PyPI Trusted Publishing as intended, but add a guarded one-shot manual publish path to the existing
`.github/workflows/release-plz.yml` workflow so CI can rebuild and publish `sase-core-rs` 0.1.1 from current
`master`/`v0.1.1`.

### 1. Configure PyPI pending trusted publisher

Before running the publish job, configure a pending trusted publisher on PyPI for the not-yet-created project:

- PyPI project name: `sase-core-rs`
- Publisher: GitHub Actions
- Owner / organization: `sase-org`
- Repository: `sase-core`
- Workflow filename: `release-plz.yml` (workflow path is `.github/workflows/release-plz.yml`)
- Environment: `pypi`

If a pending publisher already exists, verify these fields exactly. The prior error is consistent with a missing
publisher, a project-name mismatch, a workflow-name mismatch, or an environment mismatch.

### 2. Add a guarded manual PyPI publish mode

Modify `.github/workflows/release-plz.yml` in `sase-core` with the smallest durable recovery mechanism:

- Add workflow-dispatch inputs:
  - `publish_pypi`, boolean, default `false`.
  - `expected_version`, string, default empty or `0.1.1`.
- Keep the existing automatic publish behavior unchanged for future real releases:
  - automatic publish still requires `release-plz-release.outputs.releases_created == 'true'`
  - automatic publish still requires not running in dry-run mode
- Extend the publish job condition to also allow manual recovery when all are true:
  - `github.event_name == 'workflow_dispatch'`
  - `inputs.build_wheels == true`
  - `inputs.publish_pypi == true`
  - `inputs.dry_run == false`

Add a pre-publish guard step for the manual recovery path before `pypa/gh-action-pypi-publish`:

- Fail unless the workflow is running on `refs/heads/master`.
- Fail unless `expected_version` is non-empty.
- Fetch tags and fail unless `HEAD` equals `v${expected_version}^{commit}`.
- Fail unless all files in `dist/` have Python metadata `Name: sase-core-rs` and `Version: ${expected_version}`.
- Query PyPI for `sase-core-rs==${expected_version}` and fail if that version already exists, so a retry cannot silently
  overwrite or duplicate an immutable PyPI release.
- Leave `skip_existing: false` for the normal publish action. If a future network failure creates a partial upload,
  handle that as a separate inspected recovery rather than hiding it.

This keeps the recovery path in the same trusted workflow PyPI will be configured to trust, but makes accidental manual
publishing hard.

### 3. Validate before publishing

Before pushing the workflow change:

- Confirm local git state in `sase-core` is clean or isolate unrelated changes.
- Run `cargo metadata --format-version 1 --no-deps`.
- Run `cargo package -p sase_core -p sase_core_py --no-verify` to confirm the moved tag/current manifests still pass the
  Cargo packaging stage that failed originally.
- Build or inspect an sdist from current `ac1be9e` and confirm its workspace dependency table includes the versioned
  `sase_core` workspace dependency.
- Run `actionlint` if available; otherwise review the workflow expression and YAML diff manually.

After the workflow change is on `master`, run a non-publishing dispatch first:

```bash
gh workflow run release-plz.yml --repo sase-org/sase-core --ref master \
  -f dry_run=true \
  -f build_wheels=true \
  -f publish_pypi=false \
  -f expected_version=0.1.1
```

Confirm the wheel matrix, sdist, and `twine check` pass, and confirm `publish to PyPI` is skipped.

### 4. Publish 0.1.1

After PyPI pending publisher configuration is confirmed, dispatch the guarded publish path:

```bash
gh workflow run release-plz.yml --repo sase-org/sase-core --ref master \
  -f dry_run=false \
  -f build_wheels=true \
  -f publish_pypi=true \
  -f expected_version=0.1.1
```

Expected behavior:

- `release-plz-release` reports no newly-created release, which is fine for this recovery.
- `Release-plz PR` runs and remains green/no-op.
- Linux, macOS, Windows wheels and sdist are rebuilt from `ac1be9e`.
- `twine check` passes.
- The guarded `publish to PyPI` job mints a PyPI token through the `pypi` environment and uploads the rebuilt 0.1.1
  distributions.

If PyPI still returns `invalid-publisher`, do not change package code. Use the new claim dump from the failed job to fix
the pending publisher fields, then rerun only the failed publish path after verifying no files were uploaded.

### 5. Post-publish validation

Verify all of the following:

- `https://pypi.org/project/sase-core-rs/` returns 200 and shows version `0.1.1`.
- `https://pypi.org/pypi/sase-core-rs/0.1.1/json` returns metadata for exactly one sdist and the expected wheels:
  - manylinux x86_64
  - manylinux aarch64
  - macOS universal2
  - Windows amd64
- In a Python 3.12+ environment, install from PyPI and smoke-test:

```bash
python -m venv /tmp/sase-core-rs-pypi-smoke
/tmp/sase-core-rs-pypi-smoke/bin/pip install --upgrade pip
/tmp/sase-core-rs-pypi-smoke/bin/pip install --only-binary=:all: sase-core-rs==0.1.1
/tmp/sase-core-rs-pypi-smoke/bin/python -c "import sase_core_rs; print(sase_core_rs.parse_query('status:Ready'))"
```

- Confirm the PyPI pending publisher converted into a normal trusted publisher.
- Confirm the GitHub release `v0.1.1` still targets `ac1be9e` and no extra release PR was created.

## Risks and Mitigations

- PyPI pending publishers do not reserve project names before first upload. Mitigation: configure the pending publisher
  immediately before publishing and verify the project is still 404 right before dispatch.
- PyPI package files are immutable. Mitigation: guard that version `0.1.1` does not already exist, keep
  `skip_existing: false`, and inspect any partial-upload failure before retrying.
- Adding a manual publish path expands workflow surface area. Mitigation: require `build_wheels`, `publish_pypi`,
  `dry_run=false`, `expected_version`, `master`, tag/HEAD equality, PyPI absence, and metadata checks before upload.
- The PyPI configuration step may require account or organization access that the local agent does not have. Mitigation:
  keep the exact fields in this plan and block publish until the user confirms they are configured.

## Non-Goals

- Do not bump beyond version `0.1.1`.
- Do not move the tag again unless validation shows it no longer points at `ac1be9e`.
- Do not publish the old `ab0a97d` artifacts from run `27206889681`.
- Do not replace Trusted Publishing with a long-lived PyPI API token unless the trusted-publisher path is explicitly
  abandoned.
