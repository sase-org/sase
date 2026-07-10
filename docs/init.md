# Initialization

SASE initialization commands create or refresh durable files that agents and companion tools rely on. Bare `sase init`
checks the current project and home setup first, then either reports that everything is current or shows the
initializers that need attention:

```bash
sase init -c       # report drift without writing
sase init          # prompt before each needed initializer
sase init --yes    # run every needed initializer in order
sase init -M --yes # opt this project into managed memory, then initialize it
sase init --all --check # check every active main project without writing
sase init --all         # visit every active main project; prompt when interactive
sase init --all --yes   # initialize every active main project without prompting
```

The coordinator plans in registry order: memory, SDD, then skills. Memory initialization owns agent-document
initialization (managed `AGENTS.md` and its provider instruction copies). Planning is read-only. In non-interactive
shells, bare `sase init` reports drift and exits non-zero instead of prompting; use `sase init --yes` when you want an
unattended apply run. Apply runs can write project files, deploy home files through chezmoi when configured, and use
each initializer's normal commit/push behavior. Bare `sase init` only lets memory init generate managed project memory
and root `AGENTS.md` content when the current project's own `./sase.yml` sets `memory.enabled: true`. Without that
explicit local opt-in, it leaves project memory and the root `AGENTS.md` untouched while still copying every existing
project-tree `AGENTS.md` to the provider instruction files beside it.

`sase init --all` uses the registered project inventory, so it can be run inside a project or from an unrelated
directory. It visits active main projects only: inactive projects, sibling bookkeeping records, and the system-managed
`home` project are excluded. Each project runs from its recorded primary workspace. Missing workspaces, invalid project
records, planning errors, and initializer failures are reported under that project's heading without preventing later
projects from being attempted; the final summary and exit status reflect the whole batch. `--all --check` is fully
read-only and exits non-zero if any project has drift or cannot be checked. Without a TTY, `--all` remains read-only
unless `--yes` is supplied.

Use `-M, --enable-project-memory` to create or update the current project's `./sase.yml` with `memory.enabled: true`
before normal initialization. The option preserves other local configuration and is available on both bare `sase init`
and `sase memory init` (as well as the `sase init memory` compatibility alias). Because it writes configuration, it
cannot be combined with `--check`. It also cannot be combined with `--all`; managed project memory must be enabled one
project at a time.

Explicit subcommands are still available when you need narrower control:

```bash
sase memory agent-docs list
sase memory init --no-commit
sase memory init --enable-project-memory --no-commit
sase memory init --check
sase memory list
sase memory review --list
sase memory log
sase memory log --include proposals
sase memory log --path generated_skills.md
sase memory log --id <read-id>
sase init sdd
sase init sdd --check
sase skill list
sase skill init --dry-run
sase skill log
sase skill log --runtime codex

# Agent-side audited operations, normally run from a SASE-launched agent:
sase memory read generated_skills.md --reason "Need generated skill context"
sase skill use sase_plan --reason "Need to prepare an implementation plan"
sase memory write --title "Generated skills" --slug generated_skills --evidence chat:abc123 --body "Durable memory body" --notify
```

Start with `sase init -c` or `sase memory init --check` when you only want a drift report. After that,
`sase memory init --no-commit` is the usual first apply run for memory because it writes the generated files but skips
the project git commit/pull/push path. It is not a dry run: it can still write project files, write home memory, and
follow home-level `use_chezmoi` deployment. `sase init memory` remains a compatibility alias for `sase memory init`, and
`sase init skills` remains a compatibility alias for `sase skill init`.

## Commands

