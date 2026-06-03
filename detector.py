"""
VLINE – Detection Engine (YOLOv11 + EasyOCR Version)
"""

import time
import queue
import threading
import logging
from datetime import datetime
from typing import Callable, Optional, Dict, Any, List
from pathlib import Path
import os

import cv2
import numpy as np

from config import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT,
    JPEG_QUALITY, DETECTION_COOLDOWN, SNAPSHOTS_DIR,
)

# Set environment variable to prevent OpenMP crash on Windows
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

logger = logging.getLogger("vline.detector")

# Global models
_plate_model = None
_ocr_reader = None
_device = "cpu"


def get_models(on_progress: Optional[Callable] = None):
    """Load YOLO + EasyOCR models. Calls on_progress(stage_text) if provided."""
    global _plate_model, _ocr_reader, _device

    # Auto-detect best device
    try:
        import torch
        if torch.cuda.is_available():
            _device = "cuda"
            logger.info(f"CUDA available – using GPU: {torch.cuda.get_device_name(0)}")
        else:
            _device = "cpu"
            logger.info("CUDA not available – using CPU")
    except ImportError:
        _device = "cpu"

    if _plate_model is None:
        if on_progress:
            on_progress("Loading YOLOv11 plate detection model…")
        logger.info("Initializing YOLO plate detection model...")
        from huggingface_hub import hf_hub_download
        from ultralytics import YOLO

        plate_weights = hf_hub_download(
            repo_id="morsetechlab/yolov11-license-plate-detection",
            filename="license-plate-finetune-v1n.pt"
        )
        _plate_model = YOLO(plate_weights)

    if _ocr_reader is None:
        if on_progress:
            on_progress("Loading EasyOCR engine…")
        logger.info("Initializing EasyOCR reader...")
        import easyocr
        gpu = (_device == "cuda")
        _ocr_reader = easyocr.Reader(['en'], gpu=gpu, verbose=False)

    if on_progress:
        on_progress("Models ready ✓")

    return _plate_model, _ocr_reader


def draw_overlays(frame: np.ndarray, detections: List[Dict[str, Any]]) -> np.ndarray:
    out = frame.copy()
    # Sleek teal-blue accent color
    color = (247, 142, 79)  # BGR for #4f8ef7

    for det in detections:
        pb = det.get("box", {})
        if pb:
            x1, y1 = pb.get("xmin", 0), pb.get("ymin", 0)
            x2, y2 = pb.get("xmax", 0), pb.get("ymax", 0)

            # Draw rounded-look rectangle
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

            label = f"{det['plate']} [{det['vehicle_type']}] {det['plate_score']:.0%}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            by = max(y1 - 8, th + 4)

            # Semi-transparent label background
            overlay = out.copy()
            cv2.rectangle(overlay, (x1, by - th - 6), (x1 + tw + 10, by + 4), color, -1)
            cv2.addWeighted(overlay, 0.85, out, 0.15, 0, out)
            cv2.putText(out, label, (x1 + 5, by),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)

    return out


def save_snapshot(frame: np.ndarray, plate: str) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    name = f"{plate}_{ts}.jpg"
    path = SNAPSHOTS_DIR / name
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return str(path)


def rotate_snapshots(max_days: int = 30):
    try:
        now = time.time()
        count = 0
        for f in SNAPSHOTS_DIR.glob("*.jpg"):
            if f.is_file():
                if now - f.stat().st_mtime > max_days * 86400:
                    f.unlink()
                    count += 1
    except Exception as e:
        logger.error(f"Snapshot rotation error: {e}")


