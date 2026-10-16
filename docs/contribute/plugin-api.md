---
title: Plugin API
description: Contributor contract for discovering and writing SASE plugins.
---

# Plugin API

This page documents how SASE discovers plugins and how to write one.

## How Plugins Are Discovered

For catalog and Admin Center installed status, a managed uv tool receipt is
authoritative: each explicitly-injected requirement is matched to its live
`importlib.metadata` distribution by PEP 503-normalized name. Receipt inspection is best
effort, so unmanaged environments or a temporarily unavailable receipt retain the
generic discovery behavior.

Generic plugin discovery uses `importlib.metadata.entry_points()` plus recognized
console-script and distribution naming to find installed packages. It is also what
supplies the contributed entry-point groups displayed by `sase plugin show`.

There are two discovery paths:

1. **Provider classes**: `sase_artifact_refs`, `sase_file_hooks`, `sase_task_types`,
   `sase_vcs`, `sase_workspace`, and `sase_llm` entry points resolve to classes. The
   relevant registry loads the class, instantiates it, and registers the instance with a
   pluggy `PluginManager`.
2. **Package resources**: `sase_macros`, `sase_config`, and `sase_plugin_manifest` entry
   points resolve to modules. The shared helper in `src/sase/main/plugin_discovery.py`
   sorts config and macro entry points by name, loads the modules, and skips module load
   failures after logging them at debug level. `sase doctor -C plugins.resources` loads
   resource entry points directly so packaging problems are visible as diagnostics
   instead of only debug logs.

### VCS Plugins (pluggy)

VCS plugins use pluggy's hook system. The hook specification is defined in `VCSHookSpec`
(`src/sase/vcs_provider/_hookspec.py`). Each hook method uses `firstresult=True`,
meaning the first plugin to return a non-`None` result wins.

The VCS registry (`src/sase/vcs_provider/_registry.py`) uses `sase_vcs` entry points in
two ways:

1. Detection/classification builds a pluggy manager containing all registered VCS
   plugins.
2. Runtime operations create a `VCSPluginManager` for the selected provider name, such
   as `bare_git`, `github`, or `hg`.

### Workspace Plugins (pluggy)

Workspace plugins use pluggy's hook system, similar to VCS plugins. The hook
specification is defined in `WorkspaceHookSpec`
(`src/sase/workspace_provider/_hookspec.py`). Most hooks use `firstresult=True`; the
exception is `ws_get_workflow_metadata` which collects results from all plugins. All
hook method names are prefixed with `ws_`. Alongside reference resolution and workspace
management, providers may implement the additive onboarding hooks `ws_parse_repo_ref`,
`ws_list_local_repo_candidates`, `ws_probe_repo`, `ws_describe_repo_creation`, and
`ws_create_repo`. Their argument names are frozen for out-of-tree plugins; the hookspec
tests pin them. Repository creation creates only the provider-owned repository. SASE
handles checkout, project registration, and setup as a separate convergent operation.

The workspace registry (`src/sase/workspace_provider/_registry.py`) creates a singleton
`WorkspacePluginManager`, registers `WorkspaceHookSpec`, and loads all `sase_workspace`
provider classes from entry points. This is why all workspace metadata can be listed at
once while hook dispatch still lets a single plugin handle each operation.

See [Workspace provider internals](workspace-provider.md) for the full workspace
provider reference.

### LLM Plugins (pluggy)

LLM provider plugins use pluggy's hook system. The hook specification is defined in
`LLMHookSpec` (`src/sase/llm_provider/_hookspec.py`), and every hook is declared with
`firstresult=True`. The core dispatch hooks (`llm_invoke`, `llm_resolve_model_name`) go
through pluggy dispatch, so the first matching plugin handles a call. The metadata hooks
are called directly on each registered plugin instance by the registry, so each provider
contributes its own values:

