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

One input creates one section. Multiple references or paths create a section for each
input in command-line order; `-` cannot be combined with other inputs. Plain output
prints a single section without decoration and separates multiple sections with
`-- i/N: title --` headings. If a TTY is available for output but not for input, SASE
falls back to the same plain output instead of starting an unusable app.

## Keys

| Key                    | Action                                                                |
| ---------------------- | --------------------------------------------------------------------- |
| `j` / `k`, Down / Up   | Scroll one line                                                       |
| `Ctrl+D` / `Ctrl+U`    | Scroll half a page                                                    |
| `g` / `G`              | Go to the top / bottom                                                |
| `Ctrl+N` / `Ctrl+P`    | Go to the next / previous section                                     |
| `/`, `n`, `N`          | Search; repeat forward / backward                                     |
| `Backspace` / `Ctrl+O` | Follow the pager trail backward; an empty back trail closes the pager |
| `Ctrl+I`               | Follow the pager trail forward                                        |
| `r`                    | Reload the current content                                            |
| `y<label>` / `yy`      | Copy a painted target reference or the current section reference      |
| `E<label>` / `EE`      | Open a painted target or the current section in `$EDITOR`             |
| `q` / `Esc`            | Close                                                                 |
| `?`                    | Show help                                                             |

With link scanning enabled, SASE paints references and file links with case-sensitive
labels from `0`-`9`, `a`-`z`, and `A`-`Z`. Documents with more than 62 targets use
two-character labels. Typing a label follows the target in place; URL targets copy the
URL instead of replacing the document. Each follow records a bounded backward/forward
trail and restores the prior section, scroll position, and search state when revisited.
Following a new target after going back discards the forward branch.

`y` and `E` are prefix keys: follow them with a painted label to copy or edit that
target, or press the prefix twice for the current section. Link scanning can be disabled
with `--links never`; ordinary reading, search, section, and trail keys still work.