| Command                                 | Purpose                                                                                     |
| --------------------------------------- | ------------------------------------------------------------------------------------------- |
| `sase init`                             | Check memory, SDD, and skills; prompt once per needed initializer in interactive shells.    |
| `sase init -a, --all`                   | Check or initialize every registered active main project, continuing after project errors.  |
| `sase init -c, --check`                 | Report initialization drift without writing and exit non-zero when changes are needed.      |
| `sase init -M, --enable-project-memory` | Opt the current project into managed memory before running initialization.                  |
| `sase init --yes`                       | Run every needed initializer in memory, SDD, skills order without prompting.                |
| `sase memory`                           | Alias for `sase memory list`.                                                               |
| `sase memory list`                      | Inspect loaded, referenced, available, and missing memory files for the current root.       |
| `sase memory agent-docs`                | Alias for `sase memory agent-docs list`.                                                    |
| `sase memory agent-docs list`           | Inspect project, home, and chezmoi `AGENTS.md` files and nearby provider instruction files. |
| `sase memory read <path>`               | Agent-side read of one long-term memory file with an attributable audit event.              |
| `sase memory write`                     | Create an attributable long-term memory proposal for human review.                          |
| `sase memory review`                    | List, inspect, approve, edit, or reject pending memory proposals.                           |
| `sase memory log`                       | Summarize audited long-term memory reads.                                                   |
| `sase memory log --include proposals`   | Include proposal and review events in the memory audit surface.                             |
| `sase memory log --path <path>`         | Show a path-level summary and matching individual read events.                              |
| `sase memory log --id <read-id>`        | Show one full audited read event by id or unambiguous id prefix.                            |
| `sase memory init`                      | Refresh home and opted-in project memory plus provider copies for existing `AGENTS.md`.     |
| `sase memory init --check`              | Report memory initialization drift without writing files.                                   |
| `sase memory init -M`                   | Create/update `./sase.yml` to enable project memory, then initialize it.                    |
| `sase memory init -C`                   | Write memory files but skip the project git commit/pull/push path.                          |
| `sase init memory`                      | Compatibility alias for `sase memory init`.                                                 |
| `sase init sdd`                         | Compatibility alias for the provider-owned `sase sdd init` flow.                            |
| `sase init sdd --check`                 | Report provider and generated-file work without writing files.                              |
| `sase skill`                            | Alias for `sase skill list`.                                                                |
| `sase skill list`                       | Inspect generated skill sources, provider targets, and deployed-file drift without writing. |
| `sase skill init`                       | Generate skill files; existing files require confirmation or `--force`.                     |
| `sase skill init --dry-run`             | Preview generated skill target paths without writing files.                                 |
| `sase skill init --check`               | Report generated skill-file drift without writing files.                                    |
| `sase skill init --force`               | Generate and overwrite deployed skill files without confirmation.                           |
| `sase skill init -p <provider>`         | Deploy only one provider's generated skill files.                                           |
| `sase skill log`                        | Summarize or inspect audited generated skill-use events.                                    |
| `sase skill use <name>`                 | Agent-side audit event recording that a generated skill was used.                           |
| `sase init skills`                      | Compatibility alias for `sase skill init`.                                                  |

Advanced deploy controls such as `--no-commit`, `--no-push`, and `--no-apply` live on explicit subcommands rather than
the bare coordinator. Scoped `--check` flags also live on explicit subcommands when you want to validate only memory,
only SDD, or only skill generated files.

## Agent Documents

`sase memory agent-docs list` is the read-only inventory for agent instruction documents: root `AGENTS.md` plus provider
instruction files such as `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md` (each a full copy of `AGENTS.md`).

```bash
sase memory agent-docs list
```

With no subcommand, `sase memory agent-docs` defaults to `sase memory agent-docs list`. The inventory shows project,
subdirectory, home, and chezmoi-source `AGENTS.md` files, their H1 titles, whether they look managed, short/long memory
reference counts, and nearby provider instruction file status. It never writes files; `sase memory init` is the command
that creates or refreshes these documents.

## Memory Initialization

`sase memory init` always initializes the home-level memory surface. It initializes project-local memory only when the
project explicitly opts in, and independently owns provider instruction copies:

`sase memory init -M` is the convenience path for a new active main project: it creates or updates `./sase.yml` with the
required opt-in before loading configuration and running the normal initializer.

- Project memory under `./memory/`, including `memory/README.md` and flat note files with `type`/`parent` frontmatter,
  only when the project's own `./sase.yml` contains `memory.enabled: true`.
