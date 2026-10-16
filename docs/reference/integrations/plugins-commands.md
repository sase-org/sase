---
title: Command plugins
description: Look up how plugins mount top-level sase commands.
---

# Command plugins

This page describes plugin-mounted top-level `sase <name>` commands.

## Command Plugins {#command-plugins-1}

A plugin can mount a top-level `sase <name>` command — for example, `sase-listen` ships
`sase listen`, which behaves exactly like the standalone `sase-listen` binary. Wherever
a plugin command appears, it renders as the same command chip: `❯ sase listen`.

A distribution declares one entry point per command in the `sase_commands` group. The
entry-point **name** is the command name, and the **value** is a module (or
`module:object`) exposing this contract:

| Member                  | Required | Meaning                                                                                            |
| ----------------------- | -------- | -------------------------------------------------------------------------------------------------- |
| `main(argv, prog)`      | yes      | Runs the command on the untouched argv after the command word. Returns an exit code (`None` is 0). |
| `build_parser(prog)`    | yes      | The full parser, used only for completion — never for dispatch. It must have no side effects.      |
| `SUMMARY: str`          | no       | One-line description for help and completion. Falls back to the distribution's `Summary` metadata. |
| `SASE_COMMAND_API: int` | no       | Contract version. Absent means 1; newer than sase supports is refused with an update hint.         |

```toml
# pyproject.toml
[project.entry-points."sase_commands"]
listen = "sase_listen.sase_command"
```

```python
# sase_listen/sase_command.py — cheap to import, and never imports sase
SASE_COMMAND_API = 1
SUMMARY = "Turn Markdown into chaptered MP3 audio editions"


def build_parser(prog="sase listen"):
    from sase_listen.cli import app

    return app.build_parser(prog=prog)


def main(argv=None, *, prog="sase listen"):
    from sase_listen import cli

    return cli.main(argv, prog=prog)
```

The execution model is in-process: sase routes, the plugin parses. Sase sets `sys.argv`
to `[f"sase {name}", *argv]` and calls `main(argv, prog=f"sase {name}")`, so libraries
that read `sys.argv` see a standalone-shaped invocation. `SystemExit` raised inside the
plugin propagates unchanged, and exceptions from the plugin's own `main` are never
caught by sase — parity with the standalone binary holds by construction. Sase never
post-processes a plugin subtree: no default-`list` delegation, no sase help formatter. A
plugin may not patch or extend built-in commands, and plugin subtrees are exempt from
sase's CLI rules.

Name rules and collisions:

- Names must match `^[a-z][a-z0-9-]{0,31}$`.
- Built-in command names (including legacy aliases), legacy root words, and `help` are
  reserved — built-ins always win and a plugin claiming one stays shadowed.
- If two distributions claim one name, the command is disabled for both and every
  surface names both owners. Sase never picks a winner by entry-point order.

Path completion: an argparse action may set `action.sase_completion = "path"` or `"dir"`
to request path completion; otherwise only argparse `choices` produce candidates.

Disable switches: `SASE_DISABLE_PLUGINS` or `SASE_DISABLE_PLUGIN_COMMANDS` turns the
whole group off. Both are permanent operational switches, not feature flags.

### Where a command shows up

Catalog panels, full help, and operation results label plugin commands with
`❯ sase <name>`. Type `sase <name>` to run the command; `❯` is a visual marker. The
label can also describe an uninstalled command or a command disabled by a name conflict,
so a chip alone does not establish that the command can run.

A **declared** command is named in a plugin's package metadata. A **mounted** command
has an eligible name with exactly one owner and is exposed on `sase`. Mounting does not
establish that its adapter can load or its parser can be built; doctor checks those
separately. The owning **distribution** is the installed Python package, whose name can
differ from the command name.

**Help.** Compact `sase --help` lists mounted commands in a **Plugin commands** group:
name, summary, and distribution. The group is omitted when none are mounted, and a load
failure falls back to the distribution's summary in compact help, so a command listed
there may still fail to run. `sase --full-help` adds the chip, the summary, and
`(distribution version)`. Problem rows (failed to load, shadowed by a built-in, invalid
name, or two distributions claiming one name) are marked `⚠` with a one-line reason. The
footer says to manage plugins with `sase plugin list` or the Updates tab.

**Doctor.** `sase doctor` runs `plugins.commands` by default. It loads mounted command
adapters and reports command and claim problems; its mounted count includes only
adapters that loaded successfully. A load failure or a name collision is `ERROR`. A
shadowed or invalid name is `WARN`. Add `sase doctor -D -C plugins.commands-parsers` to
build each parser as well; a parser failure is `ERROR`. The report currently suggests
`sase plugin update <command-name>` for a load or parser failure. If that name does not
identify the plugin in the catalog, use the owning distribution shown in the diagnostic
with `sase plugin show <distribution>` to find the plugin to update. For a collision,
doctor suggests uninstalling the first owner in its alphabetically sorted list; it does
not uninstall anything automatically. Choose which plugin to keep before running an
uninstall command.

**Catalog.** `sase plugin list` prints each installed command's chip in that plugin's
entry-point cell. `sase plugin show` adds a **Commands** row: one chip per installed
command, with its summary and a yellow note for a name conflict, shadowed name, or
invalid name. Adapter load failures are diagnosed by full help and doctor. An
uninstalled plugin shows the upstream preview in dim, labeled
`added on install · declared in pyproject.toml`, and only when that preview is known. An
unknown preview omits the row. `sase plugin list -j` includes the installed declarations
in each entry's `installed.commands` array, including names that cannot mount.

**Updates tab.** An installed plugin row shows its chips in the row accent. An
uninstalled row shows the cached declared preview in dim. Selecting it can fetch a
preview for the detail panel; drawing the list itself does not fetch one. The detail
panel uses the same Commands row as `sase plugin show`.

The confirmation modal previews changes before running an operation. Command lines are
omitted when the relevant metadata is unknown:

- Install: `❯ Adds a new command: ❯ sase <name>` for each declared command. A batch row
  gains ` (adds ❯ sase <name>, ...)`.
- Update: a single-plugin managed update shows `❯ Adds command:` and
  `❯ Removes command:` when the upstream declarations differ from the installed set. No
  command lines appear when the sets agree. Multi-plugin and editable-checkout updates
  do not show this comparison.
- Uninstall: `❯ Removes command: ❯ sase <name>` for each installed declaration,
  including commands that cannot currently mount.

In a single-plugin install confirmation, a declared name that matches a built-in warns
`sase <name> would be shadowed`. A name another installed plugin already mounts warns
`sase <name> would conflict with <distribution> — both would be disabled`. Those
warnings are yellow and appear before you confirm; batch-install and update
confirmations do not show these collision warnings. After the change, the completion
toast labels net added command names as `new command` and removed names as `removed`.
These labels describe metadata changes; use full help or doctor to check whether the
commands can load.

Previews are best-effort. An unknown preview renders no command lines; it does not mean
the plugin declares no commands.

### Migrating from the standalone `sase-listen`

```bash
sase plugin install listen
sase listen doctor
uv tool uninstall sase-listen
```

Migrate the feed host last, after the feed-host fallback is released.

## Related

- [Plugins](plugins.md) — groups, catalog, and disable switches.
- [Installing and updating plugins](plugins-update.md) — install and update commands.
- [Plugin API](../../contribute/plugin-api.md) — writing a command plugin.
- [Integrations](index.md) — other integration pages.
