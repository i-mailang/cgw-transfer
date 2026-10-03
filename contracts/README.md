# Compute Gateway — Site Transport Contract v1

**Machine-readable contract:** `site_gateway_transport_v1.json`
**Gateway version:** 0.2.0
**Production commit:** `d18849ff127188bd2e99c92544d734a5ee8a85cc`

This document describes how the ChatGPT Site talks to the Compute Gateway.
The JSON file is authoritative; this README explains the design.

---

## 1. Base URL

```
GATEWAY_BASE_URL=https://<hostname>
```

All routes are relative to this base. The Gateway itself binds `127.0.0.1:8787`
only; Caddy is the sole public ingress.

---

## 2. Authentication

Two credentials, two privilege planes. Both are compared with constant-time
equality; neither is ever logged.

| Credential | Header | Plane |
|---|---|---|
| Job token | `Authorization: Bearer <job_token>` | operational |
| Maintenance token | `X-Maintenance-Token: <maintenance_token>` **or** `Authorization: Bearer <maintenance_token>` | maintainer |

**Job token** can call:
- All operational core tools (`health`, `system_status`, `gpu_status`,
  `submit_job`, `job_status`, `job_logs`, `cancel_job`, `list_jobs`,
  `list_artifacts`, `get_artifact`)
- All ACTIVE dynamic extensions

**Maintenance token** can call everything above **plus**:
- `tools` (registry, includes maintainer tools and ACTIVE extensions)
- `list_gateway_extensions`, `get_gateway_extension`
- `upsert_gateway_extension`, `validate_gateway_extension`,
  `test_gateway_extension`, `activate_gateway_extension`,
  `disable_gateway_extension`, `rollback_gateway_extension`
- `get_gateway_maintenance_status`

A job token calling a maintainer tool gets **401 UNAUTHORIZED**.

---

## 3. Routes

### 3.1 Service root (unauthenticated)

```
GET /
→ 200 {"service": "compute-gateway", "version": "0.2.0",
        "health": "/v1/health", "tools": "/v1/tools"}
```

### 3.2 Tool registry

```
GET /v1/tools
```

Requires authentication. Returns the caller's privilege-filtered manifest.

**Job token** sees: 10 operational core tools + ACTIVE extensions.
**Maintenance token** sees: 10 operational + 9 maintainer + ACTIVE extensions.

Response:
```json
{
  "plane": "operational" | "maintainer",
  "tools": [
    {
      "name": "health",
      "summary": "Gateway liveness plus HPC reachability.",
      "endpoint": "/v1/health",
      "method": "POST",
      "plane": "operational" | "maintainer" | "extension",
      "timeout_s": 60.0,
      "parameters": {
        "type": "object",
        "properties": { ... },
        "required": [ ... ]
      }
    }
  ]
}
```

Extension tools additionally carry `revision_id` and `source_hash`.

### 3.3 Tool invocation

```
POST /v1/<tool_name>
Content-Type: application/json
Authorization: Bearer <job_token>          # for operational + extensions
X-Maintenance-Token: <maintenance_token>   # for maintainer tools

{ ... tool-specific parameters ... }
```

**Success:**
```json
{"ok": true, "result": { ... }}
```

**Error:**
```json
{"ok": false, "error": {"code": "...", "message": "...", "details": { ... }}}
```

### 3.4 Extension lifecycle (maintainer only)

All are `POST /v1/<tool_name>` with JSON body:

| Tool | Required params | Optional params |
|---|---|---|
| `upsert_gateway_extension` | `manifest` | `note` |
| `validate_gateway_extension` | `revision_id` | — |
| `test_gateway_extension` | `revision_id` | `test_payload` |
| `activate_gateway_extension` | `revision_id` | — |
| `disable_gateway_extension` | `name` | — |
| `rollback_gateway_extension` | `name` | `to_revision` |

---

## 4. Dynamic extension visibility

**Only ACTIVE extensions appear in `/v1/tools`.**

The Gateway's `ExtensionRuntime.refresh_dynamic()` rebuilds the dynamic layer
from revisions whose state is exactly `ACTIVE`. Revisions in `DRAFT`,
`VALIDATED`, `TESTED`, or `DISABLED` are never published to the tool registry.

