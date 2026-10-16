---
title: "CLI command groups"
description: "Generated CLI reference, one page per sase command group."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# CLI command groups

One page per `sase` command group, generated from the argparse tree.
Start here to find the group that owns a workflow.

SASE - Structured Agentic Software Engineering. Root options appear before the command; options after it belong to the selected command.

## Global options

| Option                                  | Description                                                                                                                                                                               | Default |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-F <flag>`, `--disable-feature <flag>` | Force a registered feature flag off for this invocation and every process it launches. Repeatable; overrides config layers, a saved machine preference, and inherited SASE_FEATURE_FLAGS. | —       |
| `-f <flag>`, `--enable-feature <flag>`  | Force a registered feature flag on for this invocation and every process it launches. Repeatable; overrides config layers, a saved machine preference, and inherited SASE_FEATURE_FLAGS.  | —       |
| `-H`, `--full-help`                     | show full command inventory and exit                                                                                                                                                      | —       |
| `-h`, `--help`                          | show compact help and exit                                                                                                                                                                | —       |
| `-p`, `--print-command`                 | Print a shell-quoted `sase ...` header to stderr before running; omit this switch, keep feature overrides, and skip tab completion.                                                       | —       |

Groups:

| Group                                  | Summary                                                                           |
| -------------------------------------- | --------------------------------------------------------------------------------- |
| [`sase agent`](agent.md)               | List, inspect, synchronize, and manage agents across projects                     |
| [`sase agent-cli`](agent-cli.md)       | Inspect and safely update supported coding-agent CLIs                             |
| [`sase artifact`](artifact.md)         | Create, discover, inspect, resolve, open, and repair artifacts                    |
| [`sase autonomy`](autonomy.md)         | Predict and inspect %auto gate decisions                                          |
| [`sase axe`](axe.md)                   | Alias of `sase scheduler`, plus the routine and job tree                          |
| [`sase bead`](bead.md)                 | Lightweight git-native issue tracking                                             |
| [`sase chat`](chat.md)                 | Discover and inspect prior agent chat transcripts                                 |
| [`sase comments`](comments.md)         | Preview mentor comments from JSON (reads from stdin or file)                      |
| [`sase completion`](completion.md)     | Generate and inspect shell completion for the sase CLI                            |
| [`sase config`](config.md)             | Inspect merged configuration, layers, and mentor profile matching                 |
| [`sase core`](core.md)                 | Inspect the required sase_core_rs Rust extension                                  |
| [`sase disk`](disk.md)                 | Inspect and reclaim SASE-owned disk usage                                         |
| [`sase doctor`](doctor.md)             | Run read-only SASE diagnostics for support                                        |
| [`sase editor`](editor.md)             | Run editor integration helpers                                                    |
| [`sase file`](file.md)                 | Filesystem completion helpers (consumed by editor integrations)                   |
| [`sase file-history`](file-history.md) | Inspect and modify the file-reference history                                     |
| [`sase file-hook`](file-hook.md)       | Inspect configured per-file repository hooks                                      |
| [`sase final`](final.md)               | Inspect configured finalizers and declarations                                    |
| [`sase flag`](flag.md)                 | Inspect, persist, and scaffold SASE feature flags                                 |
| [`sase gate`](gate.md)                 | Create or wait for durable command-backed gates                                   |
| [`sase goal`](goal.md)                 | Create, list, and reshape durable goal records                                    |
| [`sase init`](init.md)                 | Initialize SASE-managed resources                                                 |
| [`sase instructions`](instructions.md) | Inspect agent instruction documents                                               |
| [`sase launch`](launch.md)             | Resolve pending LaunchApproval requests                                           |
| [`sase logs`](logs.md)                 | Collect logs and runtime data for a date range into a pack directory              |
| [`sase lsp`](lsp.md)                   | Start the SASE macro language server                                              |
| [`sase machine`](machine.md)           | Manage enrolled remote machines                                                   |
| [`sase macro`](macro.md)               | Expand and visualize macro workflows                                              |
| [`sase memory`](memory.md)             | Inspect and initialize SASE memory context                                        |
| [`sase migrate`](migrate.md)           | Temporary offline migration kit for canonical-only cutover operations             |
| [`sase mobile`](mobile.md)             | Run mobile integration helpers                                                    |
| [`sase monitor`](monitor.md)           | Start, stop, list, and inspect monitored long-running commands                    |
| [`sase notify`](notify.md)             | Create or inspect notifications                                                   |
| [`sase pager`](pager.md)               | Read refs, paths, or stdin in the SASE link-traversing pager                      |
| [`sase patch`](patch.md)               | Inspect and maintain Patches                                                      |
| [`sase path`](path.md)                 | Print well-known sase paths (for editor integration)                              |
| [`sase pipe`](pipe.md)                 | Hand this agent's turn to the next agent session member and end this turn         |
| [`sase plan`](plan.md)                 | Review, approve, reject, propose, search, show, and validate implementation plans |
| [`sase plugin`](plugin.md)             | Discover SASE plugins from the GitHub catalog                                     |
| [`sase proc`](proc.md)                 | List, inspect, run, and kill durable procs                                        |
| [`sase project`](project.md)           | Inspect and mutate project lifecycle state                                        |
| [`sase prompt`](prompt.md)             | Inspect, search, and reuse previously submitted agent prompts                     |
| [`sase questions`](questions.md)       | Ask the user questions (used by /sase_questions skill)                            |
| [`sase repo`](repo.md)                 | Initialize, inspect, resolve, and open repositories                               |
| [`sase repro`](repro.md)               | Capture and replay reproduction bundles                                           |
| [`sase restore`](restore.md)           | Restore a reverted Patch by re-applying its diff and creating a new PR            |
| [`sase revert`](revert.md)             | Revert a Patch by pruning its PR and archiving the diff                           |
| [`sase revive-log`](revive-log.md)     | Show recent agent revive attempts from the audit log                              |
| [`sase run`](run.md)                   | Launch a detached background agent from a prompt or workflow                      |
| [`sase scheduler`](scheduler.md)       | Control the SASE scheduler                                                        |
| [`sase screenshot`](screenshot.md)     | Capture a PNG of a real live SASE TUI                                             |
| [`sase service`](service.md)           | Manage the per-machine SASE service host                                          |
| [`sase skill`](skill.md)               | Inspect and initialize generated SASE skills                                      |
| [`sase snippet`](snippet.md)           | Add, delete, list, and show SASE snippets                                         |
| [`sase stitch`](stitch.md)             | Dispatch a commit, or show the cross-repository timeline                          |
| [`sase sudo`](sudo.md)                 | Request, inspect, and answer typed sudo gates                                     |
| [`sase telemetry`](telemetry.md)       | Inspect locally persisted telemetry (defaults to list)                            |
| [`sase tmux-agent`](tmux-agent.md)     | Launch an interactive agent CLI in a new tmux window                              |
| [`sase tool`](tool.md)                 | List, run, and inspect project-owned named tools                                  |
| [`sase tui`](tui.md)                   | Open sase's TUI for agents, Patches, artifacts, notifications, and Services       |
| [`sase update`](update.md)             | Upgrade sase and all installed plugins together via uv                            |
| [`sase usage`](usage.md)               | Inspect and refresh cached LLM subscription usage                                 |
| [`sase validate`](validate.md)         | Run SASE initialization and SDD validation checks                                 |
| [`sase var`](var.md)                   | Inspect and set SASE agent output variables                                       |
| [`sase version`](version.md)           | Show the active SASE runtime package inventory                                    |
| [`sase workspace`](workspace.md)       | Inspect and manage managed workspace checkouts                                    |

Legacy aliases (`sase changespec`, `sase task`, `sase vcs`,
`sase artifact-file`) share their canonical group's page.
