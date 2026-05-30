"""
YOLO candy detector dùng chung cho camera preview trong app.
"""

from __future__ import annotations

from pathlib import Path

import cv2


class CandyDetector:
    BOX_COLORS = {
        "black_candy": (0, 0, 0),
        "blue_candy": (255, 0, 0),
        "red_candy": (0, 0, 255),
    }
    DEFAULT_BOX_COLOR = (0, 180, 0)
    CENTER_COLOR = (0, 0, 255)

    def __init__(self, model_path: str | Path = "best.pt", conf: float = 0.5, imgsz: int = 416):
        # Nạp model YOLO lazy trong app để không làm chậm lúc mở chương trình.
        from ultralytics import YOLO

        self.model_path = Path(model_path)
        self.conf = conf
        self.imgsz = imgsz
        self.model = YOLO(str(self.model_path))

    def detect(self, frame):
        # Chạy YOLO trên frame hiện tại và trả frame đã vẽ + danh sách tâm kẹo.
        results = self.model(frame, conf=self.conf, imgsz=self.imgsz, verbose=False)
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
                label = self._label_for_class(class_id)
                box_color = self._box_color_for_label(label)

                detections.append({
                    "label": label,
                    "confidence": confidence,
                    "x": x_center,
                    "y": y_center,
                    "box": (x1, y1, x2, y2),
                })

                cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)
                cv2.circle(annotated, (x_center, y_center), 5, self.CENTER_COLOR, -1)
                cv2.putText(
                    annotated,
                    f"{label} {confidence:.2f}",
                    (x1, max(18, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    box_color,
                    2,
                    cv2.LINE_AA,
                )

        return annotated, detections

    def _label_for_class(self, class_id: int) -> str:
        names = self.model.names
        if isinstance(names, dict):
            return str(names.get(class_id, "candy"))
        if 0 <= class_id < len(names):
            return str(names[class_id])
        return "candy"

    def _box_color_for_label(self, label: str):
        normalized = label.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in self.BOX_COLORS:
            return self.BOX_COLORS[normalized]
        for candy_type, color in self.BOX_COLORS.items():
            if candy_type in normalized:
                return color
        return self.DEFAULT_BOX_COLOR
