# SASE Pager

`sase pager` opens artifact references, file paths, or stdin in the SASE link-traversing
pager when the `link_pager` feature flag is enabled. The same surface is used by
`sase bead show` when `$SASE_PAGER` resolves to `sase pager`.

With redirected stdout, `--plain`, no controlling terminal, or the feature flag
disabled, the command writes plain text. That makes it safe in pipelines and safe as an
unconditional pager command.

## Usage

```bash
sase -f link_pager pager bead:sase-uk.7 src/sase/cli_pager.py
git show --stat | sase -f link_pager pager -t "git show"
SASE_PAGER="sase pager" sase -f link_pager bead show sase-uk.7
```

```text
sase pager [-c auto|always|never] [-l auto|never] [-p] [-t TITLE] [-w WIDTH] [REF|PATH ...]
```

| Option        | Purpose                                                                                   |
| ------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `REF          | PATH`                                                                                     | Artifact reference or file path. Omit it, or pass `-` by itself, to read stdin. |
| `-c, --color` | Color output mode: `auto`, `always`, or `never`.                                          |
| `-l, --links` | Link scanning mode: `auto` or `never`. `never` opens the app without painted link labels. |
| `-p, --plain` | Write plain text without starting the Textual pager.                                      |
| `-t, --title` | Title for stdin input.                                                                    |
| `-w, --wrap`  | Prose wrap width; accepts an integer, `auto`, `none`, or `0`.                             |

## Pager Environment

`page_or_print()` still resolves `$SASE_PAGER`, then `$PAGER`, then `less`. When that
resolved command is `sase pager` and `link_pager` is enabled, SASE runs the pager
in-process and passes the structured document directly. Foreign pagers still run as
subprocesses, and `SASE_PAGER` is removed from the child environment so a nested SASE
command cannot recurse back into itself.

## Keys

The pager supports the standard reading keys: `j`/`k` or arrows to scroll, `ctrl+n` and
`ctrl+p` between sections, `/` search, `q` or `Esc` to close, and `?` for the help
screen. When links are enabled, painted key labels follow links, `y` copies, `E` edits,
and `Backspace` walks the pager-owned breadcrumb trail.
