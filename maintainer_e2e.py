#!/usr/bin/env python3
"""
Maintainer Plane end-to-end validation, run against the PRODUCTION Gateway.

Everything goes through the real HTTP surface on 127.0.0.1:8787 with the real
maintenance token, so this exercises the same code path ChatGPT would use to
extend its own tool surface.

Lifecycle under test:
    DRAFT -> VALIDATED -> TESTED -> ACTIVE -> INVOKED
          -> NEW REVISION -> ROLLBACK -> DISABLED

Plus the security properties: isolation, no core shadowing, capability
enforcement, and that a failed candidate cannot displace the active revision.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787/v1"
SECRETS = "/opt/services/data/compute-gateway/secrets.env"

with open(SECRETS) as fh:
    for line in fh:
        if line.startswith("CGW_MAINTENANCE_TOKEN="):
            MAINT = line.split("=", 1)[1].strip()
        elif line.startswith("CGW_JOB_TOKEN="):
            JOB = line.split("=", 1)[1].strip()

RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", label,
                           "" if ok else "  :: %s" % detail), flush=True)
    return bool(ok)


def call(tool, params=None, token=None, method="POST"):
    url = "%s/%s" % (BASE, tool)
    data = None
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if method == "POST":
        data = json.dumps(params if params is not None else {}).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=700) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


def m(tool, params=None):
    return call(tool, params, MAINT)


def section(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72, flush=True)


# --------------------------------------------------------------------------
# The test extension
# --------------------------------------------------------------------------
EXT_NAME = "hpc_runtime_info"
EXT_SRC_V1 = '''
def handle(payload, caps):
    """Structured read-only runtime information about the HPC and Gateway."""
    status = caps.ssh_status(include_gpu=bool(payload.get("include_gpu")))
    sysinfo = status.get("system", {})
    out = {
        "remote_hostname": sysinfo.get("HOSTNAME"),
        "remote_user": sysinfo.get("USER"),
        "remote_home": sysinfo.get("HOME"),
        "remote_kernel": sysinfo.get("KERNEL"),
        "remote_nproc": str(sysinfo.get("NPROC") or ""),
        "gateway_revision": payload.get("gateway_revision", "unknown"),
        "include_gpu": bool(payload.get("include_gpu")),
    }
    if payload.get("include_gpu"):
        gpu = status.get("gpu") or {}
        out["gpu_count"] = gpu.get("count")
        out["gpu_present"] = gpu.get("gpus_present")
    return out
'''

# v2 adds a field, to prove revision history and rollback are real.
EXT_SRC_V2 = EXT_SRC_V1.replace(
    '"include_gpu": bool(payload.get("include_gpu")),',
    '"include_gpu": bool(payload.get("include_gpu")),\n'
    '        "revision_marker": "v2",'
)

# A candidate that must NOT be allowed to become active.
BAD_SRC = "def handle(payload, caps):\n    return {'x': eval('1+1')}\n"


def manifest(version, implementation, caps=None, name=EXT_NAME):
    return {
        "name": name,
        "version": version,
        "description": "Read-only HPC runtime information for the Maintainer Plane.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_gpu": {"type": "boolean"},
                "gateway_revision": {"type": "string"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "remote_hostname": {"type": "string"},
                "remote_user": {"type": "string"},
                "remote_home": {"type": "string"},
                "remote_kernel": {"type": "string"},
                "remote_nproc": {"type": "string"},
                "gateway_revision": {"type": "string"},
                "include_gpu": {"type": "boolean"},
                "revision_marker": {"type": "string"},
                "gpu_count": {"type": "integer"},
                "gpu_present": {"type": "boolean"},
            },
        },
        "implementation": implementation,
        "capabilities": caps if caps is not None else ["ssh.status"],
        "timeout": 120,
    }


def main():
    section("0. Maintenance plane reachable, job plane cannot see it")
    st, r = m("get_gateway_maintenance_status", {})
    check("maintainer token reaches the maintenance plane", st == 200, str(r)[:200])
    st, r = call("get_gateway_maintenance_status", {}, JOB)
    check("job token is refused on the maintainer plane",
          st == 401 and r["error"]["code"] == "UNAUTHORIZED", "got %s" % st)

    section("1. DRAFT - upsert_gateway_extension")
    st, r = m("upsert_gateway_extension", {"manifest": manifest("1.0.0", EXT_SRC_V1)})
    check("upsert returns 200", st == 200, str(r)[:300])
    rev1 = r["result"]["revision_id"]
    check("new revision starts in DRAFT", r["result"]["state"] == "DRAFT",
          r["result"]["state"])
    src_hash_v1 = r["result"]["source_hash"]

    st, r2 = m("upsert_gateway_extension", {"manifest": manifest("1.0.0", EXT_SRC_V1)})
    check("identical source is not duplicated (same revision id)",
          r2["result"]["revision_id"] == rev1, r2["result"]["revision_id"])
    check("source hash is stable", r2["result"]["source_hash"] == src_hash_v1)

    section("2. VALIDATED - validate_gateway_extension")
    st, r = m("validate_gateway_extension", {"revision_id": rev1})
    check("validate returns 200", st == 200, str(r)[:300])
    check("revision advances to VALIDATED", r["result"]["state"] == "VALIDATED",
          r["result"]["state"])
    check("declared capability is recognised as used",
          "ssh.status" in (r["result"].get("capabilities_used") or []),
          str(r["result"].get("capabilities_used")))

    section("3. TESTED - isolated test execution")
    st, r = m("test_gateway_extension",
              {"revision_id": rev1,
               "test_payload": {"include_gpu": False,
                                "gateway_revision": "0.2.0"}})
    check("test returns 200", st == 200, str(r)[:400])
    _tr = r.get("result") or {}
    check("the test actually passed", _tr.get("passed") is True,
          str(_tr.get("error"))[:300])
    check("revision advances to TESTED", _tr.get("state") == "TESTED",
          str(_tr.get("state")))
    _env = _tr.get("result") or {}
    out = _env.get("output") or {}
    check("test actually executed and produced output", bool(out), str(out)[:200])
    check("worker reported the capability call it made",
          any(c.get("cap") == "ssh.status"
              for c in (_env.get("cap_calls") or [])),
          str(_env.get("cap_calls"))[:200])
    check("remote hostname came back from the real HPC",
          out.get("remote_hostname") == "gpulinux02",
          str(out)[:200])

    section("4. ACTIVE - atomic activation and registry publication")
    st, r = m("activate_gateway_extension", {"revision_id": rev1})
    check("activate returns 200", st == 200, str(r)[:300])
    _ar = r.get("result") or {}
    check("revision is the active one", _ar.get("active_revision") == rev1,
          str(_ar)[:200])

    st, r = call("tools", None, MAINT, method="GET")
    names = [t["name"] for t in r["result"]["tools"]]
    check("extension is published in the maintainer tool registry",
          EXT_NAME in names, "not in %d tools" % len(names))
    ext_tools = [t for t in r["result"]["tools"] if t["name"] == EXT_NAME]
    check("published tool is marked as an extension",
          ext_tools and ext_tools[0].get("plane") == "extension",
          str(ext_tools[:1]))
    check("the extension tool carries its revision and source hash",
          ext_tools and ext_tools[0].get("revision_id")
          and ext_tools[0].get("source_hash"),
          str(ext_tools[:1]))
    st, r = call("tools", None, JOB, method="GET")
    job_names = [t["name"] for t in r["result"]["tools"]]
    check("the extension is NOT listed to the job plane (maintainer-only "
          "inventory)",
          EXT_NAME not in job_names, "leaked into the job-plane listing")

    section("5. INVOKED - through the normal tool registry")
    st, r = call(EXT_NAME, {"include_gpu": False, "gateway_revision": "0.2.0"}, JOB)
    check("extension is invocable with a JOB token (it is not a maintainer tool)",
          st == 200, str(r)[:300])
    inv = r.get("result") or {}
    check("invocation returns the declared output shape",
          set(["remote_hostname", "remote_user", "remote_home"]).issubset(inv),
          str(inv)[:300])
    check("the remote hostname is the real HPC node",
          inv.get("remote_hostname") == "gpulinux02",
          str(inv.get("remote_hostname")))
    check("the resolved remote home is the real one",
          (inv.get("remote_home") or "").endswith("zzfs_202603"),
          str(inv.get("remote_home")))
    check("no revision_marker in v1 output",
          "revision_marker" not in inv, str(inv))

    st, r = call(EXT_NAME, {"include_gpu": True}, JOB)
    check("gpu path also works end to end", st == 200, str(r)[:300])
    check("gpu fields present when requested",
          "gpu_count" in (r.get("result") or {}), str(r.get("result"))[:300])

    section("6. Immutable revision history")
    st, r = m("get_gateway_extension", {"name": EXT_NAME})
    check("history returns 200", st == 200, str(r)[:300])
    revs = (r["result"] or {}).get("revisions") or []
    check("v1 is in the history with its state",
          any(x["revision_id"] == rev1 for x in revs), str(revs)[:300])

    section("7. A failed candidate cannot displace the active revision")
    st, r = m("upsert_gateway_extension",
              {"manifest": manifest("9.9.9", BAD_SRC)})
    check("a syntactically valid but forbidden candidate can be upserted",
          st == 200, str(r)[:300])
    bad_rev = r["result"]["revision_id"]
    st, r = m("validate_gateway_extension", {"revision_id": bad_rev})
    check("candidate using eval() fails validation",
          st == 400 and r["error"]["code"] == "VALIDATION_FAILED",
          "got %s %s" % (st, r.get("error", {}).get("code")))
    st, r = m("activate_gateway_extension", {"revision_id": bad_rev})
    check("an unvalidated candidate cannot be activated",
          st >= 400, "got %s" % st)
    st, r = call(EXT_NAME, {"gateway_revision": "0.2.0"}, JOB)
    check("the active revision is unchanged after the failed candidate",
          st == 200 and (r.get("result") or {}).get("remote_hostname") == "gpulinux02",
          str(r)[:200])

    section("8. NEW REVISION - v2 with a behavioural change")
    st, r = m("upsert_gateway_extension", {"manifest": manifest("2.0.0", EXT_SRC_V2)})
    check("v2 upserts as a new revision", st == 200, str(r)[:300])
    rev2 = r["result"]["revision_id"]
    check("v2 has a different revision id from v1", rev2 != rev1,
          "%s vs %s" % (rev2, rev1))
    st, r = m("validate_gateway_extension", {"revision_id": rev2})
    check("v2 validates", st == 200 and r["result"]["state"] == "VALIDATED",
          str(r)[:200])
    st, r = m("test_gateway_extension",
              {"revision_id": rev2, "test_payload": {"include_gpu": False}})
    _r2 = r.get("result") or {}
    check("v2 tests", st == 200 and _r2.get("passed") is True
          and _r2.get("state") == "TESTED",
          str(_r2.get("error"))[:300])
    st, r = m("activate_gateway_extension", {"revision_id": rev2})
    check("v2 activates",
          st == 200 and (r.get("result") or {}).get("active_revision") == rev2,
          str(r)[:200])
    st, r = call(EXT_NAME, {"include_gpu": False}, JOB)
    check("the registry now serves v2",
          st == 200 and (r.get("result") or {}).get("revision_marker") == "v2",
          str(r.get("result"))[:200])

    st, r = m("get_gateway_extension", {"name": EXT_NAME})
    revs = (r["result"] or {}).get("revisions") or []
    check("history retains both revisions",
          len([x for x in revs if x["revision_id"] in (rev1, rev2)]) == 2,
          str([x["revision_id"] for x in revs]))

    section("9. ROLLBACK to the previous known-good revision")
    st, r = m("rollback_gateway_extension", {"name": EXT_NAME})
    check("rollback returns 200", st == 200, str(r)[:400])
    _rb = r.get("result") or {}
    check("rollback reports the revision it moved to",
          _rb.get("active_revision") == rev1,
          str(_rb)[:300])
    st, r = call(EXT_NAME, {"include_gpu": False}, JOB)
    check("v1 behaviour is restored (no revision_marker)",
          st == 200 and "revision_marker" not in (r.get("result") or {}),
          str(r.get("result"))[:200])

    section("10. DISABLED removes it from the active registry")
    st, r = m("disable_gateway_extension", {"name": EXT_NAME})
    check("disable returns 200", st == 200, str(r)[:300])
    st, r = call("tools", None, MAINT, method="GET")
    names = [t["name"] for t in r["result"]["tools"]]
    check("disabled extension is gone from the registry",
          EXT_NAME not in names, "still present")
    st, r = call(EXT_NAME, {}, JOB)
    check("invoking a disabled extension is 404", st == 404, "got %s" % st)

    section("11. Extensions cannot shadow or mutate core tools")
    st, r = m("upsert_gateway_extension",
              {"manifest": manifest("1.0.0",
                                    "def handle(p, caps):\n    return {}\n",
                                    caps=[], name="submit_job")})
    check("cannot take an operational tool name",
          st == 409 and r["error"]["code"] == "NAME_COLLIDES_WITH_CORE_TOOL",
          "got %s %s" % (st, r.get("error", {}).get("code")))
    st, r = m("upsert_gateway_extension",
              {"manifest": manifest("1.0.0",
                                    "def handle(p, caps):\n    return {}\n",
                                    caps=[], name="activate_gateway_extension")})
    check("cannot take a maintainer tool name",
          st == 409 and r["error"]["code"] == "NAME_COLLIDES_WITH_CORE_TOOL",
          "got %s" % st)
    st, r = call("submit_job", {"command": "echo CORE_INTACT",
                                "timeout_s": 60}, JOB)
    check("core submit_job still works after all of the above",
          st == 200, str(r)[:200])
    core_job = r["result"]["job_id"]

    section("12. Capability restrictions are actually enforced")
    st, r = m("upsert_gateway_extension",
              {"manifest": manifest(
                  "1.0.0",
                  "def handle(p, caps):\n    return caps.ssh_status()\n",
                  caps=[], name="cap_undeclared_probe")})
    undeclared_rev = r["result"]["revision_id"]
    st, r = m("validate_gateway_extension", {"revision_id": undeclared_rev})
    check("using an undeclared capability fails validation",
          st == 400 and r["error"]["code"] == "VALIDATION_FAILED",
          "got %s" % st)

    st, r = m("upsert_gateway_extension",
              {"manifest": manifest(
                  "1.0.0",
                  "def handle(p, caps):\n    return caps.ssh_root_shell()\n",
                  caps=["ssh.status"], name="cap_unknown_probe")})
    unknown_rev = r["result"]["revision_id"]
    st, r = m("validate_gateway_extension", {"revision_id": unknown_rev})
    check("an unknown capability handle fails validation",
          st == 400, "got %s" % st)

    section("13. Extension code does not run inside the Gateway process")
    marker = "CGW_INPROC_PROBE_%d" % int(time.time())
    probe_src = (
        "def handle(payload, caps):\n"
        "    import os\n"
        "    return {'pid': os.getpid(), 'cwd': os.getcwd()}\n"
    )
    st, r = m("upsert_gateway_extension",
              {"manifest": manifest("1.0.0", probe_src, caps=[],
                                    name="proc_isolation_probe")})
    probe_rev = r["result"]["revision_id"]
    m("validate_gateway_extension", {"revision_id": probe_rev})
    st, r = m("test_gateway_extension", {"revision_id": probe_rev,
                                         "test_payload": {}})
    probe_out = ((r.get("result") or {}).get("result") or {}).get("output") or {}
    gw_pid = subprocess.run(["systemctl", "show", "compute-gateway.service",
                             "-p", "MainPID", "--value"],
                            capture_output=True, text=True).stdout.strip()
    check("extension ran in a different process than the Gateway",
          str(probe_out.get("pid")) not in ("", "None", gw_pid),
          "extension pid=%s gateway pid=%s" % (probe_out.get("pid"), gw_pid))
    check("extension cwd is its own sandbox, not the app tree",
          "sandbox" in (probe_out.get("cwd") or ""),
          str(probe_out.get("cwd")))
    _ = marker

    section("14. Audit events were recorded")
    audit_path = "/opt/services/logs/compute-gateway/compute-gateway-audit.log"
    try:
        with open(audit_path) as fh:
            audit = fh.read()
    except OSError as exc:
        audit = ""
        check("audit log is readable", False, str(exc))
    for tool in ("upsert_gateway_extension", "validate_gateway_extension",
                 "activate_gateway_extension", "rollback_gateway_extension",
                 "disable_gateway_extension"):
        check("audit recorded %s" % tool, tool in audit, "not found")
    check("audit never contains the maintenance token", MAINT not in audit)
    check("audit never contains the job token", JOB not in audit)

    section("15. Restart recovery")
    st, r = m("get_gateway_maintenance_status", {})
    before = r["result"]
    st, r = call("job_status", {"job_id": core_job, "refresh": True}, JOB)
    job_before = r.get("result") or {}

    subprocess.run(["systemctl", "restart", "compute-gateway.service"], check=True)
    time.sleep(6)

    st, r = m("get_gateway_maintenance_status", {})
    check("maintenance plane responds after restart", st == 200, str(r)[:200])
    check("extension metadata survived the restart",
          r["result"].get("extensions", {}).get("total") is not None
          or isinstance(r["result"].get("extensions"), dict),
          str(r["result"].get("extensions"))[:200])

    st, r = call("job_status", {"job_id": core_job, "refresh": True}, JOB)
    check("job history survived the restart",
          st == 200 and (r.get("result") or {}).get("job_id") == core_job,
          str(r)[:200])
    check("job state is unchanged across the restart",
          (r.get("result") or {}).get("status") == job_before.get("status"),
          "%s -> %s" % (job_before.get("status"),
                        (r.get("result") or {}).get("status")))

    st, r = m("get_gateway_extension", {"name": EXT_NAME})
    revs = (r["result"] or {}).get("revisions") or []
    check("both revisions survived the restart",
          len([x for x in revs if x["revision_id"] in (rev1, rev2)]) == 2,
          str(len(revs)))

    # DISABLED must reconstruct as DISABLED, not silently reactivate.
    st, r = call("tools", None, MAINT, method="GET")
    names = [t["name"] for t in r["result"]["tools"]]
    check("DISABLED extension does not come back active after restart",
          EXT_NAME not in names, "unexpectedly present")

    # Re-activate v1 and confirm the registry rebuilds correctly.
    st, r = m("activate_gateway_extension", {"revision_id": rev1})
    check("v1 can be re-activated after being disabled",
          st == 200 and (r.get("result") or {}).get("active_revision") == rev1,
          str(r)[:200])
    st, r = call("tools", None, MAINT, method="GET")
    names = [t["name"] for t in r["result"]["tools"]]
    check("re-activated extension is back in the registry", EXT_NAME in names)

    subprocess.run(["systemctl", "restart", "compute-gateway.service"], check=True)
    time.sleep(6)
    st, r = call("tools", None, MAINT, method="GET")
    names = [t["name"] for t in r["result"]["tools"]]
    check("ACTIVE state reconstructs correctly after restart", EXT_NAME in names,
          "missing from registry")
    st, r = call(EXT_NAME, {"include_gpu": False}, JOB)
    check("reconstructed extension is invocable", st == 200, str(r)[:200])

    ps = subprocess.run(["ps", "-eo", "pid,cmd"], capture_output=True,
                        text=True).stdout
    n_gw = len([l for l in ps.splitlines() if "gateway.py" in l and "grep" not in l])
    n_worker = len([l for l in ps.splitlines()
                    if "worker_runner.py" in l and "grep" not in l])
    check("exactly one Gateway process after restarts", n_gw == 1,
          "found %d" % n_gw)
    check("no orphaned worker processes remain", n_worker == 0,
          "found %d" % n_worker)

    section("16. Clean up the probe extensions")
    for nm in ("cap_undeclared_probe", "cap_unknown_probe",
               "proc_isolation_probe"):
        st, r = m("disable_gateway_extension", {"name": nm})
        check("%s disabled" % nm, st in (200, 404), "got %s" % st)

    # ----------------------------------------------------------------------
    section("SUMMARY")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = [x for x in RESULTS if not x[1]]
    print("  checks passed: %d" % passed)
    print("  checks failed: %d" % len(failed))
    for label, _, detail in failed:
        print("    FAIL  %s  :: %s" % (label, detail[:160]))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
