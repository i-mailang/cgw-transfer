#!/usr/bin/env python3
"""Print the raw test_gateway_extension response for the sandbox probe."""
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


NAME = "sandbox_probe2"
SRC = (
    "def handle(payload, caps):\n"
    "    sandbox.write('probe.txt', 'hello')\n"
    "    return {'sandbox_read': sandbox.read('probe.txt'),\n"
    "            'caps_granted': caps.describe()}\n"
)
MANIFEST = {
    "name": NAME, "version": "1.0.0", "description": "sandbox probe",
    "input_schema": {"type": "object", "properties": {}},
    "output_schema": {"type": "object", "properties": {
        "sandbox_read": {"type": "string"},
        "caps_granted": {"type": "array"},
    }},
    "implementation": SRC, "capabilities": [], "timeout": 60,
}

st, r = m("upsert_gateway_extension", {"manifest": MANIFEST})
print("upsert:", st, json.dumps(r)[:400])
rev = (r.get("result") or {}).get("revision_id")
if not rev:
    raise SystemExit("no revision")

st, r = m("validate_gateway_extension", {"revision_id": rev})
print("validate:", st, json.dumps(r)[:500])

st, r = m("test_gateway_extension", {"revision_id": rev, "test_payload": {}})
print("test:", st)
print(json.dumps(r, indent=2)[:2000])
