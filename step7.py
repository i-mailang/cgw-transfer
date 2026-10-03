"""Real HPC closed-loop step 7: cancellation and orphan-process check."""
import json
import time

from ssh_backend import SshConfig, SshBackend
from jobs import JobManager

FP = open('/tmp/hpc_fp.txt').read().strip()
b = SshBackend(SshConfig(
    host='hpc.wisesoe.com', port=58003, user='zzfs_202603',
    key_path='/opt/services/data/compute-gateway/ssh/cgw_hpc_ed25519',
    host_key_fingerprint=FP))
jm = JobManager('/tmp/loop3.db', b, '~/cgw-runs')
jm.init_schema()

# A long job that prints a marker so we can prove the process really ran.
SCRIPT = "\n".join([
    'echo "[cgw] cancel-test starting pid=$$"',
    'for i in $(seq 1 600); do echo "[cgw] tick $i"; sleep 1; done',
])

j = jm.submit({'command': SCRIPT, 'label': 'cgw-cancel', 'timeout_s': 900})
jid = j['job_id']
print('SUBMITTED   :', jid, j['status'], flush=True)

pgid = j.get('pid')
print('pgid        :', pgid, flush=True)
if not pgid:
    pgid = jm._read_pgid(jid)
    print('pgid (reread):', pgid, flush=True)

time.sleep(4)
live = jm.reconcile(jid, force=True)
print('before cancel:', live['status'], flush=True)
alive = b.run('kill -0 %s 2>/dev/null && echo ALIVE || echo GONE' % pgid,
              timeout=20).stdout.strip()
print('remote alive :', alive, flush=True)

t0 = time.time()
c = jm.cancel(jid)
print('cancel result: cancelled=%s signalled=%s status=%s (%.1fs)' % (
    c.get('cancelled'), c.get('signalled'), c.get('status'), time.time() - t0),
    flush=True)

time.sleep(2)
after = jm.reconcile(jid, force=True)
print('after cancel :', after['status'], 'exit', after.get('exit_code'), flush=True)

orphan = b.run(
    "ps -o pid,pgid,cmd -g %s 2>/dev/null | grep -v ' ps ' | head -5" % pgid,
    timeout=20).stdout.strip()
print('orphan procs :', orphan if orphan else '(none)', flush=True)
gone = b.run('kill -0 %s 2>/dev/null && echo ALIVE || echo GONE' % pgid,
             timeout=20).stdout.strip()
print('pgid now     :', gone, flush=True)

logs = jm.logs(jid, 'stdout', 8192)
ticks = [ln for ln in logs['stdout'].splitlines() if 'tick' in ln]
print('ticks seen   :', len(ticks), '(stopped growing => process was killed)',
      flush=True)
print('marker line  :', logs['stdout'].splitlines()[0] if logs['stdout'] else '(none)')
print('VERDICT      :', json.dumps({
    'job_id': jid,
    'reached_running': live['status'] == 'running',
    'cancelled': bool(c.get('cancelled')),
    'signalled': bool(c.get('signalled')),
    'final_status': after['status'],
    'pgid_alive_after': gone,
    'orphan_processes': orphan or '(none)',
    'tick_count': len(ticks),
}))
