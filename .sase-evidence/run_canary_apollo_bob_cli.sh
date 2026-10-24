#!/usr/bin/env bash
set -euo pipefail
out=.sase-evidence/canary_apollo_bob_cli
mkdir -p "$out/unpacked"
archive="$out/evidence.tar.gz"
ssh_rc=0
ssh -T apollo 'bash -s' > "$archive" 2> "$out/ssh.stderr" <<'REMOTE' || ssh_rc=$?
#!/usr/bin/env bash
set -euo pipefail
sase_bin="$HOME/.local/bin/sase"
python_bin="$HOME/.local/share/uv/tools/sase/bin/python"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dir="$HOME/.sase/recovery-backups/sase-1nv.5/canaries/apollo-bob-cli-$stamp"
source="$HOME/.sase/projects/gh_bobs-org__bob-cli/agents-publication-outbox.json"
timing="$HOME/.sase/logs/agent_publication_drains.jsonl"
mkdir -p "$dir"
archive_on_exit() { status=$?; trap - EXIT; tar -czf - -C "$dir" .; exit "$status"; }
trap archive_on_exit EXIT
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf 'host=apollo\nproject=bob-cli\nstarted_utc=%s\nbackup_dir=%s\nsource=%s\n' "$started" "$dir" "$source" > "$dir/meta.txt"
cp -p -- "$source" "$dir/outbox-before.json"
printf 'source_before_sha256=%s\n' "$(sha256sum "$source" | awk '{print $1}')" >> "$dir/meta.txt"
"$sase_bin" version --json > "$dir/version.json"
cp -p -- "$timing" "$dir/timing-before.jsonl" 2>/dev/null || : > "$dir/timing-before.jsonl"
"$python_bin" - "$dir/outbox-before.json" > "$dir/selector-preview.json" <<'PY'
import json,sys
from sase.core.agent_publication_recovery_publication import select_publication_drain
out=json.load(open(sys.argv[1])); rows=out.get('items',[])
selector_rows=[{k:r.get(k) for k in ('global_agent','primary_revision','terminal','quarantined','last_error','terminal_reason','created_at')} for r in rows]
s=select_publication_drain(selector_rows,limit=1,retry_quarantined=True,error_classes=('rebase_conflict',))
def render(selected,kind):
 result=[]
 for x in selected:
  match=next((r for r in rows if r.get('global_agent')==x.global_agent and r.get('primary_revision')==x.primary_revision),{})
  result.append({'selection':kind,'error_class':x.error_class,'prior_failure':x.prior_failure,'prior_class':x.prior_class,**match})
 return result
print(json.dumps({'active':render(s.active,'active'),'revive':render(s.revive,'revive')},indent=2))
PY
command='sase agent sync --project bob-cli --retry-quarantined --retry-limit 1 --retry-error-class rebase_conflict --json'
printf 'command=%s\ncommand_started_utc=%s\n' "$command" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$dir/meta.txt"
set +e
"$sase_bin" agent sync --project bob-cli --retry-quarantined --retry-limit 1 --retry-error-class rebase_conflict --json > "$dir/retry.json" 2> "$dir/retry.stderr"
retry_rc=$?
set -e
printf 'command_finished_utc=%s\ncommand_exit_code=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$retry_rc" >> "$dir/meta.txt"
cp -p -- "$source" "$dir/outbox-after.json"
printf 'source_after_sha256=%s\n' "$(sha256sum "$source" | awk '{print $1}')" >> "$dir/meta.txt"
cp -p -- "$timing" "$dir/timing-after.jsonl" 2>/dev/null || : > "$dir/timing-after.jsonl"
set +e
repo=$("$sase_bin" repo open agents -p gh_bobs-org__bob-cli -w 0 -r 'Validate the Apollo bob-cli recovery canary at the fetched remote revision' 2> "$dir/repo-open.stderr")
repo_rc=$?
set -e
printf 'repo_open_exit_code=%s\n' "$repo_rc" >> "$dir/meta.txt"
if [ "$repo_rc" -eq 0 ]; then
  printf '%s\n' "$repo" > "$dir/repo-path.txt"
  git -C "$repo" rev-parse HEAD > "$dir/remote-revision.txt"
  git -C "$repo" status --porcelain > "$dir/remote-worktree-status.txt"
  set +e
  "$python_bin" - "$repo" "$dir/selector-preview.json" > "$dir/remote-validation.json" 2> "$dir/remote-validation.stderr" <<'PY'
import json,subprocess,sys
from pathlib import Path
from sase.agents_sync.publication_validation import load_validated_publication
from sase.sase_agent import agent_session_page_path
repo=Path(sys.argv[1]); preview=json.load(open(sys.argv[2]))
manifests,snapshots,diagnostics=load_validated_publication(repo)
selected=preview['active']+preview['revive']; checks=[]
for row in selected:
 name=row['global_agent']; parts=name.split('.'); key=(parts[0],parts[1],row.get('local_hood',''))
 snap=snapshots.get(key); run=next((r for r in snap.runs if r.global_name==name or r.local_name==row.get('local_agent')) ,None) if snap else None
 paths=[f'agents/{name}/README.md',agent_session_page_path(name),f'families/{name}.md']
 prompts=[]; commits=[]
 if run:
  commits=[c.sha for c in run.commits]
  prompts=[{'path':ref.path,'size_bytes':ref.size_bytes,'digest':ref.digest} for kind,ref in run.files if kind=='prompt']
 checks.append({'global_agent':name,'local_hood':row.get('local_hood'),'primary_revision':row.get('primary_revision'),'snapshot_present':snap is not None,'run_found':run is not None,'commit_shas':commits,'revision_match':row.get('primary_revision') in commits,'page_candidates':[{'path':p,'present':(repo/p).is_file()} for p in paths],'prompt_refs':prompts})
print(json.dumps({'fetched_revision':subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),'manifest_count':len(manifests),'snapshot_count':len(snapshots),'diagnostics':list(diagnostics),'selected_checks':checks},indent=2))
PY
  validation_rc=$?
  set -e
  printf 'remote_validation_exit_code=%s\n' "$validation_rc" >> "$dir/meta.txt"
else
  printf 'remote_validation=skipped repo_open_failed\n' >> "$dir/meta.txt"
fi
REMOTE
mkdir -p "$out/unpacked"
tar -xzf "$archive" -C "$out/unpacked"
printf 'capture_ssh_exit=%s\n' "$ssh_rc"
cat "$out/unpacked/meta.txt"
printf 'selector-preview: '
cat "$out/unpacked/selector-preview.json"
printf 'retry-output: '
cat "$out/unpacked/retry.json"
printf 'remote-validation: '
cat "$out/unpacked/remote-validation.json" 2>/dev/null || true