- Home memory under `~/memory/`, or under `~/.local/share/chezmoi/home/` when `use_chezmoi: true`.
- A managed project `AGENTS.md` only with that same explicit opt-in. `amd_h1_title` customizes its H1; otherwise SASE
  derives the stable `<project> - Agent Instructions` title.
- Provider instruction files `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`; each is a byte-for-byte copy of
  that root's final `AGENTS.md`. Chezmoi home source roots use static `.md` files (not `*.md.tmpl` imports), since the
  inlined `AGENTS.md` carries no template variables. Legacy `@AGENTS.md` / `@/path/to/home/AGENTS.md` import shims and
  `*.md.tmpl` sources are still recognized and migrated to full copies.

For an enabled project, `sase memory init` inlines each short-term note's body into Tier 1, renders Tier 2 from
long-note descriptions, adds missing canonical frontmatter, and validates reachability. Missing, false, merged-global,
or `amd_h1_title`-only configuration does not authorize any project memory or root `AGENTS.md` creation, refresh, or
validation. Projects that previously relied on a title or inferred onboarding must add:

```yaml
memory:
  enabled: true
```

Home and chezmoi-home initialization is unchanged: those roots remain managed and take an optional title from user
config (`~/.config/sase/sase.yml`, overlays, or source-side `dot_config/sase/`).

Provider copying is the exception to project ownership. In both managed and unmanaged projects, every readable
`AGENTS.md` found with the normal project-tree pruning rules is copied byte-for-byte to `CLAUDE.md`, `GEMINI.md`,
`QWEN.md`, and `OPENCODE.md` beside it. A directory with no `AGENTS.md` is untouched, including any standalone provider
files already there.

When `use_chezmoi: true`, the home files are written to the chezmoi source tree. The command can then commit those home
changes and run `chezmoi apply --force`; `--no-commit` does not disable that home deployment path.

The generated `memory/sase.md` summarizes workspace naming and linked repositories. Project memory reads linked-repo
descriptions from the project-local `./sase.yml`; home memory reads them from the global config
`~/.config/sase/sase.yml`, or from the chezmoi-managed config path when `use_chezmoi: true`. Generated memory includes
the uniform `sase workspace open` instructions for every configured linked repo.

Every configured `linked_repos` entry (or its deprecated `sibling_repos` alias) must have a non-empty `description`.
Initialization fails instead of generating ambiguous memory when a description is missing.

By default, project memory initialization runs the configured precommit command, stages generated project files, commits
them with the standard memory-init commit message, pulls with rebase, and pushes. Use `sase memory init --check` for a
read-only drift check, or `sase memory init --no-commit` when you want to review generated project files before
committing. `--no-commit` only skips the project deploy path; home memory deployment still follows `use_chezmoi` when it
is enabled.

For managed roots, memory validation is reachability-based: Markdown files under `memory/` must be reachable from
`AGENTS.md` directly or through transitive `@memory/...` or `memory/...` references. Unreferenced memory files make the
command fail so important agent context is not silently ignored. Unmanaged project memory is not validated.

## Memory Context List

`sase memory list`, or bare `sase memory`, renders a read-only dashboard for the current directory. It reports:

- `loaded` files reached by transitive `@...` references from `AGENTS.md` in the project or home context.
- `referenced` files mentioned by plain `memory/...` text from loaded context or by audited `sase memory read`
  instructions. These are visible in the dashboard, but their contents are not loaded unless another `@...` edge reaches
  them.
- `available` files present under project or home `memory/` that the current launch context does not reach.
- `missing` referenced memory paths that do not exist.

The dashboard includes approximate local token estimates for loaded memory context.

For day-to-day read/write operations, including audited reads and reviewed long-term memory proposals, see
[Memory](memory.md).

## Memory Read Audit Log

`sase memory read <memory-relative-path> -r <reason>` is the audited path for agent-initiated long-term memory reads.
The path is relative to `memory/`; the command allows `type: long` Markdown notes and rejects `type: short` notes
because short-term memory is expected to arrive through instruction loading. The command strips one leading YAML
frontmatter block from stdout and appends `## Children` when nested long notes exist, but the audit log records only
metadata such as path, agent name, timestamp, cwd, byte count, and reason.

