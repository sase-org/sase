---
create_time: 2026-04-27 12:25:18
status: done
---
# Fix GitHub Actions just Setup Failure

## Problem

GitHub Actions is failing during the `extractions/setup-just@v2` step with:

```text
Error: no release for just matching version specifier
```

The local CI workflow uses `extractions/setup-just@v2` in every CI job and does not specify `just-version`. That means
the action resolves "latest matching just release" at runtime. This creates two risks:

- The workflow depends on the old v2 setup action implementation.
- The workflow depends on the current state of `casey/just` GitHub releases and assets at job runtime.

Current upstream `setup-just` documentation recommends `extractions/setup-just@v4`, and v4 delegates to the maintained
`extractions/setup-crate@v2` composite action. The current `just` release has suitable Linux assets, so this does not
look like a repo Justfile problem.

## Goals

- Fix CI setup so jobs can reliably install `just`.
- Keep the change tightly scoped to the GitHub Actions workflow unless verification uncovers a broader issue.
- Preserve existing CI job behavior after `just` is installed.

## Plan

1. Update `.github/workflows/ci.yml` to use the maintained `extractions/setup-just@v4` in all CI jobs.
2. Pin `just-version` to a known current release that has Linux x86_64 assets, rather than relying on the moving latest
   release during CI. Use the latest release observed during diagnosis, `1.50.0`, unless a final upstream check shows it
   is unsuitable.
3. Keep the repeated setup steps explicit in each job for a minimal change. Do not introduce a composite local action or
   workflow refactor for this fix.
4. Verify the workflow YAML still parses and that local project checks can run:
   - Ensure dependencies are installed if needed with `just install`.
   - Run `just check` as required by repo memory after making changes.
5. Report the root cause as an external CI bootstrap fragility: old setup action plus unpinned latest release
   resolution, not a failure in the project code or Justfile.

## Risks

- If upstream `just` changes release assets again, a pinned version avoids the immediate failure but will eventually
  need routine updates.
- If `just check` fails for unrelated pre-existing reasons, separate those from the workflow fix and report them
  clearly.
