"""YuNet face detector running through ONNX Runtime, GPU-accelerated.

Replaces ``cv2.FaceDetectorYN`` (which is CPU-only in pip's opencv-python-headless)
without changing the model itself. Same ONNX file
(face_detection_yunet_2023mar.onnx), same detection characteristics, runs on
the RTX 3060 Ti via ``CUDAExecutionProvider``.

The output of ``detect()`` matches ``cv2.FaceDetectorYN.detect()`` shape:
``(N, 15)`` per-face rows of [bbox_x, bbox_y, bbox_w, bbox_h, then 5 landmark
(x, y) pairs, then score]. The reframe pipeline only reads bbox + score, so
landmarks are produced but unused — kept for forward-compatibility.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# Must precede onnxruntime import so cublas/cudnn/nvrtc are RTLD_GLOBAL-loaded
# before ORT's CUDA provider tries to dlopen them.
from app import cuda_preload  # noqa: F401

import onnxruntime as ort

# YuNet 2023mar ONNX has a fixed 640x640 input. We always letterbox-resize to
# match. Aspect distortion at this scale doesn't meaningfully degrade detection.
_INPUT_SIZE = 640
_STRIDES = (8, 16, 32)


def _make_priors() -> dict[int, np.ndarray]:
    priors: dict[int, np.ndarray] = {}
    for s in _STRIDES:
        n = _INPUT_SIZE // s
        yy, xx = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        priors[s] = np.stack([xx, yy], axis=-1).reshape(-1, 2).astype(np.float32)
    return priors


class YuNetORT:
    def __init__(
        self,
        model_path: str | Path,
        conf_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        providers: list[str] | None = None,
    ) -> None:
        if providers is None:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.sess = ort.InferenceSession(str(model_path), providers=providers)
        self.input_name = self.sess.get_inputs()[0].name
        # Output names come in a fixed order; we re-resolve by name to be safe.
        self._out_idx = {n.name: i for i, n in enumerate(self.sess.get_outputs())}
        self.conf = conf_threshold
        self.nms = nms_threshold
        self._priors = _make_priors()

    @property
    def using_gpu(self) -> bool:
        return "CUDAExecutionProvider" in self.sess.get_providers()

    def detect(self, bgr: np.ndarray) -> np.ndarray | None:
        """Run face detection on a BGR uint8 image. Returns (N, 15) float32 array
        or None if no faces found."""
        src_h, src_w = bgr.shape[:2]
        # Stretch resize to model's fixed input size — same approach cv2 uses
        img = cv2.resize(bgr, (_INPUT_SIZE, _INPUT_SIZE))
        blob = img.astype(np.float32).transpose(2, 0, 1)[None, ...]
        # Map output coords back to source space at the end
        scale_x = src_w / _INPUT_SIZE
        scale_y = src_h / _INPUT_SIZE

        outs = self.sess.run(None, {self.input_name: blob})
        get = lambda name: outs[self._out_idx[name]]

        all_boxes: list[np.ndarray] = []
        all_scores: list[np.ndarray] = []
        all_kps: list[np.ndarray] = []

        for s in _STRIDES:
            cls = get(f"cls_{s}").reshape(-1)
            obj = get(f"obj_{s}").reshape(-1)
            bbox = get(f"bbox_{s}").reshape(-1, 4)
            kps = get(f"kps_{s}").reshape(-1, 10)
            # The 2023mar ONNX has sigmoid baked into the cls/obj heads — values
            # come out in [0, 1]. Multiplying directly is the right join.
            score = cls * obj

            mask = score > self.conf
            if not mask.any():
                continue

            score = score[mask]
            bbox = bbox[mask]
            kps = kps[mask]
            anchors = self._priors[s][mask]

            # YuNet anchor center is at (anchor + 0.5) * stride. The bbox's dx/dy
            # are in stride-units; dw/dh are log-stride. (Matches OpenCV's
            # face_detect.cpp face_decode logic.)
            anchor_center = (anchors + 0.5) * s
            cxcy = anchor_center + bbox[:, :2] * s
            wh = np.exp(bbox[:, 2:]) * s
            xy_top_left = cxcy - wh / 2.0
            box_xywh = np.concatenate([xy_top_left, wh], axis=-1)

            # Each of the 5 landmarks is anchor_center + kp_delta * stride
            kps_xy = anchor_center[:, None, :] + kps.reshape(-1, 5, 2) * s
            kps_flat = kps_xy.reshape(-1, 10)

            # Map from input-grid space (640x640) → source pixel space
            box_xywh[:, [0, 2]] *= scale_x
            box_xywh[:, [1, 3]] *= scale_y
            kps_flat[:, 0::2] *= scale_x
            kps_flat[:, 1::2] *= scale_y

            all_boxes.append(box_xywh)
            all_scores.append(score)
            all_kps.append(kps_flat)

        if not all_boxes:
            return None

        boxes = np.concatenate(all_boxes, axis=0)
        scores = np.concatenate(all_scores, axis=0)
        kps_arr = np.concatenate(all_kps, axis=0)

        keep = cv2.dnn.NMSBoxes(
            boxes.tolist(), scores.tolist(), self.conf, self.nms
        )
        if len(keep) == 0:
            return None
        keep = np.asarray(keep).flatten()

        return np.concatenate(
            [boxes[keep], kps_arr[keep], scores[keep][:, None]],
            axis=-1,
        ).astype(np.float32)
