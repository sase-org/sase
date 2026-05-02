---
plan: sdd/plans/202604/remove_bd_from_ci.md
---
 GitHub Actions is failing (see error below). We don't even use steveyegge's beads anymore, so we should be able to just stop installing beads in GitHub Actions. Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
Run CGO_ENABLED=0 go install github.com/steveyegge/beads/cmd/bd@latest
go: downloading github.com/steveyegge/beads v1.0.2
go: github.com/steveyegge/beads/cmd/bd@latest (in github.com/steveyegge/beads@v1.0.2):
	The go.mod file for the module providing named packages contains one or
	more replace directives. It must not contain directives that would cause
	it to be interpreted differently than if it were the main module.
Error: Process completed with exit code 1.
```