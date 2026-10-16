---
title: Reference
description: Look up exact SASE facts here, generated from code where possible.
---

# Reference

Exact SASE facts; guides teach workflows.

## CLI

- [CLI reference](../cli.md) — command index and routing
- [CLI command groups](cli/index.md) — generated flags and subcommands
- [Query language](../query_language.md) — filtering runs and beads
- [Named tools](../tool.md) — declaring and running tools

## Configuration

- [Configuration keys](config/index.md) — generated key paths, types, defaults
- [Configuration files and behavior](config/files-and-merging.md#config-file-location) —
  file layout, merge order, runtime details

## TUI

- [TUI](tui/index.md)
- [sase's TUI](../ace.md)
- [SASE Admin Center](tui/admin-center.md)
- [TUI keymaps](tui/keymaps.md)
- [SASE Pager](../pager.md)

## Macros and workflows

- [Macros](../macros.md) — reusable prompts and directives
- [Directive catalog](macros/directives.md) — generated syntax and arguments
- [Macro discovery order](macros/discovery-order.md) — file-backed definitions by
  priority
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
- [Agent auto-restart](agent-auto-restart.md) — update-skew recovery, limits
- [Agent revive log](agent-revive-log.md) — revival audit records
- [Runner slots](runner-slots.md) — capacity admission, queued agents
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

- [Editor integration](../editor.md) — Neovim, completion support
- [Integration APIs](../contribute/integration-apis.md) — building on SASE
- [Plugins](../plugins.md) — extending SASE
- [Mobile gateway](../mobile_gateway.md) — driving agents by phone

## File formats

- [ProjectSpec](../project_spec.md) — project file layout, registry

## Content layout and upgrading

- [Content layout](content-layout.md) — canonical paths
- [Upgrading](upgrading/index.md) — upgrade notes

## Glossary and decisions

- [Glossary](glossary.md) — every SASE term, generated
- [Design decisions](design-decisions.md) — why SASE works this way
