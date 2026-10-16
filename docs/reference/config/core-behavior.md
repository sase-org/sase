---
title: "Core configuration behavior"
description:
  "Runtime behavior for core identity, managed instructions, and machine settings."
---

# Core configuration behavior

Runtime behavior for core identity, managed instructions, and machine settings.

## Configuration Sections

The generated [configuration reference](index.md) owns key paths, types, defaults,
allowed values, and schema descriptions. The sections below retain file, merge, and
runtime behavior that the schema cannot express.

<a id="memoryh1title"></a> Moved to
[Core configuration behavior](core-behavior.md#memoryh1title).
<a id="generated-templates"></a> Moved to
[Core configuration behavior](core-behavior.md#generated-templates).
<a id="issasemanaged"></a> Moved to
[Core configuration behavior](core-behavior.md#issasemanaged). <a id="id"></a> Moved to
[Core configuration behavior](core-behavior.md#id). <a id="machinename-deprecated"></a>
Moved to [Core configuration behavior](core-behavior.md#machinename-deprecated).
<a id="ace"></a> <a id="aceartifactfileviewer"></a> <a id="aceartifacts"></a>
<a id="aceartifactsstitches"></a> <a id="aceaxedescriptionexpanded"></a>
<a id="acecurrentproject"></a> <a id="acetribes"></a> <a id="acenotificationtabs"></a>
<a id="acenotificationindicatormaxcounts"></a> <a id="acepagesize"></a>
<a id="acetoolcalls"></a> <a id="aceupdates"></a> Moved to
[ACE configuration behavior](ace-behavior.md#ace). <a id="artifacts"></a> Moved to
[Artifact configuration](artifacts.md#artifacts). <a id="artifactrefs"></a> Moved to
[Artifact configuration](artifacts.md#artifactrefs). <a id="llmprovider"></a>
<a id="llmproviderusagelimit"></a> <a id="llmproviderusagemetrics"></a>
<a id="llmprovidercontinuationbudget"></a> <a id="llmproviderretry"></a> Moved to
[LLM provider behavior configuration](llm-provider-behavior.md#llmprovider).
<a id="finalizers"></a> <a id="commitmessage"></a> Moved to
[Finalizer configuration](finalizers.md#finalizers). <a id="monitor"></a> Moved to
[Monitor configuration](monitor-behavior.md#monitor). <a id="repos"></a>
<a id="external-repositories"></a> Moved to
[Repository configuration behavior](repositories-behavior.md#repos).
<a id="dispatch"></a> Moved to
[Repository configuration behavior](repositories-behavior.md#dispatch).
<a id="vcsprovider"></a> Moved to
[Repository configuration behavior](repositories-behavior.md#vcsprovider).
<a id="vcsrepocompletion"></a> Moved to
[Repository configuration behavior](repositories-behavior.md#vcsrepocompletion).
<a id="vcsrefcompletion"></a> Moved to
[Repository configuration behavior](repositories-behavior.md#vcsrefcompletion).
<a id="axe"></a> Moved to [Scheduler configuration behavior](scheduler-behavior.md#axe).
<a id="filehooks"></a> Moved to
[Prompt and tool configuration](prompts-and-tools.md#filehooks). <a id="plugins"></a>
Moved to [Prompt and tool configuration](prompts-and-tools.md#plugins).
<a id="mentorprofiles"></a> Moved to
[Prompt and tool configuration](prompts-and-tools.md#mentorprofiles).
<a id="metahooks"></a> Moved to
[Prompt and tool configuration](prompts-and-tools.md#metahooks). <a id="macros"></a>
Moved to [Prompt and tool configuration](prompts-and-tools.md#macros).
<a id="macroaliases"></a> Moved to
[Prompt and tool configuration](prompts-and-tools.md#macroaliases).
<a id="usechezmoi"></a> Moved to
[Core configuration behavior](core-behavior.md#usechezmoi). <a id="commithooks"></a>
Moved to [Finalizer configuration](finalizers.md#commithooks). <a id="gate"></a> Moved
to [Agent and runner configuration](agents-and-runners.md#gate). <a id="autonomy"></a>
Moved to [Agent and runner configuration](agents-and-runners.md#autonomy).
<a id="maxrunningagents"></a> Moved to
[Agent and runner configuration](agents-and-runners.md#maxrunningagents).
<a id="maxagentpipechain"></a> Moved to
[Agent and runner configuration](agents-and-runners.md#maxagentpipechain).
<a id="runnerslots"></a> Moved to
[Agent and runner configuration](agents-and-runners.md#runnerslots).
<a id="agentscopeteardown"></a> Moved to
[Agent and runner configuration](agents-and-runners.md#agentscopeteardown).
<a id="agentautorestart"></a> Moved to
[Agent and runner configuration](agents-and-runners.md#agentautorestart).
<a id="agent-hold-limits"></a> Moved to
[Agent and runner configuration](agents-and-runners.md#agent-hold-limits).
<a id="procs"></a> Moved to
[Runtime and storage configuration](runtime-and-storage.md#procs). <a id="service"></a>
Moved to [Runtime and storage configuration](runtime-and-storage.md#service).
<a id="disk"></a> Moved to
[Runtime and storage configuration](runtime-and-storage.md#disk).
<a id="managedtmp"></a> Moved to
[Runtime and storage configuration](runtime-and-storage.md#managedtmp).
<a id="markdown"></a> Moved to
[Display and reading configuration](display-and-reading.md#markdown). <a id="pager"></a>
Moved to [Display and reading configuration](display-and-reading.md#pager).
<a id="timezone"></a> Moved to [Core configuration behavior](core-behavior.md#timezone).
<a id="chatinstall"></a> Moved to
[Integration configuration behavior](integrations-behavior.md#chatinstall).
<a id="telegram"></a> Moved to
[Integration configuration behavior](integrations-behavior.md#telegram).
<a id="tmux_agent"></a> Moved to
[Agent and runner configuration](agents-and-runners.md#tmux_agent).
<a id="mobilegateway"></a> Moved to
[Integration configuration behavior](integrations-behavior.md#mobilegateway).
<a id="sdd"></a> Moved to
[Automation configuration behavior](automation-behavior.md#sdd). <a id="bead"></a> Moved
to [Automation configuration behavior](automation-behavior.md#bead).
<a id="externalmirror"></a> Moved to
[Automation configuration behavior](automation-behavior.md#externalmirror).
<a id="featureflags"></a> <a id="saved-machine-preferences"></a>
<a id="resolution-order"></a> <a id="enable-disable-and-restart"></a> Moved to
[Feature flag configuration](feature-flags.md#featureflags). <a id="workspace"></a>
Moved to [Workspace configuration behavior](workspace-behavior.md#workspace).
<a id="telemetry"></a> Moved to
[Runtime and storage configuration](runtime-and-storage.md#telemetry).
<a id="toolruns"></a> Moved to
[Runtime and storage configuration](runtime-and-storage.md#toolruns). <a id="tools"></a>
Moved to [Prompt and tool configuration](prompts-and-tools.md#tools).
<a id="update"></a> Moved to
[Runtime and storage configuration](runtime-and-storage.md#update).

## memory.h1_title

Optionally customizes the Markdown H1 title of a generated managed `AGENTS.md`.

```yaml
memory:
  h1_title: "Structured Agentic Software Engineering (SASE) - Agent Instructions" # default: null
```

[Generated reference for `memory.h1_title`](memory.md#memory-h1_title)

For ordinary project roots, `is_sase_managed: true` in that root's own `sase/sase.yml`
is the authorization switch. A managed project with no title derives
`<project> - Agent Instructions`; `memory.h1_title` alone does not opt a project in. The
`amd_h1_title` is unsupported and `sase config layers` reports it as an invalid key. See
[Configuration migration notes](../upgrading/configuration.md#managed-instruction-templates).

Home roots are the exception. For the live home root, user config from
`~/.config/sase/sase.yml` and `~/.config/sase/sase_*.yml` can provide the home
`AGENTS.md` title. For the chezmoi home source root, source-side config under
`dot_config/sase/` is used instead. With `use_chezmoi: true`, `sase memory init`
initializes the chezmoi home source root rather than writing a live-home `AGENTS.md`.

When at least one machine overlay (`sase_*.yml` with a valid `id.machine_name`) under
that chezmoi source config dir declares `memory.h1_title`, initialization writes
`AGENTS.md.tmpl` and matching `*.md.tmpl` provider shims whose H1 is a chezmoi hostname
switch. Each title-declaring overlay must already have the hostname guard that
`sase config init` writes to `.chezmoiignore`; missing or duplicate guards block
initialization. Machines without their own guarded title keep the last-declared-wins
fallback from `sase.yml` plus overlays. Without any machine-overlay title, chezmoi
generation stays static `AGENTS.md` as before.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`

## generated templates

SASE packages default Jinja templates for managed agent instructions and generated
memory Markdown. Managed projects can replace them with root-relative files named in
their own `sase/sase.yml`:

```yaml
memory:
  agents_template: templates/AGENTS.template.md
  agents_minimal_template: templates/AGENTS.minimal.template.md
  sase_template: templates/memory-sase.template.md
  readme_template: templates/memory-README.template.md
```

| Field                            | Required Jinja variables                                                                                              | Generated target or use               |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| `memory.agents_template`         | `title`, `core_sections`, `web_sections`, `reference_entries`                                                         | Managed root `AGENTS.md`              |
| `memory.agents_minimal_template` | `title`, `core_sections`                                                                                              | Create-if-missing minimal `AGENTS.md` |
| `memory.sase_template`           | `project_name`, `linked_repo_entries`                                                                                 | Generated `sase/memory/sase.md`       |
| `memory.readme_template`         | `memory_notes`, `total_notes`, `core_notes`, `reference_notes`, `web_descriptor_notes`, `total_lines`, `total_tokens` | Generated `sase/memory/README.md`     |

`{{ web_sections }}` renders the entire `## Memory Webs` section, including its own
heading, as one numbered H3 subsection per memory web; it is the empty string when a
root has no webs, which is what makes the whole section disappear cleanly for a webless
root. `{{ reference_entries }}` renders the entire Reference Memory body: the
reference-memory instruction paragraph plus one ordered-list entry per top-level
reference note. When a root has no top-level reference notes, `{{ reference_entries }}`
is empty. A custom `agents_template` must not repeat either section's prose.

The packaged managed template places `{{ web_sections }}` after the Reference Memory
block, so `## Memory Webs` renders as the final generated H2 when a root has webs. A
custom `agents_template` controls its own authored layout instead: SASE does not reorder
its H2 sections. Set the order directly in the custom template.

The top-level `amd_agents_template`, `amd_agents_minimal_template`,
`memory_sase_template`, and `memory_readme_template` keys are accepted aliases for their
nested `memory.*` forms. When both appear in one file, the nested form wins. See
[Configuration migration notes](../upgrading/configuration.md#managed-instruction-templates).

Every configured path must remain inside the project root. Rendering uses strict
variables: required placeholders must appear, unknown placeholders are rejected, and the
rendered instruction/memory structure is validated before any file is written. Generated
agent documents are numbered automatically, so custom `AGENTS.template.md` headings
should not carry their own numbers.

The packaged `sase.md` template includes the `/sase_final` terminal-action contract. A
custom `memory.sase_template` is a full-body override and may replace that default
prose; the host recovery turn remains the correctness fallback whenever a declaration is
actually required.

Home initialization uses convention-based files instead of the project-local path keys.
Put `AGENTS.template.md`, `AGENTS.minimal.template.md`, `memory-sase.template.md`, or
`memory-README.template.md` directly in `~/.config/sase/`; with `use_chezmoi: true`, put
them in the corresponding source-side `dot_config/sase/` directory. See
[Memory initialization](../agents/memory-initialization.md#memory-initialization-1) for
ownership, preview, and deployment behavior.

Source: `src/sase/amd/_template.py`, `src/sase/main/init_memory/root_rendering.py`

## is_sase_managed

Controls whether SASE owns repository resources such as project memory, the root
`AGENTS.md`, and explicit SDD initialization.

```yaml
is_sase_managed: false # default
```

[Generated reference for `is_sase_managed`](core.md#is_sase_managed)

Only the target repository's own checked-in `sase/sase.yml` is consulted for this
authorization. A root `sase.yml` is a read-only compatibility fallback when the
canonical file is absent. Defaults, user config, and merged overlays cannot opt
repositories in globally. When false or absent, memory init does not create, refresh, or
validate project memory and does not create or alter the root `AGENTS.md`; it still
propagates every existing project `AGENTS.md` to provider files beside it. Explicit
`sase repo init` and its `sase init repo` alias become successful no-ops before provider
and storage work. Invalid local YAML or a non-boolean marker fails safely.

`memory.enabled` does not authorize repository management. Use top-level
`is_sase_managed: true` in the project's own config.

Home and chezmoi-home memory initialization does not use this project-local switch, and
provider instruction copies for existing project `AGENTS.md` files remain independent of
it.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`

## id

Declares the explicit owner in the selected machine overlay:

```yaml
id:
  username: alice
  machine_name: athena
```

[Generated reference for `id`](core.md#id)

The schema permits partial objects so `sase config init` can diagnose and repair
interrupted config initialization, but provenance requires both valid fields.

## Top-level `machine_name` compatibility

Top-level `machine_name` is schema-valid only as read-only migration input for overlays;
see [Configuration migration notes](../upgrading/configuration.md#machine-identity):

```yaml
machine_name: athena
```

Configuration writers use `id.machine_name`. Run `sase config init` to move the value
under `id`, add the required username, and preserve the rest of the overlay. See
[Owner Identity](files-and-merging.md#owner-identity) for selection, authority, and
deployment behavior.

Source: `src/sase/config/core.py`, `src/sase/config/sase.schema.json`,
`src/sase/core/paths.py`

## use_chezmoi

Enables chezmoi-aware home-file writes. When set to `true`, SASE writes generated home
instructions, memory, skills, and home-directory macro paths through the chezmoi source
tree under `~/.local/share/chezmoi/home/` instead of writing the live home files
directly. Canonical `~/sase/macros/` and `~/sase/memory/` map to source paths
`home/sase/macros/` and `home/sase/memory/`. The unchanged global config still maps to
`home/dot_config/sase/sase.yml`.

This affects initialization workflow as well as macro editing. `sase memory init`
targets the chezmoi home source root when it needs to initialize home-level `AGENTS.md`,
writes home memory there, and may run the configured chezmoi deploy path;
`sase skill init` writes provider skill files there before optional commit, push, and
apply steps.

Home-level provider instruction files (`CLAUDE.md`, `GEMINI.md`, `QWEN.md`,
`OPENCODE.md`) in the chezmoi source are byte-for-byte copies of the root's generated
`AGENTS.md`. When no machine overlay declares `memory.h1_title`, those copies stay
static `.md` files. When a machine overlay does declare a title, `sase memory init`
writes `AGENTS.md.tmpl` and preferred `*.md.tmpl` shims whose H1 switches on
`.chezmoi.hostname`, and migrates leftover static copies away. Existing `*.md.tmpl`
shims that imported `@{{ .chezmoi.homeDir }}/AGENTS.md` are recognized and migrated to
full copies.

```yaml
use_chezmoi: true # default: false
```

[Generated reference for `use_chezmoi`](core.md#use_chezmoi)

Source: `src/sase/config/core.py`

## timezone

The timezone that governs all SASE wall-clock display and timestamp generation
(notifications, agent logs, artifact/agent-name timestamps, runtime durations, TUI
displays, CLI tables, and generated Markdown pages). Column and label timezone suffixes
use the configured zone abbreviation. When unset, SASE uses the host **system
timezone**, so machines that don't share our timezone assumptions get sensible behavior
out of the box.

```yaml
timezone: "America/New_York" # default: system timezone
```

[Generated reference for `timezone`](core.md#timezone)

## Related

- [Core and identity configuration](core.md) — generated key paths and defaults.
- [Memory and instructions configuration](memory.md) — generated memory settings.
