---
title: Instruction bundles
description:
  How SASE instruction bundles are previewed and how providers report delivery behavior.
---

# Instruction bundles

This page describes the user-facing instruction bundle behavior and preview commands.

An instruction bundle collects the project, home, and SASE instructions for one agent
invocation. Its manifest records which sections were included and their digests, so you
can inspect the intended context and compare it with what a provider actually loaded.

The **root** is the agent SASE launches for a turn. A **native helper** is a subagent
that root starts through its provider's own tools. Helpers return results to their
parent; only the root submits SASE's final declaration.

Claude, Codex, Grok, and Muse deliver these bundles explicitly by default. Antigravity
(agy), Qwen, and OpenCode use their existing instruction paths, called **legacy
delivery** here. For root invocations with an artifacts directory, successful bundle
preparation records the bundle and manifest under `instructions/` and exposes
`SASE_INSTRUCTIONS_FILE` for the duration of the provider call, then restores its
previous value. Calls without an artifacts directory skip bundle preparation and use the
provider's native instruction path. The architecture is recorded as
[Instructions Are Rendered Per Invocation And Delivered By Adapters](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/instructions-per-invocation.md),
and the committed-file shape as
[The Committed AGENTS.md Stays A Readable Projection](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/readable-agents-md.md).
Rendering a bundle does not prove the provider loaded it: use `sase instructions verify`
to inspect observed delivery. If bundle preparation or transport fails, SASE attempts
native delivery and records the fallback; see
[Delivery](../../contribute/instruction-bundle-internals.md#delivery) and
[Fallback and notifications](../../contribute/instruction-bundle-internals.md#fallback-and-notifications).

See also
[Verifying instruction delivery](../providers/agent-clis.md#verifying-instruction-delivery).

## Provider behavior at a glance

| Provider                    | Root delivery                | Native helpers                                                                             |
| --------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------ |
| Claude                      | System-prompt file           | Separate helper bundle when the CLI supports it, with a guard against root-only operations |
| Codex                       | `developer_instructions`     | Inherit the root instructions; no separate helper bundle or mechanical guard               |
| Grok                        | `--rules`                    | No SASE helper delivery channel                                                            |
| Muse                        | Prompt prefix                | No SASE helper delivery channel                                                            |
| Antigravity, OpenCode, Qwen | Native `AGENTS.md` discovery | No explicit SASE helper bundle                                                             |

The four explicit adapters have default-enabled flags named
`claude_explicit_instructions`, `codex_explicit_instructions`,
`grok_explicit_instructions`, and `muse_explicit_instructions`. Disabling one restores
that provider's native delivery. This applies to SASE-managed invocations; a separately
opened interactive provider CLI uses its own discovery behavior. Provider-specific
details, including which native files remain visible, are in
[Agent Providers](../providers/agent-clis.md) and
[LLM Providers](../providers/index.md).

## Inspecting your instructions

Start with these read-only commands from your project checkout:

```bash
sase instructions list                 # Current instruction files and provider shims
sase instructions render -s            # Intended bundle sections from current sources
sase instructions show AGENT           # Archived bundle bytes and digest check
sase instructions readout --since 7d   # Handoff-aware declaration misses and memory reads
sase instructions verify -c            # Observed loads and manifest coverage
sase instructions verify -a AGENT      # Compare a recorded run's intent with its loads
```

Replace `AGENT` with a name from `sase agent list -a` (dismissed agents resolve the same
way as `sase agent show`). `sase instructions show AGENT` prints that run's recorded
bundle and checks the stored bytes against the manifest `sha256` (`bytes match`, or
`MISMATCH` with exit 1). Use `-l` to list every recorded invocation including helper
bundles, `-n NN` to pick a sequence, `-H` for the helper bundle, `-j` for the manifest
JSON, and `-s` for the section table. A missing `instructions/` directory or an unknown
name exits 2.

`render -a AGENT` instead uses that agent's facts to compile a fresh preview from
today's memory; its digest may differ from the historical bundle. `verify` looks at the
newest 20 runs per provider from the last 7 days unless you pass `-n` (maximum 200) or
`--since`, and includes dismissed runs. Delivery problems still exit 0. A bad `--since`
or `--until` value, or an unknown `-a` name, exits 2. Inspect the rows rather than
treating exit code 0 as proof that delivery is correct.

## Previewing bundles

`sase instructions render` previews the bundle for the current project and home sources
without delivering anything:

```bash
sase instructions render | head -40                      # what a root agent here would get
sase instructions render -f provider=codex -s            # sections instead of Markdown
sase instructions render -j                               # preview manifest as JSON
sase instructions render -p                               # parity against AGENTS.md files
```

Options (alphabetical): `-a/--agent NAME` starts from one agent's facts — the provider
from its run record, or its latest recorded manifest when one exists — while sources
stay the current project and home; stderr then reports whether the fresh bundle sha256
matches the agent's recorded bundle and lists changed section ids. `-f/--fact KEY=VALUE`
is repeatable and accepts comma-separated pairs; `mode=interactive|export` implies
`actor=interactive`, and a conflicting explicit actor is an error. `-j/--json` prints
the normalized manifest with `delivery.status: preview`. `-N/--no-cache` bypasses the
cache (`cache: bypass`). `-s/--sections` prints a Rich table of id, layer, status or
reason, lifecycle, bytes, `tokens_est`, and source. `-p/--parity` additionally checks
the bundle against the root and home `AGENTS.md` files: every core, reference, and web
path must map to an included or shadowed bundle section (`sase.md` maps to the
`pkg.sase.*` sections), every repository name must appear in `pkg.sase.repos`, and
exactly one included section must contain the `SASE Final Declaration` marker. The
parity table goes to stderr and the exit code is 1 on any gap; extra bundle sections
(for example `pkg.provider.*`) are reported as additions, not failures. The default
output is raw bundle Markdown on stdout plus one summary line on stderr (sha256 and
`common_digest` prefixes, section count, bytes, `tokens_est`, cache, and milliseconds).

## Related

- [Memory](index.md) — memory notes and history.
- [Agent CLIs](../providers/agent-clis.md) — provider-specific instruction delivery.

## `sase instructions`

With no subcommand, `sase instructions` defaults to `sase instructions list`.

<a id="cli-options-21"></a> Moved to
[sase instructions](instruction-bundles.md#sase-instructions).

## `sase skill`

With no subcommand, `sase skill` defaults to the read-only `sase skill list` dashboard.
It reports loaded skill sources, provider targets, and deployed-file drift without
writing files. `sase skill init` generates and deploys agent skill files from macro
sources marked with the `skill` field. Generated skill files begin with a
`sase skill use` directive so agent-side skill use can be audited and later summarized
with `sase skill log`, unless the source sets `log_skill_use: false`. See
[macros.md — Skill Field](../macros/fields.md#skill-field) for the skill-source contract
and provider targets. Existing files are skipped in non-interactive runs unless
`--force` is passed; interactive runs prompt before overwriting. Commit and land macro
template changes before deploying: writing chezmoi deploys are refused from dirty or
unmerged sources, and refused when they would move the destination off the source commit
recorded in the provenance manifest — see
[Commit Before Deploying](../agents/initialization.md#commit-before-deploying).
`sase init skills` is a compatibility alias for `sase skill init`.

<a id="cli-options-25"></a> Moved to [sase skill](instruction-bundles.md#sase-skill).
