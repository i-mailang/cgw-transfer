#!/usr/bin/env python3
"""Diagnose the TLS handshake failure against the temporary Caddy."""
import socket
import ssl
import subprocess

print("=== /etc/hosts entry for cgw.internal ===")
with open("/etc/hosts") as fh:
    for line in fh:
        if "cgw.internal" in line:
            print("  ", line.strip())

print()
print("=== resolution ===")
for name in ("cgw.internal", "localhost"):
    try:
        print("  %-16s -> %s" % (name, socket.gethostbyname(name)))
    except Exception as exc:
        print("  %-16s -> FAILED %s" % (name, exc))

print()
print("=== TCP reachability ===")
for host, port in (("127.0.0.1", 8443), ("cgw.internal", 8443)):
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((host, port))
        print("  %s:%d -> connected" % (host, port))
    except Exception as exc:
        print("  %s:%d -> FAILED %s" % (host, port, exc))
    finally:
        s.close()

print()
print("=== handshake with explicit SNI, no verification ===")
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
for host in ("127.0.0.1", "cgw.internal"):
    try:
        with socket.create_connection((host, 8443), timeout=8) as raw:
            with ctx.wrap_socket(raw, server_hostname="cgw.internal") as tls:
                print("  %-14s OK  proto=%s cipher=%s"
                      % (host, tls.version(), tls.cipher()[0]))
                cert = tls.getpeercert()
                print("     subject:", cert.get("subject"))
    except Exception as exc:
        print("  %-14s FAILED %s: %s" % (host, type(exc).__name__, exc))

print()
print("=== what is actually listening on 8443 ===")
out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
for line in out.splitlines():
    if "8443" in line:
        print("  ", line.strip())

print()
print("=== caddy processes ===")
out = subprocess.run(["ps", "-eo", "pid,cmd"], capture_output=True,
                     text=True).stdout
for line in out.splitlines():
    if "caddy" in line and "grep" not in line:
        print("  ", line.strip()[:160])
