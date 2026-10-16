---
title: CLI behavior notes
description: Root command behavior and links to CLI command and subsystem references.
---

# CLI behavior notes

## CLI Flags

Command groups that default to a nested `list` command still parse flags at the
subcommand level. Use the explicit `list` form when passing list options, such as
`sase notify list -j`, `sase agent hold list -j`, or `sase workspace list --json`. See
the [daily operation guide](agents/agent-launches.md#daily-operation) for which groups
delegate to `list`.

## `sase (global)`

These options are recognized only in the leading run of option tokens, before the first
subcommand. They do not steal `-f`/`-F` or `-p` from commands such as
`sase bead list -f json` or `sase completion candidates -p PROJECT`.

<a id="cli-options"></a> Moved to [CLI command groups](cli/index.md#global-options).

<a id="sase-tui"></a> Moved to [sase tui](cli/tui.md#sase-tui).

<a id="sase-screenshot"></a> Moved to
[Launching the TUI](tui/launching.md#sase-screenshot).

<a id="sase-tmux-agent"></a> Moved to
[Launch Control](tui/launch-control.md#sase-tmux-agent).

<a id="sase-service"></a> Moved to
[Service host initialization](agents/service-host.md#sase-service).

<a id="sase-axe"></a> Moved to [Scheduler](automation/scheduler.md#sase-axe).

<a id="sase-axe-status"></a> Moved to
[Scheduler](automation/scheduler.md#sase-axe-status).

<a id="sase-axe-start"></a> Moved to
[Scheduler](automation/scheduler.md#sase-axe-start).

<a id="sase-axe-stop"></a> Moved to [Scheduler](automation/scheduler.md#sase-axe-stop).

<a id="sase-axe-restart"></a> Moved to
[Scheduler](automation/scheduler.md#sase-axe-restart).

<a id="sase-axe-maintenance"></a> Moved to
[Scheduler](automation/scheduler.md#sase-axe-maintenance).

<a id="sase-axe-job"></a> Moved to [Scheduler](automation/scheduler.md#sase-axe-job).

<a id="sase-axe-routine"></a> Moved to
[Scheduler](automation/scheduler.md#sase-axe-routine).

<a id="sase-stitch-create"></a> Moved to
[Commit workflows](vcs/commit-workflows.md#sase-stitch-create).

<a id="sase-stitch"></a> Moved to
[Commit workflows](vcs/commit-workflows.md#sase-stitch).

<a id="sase-patch-search"></a> Moved to
[Patch Format Documentation](work-units/patches.md#sase-patch-search).

<a id="sase-patch-migrate-extension"></a> Moved to
[Patch Format Documentation](work-units/patches.md#sase-patch-migrate-extension).

<a id="sase-project"></a> Moved to
[ProjectSpec Format](work-units/project-spec.md#sase-project).

<a id="sase-repo"></a> Moved to [Workspaces](agents/workspaces.md#sase-repo).

<a id="sase-revert"></a> Moved to [sase revert](cli/revert.md#sase-revert).

<a id="sase-restore"></a> Moved to
[Patch Format Documentation](work-units/patches.md#sase-restore).

<a id="sase-run"></a> Moved to
[Agent-initiated launches](agents/agent-launches.md#sase-run).

<a id="sase-repro"></a> Moved to [Agent workflows](tui/agent-workflows.md#sase-repro).

<a id="sase-macro"></a> Moved to
[Macro CLI and editor support](macros/cli-and-editor.md#sase-macro).

<a id="sase-macro-expand"></a> Moved to [sase macro](cli/macro.md).

<a id="sase-macro-explain"></a> Moved to [sase macro](cli/macro.md).

<a id="sase-macro-list"></a> Moved to
[Macro CLI and editor support](macros/cli-and-editor.md#sase-macro-list).

<a id="sase-macro-show"></a> Moved to [sase macro](cli/macro.md).

<a id="sase-macro-graph"></a> Moved to [sase macro](cli/macro.md).

<a id="sase-macro-catalog"></a> Moved to [sase macro](cli/macro.md).

<a id="sase-macro-types"></a> Moved to
[Macro CLI and editor support](macros/cli-and-editor.md#sase-macro-types).

<a id="sase-init"></a> Moved to [Initialization](agents/initialization.md#sase-init).

<a id="sase-machine"></a> Moved to
[Machine initialization](agents/machine-initialization.md#sase-machine).

<a id="sase-instructions"></a> Moved to
[Instruction bundles](memory/instruction-bundles.md#sase-instructions).

<a id="sase-memory"></a> Moved to [Memory](memory/memory.md#sase-memory).

<a id="sase-memory-init"></a> Moved to
[Memory initialization](agents/memory-initialization.md#sase-memory-init).

<a id="sase-init-repo"></a> Moved to
[Initialization](agents/initialization.md#sase-init-repo).

<a id="sase-skill"></a> Moved to
[Instruction bundles](memory/instruction-bundles.md#sase-skill).

<a id="sase-repo-init"></a> Moved to [Workspaces](agents/workspaces.md#sase-repo-init).

<a id="sase-tool"></a> Moved to
[Named tools and ToolRuns](automation/tools.md#sase-tool).

<a id="sase-disk"></a> Moved to [SASE disk cleanup](disk-cleanup.md#sase-disk).

<a id="sase-workspace"></a> Moved to [Workspaces](agents/workspaces.md#sase-workspace).

<a id="sase-bead"></a> <a id="sase-bead-create"></a> <a id="sase-bead-list"></a>
<a id="sase-bead-search"></a> <a id="sase-bead-task-type"></a>
<a id="sase-bead-epic-symbols"></a> <a id="sase-bead-read"></a>
<a id="sase-bead-touched"></a> <a id="sase-bead-show"></a> <a id="sase-bead-open"></a>
<a id="sase-bead-update"></a> <a id="sase-bead-close"></a> <a id="sase-bead-rm"></a>
<a id="sase-bead-note"></a> <a id="sase-bead-dep"></a> <a id="sase-bead-sync"></a>
<a id="sase-bead-work"></a> Moved to [Bead CLI](work-units/bead-cli.md#sase-bead).

<a id="sdd-repository-and-plan-commands"></a> Moved to
[Plan commands](work-units/plan-cli.md#sdd-repository-and-plan-commands).

<a id="sase-validate"></a> Moved to
[Diagnostics and support reports](diagnostics.md#sase-validate).

<a id="sase-doctor"></a> Moved to
[Diagnostics and support reports](diagnostics.md#sase-doctor).

<a id="sase-flag"></a> Moved to
[Feature flag configuration](config/feature-flags.md#sase-flag).

<a id="sase-file-hook"></a> Moved to
[Prompt and tool configuration](config/prompts-and-tools.md#sase-file-hook).

<a id="sase-version"></a> Moved to
[Diagnostics and support reports](diagnostics.md#sase-version).

<a id="sase-var"></a> Moved to
[Agent output variables](agents/output-variables.md#sase-var).

<a id="sase-telemetry"></a> Moved to
[Diagnostics and support reports](diagnostics.md#sase-telemetry).

<a id="sase-logs"></a> Moved to
[Diagnostics and support reports](diagnostics.md#sase-logs).

<a id="sase-editor"></a> Moved to
[Editor Integration](integrations/editor.md#sase-editor).

<a id="sase-file"></a> Moved to [Artifact References](artifact-references.md#sase-file).

<a id="sase-file-history"></a> Moved to
[Artifact References](artifact-references.md#sase-file-history).

<a id="sase-gate"></a> Moved to
[Command-backed interaction gates](automation/notification-gates.md#sase-gate).

<a id="sase-sudo"></a> Moved to [Sudo Requests](automation/sudo.md#sase-sudo).

<a id="sase-lsp"></a> Moved to [Editor Integration](integrations/editor.md#sase-lsp).

<a id="sase-path"></a> Moved to [sase path](cli/path.md#sase-path).

<a id="sase-usage"></a> Moved to
[Diagnostics and support reports](diagnostics.md#sase-usage).

<a id="sase-notify"></a> Moved to
[Notification CLI](automation/notification-cli.md#sase-notify).

<a id="sase-plan"></a> Moved to [Plan commands](work-units/plan-cli.md#sase-plan).

<a id="sase-artifact"></a> Moved to
[Artifact References](artifact-references.md#sase-artifact).

<a id="sase-questions"></a> Moved to [sase questions](cli/questions.md#sase-questions).

<a id="sase-agent"></a> Moved to [Agent sessions](agents/agent-sessions.md#sase-agent).

<a id="sase-agent-cli"></a> Moved to
[Installing & Authenticating Agent Providers](providers/agent-clis.md#sase-agent-cli).

<a id="sase-chat"></a> Moved to
[Prompt History and Draft Recovery](prompt-history.md#sase-chat).

This page is a command index for the top-level `sase` CLI. It is meant for discovery and
routing: use it to find the surface that owns a workflow, then follow the links to the
detailed command, flag, or subsystem reference.

Compact `sase --help` lists only the common commands. Use `sase --full-help` (or `-H`)
to print every command, then this page to route from a command to its owner guide. This
page is a discovery index, not a dump of every flag. Compact help's one-line `agent`
blurb says "active and recent"; default `sase agent list` (and bare `sase agent`) is
running-only — add `-a` for recent DONE/FAILED.

When a plugin mounts commands, compact help adds a **Plugin commands** group after the
common commands. Each row is the command name, its one-line summary, and the
distribution that provides it. The group is left out when nothing is mounted. A plugin
that fails to load can still appear there with its distribution's summary, so being
listed does not prove that it can run. Load failures, name collisions, and shadowed
names appear on `sase --full-help` instead, each marked `⚠`, and that footer closes with
a pointer to `sase plugin list` and the Updates tab. See
[Command plugins](integrations/plugins-commands.md#command-plugins-1).

Current memory commands inspect, read, initialize, and audit memory; sase's TUI Memory
panel can add, edit, and delete flat notes and add or delete strands, while existing
strand bodies and web descriptors are edited in `$EDITOR`. Agents must route all
memory-file changes through `/sase_memory_write` first.

For exhaustive flags, options, and subcommands, see the generated
[CLI command groups](cli/index.md).

The root `sase` command accepts leading global options before the subcommand:
`-f/--enable-feature` and `-F/--disable-feature` force a registered feature flag on or
off for that invocation and its children, and `-p/--print-command` prints a
shell-quoted, copyable `sase ...` header to stderr before running the command. The
printed invocation omits only the root print switch. See the
[configuration reference](config/feature-flags.md#featureflags).