Every read must include a non-empty reason via `-r` or `--reason`. The command also requires agent attribution from
`SASE_AGENT_NAME`, `SASE_AGENT`, or `SASE_ARTIFACTS_DIR/agent_meta.json`; unattributed reads fail instead of writing a
log row. Human shell users normally inspect files directly and use `sase memory review` for promotion decisions.

`sase memory write` creates an attributable proposal under `~/.sase/projects/<project>/` and never writes canonical
memory files directly. It uses the same agent-attribution rules as `read`; `--manual-author` is intended for tests and
demos. Pass `--notify` when you want a best-effort `memory.proposed` notification in the SASE inbox.
`sase memory review` is the human promotion path for listing, showing, approving, editing, or rejecting those proposals.

`sase memory log` reads the project-scoped audit log from SASE state under `~/.sase/projects/<project>/`, not from the
repo. Use `--path` or `--agent` to drill down to matching read events, `--id <read-id>` to inspect one event, and
`--json` for deterministic machine-readable output. Add `--include proposals` to include proposal and review ledger
events alongside read-log summaries.

```bash
# read requires SASE agent identity; write requires agent identity unless --manual-author is used for demos
sase memory read generated_skills.md --reason "Need generated skill context"
sase memory write --title "Generated skills" --slug generated_skills --evidence chat:abc123 --body "Durable memory body" --notify
sase memory review --list
sase memory log
sase memory log --include proposals
sase memory log --path generated_skills.md
sase memory log --id <read-id>
```

## SDD Initialization

`sase init sdd` is the compatibility alias for `sase sdd init`. It materializes the provider-selected SDD store, then
creates or refreshes generated SDD guides and the directory-map asset. GitHub setup finds or creates the required
`<owner>/<repo>--sdd` companion, applies the `sase--sdd` label, and transactionally imports legacy in-tree and local
artifacts. New companions are public by default; existing private companions remain private. Bare-git projects keep
their provider-owned in-tree layout.

```bash
sase init sdd
sase init sdd --check
sase init sdd --path /path/to/project
```

Keep conceptual SDD documentation in [docs/sdd.md](sdd.md) and storage-mode details in
[docs/sdd_storage.md](sdd_storage.md). The files generated by `sase init sdd` are intentionally short project-local
guides and are safe to overwrite. Use `--check` to preview provider work and generated-file changes without writing.

Built-in bare-git projects run this same generated-file refresh automatically during first-use `#git:<project>`
initialization, existing bare-repo registration, workspace materialization, and the first in-tree SDD write. Manual
`sase init sdd` is still useful when you want an explicit refresh or a drift check.

## Skill Initialization

Generated skills start as xprompt sources marked with a `skill` frontmatter field. `sase skill list` is the read-only
inventory: it shows loaded skill sources, the providers they target, and whether generated `SKILL.md` files are current,
stale, or missing. Bare `sase skill` shows the same dashboard.

`sase skill init` renders those sources into provider-specific `SKILL.md` files. Sources include bundled skill xprompts
and user/runtime xprompt catalog entries. By default, generated skill files include a first-step
`sase skill use <name> --reason ...` directive so agent skill usage is attributable in the same project audit surface as
memory reads; `sase skill log` summarizes and inspects those recorded skill-use rows. A source can set
`log_skill_use: false` to omit that directive. The usual workflow is to inspect first, preview writes, then deploy:

```bash
sase skill list
sase skill init --dry-run
sase skill init --force
```

Without `use_chezmoi`, generated skill files are written directly under the provider's home-directory skill targets.
When `use_chezmoi: true`, skill initialization writes through the chezmoi-managed home tree and can commit, push, and
apply those dotfile changes. The `--no-commit`, `--no-push`, and `--no-apply` flags only affect that chezmoi deployment
sequence. `sase init skills` still works as a compatibility alias for `sase skill init`.

See [XPrompt Skill Field](xprompt.md#skill-field) for the skill-source contract and bundled skill list.
