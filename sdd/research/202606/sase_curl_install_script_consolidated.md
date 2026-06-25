# SASE Curl Install Script - Consolidated Research

Date: 2026-06-25
Status: Consolidated research

## Question

Should SASE ship a one-line `curl ... | sh` installer backed by an `install.sh`
script to improve first-run setup? The request mentions checking that "UB" is
installed; this research treats that as `uv`, SASE's documented package-manager
prerequisite.

## Recommendation

Ship it, but keep it thin and explicitly secondary to the direct `uv` install.

The primary install should remain:

```bash
uv tool install sase --python 3.12
sase version
sase doctor
```

The curl installer is valuable for a different reason: it collapses the cold
start from "notice prerequisites, install uv, install SASE, discover doctor,
then install/authenticate a provider" into one guided flow that ends at the
existing readiness gate. It is an onboarding wrapper, not a replacement package
manager and not a source/developer install path.

Recommended public command:

```bash
curl --proto '=https' --tlsv1.2 -LsSf https://sase.sh/install.sh | sh
```

Recommended inspect-first command:

```bash
curl --proto '=https' --tlsv1.2 -fLso install.sh https://sase.sh/install.sh
less install.sh
sh install.sh
```

This updates, but does not fully overturn, the 2026-05 plugin/install research
that deferred `curl | sh` until users fail before reaching `uv tool install`.
Deferring again is still reasonable if there is no near-term public launch or
user evidence. If the goal is cold-reader onboarding from the website/blog, the
thin script is justified.

## Verified Baseline

- README install path is currently `uv tool install sase --python 3.12`, then
  `sase version` and `sase doctor`.
- `pyproject.toml` publishes `sase==0.5.0`, requires Python `>=3.12`, depends on
  `sase-core-rs>=0.2.0,<0.3.0`, and exposes the `sase` console script.
- Normal installs do not require Rust. `sase-core-rs` is a required extension,
  but normal PyPI installs pull prebuilt wheels; source/developer installs are
  separate.
- Live PyPI metadata on 2026-06-25 matches the repo baseline:
  `sase==0.5.0`, `sase-core-rs==0.2.0`, `sase-github==0.1.2`, and
  `sase-telegram==0.1.3`.
- `sase-core-rs==0.2.0` publishes wheels for macOS universal2,
  manylinux 2.28 x86_64, manylinux 2.28 aarch64, and Windows x86_64, plus an
  sdist. It does not publish a musllinux wheel, so Alpine/musl should fail
  clearly by default instead of silently attempting a Rust build.
- `sase-github` and `sase-telegram` publish `py3-none-any` wheels. They must be
  installed into the same uv tool environment as SASE, e.g.
  `uv tool install sase --python 3.12 --with sase-github`.
- Local `uv 0.11.24` supports the installer-relevant surface:
  `uv tool install --with`, `--force`, `--upgrade`, `--reinstall`, `--python`,
  `--refresh`, `--no-build`, `uv tool dir --bin`, and `uv tool update-shell`.
- `smoke/pypi/entrypoint.sh` already acts as the closest reference
  implementation: it installs `sase` with uv, injects optional plugins with
  `--with`, then `smoke_check.sh` verifies `sase version -j`, `sase doctor -j`,
  chop inventory, and basic provider-independent usage.

## Existing Readiness Gate

The install script should hand off to `sase doctor`; it should not duplicate
doctor checks.

`sase doctor` already covers runtime/core health, paths, config, plugins, VCS,
tools, and provider readiness. Provider discovery is entry-point based through
the `sase_llm` group, with executable autodetection and `SASE_<PROVIDER>_PATH`
overrides. Provider setup hints already live in
`src/sase/doctor/checks_providers.py`, including Claude Code, Codex, OpenCode,
Qwen Code, and Antigravity CLI.

Use `sase version` as the hard "installed correctly" check. Treat `sase doctor`
as a readiness diagnostic by default, because provider/auth failures can mean
"SASE installed successfully, but no provider is ready yet." Add a
`--strict-doctor` option for CI or docs that require full readiness.

## Script Contract

The installer should do only these jobs:

1. Detect Linux/macOS and CPU architecture. Exit clearly on unsupported
   platforms. Given the current POSIX classifier, Windows should get direct uv
   instructions or a future PowerShell installer, not a pretend `sh` path.
2. Be safe to pipe. Keep the executable body in a `main` function invoked at the
   end, use strict shell settings, and publish honestly as `sh` or `bash`
   depending on the features used.
3. Ensure `uv`. If present, use it. If missing in interactive mode, prompt to
   install via Astral's official installer. If missing in non-interactive mode,
   fail unless the user explicitly supplied `--install-uv` or
   `SASE_INSTALL_UV=1`.
4. Install SASE through uv:

   ```bash
   uv tool install sase --python 3.12 --no-build
   ```

   Let uv own Python provisioning, package resolution, the tool environment, and
   executable linking. Offer `--allow-build` as an advanced escape hatch for
   platforms without wheels.
5. Keep optional plugins opt-in but hard to install incorrectly. Translate
   friendly names like `--with github` to `--with sase-github`, and pass package
   specs such as `--with sase-github==0.1.2` through to uv.
6. Handle PATH visibility without silently rewriting shell startup files. Use
   `uv tool dir --bin` to find the executable directory. If it is not on PATH,
   make the current process able to run `sase`, then print exact shell guidance
   or offer `uv tool update-shell`.
7. Verify and hand off: run `sase version`, then `sase doctor`, then print the
   safe first command from the quickstart:

   ```bash
   sase run "#cd:$(pwd) summarize what this repository does; do not change files"
   ```

## Stable Flags

Keep the initial flag set small:

