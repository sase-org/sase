# SASE Pager

`sase pager` opens artifact references, file paths, or stdin in the SASE link-traversing
pager. The same surface is used by `sase bead show`, `sase artifact read`, and text
artifacts opened through the artifact viewer.

With redirected stdout, `--plain`, or no controlling terminal, the command writes plain
text. That makes it safe in pipelines and safe as an unconditional pager command.

## Usage

```bash
sase pager bead:sase-uk.7 src/sase/cli_pager.py
git show --stat | sase pager -t "git show"
sase bead show sase-uk.7
```

```text
sase pager [-c auto|always|never] [-l auto|never] [-p] [-t TITLE] [-w WIDTH] [REF|PATH ...]
```

| Option        | Purpose                                                                                   |
| ------------- | ----------------------------------------------------------------------------------------- |
| `REF\|PATH`   | Artifact reference or file path. Omit it, or pass `-` by itself, to read stdin.           |
| `-c, --color` | Color output mode: `auto`, `always`, or `never`.                                          |
| `-l, --links` | Link scanning mode: `auto` or `never`. `never` opens the app without painted link labels. |
| `-p, --plain` | Write plain text without starting the Textual pager.                                      |
| `-t, --title` | Title for stdin input.                                                                    |
| `-w, --wrap`  | Prose wrap width; accepts an integer, `auto`, `none`, or `0`.                             |

## CLI Paging

`page_or_print()` preserves the shared print-vs-page decision for CLI output: `never`
writes directly, `auto` pages only on a real terminal when output is taller than the
terminal and `SASE_AGENT` is unset, and `always` pages whenever the terminal can host
the Textual app. Paging runs the SASE pager in-process and passes the structured
document directly; SASE no longer shells out to `$PAGER` or `less` for this path.

## Keys

The pager supports the standard reading keys: `j`/`k` or arrows to scroll, `ctrl+n` and
`ctrl+p` between sections, `/` search, `q` or `Esc` to close, and `?` for the help
screen. When links are enabled, painted key labels follow links, `y` copies, `E` edits,
and `Backspace` walks the pager-owned breadcrumb trail.
