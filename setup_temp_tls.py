#!/usr/bin/env python3
"""Set up a temporary internal-TLS Caddy site and prove the HTTPS chain.

Uses cgw.internal as the site name so Caddy's internal CA issues a proper leaf
certificate. Production Caddy is untouched; this instance listens on :8443.
"""
import os
import subprocess
import time

CFG = """{
	admin off
	auto_https disable_redirects
	storage file_system /tmp/ct/storage
}

https://cgw.internal:8443 {
	tls internal
	reverse_proxy 127.0.0.1:8790
}
"""

os.makedirs("/tmp/ct/storage", exist_ok=True)
with open("/tmp/ct/Caddyfile", "w") as fh:
    fh.write(CFG)

# Map the internal name to loopback so the probe can resolve it.
with open("/etc/hosts") as fh:
    hosts = fh.read()
if "cgw.internal" not in hosts:
    with open("/etc/hosts", "a") as fh:
        fh.write("127.0.0.1 cgw.internal\n")
    print("added cgw.internal to /etc/hosts")

subprocess.run(["pkill", "-f", "caddy run --config /tmp/ct"], check=False)
time.sleep(1)

log = open("/tmp/ct/caddy5.log", "w")
subprocess.Popen(["caddy", "run", "--config", "/tmp/ct/Caddyfile"],
                 stdout=log, stderr=subprocess.STDOUT)
time.sleep(8)

out = subprocess.run(["ss", "-ltn"], capture_output=True, text=True).stdout
print("listening on 8443:", "8443" in out)

certs = []
for root, _, files in os.walk("/tmp/ct/storage"):
    for f in files:
        if f.endswith(".crt"):
            certs.append(os.path.join(root, f))
print("certificate files:", len(certs))
for c in certs:
    print("  ", c.replace("/tmp/ct/storage/", ""))

with open("/tmp/ct/caddy5.log") as fh:
    tail = fh.read().strip().splitlines()[-4:]
print("--- caddy log tail ---")
for line in tail:
    print("  ", line[:200])
