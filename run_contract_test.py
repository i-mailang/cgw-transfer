#!/usr/bin/env python3
"""Run contract_test.py with credentials read from secrets.env (never on cmdline)."""
import os
import subprocess
import sys

SECRETS = "/opt/services/data/compute-gateway/secrets.env"
BASE = "http://127.0.0.1:8787"

env = {}
with open(SECRETS, "r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

job = env.get("CGW_JOB_TOKEN", "")
maint = env.get("CGW_MAINTENANCE_TOKEN", "")

if not job or not maint:
    print("ERROR: missing tokens in secrets.env")
    sys.exit(1)

print(f"job token length: {len(job)}, maint token length: {len(maint)}")
print(f"base URL: {BASE}")
print()

result = subprocess.run(
    [sys.executable, "-u", "/tmp/contract_test.py", BASE, job, maint],
    capture_output=False,
)
sys.exit(result.returncode)
