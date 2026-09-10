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
sase pager [-c auto|always|never] [-l auto|never] [-p] [-s ALIAS] [-t TITLE] [-w WIDTH] [REF|PATH ...]
```

| Option         | Purpose                                                                                                |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| `REF\|PATH`    | Artifact reference or file path. Omit it, or pass `-` by itself, to read stdin.                        |
| `-c, --color`  | Color output mode: `auto`, `always`, or `never`. `never` also disables syntax highlighting.            |
| `-l, --links`  | Link scanning mode: `auto` or `never`. `never` opens the app without painted link labels.              |
| `-p, --plain`  | Write plain text without starting the Textual pager.                                                   |
| `-s, --syntax` | Highlighting language: `auto`, `none`, or a Pygments alias. Invalid aliases fail before stdin is read. |
| `-t, --title`  | Title for stdin input.                                                                                 |
| `-w, --wrap`   | Prose wrap width; accepts an integer, `auto`, `none`, or `0`.                                          |

## CLI Paging

`page_or_print()` preserves the shared print-vs-page decision for CLI output: `never`
writes directly, `auto` pages only on a real terminal when output is taller than the
terminal and `SASE_AGENT` is unset, and `always` pages whenever the terminal can host
the Textual app. Paging runs the SASE pager in-process and passes the structured
document directly; SASE no longer shells out to `$PAGER` or `less` for this path.

One input creates one section. Multiple references or paths create a section for each
input in command-line order; `-` cannot be combined with other inputs. Plain output
prints a single section without decoration and separates multiple sections with
`-- i/N: title --` headings. If stdout is a TTY but SASE cannot open the controlling
terminal (`/dev/tty`) for input, it falls back to the same plain output instead of
starting an unusable app.

`bead:<id>` inputs and followed bead links read the live bead store for the owning
project; they do not require generated Markdown pages under `pages/`.

Interactive section bodies have an editor-style line-number gutter. Numbers restart at 1
for each section and appear only on the first visual row of a wrapped logical line;
continuation rows keep an empty gutter cell. The digit column is sized once from the
largest section, so moving between sections does not shift the document. Following a
line-qualified file target such as `path/to/file.py:42` or `README.md#L42` scrolls to
that logical line. To jump within the current section, press `:` or `;`, type a line
number, and press `Enter`; this route also accents the destination's gutter number.
Plain and redirected output does not include the gutter.

## Syntax highlighting

Recognized source files, Markdown documents, and diffs pick up a muted language overlay
after the first paint. The underlying characters never change: comments, strings, and
structure are styled in place, links stay the interactive objects, and `/` search keeps
those colors under the match highlight.

Detection is conservative. Each section is classified from its own provenance, not from
`--title` or from paths mentioned in the text:

1. `-s/--syntax ALIAS` selects a Pygments lexer for eligible initial sections. `none`
   disables the added layer for the rest of the session. `auto` requests normal
   detection. `text` and `plain` keep the source unhighlighted without a language chip.
   Invalid aliases fail with exit code 2 before stdin is consumed.
2. Trusted adapter provenance identifies an actual Markdown document or diff body. A
   bead or card that merely mentions Markdown is still a formatted card.
3. Filename policy covers common source families, including `README`, `Makefile`,
   `Dockerfile`, `uv.lock`, and `.tcss`. `Justfile` and `.txt` stay deliberately plain.
4. Extensionless files may use a bounded first-line shebang (`/usr/bin/env` and `env -S`
   included).
5. Untyped stdin may be recognized as a unified or git diff in a bounded prefix.

Followed targets detect themselves. Revisiting history restores the original section
override. `--syntax none`, `pager.syntax: never`, and `--color never` stay in effect
across follow/back/forward. `--plain`, redirected stdout, and `page_or_print`'s direct
branch do not lex. Existing producer ANSI is preserved: `--syntax none` is not the same
as `--color never`.

```bash
sase pager src/sase/cli_pager.py
sase pager notes.md
git diff | sase pager -t "git diff"
cat config.yml | sase pager -s yaml
sase pager --syntax none README
```

Permanent configuration is `pager.syntax: auto | never` (default `auto`). CLI `--syntax`
overrides it. Files that exceed the syntax caps stay fully visible and searchable, just
without highlighting. Unknown types can still be forced with an explicit lexer.

