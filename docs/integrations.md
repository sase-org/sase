# Integration APIs

SASE exposes a small set of Python helpers for external plugins and editor integrations. These APIs live under
`sase.integrations` when they are meant for integration-facing use, or under the subsystem package when they are already
part of an existing provider contract. The public symbols are tracked in `public_api_methods.txt` so unused-code tooling
does not treat external consumers as dead code.

## ChangeSpec XPrompt Tags

`sase.integrations.changespec_tags.list_changespec_xprompt_tags()` returns copyable VCS xprompt references for active
ChangeSpecs. It is intended for plugins and editors that need to show a picker of targets such as `#gh:my_change` or
`#git:local_branch`.

```python
from sase.integrations.changespec_tags import list_changespec_xprompt_tags

listing = list_changespec_xprompt_tags(project="sase")
for entry in listing.entries:
    print(entry.project, entry.name, entry.status, entry.workflow_type, entry.tag)

if listing.skipped:
    print("Some ChangeSpecs could not be tagged:", listing.skipped)
```

The optional `project` argument is an exact project-name filter. Terminal ChangeSpecs are excluded after normalizing
workspace/status suffixes, so `Submitted`, `Archived`, and `Reverted` entries are not returned. Results are sorted
deterministically by project, ChangeSpec name, and normalized status.

Each returned `ChangeSpecTagEntry` has:

| Field           | Description                                                    |
| --------------- | -------------------------------------------------------------- |
| `project`       | Parsed project basename                                        |
| `name`          | ChangeSpec `NAME`                                              |
| `status`        | Normalized non-terminal status                                 |
| `workflow_type` | Detected workspace workflow type, such as `git`, `gh`, or `hg` |
| `tag`           | Copyable xprompt target in `#{workflow_type}:{name}` form      |

If workspace workflow detection fails for an entry, that ChangeSpec is omitted and a human-readable message is appended
to `ChangeSpecTagListing.skipped`. This lets callers still show the rest of the list while surfacing degraded entries.

Source: `src/sase/integrations/changespec_tags.py`
