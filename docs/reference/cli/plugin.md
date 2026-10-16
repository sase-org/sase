---
title: "sase plugin"
description: "Discover every SASE plugin that exists by treating the GitHub `sase--plugin` repository topic as the canonical registry."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase plugin

Discover SASE plugins from the GitHub catalog

Reference for `sase plugin`. Run `sase plugin --help` for the exact output on this checkout.

```text
usage: sase plugin [-h] {install,list,show,uninstall,update} ...
```

Discover every SASE plugin that exists by treating the GitHub `sase--plugin` repository topic as the canonical registry. The catalog distinguishes built-in plugins (published under the official `sase-org` org) from community plugins, and marks which are installed in the current environment. List/show also compare installed index plugins against PyPI and mark available updates with `↑`. Catalog and latest-version data are cached, so commands are instant on repeat runs; pass `-r|--refresh` to bypass caches or `-o|--offline` to use caches only. With no subcommand, `sase plugin` defaults to `sase plugin list`.

Bare `sase plugin` defaults to `sase plugin list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand              | Summary                                                       |
| ----------------------- | ------------------------------------------------------------- |
| `sase plugin install`   | Install a plugin into the same environment as sase            |
| `sase plugin list`      | List all known SASE plugins (built-in and community)          |
| `sase plugin show`      | Show detailed information about a single SASE plugin          |
| `sase plugin uninstall` | Remove one installed plugin from the same environment as sase |
| `sase plugin update`    | Upgrade one installed plugin (or every plugin with --all)     |

## `sase plugin install`

```text
usage: sase plugin install [-h] [-g] [-j] [-n] [-r] [-Q PATH] [-R PATH]
                           <plugin>
```

Install a SASE plugin into the *same* uv tool environment as sase, so its entry points are discovered the next time sase runs. The <plugin> name is resolved through the GitHub catalog (`github` -> `sase-github`); a raw requirement, git URL, or local path is passed through verbatim. By default the plugin is installed from its published distribution; it falls back to the plugin's git repository automatically only when public PyPI definitively has no such distribution (a 404). An unreachable or slow index is never treated as absence, so a transient outage still resolves from the index. Pass `-g|--git` to force the repository install regardless of index state. This only works when sase was installed via `uv tool install sase` (the canonical install path). When run from a pip/pipx install or a dev checkout's virtualenv, it fails fast with an actionable message instead of touching your environment. uv's `--with` set is reconstructed from sase's uv receipt, so existing plugins and editable/dev installs are preserved. Use `-n|--dry-run` to preview the exact uv command and resulting plugin set without changing anything. A successful install that changes packages restarts the scheduler so background automation loads the new plugin code.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`                | Show the planned uv command and plugin set without running it                                                           | `false` |
| `-g`, `--git`                    | Force install from the plugin's git repository instead of an index                                                      | `false` |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                   | Emit machine-readable JSON                                                                                              | `false` |
| `-r`, `--refresh`                | Bypass the cache and refetch the catalog from GitHub                                                                    | `false` |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description                                                     |
| -------- | --------------------------------------------------------------- |
| `plugin` | Plugin to install (catalog name, repo, requirement, or git URL) |

## `sase plugin list`

```text
usage: sase plugin list [-h] [-j] [-o] [-r] [-A] [-v]
```

List every known SASE plugin in two clearly-labeled sections — built-in (official `sase-org`) first, then community (third-party) — marking installed versions, latest available versions, and updates with `↑`. The footer shows cache age and the exact refresh command. Use `-o|--offline` to render from caches only.

Options:

| Option               | Description                                                               | Default |
| -------------------- | ------------------------------------------------------------------------- | ------- |
| `-A`, `--all-latest` | Fetch latest versions for every catalog entry, not just installed plugins | `false` |
| `-h`, `--help`       | show this help message and exit                                           | —       |
| `-j`, `--json`       | Emit machine-readable JSON                                                | `false` |
| `-o`, `--offline`    | Use caches only; never check GitHub or PyPI                               | `false` |
| `-r`, `--refresh`    | Bypass caches and refetch the catalog and latest versions                 | `false` |
| `-v`, `--verbose`    | Show extra columns: stars, last updated, and the full topic list          | `false` |

