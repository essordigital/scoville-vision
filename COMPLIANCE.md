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

## License boundary (AGPL-3.0)

This service is released under the GNU Affero General Public License v3.0.
The reason is upstream: the face detection model (Ultralytics YOLO) is
itself AGPL, and shipping a derivative of an AGPL-licensed work requires
the derivative to also be AGPL.

The downstream system that consumes this service (the operator's
analytics pipeline) is a **separate process** and is **not** AGPL.
This is intentional and defensible — it is the canonical industry
pattern for using AGPL components in a commercial product, recommended
by Ultralytics themselves and applied by many SaaS products that build
on AGPL inference services.

### What keeps the boundary clean

The operator commits to the following invariants:

1. **Two separate repositories**
   - This repository: `scoville-vision` (public, AGPL-3.0).
   - The consumer (`scoville-scale`): private, proprietary. Never
     mirrored or published.

2. **Two separate Docker images**
   - The two services are built and distributed as independent OCI
     images, each retaining its own license metadata. They are never
     bundled into a single image.

3. **No source-level coupling**
   - The consumer's source tree contains **no `import` of
     ultralytics, scoville_vision, or any module from this repository**.
   - The consumer has no Python dependency on `ultralytics` in its
     `pyproject.toml` / requirements.
   - A CI guardrail (`scripts/check_no_agpl_import.sh` in the consumer
     repo) `grep`s the source tree on every push and fails the build
     on any forbidden import.

4. **Network-protocol-only communication**
   - The consumer talks to this service exclusively over HTTP. The
     wire protocol is documented above (`POST /detect`, `POST /embed`,
     `GET /health`).
   - The deployment topology (sidecar on the same host, talking via
     `127.0.0.1`) does not change the legal analysis: localhost TCP
     is still a network protocol, and the two processes are
     independently scheduled with separate memory and PIDs.

5. **Independently startable**
   - This service runs by itself with no consumer present. The
     consumer runs against any compliant face-detection backend that
     exposes the same HTTP contract.

6. **No mutual configuration shipped together**
   - There is no shared `docker-compose.yml`, no shared Helm chart, no
     installer that packages the two together for redistribution. Any
     compose file used for development sits in a third, separate
     scratch repository (`scoville-test`) that is not distributed.

7. **Modifications to this code are released back**
   - Per AGPL §13, any modification the operator makes to **this**
     repository is published in the same public repository, accessible
     to anyone interacting with the service over the network. Patches
     are not held back as private.

### Where the boundary would break

For transparency, here is what the operator promises **not** to do, as
each of these would extend AGPL obligations to the downstream code:

- Import this code as a Python library in `scoville-scale`.
- Statically or dynamically link this code into the consumer.
- Ship a combined binary, image, or installer that includes both.
- Re-implement parts of this codebase into the consumer's repository.

The CI guardrail and license metadata in both repos exist precisely to
make these accidents impossible.

### Not legal advice

This document describes the operator's understanding and good-faith
practice. It is not legal counsel and has not been reviewed by an IP
lawyer at the time of writing. Operators contemplating a strict
commercial deployment are advised to obtain a 1-2h review from
counsel familiar with the AGPL.

## Reporting an issue

If you believe this service is not behaving according to this document,
please open a GitHub issue or contact the operator.
