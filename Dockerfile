# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base

# Disable Ultralytics analytics / phone-home behavior at the OS level.
# This is reinforced in the application bootstrap (YOLO.settings.update).
ENV YOLO_OFFLINE=1 \
    YOLO_VERBOSE=False \
    PYTHONFAULTHANDLER=0 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps required by OpenCV at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy files referenced by pyproject.toml (LICENSE, README) plus the
# source tree so the editable install can resolve metadata.
COPY pyproject.toml LICENSE README.md ./
COPY src ./src

RUN pip install --upgrade pip && pip install -e .

# Pre-download model weights at build time so the runtime container
# does not need outbound internet access — first request is served
# immediately, no 30-60s cold start, no surprise download during prod.
# The URLs match the defaults in src/scoville_vision/vision.py.
RUN mkdir -p /app/models && \
    curl -fsSL \
      "https://huggingface.co/AdamCodd/YOLOv11n-face-detection/resolve/main/model.pt" \
      -o /app/models/yolov11n-face.pt && \
    curl -fsSL \
      "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx" \
      -o /app/models/face_recognition_sface_2021dec.onnx
ENV SCOVILLE_VISION_MODELS=/app/models

EXPOSE 8001

# Drop core dumps to avoid persisting any image bytes from a crash.
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl -fs http://localhost:8001/health || exit 1

CMD ["uvicorn", "scoville_vision.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
