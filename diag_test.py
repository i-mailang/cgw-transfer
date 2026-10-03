#!/usr/bin/env python3
"""Diagnose why test_gateway_extension returns 200 but leaves the revision
in VALIDATED with no output."""
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


st, r = m("get_gateway_extension", {"name": "hpc_runtime_info"})
print("get_gateway_extension:", st)
ext = r.get("result") or {}
for rev in ext.get("revisions", []):
    print("  rev", rev["revision_id"], "version", rev.get("version"),
          "state", rev.get("state"), "caps", rev.get("declared_caps"))
    rev_id = rev["revision_id"]

print()
st, r = m("test_gateway_extension",
          {"revision_id": rev_id, "test_payload": {"include_gpu": False}})
print("test_gateway_extension:", st)
print(json.dumps(r, indent=2)[:2500])

print()
st, r = m("get_gateway_extension", {"name": "hpc_runtime_info",
                                    "revision_id": rev_id})
print("after test, revision state:", st)
res = r.get("result") or {}
print("  state:", (res.get("revision") or {}).get("state"))
print("  test_json:", json.dumps((res.get("revision") or {}).get("test"))[:1200])
