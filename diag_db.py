#!/usr/bin/env python3
"""Inspect the extensions tables directly to see why refresh_dynamic finds
nothing to publish."""
import sqlite3

DB = "/opt/services/data/compute-gateway/gateway.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=== extensions ===")
for r in conn.execute("SELECT * FROM extensions ORDER BY name"):
    print("  name=%s active_revision=%s" % (r["name"], r["active_revision"]))

print()
print("=== extension_revisions (newest first) ===")
for r in conn.execute(
        "SELECT revision_id, name, version, state, activated_at, disabled_at"
        " FROM extension_revisions ORDER BY created_at DESC LIMIT 15"):
    print("  %-24s %-18s v%-6s %-9s act=%s dis=%s" % (
        r["revision_id"], r["name"], r["version"], r["state"],
        r["activated_at"], r["disabled_at"]))

print()
print("=== the join refresh_dynamic uses ===")
for r in conn.execute(
        "SELECT e.name, e.active_revision, r.state AS active_state"
        " FROM extensions e"
        " LEFT JOIN extension_revisions r ON r.revision_id = e.active_revision"
        " ORDER BY e.name"):
    print("  name=%-22s active_rev=%-24s active_state=%s" % (
        r["name"], r["active_revision"], r["active_state"]))
