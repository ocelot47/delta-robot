"""
YOLO candy detector dùng chung cho camera preview trong app.
"""

from __future__ import annotations

from pathlib import Path

import cv2


class CandyDetector:
    def __init__(self, model_path: str | Path = "best.pt", conf: float = 0.5):
        # Nạp model YOLO lazy trong app để không làm chậm lúc mở chương trình.
        from ultralytics import YOLO

        self.model_path = Path(model_path)
        self.conf = conf
        self.model = YOLO(str(self.model_path))

    def detect(self, frame):
        # Chạy YOLO trên frame hiện tại và trả frame đã vẽ + danh sách tâm kẹo.
        results = self.model(frame, conf=self.conf, verbose=False)
        detections = []
        annotated = frame.copy()

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0]
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                x_center = int((x1 + x2) / 2)
                y_center = int((y1 + y2) / 2)
                confidence = float(box.conf[0]) if box.conf is not None else 0.0
                class_id = int(box.cls[0]) if box.cls is not None else 0
                label = self.model.names.get(class_id, "candy")

                detections.append({
                    "label": label,
                    "confidence": confidence,
                    "x": x_center,
                    "y": y_center,
                    "box": (x1, y1, x2, y2),
                })

                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 180, 0), 2)
                cv2.circle(annotated, (x_center, y_center), 5, (0, 0, 255), -1)
                cv2.putText(
                    annotated,
                    f"{label} {confidence:.2f} ({x_center},{y_center})",
                    (x1, max(18, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 180, 0),
                    2,
                    cv2.LINE_AA,
                )

        return annotated, detections
