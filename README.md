# OpenSandbox — Local API Examples

This is a local sandbox environment running the `opensandbox` PyPI package
(v0.1.16) via `opensandbox-server` (FastAPI/uvicorn), backed by Docker.

- Server: `http://localhost:8080`
- Interactive docs: `http://localhost:8080/docs`
- OpenAPI spec: `http://localhost:8080/openapi.json`
- Health check: `http://localhost:8080/health`

All examples below use the versioned `/v1` API prefix.

## Health & version

```bash
curl -s http://localhost:8080/health
curl -s http://localhost:8080/version
```

## Create a sandbox

`entrypoint` is required whenever `image` is provided, and `resourceLimits`
is required unless a `poolRef` is used instead.

```bash
curl -s -X POST http://localhost:8080/v1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "image": {"uri": "python:3.11-slim"},
    "entrypoint": ["sleep", "300"],
    "timeout": 300,
    "resourceLimits": {"cpu": "500m", "memory": "512Mi"},
    "metadata": {"purpose": "manual-api-test"}
  }'
```

Save the returned `id` for the calls below:

```bash
SID=<sandbox-id-from-response>
```

## Get sandbox details

```bash
curl -s http://localhost:8080/v1/sandboxes/$SID
```

## List sandboxes

```bash
curl -s http://localhost:8080/v1/sandboxes
```

## Diagnostics

```bash
# Combined summary: inspect + events + last 50 log lines
curl -s http://localhost:8080/v1/sandboxes/$SID/diagnostics/summary

curl -s http://localhost:8080/v1/sandboxes/$SID/diagnostics/logs
curl -s http://localhost:8080/v1/sandboxes/$SID/diagnostics/inspect
curl -s http://localhost:8080/v1/sandboxes/$SID/diagnostics/events
```

## Pause / resume

```bash
curl -s -X POST http://localhost:8080/v1/sandboxes/$SID/pause
curl -s -X POST http://localhost:8080/v1/sandboxes/$SID/resume
```

## Renew expiration

```bash
curl -s -X POST http://localhost:8080/v1/sandboxes/$SID/renew-expiration
```

## Patch metadata

```bash
curl -s -X PATCH http://localhost:8080/v1/sandboxes/$SID/metadata \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"purpose": "updated-label"}}'
```

## Snapshots

```bash
# Create a snapshot of the sandbox
curl -s -X POST http://localhost:8080/v1/sandboxes/$SID/snapshots

# List / get / delete snapshots
curl -s http://localhost:8080/v1/snapshots
curl -s http://localhost:8080/v1/snapshots/<snapshot-id>
curl -s -X DELETE http://localhost:8080/v1/snapshots/<snapshot-id>
```

## Pools

```bash
curl -s -X POST http://localhost:8080/v1/pools \
  -H "Content-Type: application/json" \
  -d '{
    "name": "example-pool",
    "image": {"uri": "python:3.11-slim"},
    "entrypoint": ["sleep", "300"],
    "resourceLimits": {"cpu": "500m", "memory": "512Mi"}
  }'

curl -s http://localhost:8080/v1/pools
curl -s http://localhost:8080/v1/pools/example-pool
curl -s -X DELETE http://localhost:8080/v1/pools/example-pool
```

## Proxy into a sandboxed port

The injected `execd` daemon (and any app you run inside the sandbox) can be
reached through the proxy route:

```bash
curl -s http://localhost:8080/v1/sandboxes/$SID/endpoints/<port>
curl -s http://localhost:8080/v1/sandboxes/$SID/proxy/<port>/<path>
```

## Delete a sandbox

```bash
curl -s -X DELETE http://localhost:8080/v1/sandboxes/$SID
```

A subsequent `GET` on a deleted sandbox returns `404` with
`{"code": "DOCKER::SANDBOX_NOT_FOUND", ...}`.
