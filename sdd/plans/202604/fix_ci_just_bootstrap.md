---
create_time: 2026-04-27 12:36:34
status: done
prompt: sdd/prompts/202604/fix_ci_just_bootstrap.md
---
# Fix CI just Bootstrap Failure

## Problem

CI still fails at `extractions/setup-just@v4`:

```text
Error: no release for just matching version specifier 1.50.0
```

The pinned `just` version is valid. GitHub shows `casey/just` release `1.50.0`, and the release has
`just-1.50.0-x86_64-unknown-linux-musl.tar.gz`. The local reproduction of
`extractions/setup-crate@0551596312d4008a6dfbc4d3c38fa20eaef46d2d` also succeeds when no GitHub token is supplied.

The likely CI-only difference is the v4 action's default `github-token: ${{ github.token }}`. That token is a GitHub App
installation token for this repository, not a general token for `casey/just`. The setup action queries the external
repository's release list through `setup-crate`; if the authenticated token cannot see that external repo's releases,
the resolver sees no matching release and reports the misleading version-specifier error.

## Goals

- Keep CI bootstrapping deterministic.
- Avoid depending on the setup action's external release-list resolver.
- Keep the change scoped to `.github/workflows/ci.yml`.
- Verify the workflow syntax and local project checks after implementation.

## Recommended Fix

Replace each `extractions/setup-just@v4` step with an explicit shell bootstrap step that downloads the exact pinned
Linux x86_64 release asset directly:

```yaml
- name: Install just
  run: |
    curl -fsSL https://github.com/casey/just/releases/download/1.50.0/just-1.50.0-x86_64-unknown-linux-musl.tar.gz -o /tmp/just.tar.gz
    echo "27e011cd6328fadd632e59233d2cf5f18460b8a8c4269acd324c1a8669f34db0  /tmp/just.tar.gz" | sha256sum -c -
    tar -xzf /tmp/just.tar.gz -C /tmp just
    sudo install -m 0755 /tmp/just /usr/local/bin/just
    just --version
```

This uses the exact release URL instead of listing releases through the GitHub API, and it verifies the archive digest
published in the release metadata before installing.

## Alternatives Considered

- Add `github-token: ""` to `setup-just@v4`. This matches the successful local reproduction, but it still depends on the
  action's release-list API behavior and unauthenticated GitHub API rate limits.
- Use `cargo install just --locked --version 1.50.0`. This is slower, depends on crates.io and Rust toolchain behavior,
  and introduces more CI work before Python checks can start.
- Pin another third-party action. This shifts trust and resolver behavior to a different action rather than removing the
  fragile lookup.

## Implementation Steps

1. Update `.github/workflows/ci.yml` only.
2. Replace the four `setup-just` steps in `lint`, `fmt-md-check`, `test`, and `build` with the direct install step.
3. Reuse the same pinned version and checksum in each job to keep the workflow obvious and independent per job.
4. Validate YAML parsing.
5. Run `just install` because this workspace may have stale editable dependencies.
6. Run `just check` per repo instructions.

## Risks

- The installer is Ubuntu x86_64 specific. This matches all current CI jobs because they use `ubuntu-latest`.
- If CI later adds non-Linux or non-x64 runners, the install step will need a small platform switch.
- Direct URL downloads still depend on GitHub release asset availability, but no longer depend on external release
  discovery or token scoping.
