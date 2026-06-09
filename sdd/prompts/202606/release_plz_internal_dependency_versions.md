---
plan: sdd/tales/202606/release_plz_internal_dependency_versions.md
---
 #fork:43.f1 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

```
-- Running release-plz release-pr --
2026-06-09T12:43:49.377681Z  INFO using release-plz config file release-plz.toml
2026-06-09T12:43:49.432743Z  INFO Latest release of package sase_core: tag `v0.1.1` (version 0.1.1)
2026-06-09T12:43:49.682528Z ERROR failed to update packages

Caused by:
    0: failed to determine next versions
    1: run cargo package
    2: cargo package failed: "\u{1b}[1m\u{1b}[92m    Updating\u{1b}[0m crates.io index\n\u{1b}[1m\u{1b}[92m   Packaging\u{1b}[0m sase_core v0.1.1 (/tmp/release-plz-sase_core-wxQ1Qp/worktree/crates/sase_core)\n\u{1b}[1m\u{1b}[92m    Updating\u{1b}[0m crates.io index\n\u{1b}[1m\u{1b}[92m    Packaged\u{1b}[0m 98 files, 1.3MiB (246.4KiB compressed)\n\u{1b}[1m\u{1b}[91merror\u{1b}[0m: failed to verify manifest at `/tmp/release-plz-sase_core-wxQ1Qp/worktree/crates/sase_core_py/Cargo.toml`\n\nCaused by:\n  all dependencies must have a version requirement specified when packaging.\n  dependency `sase_core` does not specify a version\n  Note: The packaged dependency will use the version from crates.io,\n  the `path` specification will be removed from the dependency declaration.\n"
Error: failed to update packages

Caused by:
    0: failed to determine next versions
    1: run cargo package
    2: cargo package failed: "\u{1b}[1m\u{1b}[92m    Updating\u{1b}[0m crates.io index\n\u{1b}[1m\u{1b}[92m   Packaging\u{1b}[0m sase_core v0.1.1 (/tmp/release-plz-sase_core-wxQ1Qp/worktree/crates/sase_core)\n\u{1b}[1m\u{1b}[92m    Updating\u{1b}[0m crates.io index\n\u{1b}[1m\u{1b}[92m    Packaged\u{1b}[0m 98 files, 1.3MiB (246.4KiB compressed)\n\u{1b}[1m\u{1b}[91merror\u{1b}[0m: failed to verify manifest at `/tmp/release-plz-sase_core-wxQ1Qp/worktree/crates/sase_core_py/Cargo.toml`\n\nCaused by:\n  all dependencies must have a version requirement specified when packaging.\n  dependency `sase_core` does not specify a version\n  Note: The packaged dependency will use the version from crates.io,\n  the `path` specification will be removed from the dependency declaration.\n"
Error: Process completed with exit code 1.
```