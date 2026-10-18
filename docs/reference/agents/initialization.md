---
title: Initialization
description: Look up project initialization commands and the files they manage.
---

# Initialization

This page describes the initialization commands and the project files they prepare.

SASE initialization commands create or refresh durable files that agents and sidecar
tools rely on. Bare `sase init` checks the current project and home setup first, then
either reports that everything is current or shows the initializers that need attention:

```bash
sase init -c       # report drift without writing
sase init          # prompt before each needed initializer
sase init --yes    # run every needed initializer in order
sase init -M --yes # mark this repository as SASE-managed, then initialize it
sase init --all --check # check every enabled main project without writing
sase init --all         # visit every enabled main project; prompt when interactive
sase init --all --yes   # skip generic prompts for every enabled main project
sase init -p sase -p notes --check --json  # structured plan for named projects
sase init -p sase --yes                    # initialize named projects as one process
```

The coordinator first builds all six read-only plans in registry order—config, machine,
memory, repositories, service, then skills—before it writes anything. It then applies
the changed initializers in that same order. Config initialization establishes the
explicit per-user/per-machine owner identity; machine initialization offers optional
remote-machine enrollment after that identity exists; memory initialization owns
agent-document initialization (managed `AGENTS.md` and its provider instruction copies);
repository initialization owns configured sidecars and the workspace ignore rule.
Service initialization offers the machine-level native user unit once per init batch;
declining records a machine marker so later bare onboarding stays quiet, while an
explicit `sase service init` still checks it. In non-interactive shells, bare
`sase init` reports drift and exits non-zero instead of prompting; use `sase init --yes`
when you want to apply everything that does not require a resource-specific
confirmation. Owner identity creation and migration still require a TTY. Apply runs can
write project files, deploy home files through chezmoi when configured, and use each
initializer's normal commit/push behavior. Project-wide ownership requires
`is_sase_managed: true` in the current repository's own `sase/sase.yml`; defaults and
merged user configuration cannot grant it. Without that local marker, memory init leaves
project memory and the root `AGENTS.md` untouched while still copying every existing
project-tree `AGENTS.md` to the provider instruction files beside it, and explicit
repository initialization exits successfully without detecting a provider, materializing
sidecars, or generating files.

One resource-specific exception is intentionally non-bypassable: `--yes` can run the
repository initializer, but it cannot approve creation of a missing provider sidecar.
Each creation always requires an interactive `y`/`yes` response to a prompt naming the
host, repository, and configured visibility; unattended initialization can connect
existing sidecars but cannot create them.

`sase init --all` uses the registered project inventory, so it can be run inside a
project or from an unrelated directory. It visits enabled main projects only: disabled
projects, sibling bookkeeping records, and the system-managed `home` project are
excluded. Each project runs from its recorded primary workspace. Missing workspaces,
invalid project records, planning errors, and initializer failures are reported under
that project's heading without preventing later projects from being attempted; the final
summary and exit status reflect the whole batch. `--all --check` is fully read-only and
exits non-zero if any project has drift or cannot be checked. Without a TTY, `--all`
remains read-only unless `--yes` is supplied. Machine enrollment is offered at most once
per `--all` or repeated `-p/--project` invocation; accepting, declining, EOF, or a
machine-init failure consumes that batch's machine opportunity while later projects
continue with their other initializers.

`-p, --project NAME` selects one or more of those same enabled projects by project name,
display name, or alias. Repeat the option to name a subset
(`sase init -p alpha -p beta --yes`). Named projects still run as one process with one
batched chezmoi deploy. The selector cannot be combined with `--all`,
`--enable-project-memory`, or an explicit init subcommand. An unknown or non-enabled
name fails immediately and lists the valid names.

`sase project add REF` registers an existing repository before this initialization step.
When its setup succeeds in a terminal, add can offer `sase init -p KEY` directly. This
handoff uses the normal initializer, including its per-sidecar confirmation: accepting
the add command does not approve creation of a missing remote sidecar.

When project add or create includes SASE setup, it sets `is_sase_managed: true` in
`sase/sase.yml`, preserves other configuration, and commits and pushes that file. The
management commit contains only that file. For an empty origin with no branches, setup
can create the repository's first commit without a README or an existing default-branch
tip. It uses the branch recorded by an interrupted setup, otherwise the provider's
reported default branch, otherwise the clone's current branch. Setup verifies the pushed
commit and configures the local branch to track it.

