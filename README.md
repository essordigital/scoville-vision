# scoville-vision

Face detection and embedding microservice for the Scoville analytics platform.

Stateless HTTP service that takes an image, detects faces, returns bounding
boxes, 5-point landmarks, and 512-dimensional embeddings. Designed to be
called over a private mesh network (Tailscale / WireGuard) from a downstream
analytics worker.

## Design

- **Detection**: YOLOv11-face (Ultralytics)
- **Embedding**: SFace (OpenCV DNN, 512-dim)
- **Alignment**: 5-point landmarks (from YOLO output or MediaPipe fallback)
- **Transport**: synchronous HTTP via FastAPI / Uvicorn
- **State**: none. Images are processed in RAM and discarded after the
  response is sent. No database, no on-disk storage of input data.

## Privacy & compliance

This service handles images that may contain personal data (faces). See
[COMPLIANCE.md](./COMPLIANCE.md) for a full description of the data
processing posture, retention (none), and audit log policy.

## API

### `POST /detect`

Input: image bytes (`multipart/form-data` field `image`, or base64-encoded
in a JSON body).

Output:

```json
{
  "version": "1.0.0",
  "image": { "width": 1920, "height": 1280 },
  "faces": [
    {
      "id": 0,
      "bbox": [x1, y1, x2, y2],
      "score": 0.97,
      "embedding": [0.012, -0.045, ...],
      "landmarks_5pt": [[lx1, ly1], ..., [lx5, ly5]]
    }
  ],
  "process_time_ms": 142
}
```

### `POST /embed`

Re-embed an already-detected face crop. Input: `{ image_b64, bbox }`.
Output: `{ embedding: [512 floats] }`.

### `GET /health`

Liveness probe. Returns `{ "status": "ok", "version": "1.0.0", "uptime_s": 1234 }`.

## Quick start (development)

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
uvicorn scoville_vision.main:app --port 8001
```

## Container

```bash
docker build -t scoville-vision:dev .
docker run --rm -p 8001:8001 \
  -e YOLO_OFFLINE=1 \
  --ulimit core=0 \
  scoville-vision:dev
```

## License

[GNU Affero General Public License v3.0](./LICENSE). If you modify and
operate this service over a network, you must make the modified source
available to its users.

## Status

This repository is in initial scaffolding. Implementation is tracked in
issues.

## Continuous integration

CI checks are exposed via the `Makefile` so they can run locally and
from any CI system. To match what the eventual GitHub Actions workflow
will execute:

```bash
make ci   # ruff check + pytest
make scan # trivy image scan (requires trivy installed locally)
```

The GitHub Actions YAML workflow will be added once the deploy key /
PAT used to push to this repository has the `workflow` OAuth scope.
