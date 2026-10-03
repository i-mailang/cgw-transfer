#!/usr/bin/env python3
"""Remove the temporary cgw.internal hosts entry used by the TLS probe."""
p = "/etc/hosts"
with open(p) as fh:
    lines = fh.readlines()
kept = [l for l in lines if "cgw.internal" not in l]
if len(kept) != len(lines):
    with open(p, "w") as fh:
        fh.writelines(kept)
    print("removed cgw.internal from /etc/hosts")
else:
    print("no cgw.internal entry present")

with open(p) as fh:
    print("cgw.internal still present:", "cgw.internal" in fh.read())
