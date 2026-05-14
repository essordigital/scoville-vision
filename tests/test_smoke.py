"""Smoke tests that do not require model weights.

The full inference path is exercised in integration tests (skipped by
default in CI; opt-in with `RUN_INTEGRATION_TESTS=1`).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


def test_models_module_imports():
    """The Pydantic I/O module should import without pulling in OpenCV/YOLO."""
    from scoville_vision import models

    face = models.Face(
        id=0,
        bbox=[10, 10, 50, 50],
        score=0.9,
        embedding=[0.0] * 512,
    )
    assert face.bbox == [10, 10, 50, 50]
    assert len(face.embedding) == 512


def test_face_embedding_size_validation():
    """Embeddings must be exactly 512 floats."""
    from scoville_vision import models

    with pytest.raises(ValueError):
        models.Face(id=0, bbox=[0, 0, 1, 1], score=0.5, embedding=[0.0] * 100)


def test_detect_response_serialization():
    """The full DetectResponse should round-trip through JSON cleanly."""
    from scoville_vision import models

    resp = models.DetectResponse(
        version="0.1.0",
        image=models.ImageDimensions(width=1920, height=1280),
        faces=[],
        process_time_ms=42.0,
    )
    dumped = resp.model_dump_json()
    rebuilt = models.DetectResponse.model_validate_json(dumped)
    assert rebuilt.image.width == 1920


@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require model weights — set RUN_INTEGRATION_TESTS=1 to enable",
)
def test_health_endpoint_with_models():
    """End-to-end smoke: /health should return ok once models are loaded."""
    from scoville_vision.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["models_loaded"]["yolo_face"] is True
        assert body["models_loaded"]["sface"] is True
