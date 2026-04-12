## End-to-End Testing w/ `sase ace --agent`

The `sase ace --agent` command runs the TUI headlessly and returns structured JSON output. Use `--keys` to send
keystrokes and `--size` to control terminal dimensions.

```bash
# See initial TUI state
sase ace --agent

# Navigate down two items
sase ace --agent --keys j j

# Open query modal
sase ace --agent --keys slash

# Switch to agents tab
sase ace --agent --keys tab

# Custom terminal size
sase ace --agent --size 200x50 --keys j
```