| Area                  | Hooks                                                                                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Identity and models   | `llm_provider_name`, `llm_provider_short_name`, `llm_known_model_names`, `llm_model_short_aliases`, `llm_model_advisories`                       |
| Skills                | `llm_skill_template_context`, `llm_skill_deploy_subpath`, `llm_additional_skill_deploy_subpaths`                                                 |
| Detection and display | `llm_cli_status_color`, `llm_autodetect_priority`, `llm_autodetect_cli_name`, `llm_auth_evidence`, `llm_hidden_from_model_pickers`               |
| CLI management        | `llm_install_metadata`, `llm_interactive_cli`, `llm_hidden_from_agent_cli_management`                                                            |
| Failure policy        | `llm_default_retry_config`, `llm_default_usage_limit_config`                                                                                     |
| Instruction delivery  | `llm_instruction_delivery` (see [Delivery](instruction-bundle-internals.md#delivery))                                                            |
| Subscription usage    | `llm_usage_capabilities`, `llm_usage_probe` (see [Subscription usage extension](../reference/providers/plugins.md#subscription-usage-extension)) |

`llm_auth_evidence()` lists credential paths and API-key environment variable names
(never secret values) for `sase doctor`. `llm_hidden_from_model_pickers()` hides a
testing-only provider from the model picker and `%model` completion without changing
routing, and `llm_hidden_from_agent_cli_management()` opts a provider out of
`sase agent-cli` and the Admin Center's Agent CLIs list. Omitting any metadata hook
keeps the default behavior. All hook method names are prefixed with `llm_`.
`llm_instruction_delivery()` returns the provider's root and subagent slots; omitting
it, raising, or returning an invalid mapping resolves to native discovery (legacy) for
that invocation. The adapter contract for an explicit slot is in
[Delivery](instruction-bundle-internals.md#adapter-contract).

Core Sase ships Claude, Codex, Antigravity (`agy`), Qwen, OpenCode, Meta's Muse Code,
and xAI's Grok Build providers as built-in entry points. Additional providers belong in
external plugin packages that declare `sase_llm` entry points and provide their own
metadata hooks.

#### LLM Provider Install Metadata and Advisories

`llm_install_metadata()` describes how a provider's CLI is installed, versioned, and
updated, and drives
[`sase agent-cli`](../reference/providers/agent-clis.md#inventory-and-updates). Every
key is optional and every one defaults to today's behavior, so an existing plugin needs
no changes.

| Key                         | Purpose                                                                                                               |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `manager`                   | `npm`, `homebrew`, `bundled`, or `script` (installed by a remote install script).                                     |
| `package` / `brew_package`  | Package identity for the npm and Homebrew managers. An npm `package` also drives `sase agent-cli install`.            |
| `display_name` / `docs_url` | Human-facing name and canonical vendor docs link.                                                                     |
| `vendor`                    | Secondary label shown by tmux Agent (`"Anthropic"`, `"OpenAI"`, `"Google"`, `"Alibaba"`, `"SST"`, `"xAI"`, `"Meta"`). |
| `version_argv`              | Argv used to probe the installed version (default `["--version"]`).                                                   |
| `version_regex`             | Regex with a `version` group, when the CLI's version output is not plain semver.                                      |
| `latest_version_package`    | npm package whose `latest` dist-tag is the newest known version.                                                      |
| `latest_version_url`        | HTTPS JSON endpoint serving the newest version, for channel-versioned CLIs distributed outside npm.                   |
| `latest_version_json_field` | Field to read from that endpoint's JSON body (default `version`).                                                     |
| `version_compare`           | `pep440` (default) or `exact`. Use `exact` when release ids are not valid PEP 440 versions.                           |
| `self_update_argv`          | The CLI's own update command; declaring one classifies the CLI as self-managed.                                       |
| `self_update_env`           | Environment overlay applied to that update command, for CLIs whose update is env-driven rather than a subcommand.     |
| `install_script_url`        | HTTPS install script `sase agent-cli install` fetches, digests, and runs without a shell.                             |
| `install_env`               | Environment overlay applied to that install script.                                                                   |
| `install_dir`               | Where the installer writes the binary, so SASE can name the target and find it afterwards.                            |
| `install_dir_env`           | Environment variable that overrides `install_dir`.                                                                    |

`llm_interactive_cli()` describes how the provider's CLI is launched in a terminal by
[tmux Agent](../ace.md#tmux-agent). All keys are optional so third-party providers stay
compatible. Omitting the hook entirely means "launchable as the bare CLI name with no
extra flags", so a new provider is usable the moment it declares a CLI.

| Key           | Purpose                                                                                                          |
| ------------- | ---------------------------------------------------------------------------------------------------------------- |
| `argv`        | Base argv; defaults to `[llm_autodetect_cli_name()]`.                                                            |
| `args`        | Always-on interactive args.                                                                                      |
| `bypass_args` | Args that skip this CLI's approval prompts. Used when `tmux_agent.bypass_permissions` is on.                     |
| `model_args`  | Argv fragment selecting a model; the literal `{model}` token is replaced with the configured model exactly once. |
| `env`         | Environment the CLI needs in interactive mode.                                                                   |
| `menu_key`    | Preferred single-character shortcut.                                                                             |
| `supported`   | `False` marks a provider with no interactive CLI, which excludes it from the tmux Agent launcher.                |

Malformed values degrade to the default rather than raising. A provider that should not
appear in the launcher (the built-in `fakey` testing provider) returns
`{"supported": False}`.

`llm_model_advisories()` returns a per-model map of terms a user should see when they
choose a model — a discounted tier that trains on its inputs, a preview model with no
stability guarantee, and so on:

```python
@hookimpl
def llm_model_advisories(self) -> dict[str, dict[str, str]]:
    return {
        "vendor-model-discounted": {
            "severity": "warn",  # or "info"
            "label": "trains on your data",
            "detail": "One sentence the user reads before agreeing to this.",
        }
    }
```

Omitting the hook means no advisories, and non-conforming values are dropped rather than
raising, so third-party providers stay compatible. The registry normalizes the map and
every render site reads from it, so a new advisory needs no new render site. See
[LLM Providers — Model advisories](../reference/providers/models.md#model-advisories)
for where advisories surface.

See [LLM providers](../reference/providers/index.md) for the provider reference,
including authoring new providers with `@hookimpl`.

### Macro Plugins

Plugin packages can contribute macro templates by declaring a `sase_macros` entry point
that points to a module. The module's package directory is searched for `macros/*.md`
files and `macros/*.yml` / `macros/*.yaml` workflow files. Plugin macros are priority 8
in the [discovery order](../reference/macros/discovery.md#discovery-order) (above
built-in files and below config-based macros).

The retired entry-point and resource-directory spellings listed in the
[Macros compatibility table](../reference/upgrading/macros.md#retired-macro-spellings)
remain accepted. When both entry-point groups register the same module value, the
canonical `sase_macros` registration wins and the module is loaded once. SASE searches
`macros/` first, falling back to the retired directory when the canonical directory is
absent.

Macro-plugin entry-point discovery is cached within each running process. Changes to the
Python search path, its directory modification times (as during package installation or
removal), or the plugin-disable environment variables invalidate that cache. Editing
distribution metadata in place may not change those directory times. Cache invalidation
also does not reload Python modules that are already imported; restart the TUI or other
long-running consumer after changing entry points or plugin Python code during
development.

### Config Plugins

Plugin packages can provide default configuration by declaring a `sase_config` entry
point. The referenced module's package must contain a `default_config.yml` file. Plugin
configs are merged between the bundled package defaults and the user's `sase.yml`. See
the [Deep-Merge System](../reference/config/files-and-merging.md#deep-merge-system) for
details on the merge chain.

### Service Procs

A plugin declares a service proc through its `sase_config` layer: add a
`service.procs.<name>` entry to the package's `default_config.yml` with a `command` (or
exact argv array), a `description`, and the usual proc fields (`cwd`, `env`, `restart`,
`stop_signal`, `stop_timeout`, `after`, `log_max_bytes`). See
[service configuration](../reference/config/runtime-and-storage.md#service) for the full
field contract.

Plugin-shipped entries default to `enabled: false`, so installing a plugin never starts
work on a machine by itself. A machine opts in through its machine overlay, or at
runtime with `sase service proc enable <name>`. There is no Python plugin proc API in
v1: no entry-point group launches procs, only `service.procs` config declaration.

### Artifact Reference and File-Hook Providers

The `sase_artifact_refs` and `sase_file_hooks` groups share the declarative artifact
provider host. A provider class can implement either or both hooks:

- `artifact_ref_provider_specs()` returns one mapping or an iterable of mappings. Each
  schema-versioned specification has a unique provider ID and `ref.kind`, plus its
  Artifacts tab `ref.icon`, expansion, metadata, inventory, identity, and publication
  policy. A sidecar selects it with `ref: {use: <plugin>@<provider-id>}`; local sidecar
  fields deep-merge over the base. During the compatibility window, a ref provider spec
  without `ref.icon` is admitted with a generic mark and a warning diagnostic.
- `artifact_file_hook_provider_specs()` returns schema-versioned file-hook templates.
  Each template has a unique provider ID, a `file_hook` mapping, and an optional list of
  required fields. A configured hook selects it with `use: <plugin>@<provider-id>` and
  supplies the required values.

SASE validates all returned specifications before adding them to the registry. Duplicate
provider IDs, duplicate reference kinds, reserved kinds, invalid schemas, load errors,
and hook failures are diagnosed rather than silently taking precedence. The core package
always registers the built-in `plan` reference provider through the same schema and
registry path, even when third-party provider entry points are disabled. Run
`sase doctor -C config.repos` for sidecar provider problems and `sase file-hook list`
for configured file hooks.

### Task-Type Plugins

The `sase_task_types` group contributes declarative task-type specs to the catalog that
`sase bead create -T 'task(<slug>)'` and `sase bead task-type` read. The hook
specification is `task_type_specs()` in `src/sase/task_types/_hookspec.py`; it returns
one mapping or an iterable of mappings matching the Rust `TaskTypeSpecWire` shape
(`schema_version: 1`).

Three sources feed one validator. First wins, later duplicates are dropped with a
diagnostic naming the winner:

1. Builtin specs (`bug`, `ci`, `feature`, `flake`, `memory`) from
   `src/sase/task_types/_builtin.py`. Builtin slugs are reserved against plugins.
2. Plugin hooks, collected from `sase_task_types` entry points sorted by name.
   Per-plugin load failures become `entry_point_load_failed` diagnostics rather than
   aborting the catalog.
3. Project config (`bead.task_types`). An entry with `use: <plugin>@<slug>` deep-merges
   its sibling keys onto that slug and may override a builtin. An entry without `use:`
   defines a new slug and may not shadow a builtin or reserved slug (`plan`, `phase`,
   `task`, `flag`, `untyped`, `unknown`, `all`, `none`).

Each spec declares `task_type`, `label`, `summary`, `when_to_use`, optional
`glyph`/`accent_color`/`agent_creatable`/`default_size`, typed `fields` (`string`,
`enum`, `integer`, `date`), an optional Jinja `body_template`, and optional
`triage.min_plus_ones`. Rust validates the spec, its field values, and its digest;
Python owns discovery and membership. `sase doctor -C beads.task_types` surfaces catalog
diagnostics.

A plugin-provided type such as `github` is usually `agent_creatable: false` and is
stamped by the external-issue mirror rather than by agents. When the plugin is absent,
reads degrade: `sase bead show` prints the raw fields under a
`(not installed on this machine)` header, and create names the package plus
`sase plugin install`.

List the providing distribution in
[`plugins.required`](../reference/config/prompts-and-tools.md#plugins) so
`sase memory init` can snapshot the type into `sase/task_types.json`. Optional plugins
that contribute types stay live-only and do not change generated `AGENTS.md`.

```toml
# pyproject.toml
[project.entry-points."sase_task_types"]
github = "sase_github.task_types:GitHubTaskTypes"
```

```python
from sase.task_types import hookimpl


class GitHubTaskTypes:
    @hookimpl
    def task_type_specs(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "task_type": "github",
            "label": "GitHub",
            "summary": "A GitHub issue mirrored into a task bead.",
            "when_to_use": "Agents never create this type.",
            "glyph": "⑂",
            "accent_color": "#B2B2B2",
            "agent_creatable": False,
            "fields": [],
        }
```

See [Task Types](../reference/work-units/beads.md#task-types) for the create grammar and
degraded render.

### Job Script Packages

Job scripts are installed console scripts, not a pluggy entry-point group. Axe resolves
the exact configured `script` name from `axe.job_script_dirs`, the running interpreter's
bin directory, then `$PATH`; it never adds a `sase_job_` prefix. A package may also
expose a `sase_config` resource when it wants to contribute disabled-by-default or
ready-to-patch routine configuration. Exact-name job packages do not need to rename
their public scripts to `sase_job_*` merely to appear installed in the catalog: when
Sase injects them into its managed uv tool environment, receipt membership provides that
installed identity.

Proposal-emitting packages should depend on `sase` and use the public `sase.jobs` SDK.
Scripts read `--context`, write their versioned result atomically to
`SASE_JOB_RESULT_FILE`, and emit structured launch proposals. They must not call
`sase run` themselves, and proposal prompts cannot contain standalone `#!workflow`
references. Axe validates and launches proposals so dry runs remain side-effect free and
action lifecycle stays observable.

Packages can group proposals in one runner-owned clan by passing the same template to
`clan` and a member ID to `agent_name`. The runner allocates one concrete clan, makes
the first accepted proposal its declarer, assigns the `job` tribe at clan level, and
resolves `wait_on` to full member names. Authors may also pass a literal Rich
`clan_summary`; repeat the identical value on every member that shares the raw clan
template. Axe remains the sole owner of concrete clan allocation and emits the summary
only on the surviving declarer's `%clan` directive. Do not combine `clan` with `tribe`.

A member ID may itself end in (or contain) one `@` auto-name marker, so `clan` and
`agent_name` carry at most one marker each. Axe picks the clan token for the whole group
first and then allocates each templated member inside that concrete clan, so
`clan="toobig-@"` with `agent_name="split_file.src.pkg.large.@"` becomes
`toobig-0.split_file.src.pkg.large.0`. Prefer a trailing `.@` over hashing a
discriminator into the member ID: two members that would otherwise collide land on `.0`
and `.1` instead of failing the run. See
[Axe launch proposals](../reference/automation/scheduler-jobs.md#structured-results-and-launch-proposals)
for the full allocation rule.

## Writing a Plugin

A sase plugin is a standard Python package that declares entry points in
`pyproject.toml`.

### Example: VCS Plugin

```toml
# pyproject.toml
[project.entry-points."sase_vcs"]
my_vcs = "my_sase_plugin.vcs:MyVCSPlugin"

[project.entry-points."sase_config"]
my_vcs = "my_sase_plugin"
```

The VCS plugin class implements hooks from `VCSHookSpec` using the `@hookimpl`
decorator:

```python
from sase.vcs_provider._hookspec import hookimpl

class MyVCSPlugin:
    @hookimpl
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None] | None:
        # Implementation here
        ...

    @hookimpl
    def vcs_diff(self, cwd: str) -> tuple[bool, str | None] | None:
        # Implementation here
        ...
```

Methods should return `None` (implicitly or explicitly) for operations they don't
support, allowing other plugins to handle them.

### Example: Workspace Plugin

```toml
# pyproject.toml
[project.entry-points."sase_workspace"]
my_workspace = "my_sase_plugin.workspace:MyWorkspacePlugin"
```

The workspace plugin class implements hooks from `WorkspaceHookSpec` using the
`@hookimpl` decorator:

```python
from sase.workspace_provider._hookspec import WorkflowMetadata, hookimpl

class MyWorkspacePlugin:
    @hookimpl
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
        return WorkflowMetadata(
            workflow_type="my_vcs",
            ref_pattern=r"#my_vcs:(\w+)",
            display_name="My VCS",
            pre_allocated_env_prefix="SASE_MYVCS",
            vcs_family="git",
            vcs_provider_name="my_vcs",
        )

    @hookimpl
    def ws_detect_workflow_type(self, project_file: str) -> str | None:
        # Return workflow type if this plugin handles the project
        ...
```

### Example: Macro Plugin

Place macro files in your package's `macros/` directory and register the module:

```toml
[project.entry-points."sase_macros"]
my_plugin = "my_sase_plugin"
```

```
my_sase_plugin/
├── __init__.py
└── macros/
    ├── my_template.md
    └── my_workflow.yml
```

Use `.md` for prompt templates and `.yml` / `.yaml` for workflow definitions.

### Example: Config Plugin

Place a `default_config.yml` alongside your module and register it:

```toml
[project.entry-points."sase_config"]
my_plugin = "my_sase_plugin"
```

```
my_sase_plugin/
├── __init__.py
└── default_config.yml
```

Plugin configs are merged using the
[deep-merge system](../reference/config/files-and-merging.md#deep-merge-system). User
config in `sase.yml` takes precedence over plugin defaults.

### Example: Declarative Artifact Providers

Register artifact-reference and file-hook providers separately. Each class implements
only the hook for its entry-point group:

```toml
[project.entry-points."sase_artifact_refs"]
my_docs = "my_sase_plugin.artifacts:DocumentProviders"

[project.entry-points."sase_file_hooks"]
my_hooks = "my_sase_plugin.artifacts:FileHookProviders"
```

```python
import pluggy


hookimpl = pluggy.HookimplMarker("sase_artifact")


class DocumentProviders:
    @hookimpl
    def artifact_ref_provider_specs(self):
        return ({
            "schema_version": 1,
            "provider": "design",
            "ref": {
                "kind": "design",
                "expansion_format": (
                    "the {repo_relative_path} file in the {sidecar_role} sidecar repo"
                ),
                "properties": {},
                "detail": {},
                "identity": {},
                "inventory": {"globs": ["**/*.md", "!drafts/**"]},
                "publication": {
                    "link": "vcs_permalink",
                    "referenced_by": "markdown_table",
                },
            },
        },)


class FileHookProviders:
    @hookimpl
    def artifact_file_hook_provider_specs(self):
        return ({
            "schema_version": 1,
            "provider": "research-highlights",
            "required": ["command"],
            "file_hook": {
                "description": "Render new research reports into Highlights PDFs.",
                "filters": {"sidecars": ["research"], "ops": ["ADD"]},
                "timeout": "120s",
            },
        },)
```

The direct pluggy marker above is equivalent to SASE's public `hookimpl`. In the current
release, importing `hookimpl` from `sase.artifact_providers` before another SASE module
has initialized configuration can hit a circular import, so a plugin module loaded as an
entry point should construct the marker directly.

The project can then select the document provider with
`repos.sidecar.custom.design.ref.use: my_sase_plugin@design` and instantiate the hook
with a `file_hooks` entry containing `use: my_sase_plugin@research-highlights` plus its
required `command`. Every hook command receives the producing project's display name in
`SASE_FILE_HOOK_PROJECT` (unset when the project is missing or `unknown`), so a
`research-highlights` command can route on it, for example with
`-P "$SASE_FILE_HOOK_PROJECT"` (quoted, so names with spaces stay one argument).
Provider and kind names must not collide with another installed provider or a reserved
built-in kind. Use `sase doctor -C config.repos`, `sase doctor -C config.file_hooks`,
and `sase file-hook list` to verify the effective configuration.

### Example: Job Script Package

Declare each executable by its full public name:

```toml
[project]
dependencies = ["sase"]

[project.scripts]
my_job_audit = "my_sase_plugin.jobs.audit:main"
```

Use the SDK to load the runner context and write a validated result:

```python
from sase.jobs import JobResultBuilder, load_job_invocation


def main() -> None:
    invocation = load_job_invocation(description="Audit one target project")
    target = invocation.context.target or {}
    workspace = str(target["workspace"])
    result = JobResultBuilder(
        summary="audit: targets=1 proposals=2",
        counters={"targets": 1, "proposals": 2},
    )
    clan_summary = "[bold]Project audit[/bold]"
    result.propose(
        "Audit recent changes and fix confirmed correctness bugs only.",
        workspace,
        proposal_id="audit",
        agent_name="audit",
        clan="project-audit-@",
        clan_summary=clan_summary,
    )
    result.propose(
        "Review the audit fixes and add focused regression tests.",
        workspace,
        agent_name="review",
        clan="project-audit-@",
        clan_summary=clan_summary,
        wait_on="audit",
    )
    result.write(context=invocation.context)
```

Configure the exact script name and debug it through the runner:

```yaml
axe:
  routines:
    audits:
      description: Run project audits every five minutes
      interval: 300
      jobs:
        project_audit:
          description: Audit enabled projects for actionable improvements
          script: my_job_audit
          for_each: { source: projects }
```

```bash
sase axe job run 'project_audit[sase]' -L audits --dry-run --job-verbose
```

Third-party packages can opt into `sase plugin list` by adding the `sase--plugin`
repository topic. See
[Axe](../reference/automation/scheduler-jobs.md#structured-results-and-launch-proposals)
for the result contract, proposal fields, trigger/guard policy, and lifecycle statuses.

### Example: LLM Provider Plugin

LLM providers declare a `sase_llm` provider class:

```toml
[project.entry-points."sase_llm"]
my_llm = "my_sase_plugin.llm:MyLLMProvider"
```

The provider implements hooks from `LLMHookSpec` using `@hookimpl`, including
`llm_invoke()` for execution and metadata hooks such as `llm_provider_name()`,
`llm_known_model_names()`, and `llm_autodetect_priority()`. Optional
`llm_usage_capabilities()` (static, no I/O) and `llm_usage_probe(context)` collect
subscription usage; omitting them leaves invoke unchanged. See
[External provider plugins](../reference/providers/plugins.md#external-provider-plugins-1)
for the full provider contract.

### Example: Turn-Finalizer Plugin

Turn-finalizer providers declare a `sase_finalizers` provider object:

```toml
[project.entry-points."sase_finalizers"]
my_checks = "my_sase_plugin.finalizers:MyChecksProvider"
```

The provider implements `describe()`, `validate()`, `execute()`, and `verify()`, each
taking a JSON request mapping and returning a JSON result mapping; stdout stays the
result channel. See `src/sase/finalizers/sdk.py` (`FinalizerProvider`,
`dispatch_provider_request`) for the accepted entry-point shapes.

**Run visibility.** Everything a finalizer reports also feeds the Agents tab ⊛ FINAL
deck and `sase final status` (see
[Finalizers on the Agents tab](../reference/tui/agent-statuses.md#finalizers-on-the-agents-tab)):

- **Step channel.** While an attempt runs, the host sets `SASE_FINALIZER_STEPS_FILE` to
  an `attempt-<N>.<op>.steps.jsonl` path. Report structured progress with
  `sase.finalizers.sdk.step(name, state=...)` (`state` is `start`, `ok`, `warn`, or
  `fail`; text caps at 120 characters, detail at 500, file at 64 KiB). The helper does
  nothing outside a finalizer attempt and never raises, so progress stays best-effort
  observability that cannot change a verdict. Never scrape progress from stdout.
- **Typed evidence.** Each result mapping may carry an `evidence` list of `kind`/`value`
  records. The shared projection types them (`sha`, `url`, `bead`) and the FINAL deck
  renders them on the instance card (commit SHAs, links, beads), picking one as the
  headline.
- **Operation records.** Every operation inside an attempt writes one uniform schema-v1
  `attempt-<N>.<op>.outcome.json` record (`kind` is `subprocess`, `model_turn`,
  `validation`, or `internal`) and emits `op_started`/`op_finished` journal events; work
  before an attempt exists (plugin `describe`/`validate`) lands in
  `preflight.<op>.outcome.json` instead. Records are write-once and exclusive, exactly
  like the commit outcome record.

## Shipping input types

Plugins share closed enums with an `input_types.yml` manifest at the package root,
beside `default_config.yml` and `macros/`:

```yaml
schema_version: 1
types:
  audio_edition:
    description: Narration length for guide-backed audio editions.
    choices:
      - { value: brief, description: About 4 minutes }
      - { value: full, label: Full edition, description: About 16 minutes }
```

Only static closed enums are supported. IDs match `[a-z0-9][a-z0-9_-]*`. The envelope
accepts exactly `schema_version` and `types`; each type accepts exactly required
`description` and `choices`. Values must be strings, nonempty words without whitespace,
distinct, and different from literal `null`. Matching is exact and case-sensitive. A
type with any error is wholly skipped while valid siblings remain usable; malformed
files produce file diagnostics without breaking unrelated plugins or macros.

The package must register a `sase_macros` entry point (or its compatibility alias) for
SASE to discover this manifest. The providing distribution is identified by installed
package metadata. When macro plugins are enabled, a registered distribution without a
manifest is still known to the type registry: a reference to one of its types reports an
unknown ID rather than a missing plugin. Changes to an already discovered manifest's
modification time or size refresh the parsed type registry on its next lookup; adding a
new manifest or changing entry points may require restarting a running consumer. Use
`sase macro types` and `sase doctor -C config.macro_input_types` to inspect the result.

Macros always use the qualified spelling `<distribution>@<id>`, for example
`sase-research-artifacts@audio_edition`. Distributions use PEP 503 canonicalization.
Missing plugins name the install command (`sase plugin install <dist>`); unknown IDs
suggest known IDs and point to `sase macro types`. Named types reject an authored
`choices` override because the type already defines its values. Serializers write the
named type without copying resolved choices back.

Project macros that reference a plugin type should list that distribution in the
project's `plugins.required`; `sase doctor -C config.macro_input_types` warns with the
exact requirement to add. See `sase macro types` for the installed catalog.

## Related

- [Plugins](../reference/integrations/plugins.md) — groups, catalog, and disable
  switches.
- [Command plugins](../reference/integrations/plugins-commands.md) — mounted commands.
- [VCS provider API](vcs-provider-api.md) — VCS hook contract.
- [Workspace provider](workspace-provider.md) — workspace hook contract.
