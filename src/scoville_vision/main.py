"""FastAPI HTTP entry point for scoville-vision.

The service is stateless: each request is processed in RAM and the
image bytes are discarded immediately after the response is built. See
COMPLIANCE.md at the repository root for the full data processing
posture.
"""
from __future__ import annotations

import base64
import gc
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from scoville_vision import __version__
from scoville_vision.models import (
    DetectResponse,
    EmbedRequest,
    EmbedResponse,
    HealthResponse,
    ImageDimensions,
)
from scoville_vision.vision import VisionService

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

_service: VisionService | None = None
_startup_ts: float = 0.0


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load models once at startup, release at shutdown."""
    global _service, _startup_ts
    _startup_ts = time.time()
    logger.info("scoville-vision %s starting up", __version__)
    _service = VisionService()
    logger.info("Models loaded, ready to serve")
    yield
    logger.info("scoville-vision shutting down")
    _service = None


app = FastAPI(
    title="scoville-vision",
    version=__version__,
    description=(
        "Face detection and embedding microservice for the Scoville analytics "
        "platform. Stateless — see COMPLIANCE.md for the data processing posture."
    ),
    lifespan=lifespan,
)


def _decode_image(data: bytes) -> np.ndarray:
    """Decode image bytes to a BGR uint8 numpy array."""
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(
            status_code=400, detail="Could not decode image (unsupported format or corrupted)"
        )
    return image


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe. Returns version + uptime + model load status."""
    uptime_s = time.time() - _startup_ts if _startup_ts else 0.0
    models = _service.models_loaded() if _service else {"yolo_face": False, "sface": False}
    return HealthResponse(
        status="ok",
        version=__version__,
        uptime_s=uptime_s,
        models_loaded=models,
    )


@app.post("/detect", response_model=DetectResponse)
async def detect(image: Annotated[UploadFile, File(description="Image to process")]) -> DetectResponse:
    """Detect all faces in the supplied image, return bboxes + embeddings.

    Input: multipart form field `image` containing a JPEG or PNG.
    Output: see models.DetectResponse.

    Image bytes are discarded from memory once the response is built.
    """
    if _service is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty image payload")

    t0 = time.perf_counter()
    img = _decode_image(data)
    height, width = img.shape[:2]

    try:
        faces = _service.detect_and_embed(img)
    finally:
        # Explicit cleanup of the raw image data — see COMPLIANCE.md.
        del data
        del img
        gc.collect()

    process_time_ms = (time.perf_counter() - t0) * 1000.0
    return DetectResponse(
        version=__version__,
        image=ImageDimensions(width=width, height=height),
        faces=faces,
        process_time_ms=round(process_time_ms, 1),
    )


@app.post("/embed", response_model=EmbedResponse)
async def embed(payload: EmbedRequest) -> EmbedResponse:
    """Compute the embedding of an already-cropped face (or a bbox region)."""
    if _service is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        data = base64.b64decode(payload.image_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64: {exc}") from exc

    t0 = time.perf_counter()
    img = _decode_image(data)

    try:
        if payload.bbox is not None:
            x1, y1, x2, y2 = payload.bbox
            h, w = img.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                raise HTTPException(status_code=400, detail="Invalid bbox")
            img = img[y1:y2, x1:x2]

        embedding = _service.embed_crop(img)
    finally:
        del data
        del img
        gc.collect()

    process_time_ms = (time.perf_counter() - t0) * 1000.0
    return EmbedResponse(
        embedding=embedding,
        process_time_ms=round(process_time_ms, 1),
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_request, exc: Exception):
    """Return a sanitized 500 — never leak request data into the response."""
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error", "type": exc.__class__.__name__},
    )
