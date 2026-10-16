---
title: "sase stitch"
description: "Dispatch a commit, proposal, or pull request, or show the cross-repository stitch timeline for the primary repo and configured linked repos."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase stitch

Dispatch a commit, or show the cross-repository timeline

Aliases: `sase vcs`.

Reference for `sase stitch`. Run `sase stitch --help` for the exact output on this checkout.

```text
usage: sase stitch [-h] {create,list} ...
```

Dispatch a commit, proposal, or pull request, or show the cross-repository stitch timeline for the primary repo and configured linked repos. Sidecar history is available on request. `sase vcs` remains accepted as a legacy alias. With no subcommand, `sase stitch` defaults to `sase stitch list`.

Bare `sase stitch` defaults to `sase stitch list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                                                |
| -------------------- | ------------------------------------------------------ |
| `sase stitch create` | Dispatch a commit, proposal, or pull request           |
| `sase stitch list`   | Show a chronological, cross-repository stitch timeline |

## `sase stitch create`

```text
usage: sase stitch create [-h] [-m MESSAGE | -M MESSAGE_FILE] [-x PATH]
                          [-n NAME] [-b BUG_ID] [-B {close,keep}]
                          [-c CHECKOUT_TARGET] [-p PARENT]
                          [-s {wip,draft,ready}]
                          [-t {create_commit,create_proposal,create_pull_request,commit,propose,pr}]
                          [-r]
```

Dispatch a commit, proposal, or pull request through the configured VCS provider.

Options:

| Option                                                    | Description                                                                                                                                                   | Default  |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `-B {close,keep}`, `--bead-action {close,keep}`           | Explicit assigned-bead decision from agent context: 'keep' for intermediate work, 'close' after completing and verifying the bead (choices: `close`, `keep`)  | —        |
| `-b BUG_ID`, `--bug-id BUG_ID`                            | Bug ID to associate with the commit (overrides $SASE_BUG_ID)                                                                                                  | `0`      |
| `-c CHECKOUT_TARGET`, `--checkout-target CHECKOUT_TARGET` | Branch point for create_pull_request (default: HEAD~1)                                                                                                        | `HEAD~1` |
| `-x PATH`, `--exclude PATH`                               | Repo-relative file or directory to leave out of the commit (repeatable)                                                                                       | —        |
| `-h`, `--help`                                            | show this help message and exit                                                                                                                               | —        |
| `-m MESSAGE`, `--message MESSAGE`                         | Commit message string                                                                                                                                         | —        |
| `-M MESSAGE_FILE`, `--message-file MESSAGE_FILE`          | Path to file containing the commit message / PR description                                                                                                   | —        |
| `-n NAME`, `--name NAME`                                  | Branch/Patch name (required for create_pull_request)                                                                                                          | —        |
| `-p PARENT`, `--parent PARENT`                            | Parent Patch name (overrides auto-detection from current branch)                                                                                              | —        |
| `-r`, `--resume`                                          | Resume a previously-checkpointed commit after manual conflict resolution. When set, -m/-M/-x and other commit args are ignored.                               | `false`  |
| `-s STATUS`, `--status STATUS`                            | Patch status (overrides $SASE_PR_STATUS; default: draft) (choices: `draft`, `ready`, `wip`)                                                                   | —        |
| `-t METHOD`, `--type METHOD`                              | Commit method (default: $SASE_COMMIT_METHOD or create_commit) (choices: `commit`, `create_commit`, `create_proposal`, `create_pull_request`, `pr`, `propose`) | —        |

## `sase stitch list`

```text
usage: sase stitch list [-h] [-a] [-A PATTERN] [-b REF]
                        [-c {auto,always,never}] [-o] [-F]
                        [-f {pretty,full,oneline,json}] [-n N]
                        [-m {hide,show,only}] [-N] [-T] [--origin ORIGIN]
                        [-r NAME] [-R] [-S] [-s DATE] [-u DATE]
```

Show a chronological, cross-repository stitch timeline across the primary repo and linked repos. Use --sdd to include all sidecar repository commits, and --all to merge repositories from every registered project.

Options:

| Option                                     | Description                                                                                                    | Default  |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------- | -------- |
| `-s DATE`, `--since DATE`, `--after DATE`  | Only commits at/after DATE                                                                                     | —        |
| `-a`, `--all`                              | Include repos from every registered enabled or disabled project                                                | `false`  |
| `-A PATTERN`, `--author PATTERN`           | Filter by author name/email substring (repeatable; ORed)                                                       | —        |
| `-u DATE`, `--until DATE`, `--before DATE` | Only commits at/before DATE                                                                                    | —        |
| `-c COLOR`, `--color COLOR`                | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                      | `auto`   |
| `-o`, `--current-only`                     | Only the current/primary repo (skip linked and sidecar repos)                                                  | `false`  |
| `-F`, `--fetch`                            | Fetch remote refs now, bypassing the short freshness cache                                                     | `false`  |
| `-f FORMAT`, `--format FORMAT`             | Output format: pretty, full, oneline, or json (default: pretty) (choices: `full`, `json`, `oneline`, `pretty`) | `pretty` |
| `-h`, `--help`                             | show this help message and exit                                                                                | —        |
| `-n N`, `--limit N`                        | Max commits in the merged timeline; 0 means unlimited (default: 40)                                            | `40`     |
| `-m MERGES`, `--merges MERGES`             | Merge-commit visibility: hide, show, or only (default: hide) (choices: `hide`, `only`, `show`)                 | `hide`   |
| `-N`, `--no-fetch`                         | Skip remote fetch; compare against existing remote-tracking refs                                               | `false`  |
| `-T`, `--no-tags`                          | Hide trailing SASE_* commit tags                                                                               | `true`   |
| `--origin ORIGIN`                          | Filter by commit origin: stitch, auto, or manual (repeatable; ORed) (choices: `auto`, `manual`, `stitch`)      | —        |
| `-b REF`, `--branch REF`, `--ref REF`      | Compare against REF on origin instead of the resolved remote ref                                               | —        |
| `-r NAME`, `--repo NAME`                   | Restrict to a repo label or unambiguous source name (repeatable)                                               | —        |
| `-R`, `--reverse`                          | Show the selected commits oldest-first                                                                         | `false`  |
| `-S`, `--sdd`                              | Include commits from sidecar repositories                                                                      | `false`  |

Related: [CLI command groups](index.md).
