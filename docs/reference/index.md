---
title: Reference
description: Look up exact SASE facts here, generated from code where possible.
---

# Reference

Look up exact flags, keys, defaults, and behaviors here. Reference teaches no workflow;
it names the thing so tutorials and guides can link to the facts.

## CLI

- [CLI reference](../cli.md) — command index and routing
- [CLI command groups](cli/index.md) — generated flags, options, and subcommands
- [Query language](../query_language.md) — filtering runs and beads
- [Named tools](../tool.md) — declaring and running tools

## Configuration

- [Configuration](../configuration.md) — every setting and default

## TUI

- [sase's TUI](../ace.md) — tabs, pickers, panes
- [SASE Pager](../pager.md) — paging long output

## Macros and workflows

- [Macros](../macros.md) — reusable prompts and directives
- [Workflows](../workflow_spec.md) — multi-agent workflow files

## Work units

- [Patches](../change_spec.md) — local units of change
- [Beads](../beads.md) — git-native issue tracking
- [Goals](../goals.md) — durable outcome records

## Agents and workspaces

- [Agent providers](../agent_providers.md) — CLIs SASE can drive
- [Agent sessions](../agent_sessions.md) — runs and their turns
- [Agent hood sync](../agents_sidecar.md) — sharing agents across checkouts
- [Agent attachments](../agent_images.md) — images agents can see
- [Agent auto-restart](agent-auto-restart.md) — update-skew recovery and limits
- [Agent revive log](agent-revive-log.md) — revival audit records
- [Runner slots](runner-slots.md) — capacity admission and queued agents
- [Instruction bundles](../instruction_bundles.md) — generated agent instructions
- [Mentors](../mentors.md) — automated code review
- [Remote dispatch](../remote_dispatch.md) — running agents elsewhere
- [Workspaces](../workspace.md) — numbered clones agents claim

## Automation

- [Scheduler and service host](../axe.md) — recurring and hosted work
- [Monitors](../monitors.md) — long commands outliving agents
- [Notifications](../notifications.md) — staying informed
- [Sudo requests](../sudo.md) — approving privileged commands

## Providers

- [LLM providers](../llms.md) — models, tiers, aliases
- [VCS providers](../vcs.md) — git and changer hosting

## Memory

- [Memory](../memory.md) — durable agent context
- [Memory history](../memory_history.md) — how memory changed

## Prompts and artifacts

- [Prompt history](../prompt.md) — replaying past prompts
- [Artifact references](../artifact_references.md) — citing records in prompts
- [Artifact links](../artifact_links.md) — typed links between records

## Integrations

- [Editor integration](../editor.md) — Neovim and completion support
- [Integration APIs](../integrations.md) — building on SASE
- [Plugins](../plugins.md) — extending SASE
- [Mobile gateway](../mobile_gateway.md) — driving agents by phone

## File formats

- [ProjectSpec](../project_spec.md) — project file layout and registry

## Migration

- [Content layout migration](../content_layout.md) — the 2026 docs move

## Glossary and decisions

- [Glossary](glossary.md) — every SASE term, generated
- [Design decisions](design-decisions.md) — why SASE works this way
