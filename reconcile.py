import time
from ssh_backend import SshConfig, SshBackend
from jobs import JobManager

FP = open('/tmp/hpc_fp.txt').read().strip()
b = SshBackend(SshConfig(host='hpc.wisesoe.com', port=58003, user='zzfs_202603',
    key_path='/opt/services/data/compute-gateway/ssh/cgw_hpc_ed25519',
    host_key_fingerprint=FP))
jm = JobManager('/tmp/loop.db', b, '~/cgw-runs')
jm.init_schema()
jid = open('/tmp/jid.txt').read().strip()
print('job:', jid, flush=True)
for i in range(20):
    r = jm.reconcile(jid, force=True)
    print('%2ds status=%-10s exit=%-5s dur=%s' % (
        i * 3, r['status'], r.get('exit_code'), r.get('duration_s')), flush=True)
    if r['status'] in ('succeeded', 'failed', 'timeout', 'cancelled', 'lost'):
        break
    time.sleep(3)
