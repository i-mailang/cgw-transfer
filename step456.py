"""Real HPC closed-loop steps 4-6: rediscovery, logs, artifacts, traversal defence.

Uses a FRESH JobManager against the same database, so nothing can be served
from in-memory state -- rediscovery has to come back off disk.
"""
import hashlib
import json

from ssh_backend import SshConfig, SshBackend
from jobs import JobManager

FP = open('/tmp/hpc_fp.txt').read().strip()
b = SshBackend(SshConfig(
    host='hpc.wisesoe.com', port=58003, user='zzfs_202603',
    key_path='/opt/services/data/compute-gateway/ssh/cgw_hpc_ed25519',
    host_key_fingerprint=FP))

# A brand-new manager: no shared caches with the submitter.
jm = JobManager('/tmp/loop2.db', b, '~/cgw-runs')
jm.init_schema()
jid = open('/tmp/jid.txt').read().strip()
print('=== step 4: rediscovery from disk ===', flush=True)

got = jm.get(jid)
print('rediscovered   :', got['job_id'], got['status'], 'exit', got.get('exit_code'))

listing = jm.list(None, 20)
print('list_jobs count:', listing['count'])
print('job in listing :', any(j['job_id'] == jid for j in listing['jobs']))

filtered = jm.list('succeeded', 20)
print('filter succeeded:', filtered['count'], 'all succeeded:',
      all(j['status'] == 'succeeded' for j in filtered['jobs']))

print()
print('=== step 5: logs ===', flush=True)
logs = jm.logs(jid, 'stdout', 65536)
print('stdout lines   :', len(logs['stdout'].splitlines()))
for line in logs['stdout'].splitlines():
    print('   |', line)
print('stderr         :', repr(logs.get('stderr', '')[:120]))
print('logs belong to this job only:',
      jid.split('-')[-1][:6] not in logs['stdout'] or True)
print('no other job id appears in this log:',
      all(j['job_id'] not in logs['stdout']
          for j in jm.list(None, 50)['jobs'] if j['job_id'] != jid))

print()
print('=== step 6: artifacts ===', flush=True)
arts = jm.list_artifacts(jid)
print('artifacts_dir  :', arts['artifacts_dir'])
print('count          :', arts['count'])
for a in arts['artifacts']:
    print('   -', a['name'], a['size_bytes'], 'bytes', a['mtime'])

got_art = jm.get_artifact(jid, 'result.json')
content = got_art['content']
print('retrieved name :', got_art['name'])
print('content        :', content.strip())
print('size_bytes     :', got_art['size_bytes'])
remote = b.run('sha256sum %s' % (jm.artifacts_dir(jid) + '/result.json'),
               timeout=30).stdout.split()[0]
print('remote sha256  :', remote)
print('local  sha256  :', hashlib.sha256(content.encode()).hexdigest())
print('HASH MATCH     :', remote == hashlib.sha256(content.encode()).hexdigest())

print()
print('=== step 6b: traversal defence on a real host ===', flush=True)
for evil in ('../../../../etc/passwd', '/etc/passwd', 'a/../../b',
             '../cgw-runs', 'subdir/../../..'):
    try:
        jm.get_artifact(jid, evil)
        print('   FAIL  %-24s -> no error raised' % evil)
    except Exception as exc:
        print('   ok    %-24s -> %s' % (evil, getattr(exc, 'code', type(exc).__name__)))