| Flag | Behavior |
| --- | --- |
| `--yes`, `-y` | Non-interactive mode for SASE-owned prompts. |
| `--install-uv` | Install uv automatically if missing. |
| `--no-install-uv` | Fail if uv is missing. |
| `--version <version>` | Install `sase==<version>` instead of latest stable. |
| `--python <version>` | Python request for uv; default `3.12`. |
| `--with github` | Add `--with sase-github`. |
| `--with telegram` | Add `--with sase-telegram`. |
| `--with <package>` | Advanced uv `--with` passthrough. |
| `--force` | Pass `uv tool install --force`. |
| `--upgrade` | Pass `--upgrade --refresh`. |
| `--allow-build` | Do not pass `--no-build`; permit source builds. |
| `--no-modify-shell` | Never call `uv tool update-shell`; print guidance only. |
| `--no-doctor` | Skip post-install `sase doctor`. |
| `--strict-doctor` | Exit nonzero if `sase doctor` exits nonzero. |
| `--dry-run` | Print the planned commands. |
| `--help` | Print usage and exit. |

Honor `NO_COLOR` and propagate uv/SASE failures. Re-running should be
idempotent: no-op, upgrade, or explain the conflict rather than half-installing.

## Non-goals

- Do not reimplement Python, uv, wheel, or Rust-core installation.
- Do not install provider CLIs such as `claude`, `codex`, `agy`, `qwen`, or
  `opencode` behind the user's back. Provider auth is provider-owned.
- Do not duplicate `sase doctor` checks in shell.
- Do not silently edit shell rc files.
- Do not become the contributor/source install path (`uv venv` plus
  `just install`).
- Do not make plugins default. Core SASE should install alone; plugins stay
  opt-in through uv `--with`.

## Security Posture

`curl | sh` is acceptable here only if the script stays narrow and auditable.
Use HTTPS on a controlled domain (`https://sase.sh/install.sh` or
`get.sase.sh`), keep the served script in this repo, and document the
inspect-first path beside the pipe command.

The script should fetch from three places only: `sase.sh` for itself, Astral's
uv installer when the user explicitly accepts uv installation, and PyPI through
uv. Avoid additional GitHub raw downloads or self-managed release asset logic.

Do not make the curl line the only documented install path. Reviewers and
security-conscious users should always have the direct `uv tool install` path.

## Test Matrix Before Publishing

| Scenario | Expected result |
| --- | --- |
| Fresh Linux/macOS with uv present | Installs SASE; `sase version` passes. |
| Fresh Linux/macOS without uv | Interactive prompt offers uv install; decline aborts cleanly. |
| `--yes --no-install-uv` without uv | Fails without prompting. |
| `--yes --install-uv` without uv | Installs uv through Astral, then installs SASE. |
| PATH missing uv tool bin | Current process can run `sase`; user gets PATH guidance. |
| Existing conflicting `sase` executable | Refuses or explains unless `--force` is supplied. |
| `--with github` | Installs `sase-github` into the same uv tool environment. |
| `--with telegram` | Installs `sase-telegram` into the same uv tool environment. |
| Alpine/musl default | Fails clearly because `--no-build` prevents an unexpected Rust build. |
| `--allow-build` on no-wheel platform | Attempts source build and leaves uv output visible. |
| Windows non-WSL | Exits with direct uv or future PowerShell guidance. |

Also run `shellcheck` and keep the smoke harness aligned with the installer so
`smoke/pypi/entrypoint.sh` and public install behavior do not drift.

## Rollout

1. Add the thin script with `--help`, `--yes`, uv detection, SASE install,
   `sase version`, non-fatal `sase doctor`, and first-run guidance.
2. Add CI/smoke coverage for clean Linux and macOS runs, reusing the existing
   PyPI smoke expectations.
3. Add README/docs examples with direct uv first and curl as the guided option.
4. Add polish flags (`--with`, `--version`, `--dry-run`, `--strict-doctor`) once
   the MVP is proven.
5. Consider a PowerShell installer only after Windows support is declared.

## Open Questions

- Is the public-launch/onboarding context strong enough to justify shipping the
  script now, or should the 2026-05 deferral remain until user evidence appears?
- Should the hosted path be `sase.sh/install.sh` or `get.sase.sh`?
- Should `--install-uv` be enough for automation, or should docs require both
  `--yes --install-uv` so accidental package-manager installation is harder?
- Confirm that "UB" meant `uv`.

## Sources

Internal:

- `README.md`
- `pyproject.toml`
- `docs/rust_backend.md`
- `src/sase/doctor/runner.py`
- `src/sase/doctor/checks_providers.py`
- `src/sase/llm_provider/registry.py`
- `smoke/pypi/entrypoint.sh`
- `smoke/pypi/smoke_check.sh`
- `sdd/research/202605/preferred_plugins_chops_install_strategy.md`
- `sdd/research/202606/new_user_onboarding_recommendations_consolidated.md`
- `sdd/research/202606/sase_dev_install_strategy.md`

External:

- uv installation and tool docs: https://docs.astral.sh/uv/getting-started/installation/,
  https://docs.astral.sh/uv/concepts/tools/
- PyPI package metadata: https://pypi.org/pypi/sase/json,
  https://pypi.org/pypi/sase-core-rs/json,
  https://pypi.org/pypi/sase-github/json,
  https://pypi.org/pypi/sase-telegram/json
- Homebrew install behavior: https://brew.sh/,
  https://docs.brew.sh/Installation
- Deno install and verification guidance:
  https://docs.deno.com/runtime/getting_started/installation/
- Bun install and PATH troubleshooting: https://bun.com/docs/installation
- Rust/rustup curl flags and PATH notes: https://rust-lang.org/tools/install/
- pipx isolated-app install precedent: https://pipx.pypa.io/stable/installation/
