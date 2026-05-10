---
create_time: 2026-04-13 18:59:53
status: wip
prompt: sdd/prompts/202604/gemini_memory_files.md
---

# Plan: Create Gemini Long-Term Memory Files

## Context

Four mentor profiles in retired Mercurial plugin (`aaa`, `g3doc`, `sql`, `ui`) encode domain knowledge as review guidelines. The user
wants this knowledge extracted into standalone long-term memory files at `~/tmp/gemini/memory/long/`, following the same
format as existing sase memory files (YAML frontmatter with keywords, markdown body). The files must NOT reference
mentors — only the underlying knowledge/rules.

## Source Knowledge Summary

| Mentor  | Core Knowledge                                                                                                   | File Globs                                |
| ------- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `aaa`   | AAA (Arrange, Act, Assert) test structure rules for Java/Dart                                                    | `javatests/**/*.java`, `**/test*.dart`    |
| `g3doc` | Markdown documentation style per `@corp/g3doc/docs/reference/style.md`                                           | `**/*.md`                                 |
| `sql`   | SQL data change file path conventions and best practices per `@contentads/gfp/agave/g3doc/modify/data_change.md` | `**/*.sql`                                |
| `ui`    | UI styling guidelines per `@contentads/drx/fe/client/g3doc/drx_ui_style.md`, Dart typing exception               | `**/*.dart`, `**/*.acx.html`, `**/*.scss` |

## Files to Create

### 1. `~/tmp/gemini/memory/long/aaa_test_structure.md`

- **Keywords**: `aaa`, `arrange act assert`, `test structure`, `test method`, `java test`, `dart test`
- **Content**: Rules for structuring test methods using the AAA pattern — section separation via blank lines, no
  section-name comments, when blank lines are/aren't needed, comment usage for intra-section separation.

### 2. `~/tmp/gemini/memory/long/g3doc_style.md`

- **Keywords**: `g3doc`, `documentation`, `markdown style`, `docs`
- **Content**: Directive to follow g3doc best practices from `@corp/g3doc/docs/reference/style.md` when editing markdown
  files.

### 3. `~/tmp/gemini/memory/long/sql_data_changes.md`

- **Keywords**: `sql`, `data change`, `f1`, `data_changes`
- **Content**: File path conventions for SQL data change files (two allowed forms), team subdirectory rules with
  README.md requirement, reference to `@contentads/gfp/agave/g3doc/modify/data_change.md`.

### 4. `~/tmp/gemini/memory/long/ui_style.md`

- **Keywords**: `ui`, `styling`, `dart`, `acx`, `scss`, `frontend`
- **Content**: Directive to follow UI styling guidelines from `@contentads/drx/fe/client/g3doc/drx_ui_style.md`,
  explicit exception about not adding explicit types to Dart code unless the build fails without them.

## File to Update

### `~/tmp/gemini/GEMINI.md`

Add four new entries to the existing Tier 3 section, following the established format:

```markdown
**`memory/long/aaa_test_structure.md`**  
AAA (Arrange, Act, Assert) test structure rules for Java and Dart test methods.  
_Read when writing or modifying tests._

**`memory/long/g3doc_style.md`**  
G3doc markdown documentation style guidelines.  
_Read when editing markdown documentation files._

**`memory/long/sql_data_changes.md`**  
SQL data change file path conventions and best practices.  
_Read when adding or modifying SQL data change files._

**`memory/long/ui_style.md`**  
UI styling guidelines for Dart, ACX HTML, and SCSS files.  
_Read when modifying UI code._
```
