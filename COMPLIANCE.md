# Compliance & data processing posture

`scoville-vision` is designed to be trivially auditable under GDPR. This
document describes the data processing posture and the technical controls
that back the claims.

## Summary

> This service is a stateless face detection and embedding compute box. It
> receives an image over HTTPS, detects faces, computes embeddings, returns
> the result, and discards everything from memory. No database. No log of
> input content. No third-party telemetry.

## Data flow

```
[caller]  ─── HTTPS over Tailscale ───►  [scoville-vision]
   ▲                                          │
   │                                          │  (in-memory only)
   │                                          ▼
   │                                    YOLO + SFace inference
   │                                          │
   └─────────── faces[] JSON ◄────────────────┘
```

| Step | What lives where |
|------|------------------|
| Network in | TLS-encrypted via the mesh (Tailscale WireGuard) |
| Image bytes | RAM only, scope = request handler |
| Inference | RAM only |
| Response | JSON over the same encrypted connection |
| After response | Image bytes freed (`del` + explicit `gc.collect()` after each request) |

## What is stored

**None.** This service has no database, no disk volume for input data, no
S3 bucket. The container filesystem contains the application code and
model weights; nothing user-supplied is written.

## What is logged

| Log type | Content | Retention |
|----------|---------|-----------|
| HTTP access log | timestamp, source IP (mesh-internal), HTTP method/path, status code, response size, process time | 7 days, rotated |
| Application log | startup, errors, performance metrics — no image content, no face data | 7 days, rotated |
| Audit log | none — this service has no privileged operations to audit |

The `DEBUG` log level is disabled in production. Logs never contain image
bytes, embeddings, or bounding-box coordinates of detected faces.

## Network

The service is only reachable via the internal mesh network. Access is
controlled by mesh ACLs (only the analytics workers are authorized to
contact `scoville-vision`). The public internet has no route to the
service.

## Third-party telemetry

The Ultralytics YOLO package emits analytics by default. This is disabled
at two layers:

1. Environment variable in the container: `YOLO_OFFLINE=1`
2. Programmatic kill switch at startup: `YOLO.settings.update({"sync": False})`

The deployment is verified post-install with `tcpdump` to confirm zero
egress traffic to third-party hosts.

## Process safety

- Core dumps disabled (`ulimit -c 0`) to prevent any image bytes from being
  written to disk in case of crash.
- `PYTHONFAULTHANDLER=0` to avoid stack traces that may contain incidental
  data.

## Data Processing Agreements

| Sub-processor | Role | Region | DPA |
|---------------|------|--------|-----|
| Hetzner Online GmbH | Compute hosting | EU (DE) | Standard DPA, signed |
| Tailscale Inc. | Mesh control plane (connection metadata only — no user data passes through Tailscale's servers) | US | Standard DPA, signed |

A migration path to a self-hosted mesh control plane (e.g. Headscale or
plain WireGuard) is on the roadmap if stricter data residency is required
by a downstream consumer.

## Right to erasure

Because this service does not store input data, there is nothing to erase
on this side. Erasure of stored derivatives (e.g. embeddings persisted
downstream) is the responsibility of the calling system, which holds the
authoritative storage.

## Auditing this service

A reviewer who wants to verify the claims above can:

1. Inspect this repository — it contains the full source of the service.
2. Run the service locally, exercise it with a sample image, observe that
   no file is written and no outbound traffic leaves the host beyond the
   expected response.
3. Check the container image layers to confirm no debugger / telemetry
   agent is installed.

## Reporting an issue

If you believe this service is not behaving according to this document,
please open a GitHub issue or contact the operator.
