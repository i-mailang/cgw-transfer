#!/usr/bin/env python3
"""Compare the same initialize request direct vs through Caddy, to isolate
where the 400 comes from."""
import json
import ssl
import urllib.request

with open("/opt/services/data/site-mcp/mcp_token") as fh:
    TOK = fh.read().strip()

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

REQ = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
       "params": {"protocolVersion": "2025-06-18",
                  "capabilities": {},
                  "clientInfo": {"name": "diag", "version": "1"}}}


def call(base, ctx=None, label=""):
    body = json.dumps(REQ).encode()
    req = urllib.request.Request(
        base + "/mcp", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + TOK,
                 "Accept": "application/json, text/event-stream"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            raw = resp.read().decode()
            print("%-28s HTTP %s" % (label, resp.status))
            print("   ", raw[:400])
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        print("%-28s HTTP %s" % (label, exc.code))
        print("    raw:", raw[:400])
        for h in ("Content-Type", "Server", "Content-Length"):
            v = exc.headers.get(h)
            if v:
                print("    %s: %s" % (h, v))
    except Exception as exc:
        print("%-28s FAILED %s: %s" % (label, type(exc).__name__, exc))


print("=== direct to the adapter (no TLS, no Caddy) ===")
call("http://127.0.0.1:8790", None, "direct")

print()
print("=== through Caddy (TLS) ===")
call("https://cgw.internal:8443", CTX, "via caddy")

print()
print("=== tools/list through Caddy for comparison ===")
REQ2 = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
body = json.dumps(REQ2).encode()
req = urllib.request.Request(
    "https://cgw.internal:8443/mcp", data=body,
    headers={"Content-Type": "application/json",
             "Authorization": "Bearer " + TOK,
             "Accept": "application/json, text/event-stream"},
    method="POST")
try:
    with urllib.request.urlopen(req, timeout=30, context=CTX) as resp:
        d = json.loads(resp.read().decode())
        print("HTTP", resp.status, "| tools:",
              len((d.get("result") or {}).get("tools") or []))
except Exception as exc:
    print("FAILED:", type(exc).__name__, exc)
