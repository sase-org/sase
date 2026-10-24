#!/bin/sh
set -u
EVIDENCE_DIR=/tmp/sase-1nv5-evidence
mkdir -p "$EVIDENCE_DIR"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
backup_dir="$HOME/.sase/recovery-backups/sase-1nv.5/athena-sase-20261024T183012Z"
expected=86d91095f0f97aa87f99936825ee647644ff808a60217fb18867ece766e00147
remote_command='sase agent sync --repair-revisions --apply --project sase --json'
ssh athena 'zsh -lic "sh -s"' >"$EVIDENCE_DIR/apply_athena_sase.json" 2>"$EVIDENCE_DIR/apply_athena_sase.stderr" <<'REMOTE'
#!/bin/sh
set -eu
backup_dir="$HOME/.sase/recovery-backups/sase-1nv.5/athena-sase-20261024T183012Z"
expected=86d91095f0f97aa87f99936825ee647644ff808a60217fb18867ece766e00147
outbox="$HOME/.sase/projects/gh_sase-org__sase/agents-publication-outbox.json"
audit="$HOME/.sase/projects/gh_sase-org__sase/agents-publication-repair-audit.jsonl"
src_hash="$(sha256sum "$outbox" | awk '{print $1}')"
backup_hash="$(sha256sum "$backup_dir/agents-publication-outbox.json" | awk '{print $1}')"
printf 'preflight_utc=%s\nsource_sha256=%s\nbackup_sha256=%s\nexpected_sha256=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$src_hash" "$backup_hash" "$expected" >&2
if [ "$src_hash" != "$expected" ] || [ "$backup_hash" != "$expected" ]; then
  printf 'preflight=FAILED\n' >&2
  exit 40
fi
if [ -f "$audit" ]; then cp -- "$audit" "$backup_dir/repair-audit-before.jsonl"; else : > "$backup_dir/repair-audit-before.jsonl"; fi
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
sase agent sync --repair-revisions --apply --project sase --json > "$backup_dir/apply.json" 2> "$backup_dir/apply.stderr"
rc=$?
set -e
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -f "$audit" ]; then cp -- "$audit" "$backup_dir/repair-audit-after.jsonl"; else : > "$backup_dir/repair-audit-after.jsonl"; fi
post_hash="$(sha256sum "$outbox" | awk '{print $1}')"
printf 'preflight=exact-match\napply_started_utc=%s\napply_finished_utc=%s\napply_exit_code=%s\npost_source_sha256=%s\naudit_before_lines=%s\naudit_after_lines=%s\n' "$started" "$finished" "$rc" "$post_hash" "$(wc -l < "$backup_dir/repair-audit-before.jsonl")" "$(wc -l < "$backup_dir/repair-audit-after.jsonl")" >&2
cat "$backup_dir/apply.json"
exit "$rc"
REMOTE
rc=$?
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
{
  printf 'host=athena\nproject=sase\ncommand=%s\nstarted_utc=%s\nfinished_utc=%s\nexit_code=%s\nbackup=%s/agents-publication-outbox.json\nexpected_backup_sha256=%s\n' "$remote_command" "$started" "$finished" "$rc" "$backup_dir" "$expected"
  sha256sum "$EVIDENCE_DIR/apply_athena_sase.json"
} >"$EVIDENCE_DIR/apply_athena_sase.meta"
if [ "$rc" -ne 0 ]; then cat "$EVIDENCE_DIR/apply_athena_sase.stderr" >&2; exit "$rc"; fi
