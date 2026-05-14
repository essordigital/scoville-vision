"""I/O models for the scoville-vision HTTP API.

All payloads are JSON. Image bytes flow as `multipart/form-data` on
`POST /detect` (most efficient) or base64-encoded inside JSON when the
caller cannot easily multipart-upload.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Point(BaseModel):
    x: float
    y: float


class Face(BaseModel):
    """A single detected face with its embedding."""
    id: int = Field(description="Index in the detection list, stable per request only")
    bbox: list[int] = Field(
        description="[x1, y1, x2, y2] in absolute pixel coordinates",
        min_length=4,
        max_length=4,
    )
    score: float = Field(ge=0.0, le=1.0, description="Detection confidence")
    embedding: list[float] = Field(
        description="128-dim L2-normalized face embedding from SFace "
                    "(OpenCV's face_recognition_sface_2021dec.onnx)",
        min_length=128,
        max_length=128,
    )
    landmarks_5pt: list[list[float]] | None = Field(
        default=None,
        description="5 facial keypoints (right eye, left eye, nose, right mouth, left mouth) "
                    "in absolute pixel coordinates. None when the detector did not return them.",
    )


class ImageDimensions(BaseModel):
    width: int
    height: int


class DetectResponse(BaseModel):
    """Result of POST /detect."""
    version: str = Field(description="Service version (semver)")
    image: ImageDimensions
    faces: list[Face]
    process_time_ms: float


class EmbedRequest(BaseModel):
    """Payload for POST /embed when re-embedding an already-cropped face."""
    image_b64: str = Field(description="Base64-encoded face crop (PNG or JPEG)")
    bbox: list[int] | None = Field(
        default=None,
        description="Optional bbox if image_b64 is the full image, "
                    "not just a pre-cropped face",
        min_length=4,
        max_length=4,
    )


class EmbedResponse(BaseModel):
    embedding: list[float] = Field(min_length=128, max_length=128)
    process_time_ms: float


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    uptime_s: float
    models_loaded: dict[str, bool]
