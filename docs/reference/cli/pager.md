---
title: "sase pager"
description: "Open artifact references, file paths, or stdin as one navigable SASE pager document."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase pager

Read refs, paths, or stdin in the SASE link-traversing pager

Reference for `sase pager`. Run `sase pager --help` for the exact output on this checkout.

```text
usage: sase pager [-h] [-c {auto,always,never}] [-l {auto,never}] [-p]
                  [-s ALIAS] [-t TITLE] [-w WIDTH]
                  [REF|PATH ...]
```

Open artifact references, file paths, or stdin as one navigable SASE pager document. With redirected stdout, --plain, or no controlling terminal, the command writes plain text instead of starting the Textual app.

Options:

| Option                       | Description                                                                                                                                                               | Default |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-c COLOR`, `--color COLOR`  | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                                                 | `auto`  |
| `-h`, `--help`               | show this help message and exit                                                                                                                                           | —       |
| `-l LINKS`, `--links LINKS`  | Link scanning and painted keys: auto or never (default: auto) (choices: `auto`, `never`)                                                                                  | `auto`  |
| `-p`, `--plain`              | Dump plain text without starting the pager                                                                                                                                | `false` |
| `-s ALIAS`, `--syntax ALIAS` | Highlighting language: auto, none, or a Pygments alias (default: auto; config pager.syntax). Invalid aliases fail before stdin is read; text/plain skip the language chip | —       |
| `-t TITLE`, `--title TITLE`  | Document title for stdin input                                                                                                                                            | —       |
| `-w WIDTH`, `--wrap WIDTH`   | Wrap prose at WIDTH columns; accepts 'auto', 'none', or 0 (default: 88)                                                                                                   | `88`    |

Arguments:

| Argument | Description                                                                                   |
| -------- | --------------------------------------------------------------------------------------------- |
| `inputs` | Artifact reference or file path to add as a section; omit or pass '-' by itself to read stdin |

Related: [CLI command groups](index.md).
