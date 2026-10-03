#!/usr/bin/env python3
"""Prove HTTPS -> Caddy -> Site MCP adapter -> Gateway -> HPC, end to end.

Runs against a TEMPORARY Caddy instance on :8443 using an internal (self-signed)
certificate. Production Caddy is not touched. This validates the ingress shape
so that only the hostname + real certificate remain outstanding.
"""
import json
import ssl
import urllib.request

BASE = "https://127.0.0.1:8443"
with open("/opt/services/data/site-mcp/mcp_token") as fh:
    TOK = fh.read().strip()

# The temporary instance uses Caddy's internal CA, which the system trust store
# does not know. Verification is disabled ONLY for this probe; production TLS
# will use a real certificate and full verification.
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def post(path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=700, context=CTX) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=15, context=CTX) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


print("=== TLS: is the connection actually HTTPS? ===")
try:
    with urllib.request.urlopen(BASE + "/health", timeout=15, context=CTX) as r:
        print("  TLS protocol:", r.version())
        print("  cipher:", r.cipher()[0] if r.cipher() else "?")
except Exception as exc:
    print("  FAILED:", exc)

print()
print("=== unauthenticated over HTTPS is refused ===")
st, _ = get("/health")
print("  GET /health  ->", st, "(adapter liveness, intentionally open)")
st, body = post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"})
print("  POST /mcp without token ->", st)

print()
print("=== authenticated MCP over HTTPS ===")
st, body = post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18",
                                    "capabilities": {},
                                    "clientInfo": {"name": "caddy-probe",
                                                   "version": "1"}}}, TOK)
print("  initialize ->", st, json.dumps(body.get("result", {}).get("serverInfo")))

st, body = post("/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, TOK)
tools = (body.get("result") or {}).get("tools") or []
print("  tools/list ->", st, "| %d tools" % len(tools))
print("  contains hpc_runtime_info:", any(t["name"] == "hpc_runtime_info"
                                          for t in tools))

print()
print("=== invoke a real tool over HTTPS (full chain to the HPC) ===")
st, body = post("/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                         "params": {"name": "hpc_runtime_info",
                                    "arguments": {"include_gpu": False}}}, TOK)
content = (body.get("result") or {}).get("content") or []
payload = json.loads(content[0]["text"]) if content else {}
inv = payload.get("result") or {}
print("  status:", st, "| ok:", payload.get("ok"))
print("  remote_hostname:", inv.get("remote_hostname"))
print("  remote_home    :", inv.get("remote_home"))
print("  remote_kernel  :", inv.get("remote_kernel"))

print()
print("=== credentials never appear in the HTTPS response ===")
blob = json.dumps(body, ensure_ascii=False)
with open("/opt/services/data/compute-gateway/secrets.env") as fh:
    sec = fh.read()
import re
for key in ("CGW_JOB_TOKEN", "CGW_MAINTENANCE_TOKEN"):
    m = re.search(r"^%s=(.+)$" % key, sec, re.M)
    if m:
        print("  %-24s present in response: %s" % (key, m.group(1) in blob))
print("  MCP token present in response:", TOK in blob)
