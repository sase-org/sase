---
title: Hand a result to another agent
description: Give a follow-up agent a transcript or specific artifact as task context.
---

# Hand a result to another agent

Use an artifact reference to give a follow-up agent the result it needs to continue the
work.

## Before you start

You need the completed agent run and a specific next task. Decide whether the next agent
needs the earlier conversation, a file, a Patch, or another recorded artifact.

## 1. Copy a reference to the result

On the Agents tab, focus the completed run and press `a` to open its artifacts. Select
the result, press `%` to open the **Copy as…** palette, and choose its prompt-reference
form. For the whole agent conversation, use an agent reference such as `@agent:<name>`;
replace `<name>` with the selected run's name.

## 2. Put the reference in a focused prompt

Start a new agent prompt and paste the reference. State what the next agent should do
with that context, which files or behavior it owns, and how to confirm the result. For
example:

```text
Use @agent:<name> as context. Fix the remaining issue it identified in the parser,
add coverage for that case, and report the verification result.
```

For one particular file or Patch, cite that artifact directly instead of asking the next
agent to search the earlier transcript. References are expanded into the prompt when the
agent starts, so the next workspace does not depend on files being present in the
earlier workspace.

## 3. Review the follow-up

Watch the new run on the Agents tab. Check that it used the cited result and that its
changes answer the next task. Repeat with a new reference if another agent needs to
continue the work.

## If it goes wrong

If a reference does not resolve, check that its identifier is correct and that the new
prompt targets the project that owns the artifact. A local file reference must also be
allowed by the project's artifact-reference settings.

## Related

- [Artifact references](../artifact_references.md) — supported reference forms and
  resolution rules.
- [Agent artifacts](../ace.md#agent-artifacts) — artifact panel controls.
- [Agents, sessions, and workspaces](../concepts/agents.md) — agent runs and their
  workspaces.
