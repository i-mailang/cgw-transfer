"""Real HPC closed-loop step 8: minimal, non-destructive GPU probe.

Deliberately tiny: allocate nothing large, run no benchmark. The goal is only
to prove the Gateway can execute against the HPC GPU environment.
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
jm = JobManager('/tmp/loop4.db', b, '~/cgw-runs')
jm.init_schema()

print('=== gpu_status via the Gateway tool ===', flush=True)
g = jm.gpu_status()
print('gpus_present  :', g.get('gpus_present'), flush=True)
print('count         :', g.get('count'), flush=True)
print('note          :', g.get('note'), flush=True)
for gpu in (g.get('gpus') or []):
    print('   GPU %s %s  mem %s/%s MiB  util %s%%  temp %sC  power %s/%sW' % (
        gpu.get('index'), gpu.get('name'), gpu.get('memory_used_mb'),
        gpu.get('memory_total_mb'), gpu.get('gpu_util_pct'), gpu.get('temp_c'),
        gpu.get('power_w'), gpu.get('power_limit_w')), flush=True)
print('other procs   :', g.get('compute_processes'), flush=True)

print()
print('=== minimal GPU-touching job through submit_job ===', flush=True)
# Query the driver and touch the runtime; no allocation, no training.
SCRIPT = "\n".join([
    'echo "[gpu] driver:"',
    'nvidia-smi --query-gpu=index,name,memory.total,driver_version '
    '--format=csv,noheader 2>&1 | head -4',
    'echo "[gpu] runtime check:"',
    'python3 -c "import importlib.util as u; '
    'print(\'torch\', bool(u.find_spec(\'torch\'))); '
    'print(\'cupy\', bool(u.find_spec(\'cupy\')))" 2>&1',
    'echo "[gpu] done"',
])
j = jm.submit({'command': SCRIPT, 'label': 'cgw-gpu-probe', 'timeout_s': 120})
jid = j['job_id']
print('SUBMITTED :', jid, j['status'], flush=True)

final = None
for i in range(20):
    time.sleep(3)
    r = jm.reconcile(jid, force=True)
    if r['status'] in ('succeeded', 'failed', 'timeout', 'cancelled', 'lost'):
        final = r
        break
print('FINAL     :', final['status'], 'exit', final.get('exit_code'), flush=True)
print('stdout    :', flush=True)
print(jm.logs(jid, 'stdout', 16384)['stdout'], flush=True)
err = jm.logs(jid, 'stderr', 8192)['stderr']
if err.strip():
    print('stderr    :', err[:400], flush=True)
