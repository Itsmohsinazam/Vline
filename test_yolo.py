from huggingface_hub import hf_hub_download
from ultralytics import YOLO
import sys

try:
    plate_weights = hf_hub_download(
        repo_id="morsetechlab/yolov11-license-plate-detection",
        filename="license-plate-finetune-v1n.pt"
    )
    plate_model = YOLO(plate_weights)
    print("MODEL_NAMES:", plate_model.names)
except Exception as e:
    print("ERROR:", str(e))