This is why a newly activated extension appears in `tools/list` immediately —
no Site redeployment is needed. The Site queries `/v1/tools` on every
`tools/list` request.

---

## 5. Error codes and HTTP status

| Code | HTTP | Meaning |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing or invalid credentials |
| `BAD_REQUEST` | 400 | Malformed body, missing required param, type mismatch |
| `NOT_FOUND` | 404 | Unknown tool or route |
| `INTERNAL_ERROR` | 500 | Unexpected server error |
| `VALIDATION_FAILED` | 400 | Extension failed static validation |
| `INVALID_STATE` | 409 | Extension lifecycle state transition not allowed |
| `NOT_TESTED` | 409 | Cannot activate a revision that has not passed testing |
| `NAME_COLLIDES_WITH_CORE_TOOL` | 409 | Extension name conflicts with a core tool |
| `EXTENSION_NOT_FOUND` | 404 | No extension with that name |
| `REVISION_NOT_FOUND` | 404 | No revision with that ID |
| `EXTENSION_TIMEOUT` | 504 | Extension exceeded its timeout |
| `EXTENSION_FAILED` | 500 | Extension worker reported failure |
| `EXTENSION_OUTPUT_TOO_LARGE` | 413 | Extension produced too much output |
| `IMPLEMENTATION_TOO_LARGE` | 413 | Extension source exceeds 256 KB |
| `TIMEOUT_OUT_OF_RANGE` | 400 | Extension timeout not in [5, 600] |
| `UNKNOWN_CAPABILITY` | 400 | Extension declares an unknown capability |
| `BAD_NAME` | 400 | Extension name does not match `^[a-z][a-z0-9_]{2,63}$` |
| `BAD_VERSION` | 400 | Extension version is not semver-like |
| `BAD_SCHEMA` | 400 | input/output schema is not a JSON Schema object |
| `BAD_IMPLEMENTATION` | 400 | implementation is empty |
| `BAD_CAPABILITIES` | 400 | capabilities is not an array of strings |
| `BAD_TIMEOUT` | 400 | timeout is not an integer |
| `MANIFEST_INVALID` | 400 | manifest is not a JSON object |
| `MANIFEST_INCOMPLETE` | 400 | manifest missing a required field |
| `BAD_DESCRIPTION` | 400 | description is empty |
| `SYNTAX_ERROR` | 400 | extension source has a Python syntax error |
| `PATH_ESCAPE` | 400 | artifact path escapes the artifact root |
| `SYMLINK_ESCAPE` | 400 | artifact resolves outside the artifact root |
| `ARTIFACT_NOT_FOUND` | 404 | artifact does not exist |
| `ARTIFACT_TOO_LARGE` | 413 | artifact exceeds size limit |
| `JOB_NOT_FOUND` | 404 | job does not exist |
| `HOME_UNRESOLVED` | 400 | SSH host key fingerprint mismatch |

---

## 6. Timeouts

| Tool | Timeout (seconds) |
|---|---|
| `health` | 60 |
| `system_status` | 60 |
| `gpu_status` | 60 |
| `submit_job` | 240 |
| `job_status` | 120 |
| `job_logs` | 120 |
| `cancel_job` | 120 |
| `list_jobs` | 60 |
| `list_artifacts` | 60 |
| `get_artifact` | 60 |
| `tools` | 30 |
| `list_gateway_extensions` | 30 |
| `get_gateway_extension` | 30 |
| `upsert_gateway_extension` | 60 |
| `validate_gateway_extension` | 60 |
| `test_gateway_extension` | 660 |
| `activate_gateway_extension` | 60 |
| `disable_gateway_extension` | 60 |
| `rollback_gateway_extension` | 60 |
| `get_gateway_maintenance_status` | 30 |
| Dynamic extensions | 5–600 (per manifest) |

The Gateway enforces these with `subprocess.run(timeout=...)`. The Site should
set its read timeout to at least `timeout_s + 30` for any tool.

---

## 7. Security boundaries

- Credentials are never included in tool arguments or responses.
- The Gateway logs tool name, plane, params, and timing — never credentials.
- The audit log records the same, plus the client identifier.
- Extension code runs in an isolated worker process with no network, no
  database, no SSH key, and no host filesystem access.
- The Gateway binds `127.0.0.1:8787` only. Caddy is the sole public ingress.