Setup records its progress so repeating the same add or create command can resume a
completed write, commit, or push. A failed push preserves the local marker commit. Setup
stops if origin gains unrelated commits during the operation, if the checkout has
unpublished commits, or if the management file has local edits outside the recorded
setup. Resolve the reported condition before retrying. If creation succeeds but setup
fails, the repository remains available for that retry. The generated
[project CLI reference](../cli/project.md) lists the add and create options.

`--check -j/--json` writes exactly one JSON document to stdout instead of the Rich
report. The payload carries `schema_version` (currently `1`) and a top-level `status` of
`current`, `drift`, or `blocked` so callers can distinguish drift from blockers without
using the exit code — both still exit `1`. Each project entry includes name, display
name, an `InitRunStatus`-style per-project status, `unavailable_reason` when inventory
held the project back, and per-planner rows with label, summary, change and runnable
flags, a `requires_tty` marker, warnings, blockers, and actions (including `new_content`
so a consumer can render full diffs). `--json` requires `--check`.

The [Admin Center Projects tab](../tui/projects-tab.md#initialize-from-the-projects-tab)
can drive the same flow: `i` initializes the marked or highlighted projects and `I`
initializes every enabled project.

Use `-M, --enable-project-memory` to create or update the current project's
`sase/sase.yml` with `is_sase_managed: true` before normal initialization. The
compatibility spelling remains, but the marker now authorizes SASE management of the
repository as a whole and thereby enables managed project memory and explicit repository
initialization. The option preserves other local configuration and is available on both
bare `sase init` and `sase memory init` (as well as the `sase init memory` compatibility
alias). Because it writes configuration, it cannot be combined with `--check`, `--all`,
or `-p/--project`; repositories must be marked one at a time.

Explicit subcommands are still available when you need narrower control:

```bash
sase config init
sase config init --check
sase init config # compatibility alias
sase machine init
sase machine init --check
sase init machine # compatibility alias
sase memory init --no-commit
sase memory init --enable-project-memory --no-commit
sase memory init --check
sase memory list
sase memory log
sase memory log --path generated_skills.md
sase memory log --id <read-id>
sase repo init
sase repo init --check
sase repo init --diff --no-commit
sase init repo # alias for sase repo init
sase service init --check
sase service init --diff
sase service init --yes
sase init service # compatibility alias for sase service init
sase instructions list
sase skill list
sase skill init --dry-run
sase skill log
sase skill log --runtime codex

# Agent-side audited operations, normally run from a SASE-launched agent:
sase memory read generated_skills.md --reason "Need generated skill context"
sase skill use sase_plan --reason "Need to prepare an implementation plan"
```

Start with `sase init -c` or `sase memory init --check` when you only want a drift
report. Home-root write drift is a deferred warning on `--check`; project-root drift
still fails. After that, `sase memory init --no-commit` is the usual first apply run for
memory because it writes the generated files but skips the project git commit/pull/push
path. It is not a dry run: it can still write project files, write home memory, and
follow home-level `use_chezmoi` deployment, except that agents and monitors skip the
home write, commit, and apply unless `SASE_GATE_COMMAND=1` or
`SASE_HOME_MEMORY_DEPLOY_BYPASS` holds a reason. `sase init memory` remains a
compatibility alias for `sase memory init`, and `sase init config` remains a
compatibility alias for `sase config init`, `sase init repo` is an alias for
`sase repo init`, and `sase init skills` remains an alias for `sase skill init`.
`sase init machine` remains a compatibility alias for `sase machine init`, and
`sase init service` remains a compatibility alias for `sase service init` — except that
the alias has no preview step or `--yes` flag: unless you pass `--check`, it applies the
service plan immediately.

## Commands

The generated [CLI reference](../cli/index.md) lists exact commands and options. The
relevant groups are [init](../cli/init.md), [config](../cli/config.md),
[machine](../cli/machine.md), [memory](../cli/memory.md),
[instructions](../cli/instructions.md), [repo](../cli/repo.md),
[service](../cli/service.md), and [skill](../cli/skill.md).

Advanced deploy controls such as `--no-commit`, `--no-push`, and `--no-apply` live on
explicit subcommands rather than the bare coordinator. Scoped `--check` flags also live
on explicit subcommands when you want to validate only memory, repository/sidecar
wiring, native service installation, or generated skill files.

## Agent Documents

`sase instructions list` is the read-only inventory for agent instruction documents:
root `AGENTS.md` plus the project-root provider copy `CLAUDE.md` (a full copy of
`AGENTS.md`). Home and chezmoi roots also keep `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`
copies of `AGENTS.md`. agy, Qwen, and OpenCode read `AGENTS.md`.

```bash
sase instructions list
```

With no subcommand, `sase instructions` defaults to `sase instructions list`. The
inventory shows project, subdirectory, home, and chezmoi-source `AGENTS.md` files, their
H1 titles, whether they look managed, core/reference memory reference counts, and nearby
provider instruction file status. It never writes files; `sase memory init` is the
command that creates or refreshes these documents. For instruction-surface and
provider-delivery details, see [Instruction Bundles](../memory/instruction-bundles.md).

## Repository Initialization

`sase repo init` initializes every enabled `repos.sidecar` entry for the current managed
project. It also adds the explicit project-local plans, beads, and research declarations
when absent:

```yaml
repos:
  sidecar:
    builtin:
      plans:
        auto_clone: true
      beads:
        auto_sync: true
    custom:
      research:
        description: Durable SASE research reports and generated media.
```

Reserved roles are written under `repos.sidecar.builtin` and document sidecars under
`repos.sidecar.custom`. If `repos.sidecar` still uses the removed list form, the write
stops with an error asking you to migrate it to the two-bucket mapping first;
`sase doctor` names the target bucket for each existing entry.

An existing entry for any of those roles is preserved verbatim, including
`disabled: true`; disabling research is the project-local opt-out. The unpinned research
entry derives `<owner>/<project>--research` from the primary GitHub repository, and the
beads entry likewise derives `<owner>/<project>--beads`. The write uses SASE's
comment-preserving configuration editor. The same initializer adds `/sase/repos/` to the
tracked root `.gitignore`; those two project-file changes use the normal
commit/pull/push path unless `--no-commit` is supplied.

For each enabled sidecar, provider discovery runs before materialization. A missing
remote gets its own default-no prompt naming the visibility, provider, full repository
name, and host. Only `y` or `yes` authorizes creation; `--yes`, blank answers, EOF,
interruption, and non-interactive stdin cannot authorize it. The configured `repo:` pin
and `visibility:` are passed to the provider. For a missing remote, initialization fails
closed if the provider would create it with a different visibility; it does not verify
an existing remote's visibility.

A sidecar repository may be created public only when the primary repository is verified
public. When the primary repository is private — or when its visibility cannot be
verified — every sidecar is created private instead, even when its entry says
`visibility: public`, and the public-only `attachments` sidecar is skipped entirely. A
definitively private primary is also persisted as `visibility: private` in the project's
`repos.sidecar` entries, so config-only readers stay consistent; an unverifiable primary
still gets private sidecars but leaves the config untouched. `sase doctor` warns about
any recorded sidecar that is still public while the primary is private (see
`project.sidecar_visibility`).

When non-interactive bare `sase init --yes` discovers a missing sidecar remote, it
writes the project wiring, reports the missing repository, and leaves creation for a
later interactive `sase repo init`. This keeps automated onboarding and post-commit
hooks non-blocking without allowing `--yes` to authorize remote creation.

Managed projects also resolve an implicit public `<project>--agents` sidecar unless
project configuration disables it, sets `default_linked_repos: false`, or supplies an
explicit replacement. Its missing remote receives a separate, agent-specific, default-no
creation prompt; `--yes` never authorizes publishing agent history. Declining that
prompt continues initialization without the agents sidecar, while another missing
sidecar can still make initialization incomplete. Before accepting, review the
transported prompt, chat, commit, and relationship data and set a project-local
`visibility: private` override when appropriate. Publication requires the selected
overlay's complete `id.username` / `id.machine_name` identity; run `sase config init`
first to migrate a top-level `machine_name` setting. The initialized README explains the
full project-scoped hood privacy implications, owner-sharded v2 browsing layout,
active/optional transcript behavior, and synchronization/recovery commands. Existing v1
payload remains read-only during migration. See [Agent Hood Synchronization](index.md).

The same managed-project resolution adds an implicit private
`<project>--attachments-private` sidecar unless that role is already configured,
disabled, or suppressed with `default_linked_repos: false`. Its missing remote gets its
own default-no prompt. The prompt says the repository holds private bead attachment
bytes and names `repos.sidecar.builtin.attachments-private.disabled: true` as the
opt-out. Declining continues initialization without that sidecar. The clone is a bare
partial repository at `~/.sase/projects/<project_key>/repos/attachments-private`. It has
no worktree and no README, so initialization prints the clone path itself. A
`visibility: public` override resolves to `private` for remote creation. Check an
existing remote's visibility before storing attachments there. On projects with a public
beads sidecar whose primary repository is verified public, initialization also offers to
create the public `<project>--attachments` sidecar that holds public attachment bytes;
the prompt names its PUBLIC visibility and refuses when the beads sidecar is not public.
Declining leaves public uploads queued with `⇡ pending upload` until the store exists,
and `repos.sidecar.builtin.attachments.disabled: true` opts out. Disabling either
attachments role later hides it even when a clone already exists; use `-L/--local-only`
for a particular attachment. See
[Attachments](../work-units/bead-attachments.md#attachments).

`plans`, `beads`, `agents`, and the default `research` presentation preset receive
illustrated README guides and directory-map assets. `attachments-private` does not.
Rerunning `sase repo init` upgrades a missing or stale agents infographic while
preserving the manifest-derived root index of a populated agents sidecar. Custom sidecar
roles receive a deterministic generic README using their configured description.
Initialized guide files are committed and pushed in their respective sidecar
repositories. When plans are available, the split SDD store record records every
initialized role; `research` is not required.

The beads sidecar holds the project's durable bead state at its repository root. When it
is created for a project whose bead state still lives in the plans clone,
`sase repo init` adopts that state as part of the same run: it copies the store into the
beads clone, commits it as `Import bead state from <plans-repo>@<sha>` and pushes,
writes the schema-3 store record that makes bead commands resolve to the new repository,
and only then removes `beads/` from the plans clone. `sase repo init --check` lists that
data move as a distinct planned action. Adoption is idempotent, so rerunning
initialization after a partial failure retries cleanly; see
[SDD Storage](../../contribute/sdd-storage.md) for the full transaction and its failure
semantics.

```bash
sase repo init                    # initialize sidecars and project wiring
sase repo init --check            # preview without network probes or writes
sase repo init --diff             # show file diffs, then apply
sase repo init --no-commit        # write project config/ignore changes without committing
sase init repo                    # alias for sase repo init
```

Both apply and `--check` first read the current repository's own `sase/sase.yml` (with
root `sase.yml` as a fallback). A missing or false `is_sase_managed` marker makes the
command an informative, successful no-op before provider work; malformed YAML and
non-boolean marker values fail safely. `sase init repo` delegates to the same repository
initializer.

Built-in bare-git projects keep their provider-owned in-tree SDD layout. For those
projects, `sase repo init` refreshes the existing generated SDD guides while still
maintaining the managed sidecar declarations and repository ignore rule. Keep conceptual
SDD documentation in [the plan reference](../work-units/plans.md) and storage-mode
details in [docs/contribute/sdd-storage.md](../../contribute/sdd-storage.md).

## Skill Initialization

Generated skills start as Markdown sources in a canonical `skills/` directory that set a
truthy `skill` frontmatter field — see [Skill Field](../macros/fields.md#skill-field).
`sase skill list` is the read-only inventory: it shows loaded skill sources, the
providers they target, and whether generated `SKILL.md` files are current, stale, or
missing. It also reports misplaced sources in a "Misplaced Sources" panel. Bare
`sase skill` shows the same dashboard.

`sase skill init` renders those sources into provider-specific `SKILL.md` files, and
exits non-zero without writing anything while any placement violation remains. Sources
include the bundled `src/sase/macros/skills/` templates plus project, home, and plugin
skill directories. By default, generated skill files include a first-step
`sase skill use <name> --reason ...` directive so agent skill usage is attributable in
the same project audit surface as memory reads; `sase skill log` summarizes and inspects
those recorded skill-use rows. A source can set `log_skill_use: false` to omit that
directive. The usual workflow is to inspect first, preview writes, commit the source
change, and only then deploy:

```bash
sase skill list
sase skill init --dry-run
sase skill init --diff
# commit the skill source change and land it on the canonical branch first
sase skill init --force
```

Without `use_chezmoi`, generated skill files are written directly under the provider's
home-directory skill targets. When `use_chezmoi: true`, skill initialization writes
through the chezmoi-managed home tree and can commit, push, and apply those dotfile
changes. The `--no-commit`, `--no-push`, and `--no-apply` flags only affect that chezmoi
deployment sequence. `sase init skills` still works as a compatibility alias for
`sase skill init`.

### Commit Before Deploying

The chezmoi destination is a single global tree shared by every workspace, so a deploy
from a workspace whose sources are not canonical publishes content that exists in no
landed sase revision and can revert another agent's deployment. Two guards enforce that,
and they apply only to writing chezmoi deploys — `--check`, `--diff`, `--dry-run`, and
non-chezmoi targets are unaffected:

- **Source integrity.** The deploy is refused when `src/sase/macros/` has uncommitted
  changes, or when the invoking workspace's `HEAD` is not an ancestor of the canonical
  branch. The error names the offending files or the unmerged commits.
- **Provenance manifest.** Each deploy records the source commit and a macro-set hash in
  `.sase-skills-manifest.json` under the chezmoi source root. A deploy whose source
  commit differs from the recorded one is refused rather than allowed to move the
  destination backwards. A missing or unparsable manifest bootstraps cleanly.

So the corrected workflow is: iterate with `--diff` / `--dry-run`, commit the template
change to the sase repo, land it on the canonical branch, and deploy from that clean
merged tree.

Because of those guards, `--check` does not fail on chezmoi deploy drift it has no way
to resolve. When chezmoi deployment is enabled and generated skill files differ from
their deployed chezmoi copies, `sase init skills --check` counts those files, reports
them as a warning telling you to rerun `sase init skills` after landing, and drops them
from its action list — so the check itself passes. If a dirty or unlanded tree would
also make the real deploy refuse, that source-integrity reason is reported as a second
warning. This keeps an unrelated read-only check from either failing for drift only a
land can clear or triggering a mutating deploy as a side effect. Writing plans
(interactive onboarding and direct deploys) are unaffected, as is the deploy-side
integrity refusal. `sase validate` surfaces these warnings in its own `Warnings:` block;
see [`sase validate`](../cli/validate.md#sase-validate).

`--allow-dirty` overrides the source-integrity guard and `--force` overrides the
manifest guard. Both are deliberate escape hatches that can revert other agents'
deployments; reach for them only when you know the destination is stale. `--force` still
records the new manifest entry.

See [Macro Skill Field](../macros/fields.md#skill-field) for the skill-source contract
and bundled skill list.

## Related

- [Agents and workspaces](index.md) — the section hub.

## `sase init`

Bare `sase init` is the onboarding coordinator for SASE-managed resources. It runs
read-only planners for config (owner identity), machine enrollment, memory,
repositories, service, and skills, in that order, prints a grouped summary, and prompts
once per initializer that needs work when stdin is interactive. Non-interactive runs
never prompt; they print the drift summary and ask the caller to rerun with `--yes`.
That flag runs needed initializers but cannot authorize creation of a missing provider
sidecar repository, which always requires its own interactive `y`/`yes` response. The
memory planner (which owns agent-document initialization) only generates managed project
`AGENTS.md` from bare `sase init` when the current project's own `sase/sase.yml` sets
`is_sase_managed: true`. The repository planner uses that same local marker and skips
unmanaged repositories before provider work. Neither planner infers project ownership
from `memory.h1_title`, existing memory notes, lifecycle state, or merged configuration.
See [Initialization](index.md) for the full flow.

`--all` applies that coordinator to every registered enabled main project from its
recorded primary workspace, even when the command starts outside a project. It excludes
disabled projects, internal sibling backing records, `home`, and other system-managed
records, continues after per-project failures, and returns non-zero if any project has
drift, is unavailable, or fails. `--all --check` is read-only, while non-interactive
apply still requires `--yes`. `--all` is incompatible with `--enable-project-memory` and
with explicit compatibility subcommands. `-p/--project` names a subset of the same
enabled projects instead and has the same restrictions, plus it cannot be combined with
`--all`.

Advanced deploy controls stay on explicit subcommands such as
`sase memory init --no-commit` and `sase skill init --no-push`. The compatibility
subcommands `sase init config`, `sase init machine`, `sase init memory`,
`sase init repo`, and `sase init skills` accept the flags of `sase config init`,
`sase machine init`, `sase memory init`, `sase repo init`, and `sase skill init`.

<a id="cli-options-19"></a> Moved to [sase init](initialization.md#sase-init).

## `sase init repo`

`sase init repo` is an alias for `sase repo init`. For targets marked
`is_sase_managed: true` in their own `sase/sase.yml`, it initializes configured
sidecars, creates or refreshes generated README files, ensures the managed plans and
research declarations, and maintains the root `/sase/repos/` ignore rule. Missing or
false markers produce an informative successful no-op, while invalid local configuration
fails before provider or filesystem work. The command always targets the Git repository
that contains the current directory; it has no `--path` option. GitHub setup creates
missing sidecars with their configured public/private visibility. Bare-git projects
refresh generated files automatically during repository setup and first SDD writes; the
explicit command remains useful for refreshes and `--check` audits.

When the GitHub sidecar is missing, this alias uses the same default-no
repository-specific confirmation as `sase repo init`. EOF, interruption, and any answer
other than `y`/`yes` return nonzero before remote creation. Generic `--yes` approval
never authorizes repository creation; non-interactive bare onboarding instead reports
the missing remote and defers its creation.

<a id="cli-options-24"></a> Moved to [sase init](../cli/init.md).
