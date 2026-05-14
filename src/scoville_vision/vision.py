"""Face detection + embedding pipeline.

Detection: YOLOv11-face (Ultralytics).
Embedding: SFace (OpenCV DNN).
Alignment: 5-point keypoints from the detector when available, otherwise
the bbox crop is used directly (slightly less accurate embedding but
acceptable for downstream clustering).

The module is intentionally a single class so a FastAPI app can hold one
instance for the process lifetime — model weights are big and should be
loaded exactly once at startup.
"""
from __future__ import annotations

import logging
import os
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Ultralytics emits telemetry by default; disable at the OS level and
# again programmatically below for defense in depth.
os.environ.setdefault("YOLO_OFFLINE", "1")
os.environ.setdefault("YOLO_VERBOSE", "False")

# Default model locations. Override via env var when the container runs
# offline (weights baked into the image at build time).
DEFAULT_YOLO_FACE_URL = (
    "https://huggingface.co/AdamCodd/YOLOv11n-face-detection/"
    "resolve/main/model.pt"
)
DEFAULT_SFACE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)

MODEL_CACHE_DIR = Path(os.environ.get("SCOVILLE_VISION_MODELS", "/app/models"))

# Standard SFace input is 112x112 BGR uint8.
SFACE_INPUT_SIZE = 112


def _download_if_missing(url: str, dest: Path) -> Path:
    """Pull a model weight file once and cache it on disk."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    logger.info("Downloading model weights: %s → %s", url, dest)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    return dest


def _align_face_5pt(
    image: np.ndarray, keypoints: np.ndarray, output_size: int = SFACE_INPUT_SIZE
) -> np.ndarray:
    """Affine-align a face crop using 5 keypoints to a canonical template.

    The template positions match what SFace was trained on. Order of
    keypoints expected: [right_eye, left_eye, nose, right_mouth, left_mouth].
    """
    # Standard ArcFace / SFace 5-point template for 112x112 input
    template = np.array(
        [
            [38.2946, 51.6963],
            [73.5318, 51.5014],
            [56.0252, 71.7366],
            [41.5493, 92.3655],
            [70.7299, 92.2041],
        ],
        dtype=np.float32,
    )
    if output_size != SFACE_INPUT_SIZE:
        template = template * (output_size / SFACE_INPUT_SIZE)

    src = np.array(keypoints[:5], dtype=np.float32).reshape(5, 2)
    # estimateAffinePartial2D returns (M, inliers) — we want the matrix
    matrix, _ = cv2.estimateAffinePartial2D(src, template, method=cv2.LMEDS)
    if matrix is None:
        # Degenerate keypoints (e.g. colinear). Fall back to bbox crop.
        return cv2.resize(image, (output_size, output_size))
    aligned = cv2.warpAffine(
        image, matrix, (output_size, output_size), borderValue=0.0
    )
    return aligned


def _crop_with_margin(
    image: np.ndarray, bbox: list[int], margin_ratio: float = 0.2
) -> np.ndarray:
    """Crop a face from an image with a margin around the bbox."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    mx, my = int(bw * margin_ratio), int(bh * margin_ratio)
    x1 = max(0, x1 - mx)
    y1 = max(0, y1 - my)
    x2 = min(w, x2 + mx)
    y2 = min(h, y2 + my)
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        # Defensive: should never happen with valid bboxes
        return np.zeros((SFACE_INPUT_SIZE, SFACE_INPUT_SIZE, 3), dtype=np.uint8)
    return crop