class VideoProcessor(threading.Thread):
    def __init__(
        self,
        source,
        frame_skip: int = 10,
        conf_thresh: float = 0.3,
        min_len: int = 4,
        on_frame:     Optional[Callable] = None,
        on_detection: Optional[Callable] = None,
        on_error:     Optional[Callable] = None,
        on_finished:  Optional[Callable] = None,
        on_progress:  Optional[Callable] = None,
    ):
        super().__init__(daemon=True, name="VideoProcessor")
        self.source      = source
        self.frame_skip  = max(1, frame_skip)
        self.conf_thresh = conf_thresh
        self.min_len     = min_len
        self.on_frame     = on_frame
        self.on_detection = on_detection
        self.on_error     = on_error
        self.on_finished  = on_finished
        self.on_progress  = on_progress

        self._stop_event      = threading.Event()
        self._recent_plates: Dict[str, float] = {}
        self._frame_queue     = queue.Queue(maxsize=2)

        # Atomic latest-frame reference (GUI reads, capture writes)
        self._latest_display_frame = None
        self._frame_lock = threading.Lock()

    def stop(self):
        self._stop_event.set()

    @property
    def stopped(self):
        return self._stop_event.is_set()

    def get_latest_frame(self):
        """Atomically retrieve and clear the latest display frame."""
        with self._frame_lock:
            frame = self._latest_display_frame
            self._latest_display_frame = None
            return frame

    def _capture_loop(self):
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            if self.on_error:
                self.on_error(f"Cannot open source: {self.source}")
            self.stop()
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        sleep_time = 1.0 / fps if (fps and fps > 0) else 0.033
        if self.source == 0:
            sleep_time = 0.033

        frame_idx = 0
        while not self._stop_event.is_set():
            start_t = time.time()
            ok, frame = cap.read()
            if not ok:
                break

            frame_idx += 1

            # Resize for display and store as latest (GUI picks it up)
            display = cv2.resize(frame, (DISPLAY_WIDTH, DISPLAY_HEIGHT))
            with self._frame_lock:
                self._latest_display_frame = display

            # Only queue full-res frames for YOLO detection at skip interval
            if frame_idx % self.frame_skip == 0:
                try:
                    self._frame_queue.put_nowait(frame.copy())
                except queue.Full:
                    pass

            elapsed = time.time() - start_t
            if elapsed < sleep_time:
                time.sleep(sleep_time - elapsed)

        cap.release()
        # Only fire finished if we weren't already stopped by the user
        if not self._stop_event.is_set():
            self._stop_event.set()
        if self.on_finished:
            self.on_finished()

    def run(self):
        try:
            rotate_snapshots()
            plate_model, ocr_reader = get_models(on_progress=self.on_progress)
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            if self.on_error:
                self.on_error(f"Failed to load models: {e}")
            return

        cap_thread = threading.Thread(target=self._capture_loop, daemon=True)
        cap_thread.start()

        source_tag = "camera" if self.source == 0 else "video"

        while not self._stop_event.is_set():
            try:
                frame = self._frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                # 1. Detect plate box with YOLO (auto device)
                results = plate_model.predict(
                    source=frame, imgsz=640,
                    conf=self.conf_thresh, device=_device, verbose=False,
                )

                detections = []
                for box in results[0].boxes:
                    prob = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    # Ensure coordinates are within frame
                    h, w = frame.shape[:2]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)

                    if x2 - x1 < 10 or y2 - y1 < 10:
                        continue  # Box too small

                    # 2. Crop the plate region
                    plate_crop = frame[y1:y2, x1:x2]

                    if plate_crop.size == 0:
                        continue  # Prevent crash on empty crop

                    # 3. Read text with EasyOCR
                    ocr_results = ocr_reader.readtext(plate_crop)

                    best_text = ""
                    best_prob = 0.0

                    for ocr_box, text, ocr_prob in ocr_results:
                        clean_text = "".join(c for c in text if c.isalnum()).upper()
                        if len(clean_text) >= self.min_len and ocr_prob > best_prob:
                            best_text = clean_text
                            best_prob = ocr_prob

                    if not best_text:
                        continue  # No valid text found in the plate crop

                    detections.append({
                        "plate":        best_text,
                        "vehicle_type": "Unknown",
                        "confidence":   prob,             # YOLO confidence
                        "plate_score":  float(best_prob), # OCR confidence
                        "region":       "N/A",
                        "box":          {"xmin": x1, "ymin": y1, "xmax": x2, "ymax": y2},
                        "vehicle_box":  {},
                    })

                now = time.time()

                # Prune old plates to prevent long-term memory leak
                cutoff = now - 60.0
                self._recent_plates = {
                    k: v for k, v in self._recent_plates.items() if v > cutoff
                }

                for det in detections:
                    plate = det["plate"]
                    last  = self._recent_plates.get(plate, 0)
                    if now - last >= DETECTION_COOLDOWN:
                        self._recent_plates[plate] = now
                        snap = save_snapshot(frame, plate)
                        det["snapshot"]  = snap
                        det["source"]    = source_tag
                        det["timestamp"] = datetime.now()
                        if self.on_detection:
                            self.on_detection(det)

                if detections:
                    annotated = draw_overlays(frame, detections)
                    display = cv2.resize(annotated, (DISPLAY_WIDTH, DISPLAY_HEIGHT))
                    with self._frame_lock:
                        self._latest_display_frame = display

            except Exception as e:
                logger.error(f"Inference Error: {e}")
                if self.on_error:
                    self.on_error(f"Inference Error: {e}")
