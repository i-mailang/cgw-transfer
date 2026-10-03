"""Real HPC closed-loop: submit a minimal CPU job, watch it reach succeeded."""
import hashlib
import json
import time

from ssh_backend import SshConfig, SshBackend
from jobs import JobManager

FP = open('/tmp/hpc_fp.txt').read().strip()
b = SshBackend(SshConfig(host='hpc.wisesoe.com', port=58003, user='zzfs_202603',
    key_path='/opt/services/data/compute-gateway/ssh/cgw_hpc_ed25519',
    host_key_fingerprint=FP))
jm = JobManager('/tmp/loop2.db', b, '~/cgw-runs')
jm.init_schema()
print('resolved home :', jm.resolve_home(), flush=True)
print('runs root     :', jm.abs_runs_root(), flush=True)

SCRIPT = (
    'echo "[cgw] start pid=$$"\n'
    'echo "[cgw] host=$(hostname) user=$(id -un)"\n'
    'echo "[cgw] pwd=$(pwd)"\n'
    'sleep 5\n'
    'echo "[cgw] writing artifact"\n'
    "printf '{\\"job\\":\\"%s\\",\\"ok\\":true}\\n' > artifacts/result.json\n"
    'echo "[cgw] done"\n'
)
j = jm.submit({'command': SCRIPT, 'label': 'cgw-loop-1', 'timeout_s': 180})
jid = j['job_id']
print('SUBMITTED     :', jid, flush=True)
print('initial state :', j['status'], flush=True)
print('job dir       :', jm.job_dir(jid), flush=True)
open('/tmp/jid.txt', 'w').write(jid)

seen = [j['status']]
for i in range(25):
    time.sleep(3)
    r = jm.reconcile(jid, force=True)
    if not seen or seen[-1] != r['status']:
        seen.append(r['status'])
        print('  %2ds -> %-10s exit=%s' % (i * 3, r['status'], r.get('exit_code')), flush=True)
    if r['status'] in ('succeeded', 'failed', 'timeout', 'cancelled', 'lost'):
        print('FINAL         :', json.dumps({
            'job_id': r['job_id'], 'status': r['status'],
            'exit_code': r.get('exit_code'), 'duration_s': r.get('duration_s'),
            'transitions': seen,
        }), flush=True)
        break
else:
    print('TIMED OUT watching; last:', seen, flush=True)