## Keys

| Key                    | Action                                                                |
| ---------------------- | --------------------------------------------------------------------- |
| `j` / `k`, Down / Up   | Scroll one line                                                       |
| `Ctrl+D` / `Ctrl+U`    | Scroll half a page                                                    |
| `g` / `G`              | Go to the top / bottom                                                |
| `Ctrl+N` / `Ctrl+P`    | Go to the next / previous section                                     |
| `/`, `n`, `N`          | Search; repeat forward / backward                                     |
| `Backspace` / `Ctrl+O` | Follow the pager trail backward; an empty back trail closes the pager |
| `<tab>`                | Follow the pager trail forward (`Ctrl+I` remains an alias)            |
| `r`                    | Reload the current content                                            |
| `y<label>`             | Copy a painted artifact reference or resolved file path               |
| `yy`                   | Copy the current section's reference or path, when one is available   |
| `E<label>`             | Open a painted file-backed target in `$EDITOR`                        |
| `EE`                   | Open the current section in `$EDITOR` when it is file-backed          |
| `q` / `Esc`            | Close                                                                 |
| `?`                    | Show help                                                             |

With link scanning enabled, SASE paints references and file links with case-sensitive
labels drawn from `0`-`9`, `a`-`z`, and `A`-`Z`. Pager commands reserve `q`, `j`, `k`,
`g`, `G`, `y`, `E`, `r`, `n`, and `N`, leaving 52 label characters. Up to 52 targets
therefore use one-character labels. Larger documents use a prefix-free mix of one- and
two-character labels; documents beyond the two-character capacity label only a window of
nearby targets. Typing a label follows the target in place; URL targets copy the URL
instead of replacing the document. Each follow records a bounded backward/forward trail
and restores the prior section, scroll position, and search state when revisited.
Following a new target after going back discards the forward branch.

When either trail direction exists, a breadcrumb band appears below the subject line.
The first row shows the retained visit position, total retained visits, available
Back/Forward counts, and a `? trail` hint. The second row shows retained visits in
chronological order with `›` separators; `●` marks the current visit and `…N` marks an
omitted run of exactly `N` retained visits that did not fit. Returning to the earliest
retained visit still shows forward context. On pager screens of 12 rows or fewer, the
band compacts to one row with the same position, current marker, direction counts, and
help hint. Positions count only retained visits, so older entries evicted by the bounded
trail are not recoverable through the band or help sheet.

Press `?` outside search typing or the goto prompt to open the scrollable Trail & keys
sheet. When history exists, the complete retained trail appears before the key guide;
each visit is numbered and marked as `back`, `current`, or `forward`, with identity
details when they disambiguate identical titles. The sheet has its own scrolling keys:
`j`/`k`, arrows, `Ctrl+D`/`Ctrl+U`, and `g`/`G`; `q`, `Esc`, or `?` dismiss it without
changing document scroll, search state, pending link prefixes, or either history stack.

`y` and `E` are prefix keys: follow them with a painted label to copy or edit that
target, or press the prefix twice for the current section. Link scanning can be disabled
with `--links never`; ordinary reading, search, section, and trail keys still work.

## Resolution

Follow, copy, and edit use the same semantic target: a typed artifact reference without
a leading `@`, a decoded path (quotes and prompt sigils stripped), a URL, or a
caller-attached object. Painting uses the original character span; `@` and quoting are
syntax, not path bytes.

Resolution uses the document's owning project and already-available repositories, not
the viewer's current directory. A same-named file in an unrelated checkout is not a hit.
Distinct repositories that each contain the path produce an ambiguity page with
followable candidate links rather than a first-hit guess. A source path that exists only
in a linked repository still resolves even when the primary Git index has no matching
entry.

URL labels copy the exact destination, including query strings and fragments. File and
artifact labels that cannot be resolved stay visible. The toast names the outcome:
missing checkout, unavailable revision, filtered/denied, proven missing, or not found.
Temporary failures and missing checkouts are retryable — `r` clears the dangling cache
so a later press can succeed after the target appears. Failed navigation leaves the
current document and trail unchanged.

Reload and retry never clone, reset, or clean a workspace. Each press searches once on a
background worker; diagnostics travel with that result, so the UI does not run a second
Git search to build a toast.
