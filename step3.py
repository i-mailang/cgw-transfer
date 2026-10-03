"""Real HPC closed-loop step 3: submit a minimal CPU job, observe its lifecycle.

Uploaded as a file rather than inlined because the job script contains quotes
and backslashes that do not survive two levels of shell escaping.
"""
import json
import time

from ssh_backend import SshConfig, SshBackend
from jobs import JobManager

FP = open('/tmp/hpc_fp.txt').read().strip()
b = SshBackend(SshConfig(
    host='hpc.wisesoe.com', port=58003, user='zzfs_202603',
    key_path='/opt/services/data/compute-gateway/ssh/cgw_hpc_ed25519',
    host_key_fingerprint=FP))
jm = JobManager('/tmp/loop2.db', b, '~/cgw-runs')
jm.init_schema()
print('resolved home :', jm.resolve_home(), flush=True)
print('runs root     :', jm.abs_runs_root(), flush=True)

ARTIFACT_BODY = '{"job": "JOBID", "ok": true, "note": "written by the job itself"}'

SCRIPT = "\n".join([
    'echo "[cgw] start pid=$$"',
    'echo "[cgw] host=$(hostname) user=$(id -un)"',
    'echo "[cgw] pwd=$(pwd)"',
    'sleep 5',
    'echo "[cgw] writing artifact"',
    "printf '%s\\n' " + json.dumps(ARTIFACT_BODY) + " > artifacts/result.json",
    'echo "[cgw] done"',
])

j = jm.submit({'command': SCRIPT, 'label': 'cgw-loop-1', 'timeout_s': 180})
jid = j['job_id']
print('SUBMITTED     :', jid, flush=True)
print('initial state :', j['status'], flush=True)
print('job dir       :', jm.job_dir(jid), flush=True)
print('artifacts dir :', jm.artifacts_dir(jid), flush=True)
open('/tmp/jid.txt', 'w').write(jid)

seen = [j['status']]
final = None
for i in range(25):
    time.sleep(3)
    r = jm.reconcile(jid, force=True)
    if seen[-1] != r['status']:
        seen.append(r['status'])
        print('  %2ds -> %-10s exit=%s' % (i * 3, r['status'], r.get('exit_code')),
              flush=True)
    if r['status'] in ('succeeded', 'failed', 'timeout', 'cancelled', 'lost'):
        final = r
        break

if final is None:
    print('STILL RUNNING after 75s; last state:', seen, flush=True)
else:
    print('FINAL         :', json.dumps({
        'job_id': final['job_id'],
        'status': final['status'],
        'exit_code': final.get('exit_code'),
        'duration_s': final.get('duration_s'),
        'transitions': seen,
    }), flush=True)