## `sase plugin show`

```text
usage: sase plugin show [-h] [-j] [-o] [-r] <plugin_name>
```

Show a detailed view of one SASE plugin: description, installed status and entry points, latest available version, repository, homepage, topics, stars, last update, and license. Community plugins lead with a prominent third-party warning. <plugin_name> matches the short name (`github`), the repo (`sase-github`), or the full name (`sase-org/sase-github`); an unknown name prints `did you mean…?` suggestions and exits non-zero. Use `-o|--offline` to render from caches only.

Options:

| Option            | Description                                               | Default |
| ----------------- | --------------------------------------------------------- | ------- |
| `-h`, `--help`    | show this help message and exit                           | —       |
| `-j`, `--json`    | Emit machine-readable JSON                                | `false` |
| `-o`, `--offline` | Use caches only; never check GitHub or PyPI               | `false` |
| `-r`, `--refresh` | Bypass caches and refetch the catalog and latest versions | `false` |

Arguments:

| Argument      | Description                                                     |
| ------------- | --------------------------------------------------------------- |
| `plugin_name` | Plugin name to show (short name, repo, or owner/repo full name) |

## `sase plugin uninstall`

```text
usage: sase plugin uninstall [-h] [-j] [-n] [-r] [-Q PATH] [-R PATH] <plugin>
```

Uninstall a SASE plugin from the *same* uv tool environment as sase, so its entry points are no longer discovered the next time sase runs. The <plugin> name is resolved straight from sase's uv receipt (`github` -> `sase-github`, repo and `owner/repo` full names also work), so an installed plugin — even a community one absent from the catalog — resolves without a network fetch. Like `sase plugin install`, this only works when sase was installed via `uv tool install sase`. It reconstructs uv's `--with` set from sase's receipt with the target omitted, so sase core and every other plugin are preserved; editable/dev installs are kept too. When run from a pip/pipx install or a dev checkout's virtualenv, it fails fast with an actionable message instead of touching your environment. Uninstalling a plugin that is not installed is a no-op success. Use `-n|--dry-run` to preview the exact uv command and resulting plugin set without changing anything. A successful uninstall that changes packages restarts the scheduler so background automation unloads the removed plugin code.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`                | Show the planned uv command and plugin set without running it                                                           | `false` |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                   | Emit machine-readable JSON                                                                                              | `false` |
| `-r`, `--refresh`                | Bypass the cache and refetch the catalog from GitHub                                                                    | `false` |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description                                                       |
| -------- | ----------------------------------------------------------------- |
| `plugin` | Plugin to uninstall (catalog name, repo, or owner/repo full name) |

## `sase plugin update`

```text
usage: sase plugin update [-h] [-a] [-j] [-n] [-r] [-Q PATH] [-R PATH]
                          [<plugin>]
```

Upgrade a single installed SASE plugin to its latest version while leaving sase core and every other plugin pinned. Pass `-a|--all` to upgrade every installed plugin in one shot (still leaving sase core pinned). To upgrade sase core together with all plugins, use `sase update` instead. Like `sase plugin install`, this only works when sase was installed via `uv tool install sase`, reconstructs uv's `--with` set from sase's receipt (preserving editable/dev installs), and fails fast with an actionable message otherwise. A plugin that is not installed yields a hint to run `sase plugin install <plugin>` instead. Use `-n|--dry-run` to preview the exact uv command without changing anything. A successful update that changes packages restarts the scheduler so background automation loads the updated plugin code.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a`, `--all`                    | Upgrade every installed plugin (sase core stays pinned)                                                                 | `false` |
| `-n`, `--dry-run`                | Show the planned uv command without running it                                                                          | `false` |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                   | Emit machine-readable JSON                                                                                              | `false` |
| `-r`, `--refresh`                | Bypass the cache and refetch the catalog from GitHub                                                                    | `false` |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `plugin` | Plugin to upgrade (catalog name or repo); omit with -a\|--all |

Related: [CLI command groups](index.md).