class VisionService:
    """Stateful container for the loaded face detection + embedding models.

    Instantiate once per process. Thread-safe for inference (Ultralytics
    and OpenCV release the GIL during native calls).
    """

    def __init__(
        self,
        yolo_weights: str | Path | None = None,
        sface_weights: str | Path | None = None,
    ) -> None:
        # Lazy import to avoid loading ultralytics when the module is
        # imported solely for type hints (e.g. by tests).
        from ultralytics import YOLO
        try:
            from ultralytics import settings as ultralytics_settings
            ultralytics_settings.update({"sync": False})
        except Exception:  # pragma: no cover — older ultralytics versions
            pass

        yolo_path = Path(yolo_weights) if yolo_weights else (
            _download_if_missing(
                DEFAULT_YOLO_FACE_URL, MODEL_CACHE_DIR / "yolov11n-face.pt"
            )
        )
        sface_path = Path(sface_weights) if sface_weights else (
            _download_if_missing(
                DEFAULT_SFACE_URL,
                MODEL_CACHE_DIR / "face_recognition_sface_2021dec.onnx",
            )
        )

        logger.info("Loading YOLO face detector: %s", yolo_path)
        self._yolo = YOLO(str(yolo_path))

        logger.info("Loading SFace recognizer: %s", sface_path)
        self._sface = cv2.FaceRecognizerSF.create(str(sface_path), "")

        self.yolo_weights_path = yolo_path
        self.sface_weights_path = sface_path

    def models_loaded(self) -> dict[str, bool]:
        return {
            "yolo_face": self._yolo is not None,
            "sface": self._sface is not None,
        }

    def detect_and_embed(self, image: np.ndarray) -> list[dict]:
        """Run the full detect → align → embed pipeline.

        Args:
            image: BGR uint8 numpy array (OpenCV's native format).

        Returns:
            List of dicts (one per detected face) with keys:
            bbox, score, embedding, landmarks_5pt.
        """
        if image is None or image.size == 0:
            return []

        # YOLO detection
        results = self._yolo.predict(
            image,
            verbose=False,
            conf=0.4,         # Default confidence threshold
            iou=0.5,          # NMS IoU
            max_det=200,      # Plenty for crowd shots
        )
        if not results:
            return []

        result = results[0]
        if result.boxes is None or len(result.boxes) == 0:
            return []

        boxes = result.boxes.xyxy.cpu().numpy().astype(int)
        scores = result.boxes.conf.cpu().numpy().astype(float)

        # Keypoints — present when the model is a "face" variant (5 points)
        keypoints_array: np.ndarray | None = None
        if getattr(result, "keypoints", None) is not None:
            kp = result.keypoints
            if kp is not None and kp.xy is not None:
                keypoints_array = kp.xy.cpu().numpy()

        faces_out: list[dict] = []
        for i, (bbox, score) in enumerate(zip(boxes, scores)):
            x1, y1, x2, y2 = bbox.tolist()

            # Pick alignment strategy: keypoints if available, else bbox crop
            if (
                keypoints_array is not None
                and keypoints_array.shape[1] >= 5
                and keypoints_array.shape[2] >= 2
            ):
                kp_face = keypoints_array[i]
                aligned = _align_face_5pt(image, kp_face)
                landmarks_out: list[list[float]] | None = kp_face.tolist()
            else:
                crop = _crop_with_margin(image, [x1, y1, x2, y2])
                aligned = cv2.resize(crop, (SFACE_INPUT_SIZE, SFACE_INPUT_SIZE))
                landmarks_out = None

            embedding = self._sface.feature(aligned).flatten().astype(float)
            faces_out.append({
                "id": i,
                "bbox": [x1, y1, x2, y2],
                "score": float(score),
                "embedding": embedding.tolist(),
                "landmarks_5pt": landmarks_out,
            })

        return faces_out

    def embed_crop(self, image: np.ndarray) -> list[float]:
        """Re-compute the embedding for an already-cropped face.

        The crop is resized to 112x112; no alignment is attempted since
        we have no fresh keypoints. Use detect_and_embed() when accuracy
        matters more than speed.
        """
        resized = cv2.resize(image, (SFACE_INPUT_SIZE, SFACE_INPUT_SIZE))
        embedding = self._sface.feature(resized).flatten().astype(float)
        return embedding.tolist()


def benchmark(service: VisionService, image: np.ndarray, n: int = 10) -> float:
    """Helper for ad-hoc latency measurement. Returns mean ms per call."""
    t0 = time.perf_counter()
    for _ in range(n):
        service.detect_and_embed(image)
    return (time.perf_counter() - t0) * 1000 / n
