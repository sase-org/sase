# PyPI Release Smoke-Test Environment

This harness verifies the packages published to PyPI from the perspective of a fresh
user. The image contains only the toolchain; `sase`, `sase-github`, and `sase-telegram`
are installed at container start with `uv tool install --refresh`. `sase-core-rs` is
verified through the installed `sase` dependency and import path.

## Prerequisites

- Docker with Compose v2.
- Network access to PyPI, npm, and Debian package mirrors when the image is first built.

## Automated Smoke

From the repository root:

```bash
just pypi-smoke
```

The run writes a timestamped report under `smoke/pypi/results/` and exits nonzero on the
first failed stage.

The automated check covers:

- `uv tool install --force --refresh` with the plugin packages injected into the same
  tool venv.
- `sase version -j`, including `sase` and `sase-core-rs`.
- `import sase_core_rs` inside the tool venv.
- `sase version -j` discovery of `sase-github` and `sase-telegram` plugin packages, plus
  `sase axe chop list -j` and `sase axe chop doctor -j` for `sase-telegram` chop
  scripts.
- `sase doctor -j` with warnings tolerated and hard errors rejected.
- A scratch git repository using provider-independent CLI flows: help, xprompt list,
  config dump, and beads.
- A second fresh `uv venv` plus `uv pip install` flow that repeats the version, Rust
  import, and plugin checks.

## Pinning

Copy `.env.example` to `.env` in this directory to pin a historical run:

```bash
cp smoke/pypi/.env.example smoke/pypi/.env
```

Then edit the specs, for example:

```dotenv
SASE_SPEC=sase==0.1.6
SASE_GITHUB_SPEC=sase-github==0.1.1
SASE_TELEGRAM_SPEC=sase-telegram==0.1.0
SASE_CORE_RS_SPEC=sase-core-rs==0.1.2
```

`SASE_CORE_RS_SPEC` is an assertion only. The smoke install does not install a separate
`sase-core-rs` top-level tool; the distribution is pulled by `sase`.

## Interactive Shell

```bash
just pypi-smoke-shell
```

This starts the same fresh install, then opens a shell. Provider auth state is preserved
in the Compose `home` volume, so you can authenticate once and run manual checks such
as:

```bash
sase doctor
sase run "#git:home summarize this scratch environment"
sase agent list
sase ace
```

Optional `GH_TOKEN`, `GITHUB_TOKEN`, and `TELEGRAM_BOT_TOKEN` values in `.env` are
passed through for manual plugin checks.

## Reset

```bash
just pypi-smoke-clean
```

This removes the Compose volume and the smoke image so the next run starts from a
factory-clean container.
