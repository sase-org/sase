---
title: "sase update"
description: "Upgrade sase and every installed sase plugin together, in one atomic operation, by delegating to `uv tool upgrade sase`."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase update

Upgrade sase and all installed plugins together via uv

Reference for `sase update`. Run `sase update --help` for the exact output on this checkout.

```text
usage: sase update [-h] [-j] [-n] [-q] [-t {dev,pypi}] [-v] [-y]
```

Upgrade sase and every installed sase plugin together, in one atomic operation, by delegating to `uv tool upgrade sase`. This re-resolves sase core and all injected plugins in a single shot, so they always move forward as a coherent set. This only works when sase was installed via `uv tool install sase` (the canonical install path). When run from a pip/pipx install or a dev checkout's virtualenv, it fails fast with an actionable message instead of touching your environment. Use `-n|--dry-run` to preview the exact uv command and the package set without changing anything. Use `-t|--to dev|pypi` to switch between editable development checkouts and published PyPI wheels. Switching to dev fast-forwards clean existing checkouts to their configured upstream before reinstalling editables.

Options:

| Option             | Description                                                                                 | Default |
| ------------------ | ------------------------------------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`  | Show the planned uv command and package set without running it                              | `false` |
| `-h`, `--help`     | show this help message and exit                                                             | —       |
| `-j`, `--json`     | Emit machine-readable JSON                                                                  | `false` |
| `-q`, `--quiet`    | Suppress progress output; print only a one-line summary                                     | `false` |
| `-t TO`, `--to TO` | Switch install mode to editable checkouts or published PyPI wheels (choices: `dev`, `pypi`) | —       |
| `-v`, `--verbose`  | Stream full output of every step (git, uv, cargo) as it runs                                | `false` |
| `-y`, `--yes`      | Skip the install-mode switch confirmation prompt                                            | `false` |

Related: [CLI command groups](index.md).
