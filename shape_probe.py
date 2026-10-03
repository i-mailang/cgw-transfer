#!/usr/bin/env python3
"""Print the exact response shapes for test / activate / disable / rollback,
so the e2e assertions can be written against reality rather than assumption."""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787/v1"
with open("/opt/services/data/compute-gateway/secrets.env") as fh:
    for line in fh:
        if line.startswith("CGW_MAINTENANCE_TOKEN="):
            MAINT = line.split("=", 1)[1].strip()


def m(tool, params=None):
    req = urllib.request.Request(
        "%s/%s" % (BASE, tool),
        data=json.dumps(params or {}).encode(),
        headers={"Authorization": "Bearer " + MAINT,
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=700) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


NAME = "shape_probe"
SRC = ("def handle(payload, caps):\n"
       "    s = caps.ssh_status()\n"
       "    return {'remote_hostname': s['system'].get('HOSTNAME'),\n"
       "            'remote_user': s['system'].get('USER'),\n"
       "            'remote_home': s['system'].get('HOME'),\n"
       "            'remote_kernel': s['system'].get('KERNEL'),\n"
       "            'remote_nproc': str(s['system'].get('NPROC') or ''),\n"
       "            'gateway_revision': '0.2.0',\n"
       "            'include_gpu': False}\n")
MANIFEST = {
    "name": NAME, "version": "1.0.0", "description": "shape probe",
    "input_schema": {"type": "object", "properties": {}},
    "output_schema": {"type": "object", "properties": {
        "remote_hostname": {"type": "string"},
        "remote_user": {"type": "string"},
        "remote_home": {"type": "string"},
        "remote_kernel": {"type": "string"},
        "remote_nproc": {"type": "string"},
        "gateway_revision": {"type": "string"},
        "include_gpu": {"type": "boolean"},
    }},
    "implementation": SRC, "capabilities": ["ssh.status"], "timeout": 120,
}

st, r = m("upsert_gateway_extension", {"manifest": MANIFEST})
rev = r["result"]["revision_id"]
print("upsert ->", st, "rev", rev)
m("validate_gateway_extension", {"revision_id": rev})

st, r = m("test_gateway_extension", {"revision_id": rev, "test_payload": {}})
print("\n=== test response ===")
print(json.dumps(r, indent=2)[:1800])

st, r = m("activate_gateway_extension", {"revision_id": rev})
print("\n=== activate response ===")
print(json.dumps(r, indent=2)[:1200])

st, r = m("rollback_gateway_extension", {"name": NAME})
print("\n=== rollback response ===")
print(json.dumps(r, indent=2)[:1200])

st, r = m("disable_gateway_extension", {"name": NAME})
print("\n=== disable response ===")
print(json.dumps(r, indent=2)[:1200])
