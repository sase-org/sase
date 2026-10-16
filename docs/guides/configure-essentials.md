---
title: Configure the essentials
description:
  Set the handful of configuration values most setups change, and find the rest.
---

# Configure the essentials

This guide sets the values most setups change and shows where every other setting lives.
It assumes SASE is installed; defaults work until you have a reason to change them, so
read first and edit only what you need.

## Before you start

You need to know where configuration lives. The base file is `~/.config/sase/sase.yml`;
overlay files matching `~/.config/sase/sase_*.yml` merge on top of it, and a
project-local `sase/sase.yml` usually takes highest priority. Check for drift without
writing anything:

```bash
sase init --check
```

## 1. Set the default model

Launches without an explicit request use
[`llm_provider.default_model`](../reference/config/llm-provider.md#llm_provider-default_model)
(`@large` unless changed). Set it when most of your work wants a different level:

```yaml
llm_provider:
  default_model: "@medium"
```

See [Choose providers and models](choose-providers-models.md) for the alias levels and
how to check provider readiness.

## 2. Keep automatic recovery on

Agents interrupted by a live update restart automatically while
[`agent_auto_restart.enabled`](../reference/config/agents.md#agent_auto_restart-enabled)
is true. Leave it on unless you are debugging the recovery itself:

```yaml
agent_auto_restart:
  enabled: true
```

## 3. Size the runner capacity

[`max_running_agents`](../reference/config/agents.md#max_running_agents) caps how many
agents run at once (default `10`). Raise it on a large machine, lower it when agents
compete with other work:

```yaml
max_running_agents: 10
```

Lowering the cap never kills running agents; new work simply waits until capacity frees
up. See [Unstick a queued agent](unstick-queued-agent.md) when runs wait longer than
expected.

## 4. Confirm the result

Validate the configuration layer and re-check initialization drift:

```bash
sase doctor -C config
sase init --check
```

Both report clean when the values parse and nothing needs to run.

## If it goes wrong

`sase doctor -C config` names the layer and key at fault; fix that value and re-run the
two confirmation commands. For failures outside configuration, start with
[Diagnose problems with sase doctor](diagnose-with-doctor.md).

## Related

- [Configuration keys](../reference/config/index.md) — every key, type, default, and
  allowed value.
- [Configuration files and behavior](../reference/config/files-and-merging.md#config-file-location)
  — file layout and merge order.
- [sase doctor](../reference/cli/doctor.md) — the diagnostic command and its checks.
