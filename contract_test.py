#!/usr/bin/env python3
"""
Contract test: prove contracts/site_gateway_transport_v1.json matches the
live Gateway behaviour.

This is not a unit test of the Gateway. It is a conformance test of the
DOCUMENT: every claim the contract makes about routes, envelopes, status
codes and visibility semantics is checked against a running instance.

Run against a live Gateway:
    python3 contract_test.py http://127.0.0.1:8787 <job_token> <maint_token>

Exit 0 = the contract is accurate. Any failure means the document has drifted
from the implementation and must be corrected.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787").rstrip("/")
JOB = sys.argv[2] if len(sys.argv) > 2 else ""
MAINT = sys.argv[3] if len(sys.argv) > 3 else ""
CONTRACT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "contracts", "site_gateway_transport_v1.json")

PASSED = 0
FAILED = 0


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  PASS  %s" % label)
    else:
        FAILED += 1
        print("  FAIL  %s  %s" % (label, str(detail)[:200]))


def call(path, body=None, job=True, maint=None, raw=False):
    """Issue a request. Returns (status, parsed_or_text)."""
    url = BASE + path
    data = None
    headers = {"Content-Type": "application/json"}
    if maint is not None:
        headers["X-Maintenance-Token"] = maint
    elif job and JOB:
        headers["Authorization"] = "Bearer " + JOB
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode()
            return resp.status, (text if raw else (json.loads(text) if text else {}))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode()
        try:
            return exc.code, json.loads(text) if text else {}
        except json.JSONDecodeError:
            return exc.code, {"raw": text[:300]}


def main():
    if not JOB or not MAINT:
        print("usage: contract_test.py <base_url> <job_token> <maint_token>")
        return 2
    doc = json.load(open(CONTRACT, encoding="utf-8"))
    print("contract: %s (v%s)" % (doc["contract_id"], doc["version"]))
    print()

    # --- 1. unauthenticated is rejected on every protected route ---
    print("1. Unauthenticated rejection")
    for path in ("/v1/tools", "/v1/health"):
        st, _ = call(path, job=False)
        check("GET %s without credentials -> 401" % path, st == 401, st)
    st, _ = call("/v1/tools", {"command": "true"}, job=False)
    check("POST /v1/tools without credentials -> 401", st == 401, st)

    # --- 2. error envelope shape ---
    print("\n2. Error envelope")
    st, body = call("/v1/tools", job=False)
    check("error sets ok=false", body.get("ok") is False, body)
    check("error has code/message/details",
          set(body.get("error", {})) >= {"code", "message", "details"}, body)
    check("error code is UNAUTHORIZED", body["error"]["code"] == "UNAUTHORIZED", body)

    # --- 3. success envelope shape ---
    print("\n3. Success envelope")
    st, body = call("/v1/health", job=True)
    check("health -> 200", st == 200, st)
    check("success sets ok=true", body.get("ok") is True, body)
    check("success carries result", "result" in body, body)

    # --- 4. registry: job plane sees operational tools only ---
    print("\n4. Registry - job plane")
    st, body = call("/v1/tools", job=True)
    tools = {t["name"]: t for t in body.get("result", {}).get("tools", [])}
    check("job plane gets 200", st == 200, st)
    check("operational tool 'health' present", "health" in tools, sorted(tools))
    check("operational tool 'submit_job' present", "submit_job" in tools, sorted(tools))
    check("maintainer tool 'upsert_gateway_extension' absent",
          "upsert_gateway_extension" not in tools, sorted(tools))
    check("tool metadata carries name/summary/endpoint/method/plane",
          all(k in tools.get("health", {}) for k in
              ("name", "summary", "endpoint", "method", "plane")),
          tools.get("health"))
    check("tool metadata carries parameters with properties+required",
          "properties" in tools["health"]["parameters"]
          and "required" in tools["health"]["parameters"],
          tools["health"]["parameters"])

    # --- 5. registry: maintainer plane sees core + ACTIVE extensions ---
    print("\n5. Registry - maintainer plane")
    st, body = call("/v1/tools", maint=MAINT)
    mtools = {t["name"]: t for t in body.get("result", {}).get("tools", [])}
    check("maintainer plane gets 200", st == 200, st)
    check("maintainer tool 'upsert_gateway_extension' present",
          "upsert_gateway_extension" in mtools, sorted(mtools))
    check("ACTIVE extension 'hpc_runtime_info' present",
          "hpc_runtime_info" in mtools, sorted(mtools))
    check("ACTIVE extension is marked plane=extension",
          mtools.get("hpc_runtime_info", {}).get("plane") == "extension",
          mtools.get("hpc_runtime_info"))

    # --- 6. privilege separation on invocation ---
    print("\n6. Privilege separation")
    st, body = call("/v1/upsert_gateway_extension",
                    {"manifest": {"name": "x", "version": "1.0.0",
                                  "description": "x",
                                  "input_schema": {"type": "object", "properties": {}},
                                  "output_schema": {"type": "object", "properties": {}},
                                  "implementation": "def handle(p, caps):\n    return {}\n"}},
                    job=True)
    check("job token invoking maintainer tool -> 401", st == 401, st)
    check("rejection names the tool",
          body.get("error", {}).get("details", {}).get("tool")
          == "upsert_gateway_extension", body)

    # --- 7. ACTIVE extension is callable with the job credential ---
    print("\n7. ACTIVE extension invocation")
    st, body = call("/v1/hpc_runtime_info", {"include_gpu": False}, job=True)
    check("job token invokes ACTIVE extension -> 200", st == 200, st)
    out = body.get("result", {})
    check("returns real HPC identity",
          bool(out.get("remote_hostname")) and bool(out.get("remote_user")), out)

    # --- 8. non-ACTIVE revisions are not callable ---
    print("\n8. Non-ACTIVE revisions invisible")
    st, body = call("/v1/tools", maint=MAINT)
    names = {t["name"] for t in body.get("result", {}).get("tools", [])}
    check("no DRAFT/VALIDATED/TESTED-only extension is callable",
          "hpc_runtime_info" in names, sorted(names))

    # --- 9. unknown tool ---
    print("\n9. Unknown tool")
    st, body = call("/v1/no_such_tool", {}, job=True)
    check("unknown tool -> 404 NOT_FOUND",
          st == 404 and body.get("error", {}).get("code") == "NOT_FOUND", (st, body))

    # --- 10. parameter validation ---
    print("\n10. Parameter validation")
    st, body = call("/v1/job_status", {}, job=True)
    check("missing required param -> 400 BAD_REQUEST",
          st == 400 and body.get("error", {}).get("code") == "BAD_REQUEST", (st, body))

    # --- 11. credentials never in responses ---
    print("\n11. Credential hygiene")
    st, body = call("/v1/tools", maint=MAINT)
    blob = json.dumps(body)
    check("job token absent from registry response", JOB not in blob)
    check("maintainer token absent from registry response", MAINT not in blob)

    print()
    print("=" * 60)
    print("  contract checks passed: %d" % PASSED)
    print("  contract checks failed: %d" % FAILED)
    print("=" * 60)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
