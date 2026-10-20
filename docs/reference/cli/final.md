---
title: "sase final"
description: "Inspect host-owned finalizer instances, provider provenance, and the current turn's declaration obligations."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase final

Inspect configured finalizers and declarations

Reference for `sase final`. Run `sase final --help` for the exact output on this checkout.

```text
usage: sase final [-h]
                  {context,defer,doctor,list,prepare,show,status,submit} ...
```

Inspect host-owned finalizer instances, provider provenance, and the current turn's declaration obligations. With no subcommand, `sase final` defaults to `sase final list`.

Bare `sase final` defaults to `sase final list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                                                            |
| -------------------- | ------------------------------------------------------------------ |
| `sase final context` | Publish and show the current turn's finalizer context              |
| `sase final defer`   | Declare a rare, host-adjudicated deferral for one dirty repository |
| `sase final doctor`  | Diagnose finalizer configuration and providers                     |
| `sase final list`    | List effective finalizer instances                                 |
| `sase final prepare` | Seal a single-use host-completion intent without submitting        |
| `sase final show`    | Show one finalizer instance                                        |
| `sase final status`  | Show the finalizer run view for one agent                          |
| `sase final submit`  | Validate and save one finalizer declaration manifest               |

## `sase final context`

```text
usage: sase final context [-h] [-f {pretty,json}]
```

Recompute selected finalizers, triggers, and opaque repository obligations for the active turn, validate the context through the shared protocol, publish final_context.json, and print it.

Options:

| Option                         | Description                               | Default  |
| ------------------------------ | ----------------------------------------- | -------- |
| `-f FORMAT`, `--format FORMAT` | Output format (choices: `json`, `pretty`) | `pretty` |
| `-h`, `--help`                 | show this help message and exit           | —        |

## `sase final defer`

```text
usage: sase final defer [-h] <repo-id> <reason> [-p <path>]
```

Defer one repository obligation instead of committing it. Deferral is rare: prefer an authored commit message through `sase final submit`. The host adjudicates every deferral against this run's own evidence before accepting it, so an unfounded deferral is rejected as a repairable error instead of failing the run. An accepted deferral leaves the repository's tree dirty by design and completes the run instead of failing it. Only supports a turn with exactly one finalizer instance and one repository requiring a decision; use `sase final context -f json` and `sase final submit` for anything wider.

Options:

| Option                        | Description                                                                                      | Default |
| ----------------------------- | ------------------------------------------------------------------------------------------------ | ------- |
| `-h`, `--help`                | show this help message and exit                                                                  | —       |
| `-p <path>`, `--paths <path>` | Path within the repository to defer (repeatable); defaults to every dirty path in the repository | —       |

Arguments:

| Argument  | Description                                                                                   |
| --------- | --------------------------------------------------------------------------------------------- |
| `repo_id` | Repository obligation ID, from `sase final context`                                           |
| `reason`  | Typed deferral reason: protected_paths, foreign_work, unsafe_content, belongs_to_another_turn |

## `sase final doctor`

```text
usage: sase final doctor [-h] [-f {pretty,json}]
```

Options:

| Option                         | Description                               | Default  |
| ------------------------------ | ----------------------------------------- | -------- |
| `-f FORMAT`, `--format FORMAT` | Output format (choices: `json`, `pretty`) | `pretty` |
| `-h`, `--help`                 | show this help message and exit           | —        |

## `sase final list`

```text
usage: sase final list [-h] [-f {pretty,json}]
```

Options:

| Option                         | Description                               | Default  |
| ------------------------------ | ----------------------------------------- | -------- |
| `-f FORMAT`, `--format FORMAT` | Output format (choices: `json`, `pretty`) | `pretty` |
| `-h`, `--help`                 | show this help message and exit           | —        |

## `sase final prepare`

```text
usage: sase final prepare [-h] <manifest-file|-> [-j]
```

Validate a versioned completion wrapper against the current host-issued finalizer context, observe opened repositories, and store a host-sealed single-use intent. Prints the immutable reference and a readable preview. Does not submit, commit, publish, or end the turn. The wrapper accepts an optional `accept: pass|no-new` policy (default `pass`); `no-new` is an explicit opt-in that completes a failed verification only with a covering verdict receipt. Prepare refuses a verification command whose project tool catalog entry lacks `stages: run_silent`, and re-sealing an unchanged tree whose passing verification was already refused host completion.

Options:

| Option         | Description                                          | Default |
| -------------- | ---------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                      | —       |
| `-j`, `--json` | Emit the sealed intent reference and preview as JSON | `false` |

Arguments:

| Argument   | Description                                        |
| ---------- | -------------------------------------------------- |
| `manifest` | JSON completion wrapper path, or '-' to read stdin |

## `sase final show`

```text
usage: sase final show [-h] instance [-f {pretty,json}]
```

Options:

| Option                         | Description                               | Default  |
| ------------------------------ | ----------------------------------------- | -------- |
| `-f FORMAT`, `--format FORMAT` | Output format (choices: `json`, `pretty`) | `pretty` |
| `-h`, `--help`                 | show this help message and exit           | —        |

Arguments:

| Argument   | Description           |
| ---------- | --------------------- |
| `instance` | Finalizer instance ID |

## `sase final status`

```text
usage: sase final status [-h] [<agent>] [-d <dir>] [-f {pretty,json}]
```

Project the finalizer run view for one agent turn and print it. The view reconciles the sealed plan, the controller progress journal, operation records, steps, and typed evidence through the shared projection, so this output agrees with the Agents tab's FINAL deck. Pretty output is colored in the shared state vocabulary; JSON output is the projection response verbatim.

Options:

| Option                              | Description                                                                     | Default  |
| ----------------------------------- | ------------------------------------------------------------------------------- | -------- |
| `-d <dir>`, `--artifacts-dir <dir>` | Read finalizer artifacts directly from <dir> instead of resolving an agent name | —        |
| `-f FORMAT`, `--format FORMAT`      | Output format (choices: `json`, `pretty`)                                       | `pretty` |
| `-h`, `--help`                      | show this help message and exit                                                 | —        |

Arguments:

| Argument | Description                                                                                               |
| -------- | --------------------------------------------------------------------------------------------------------- |
| `agent`  | Session, turn, or monitor-turn name. Defaults to the calling turn inside a SASE turn; required otherwise. |

## `sase final submit`

```text
usage: sase final submit [-h] <manifest-file|->
```

Read exactly one JSON manifest from a file or stdin, validate it against the latest finalizer context, append a bounded diagnostic attempt record, and replace final_submission.json only on success.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument   | Description                                          |
| ---------- | ---------------------------------------------------- |
| `manifest` | JSON declaration manifest path, or '-' to read stdin |

Related: [CLI command groups](index.md).
