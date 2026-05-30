"""
ui/camera_panel.py — Panel camera bên trái.
"""

import cv2
import customtkinter as ctk
from PIL import Image

from config import CAMERA_DISPLAY_WIDTH, CAMERA_DISPLAY_HEIGHT


class CameraPanel:
    def __init__(self, parent, cam, on_toggle, on_change):
        self.parent     = parent
        self.cam        = cam
        self.on_toggle  = on_toggle
        self.on_change  = on_change
        self.flip_var   = ctk.BooleanVar(value=False)
        self.detect_var = ctk.BooleanVar(value=False)
        self._ctk_image = None

        self.frame = ctk.CTkFrame(parent)
        self.frame.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)

        self.cam_label = ctk.CTkLabel(
            self.frame, text="⏳ Đang quét camera...",
            width=CAMERA_DISPLAY_WIDTH, height=CAMERA_DISPLAY_HEIGHT,
            fg_color="#111111",
        )
        self.cam_label.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="nsew")

        ctrl = ctk.CTkFrame(self.frame)
        ctrl.grid(row=1, column=0, pady=6)

        ctk.CTkLabel(ctrl, text="Camera:").grid(row=0, column=0, padx=4)
        self.cam_option = ctk.CTkOptionMenu(
            ctrl, values=["Đang quét..."], command=self.on_change,
            width=180, dynamic_resizing=False, state="disabled",
        )
        self.cam_option.grid(row=0, column=1, padx=4)
        ctk.CTkButton(ctrl, text="↻", width=30,
                      command=self._rescan).grid(row=0, column=2, padx=2)
        self.btn_cam = ctk.CTkButton(
            ctrl, text="BẬT CAMERA", command=self.on_toggle,
            fg_color="green", width=120, state="disabled",
        )
        self.btn_cam.grid(row=0, column=3, padx=4)
        ctk.CTkCheckBox(ctrl, text="Lật ảnh",
                        variable=self.flip_var, width=80).grid(row=0, column=4, padx=4)
        ctk.CTkCheckBox(ctrl, text="Nhận diện tròn",
                        variable=self.detect_var, width=130).grid(row=0, column=5, padx=4)

    # ── Scan ─────────────────────────────────────────────────

    def start_scan(self):
        self.cam_option.configure(values=["Đang quét..."], state="disabled")
        self.btn_cam.configure(state="disabled")
        self.set_label("⏳ Đang quét thiết bị camera...")
        self.cam.scan_async(
            lambda cams: self.parent.after(0, lambda: self._apply(cams))
        )

    def _rescan(self):
        if self.cam.is_running():
            self.on_toggle()
        self.start_scan()

    def _apply(self, lst: list):
        if lst:
            labels = [c["label"] for c in lst]
            self.cam_option.configure(values=labels, state="normal")
            self.cam_option.set(labels[0])
            self.btn_cam.configure(state="normal")
            self.set_label(f"✅ Tìm thấy {len(lst)} camera. Nhấn BẬT CAMERA.")
        else:
            self.cam_option.configure(values=["Không tìm thấy"], state="disabled")
            self.cam_option.set("Không tìm thấy")
            self.btn_cam.configure(state="disabled")
            self.set_label("❌ Không tìm thấy camera nào.")

    def get_index(self) -> int:
        return self.cam.label_to_index(self.cam_option.get())

    # ── Display ───────────────────────────────────────────────

    def update_display(self, frame):
        if frame is None:
            return
        if self.flip_var.get():
            frame = cv2.flip(frame, 1)
        if self.detect_var.get():
            frame = self.cam.draw_circles(frame, self.cam.detect_circles(frame))

        # Resize bằng OpenCV (nhanh hơn PIL resize nhiều lần)
        h_orig, w_orig = frame.shape[:2]
        ratio = min(CAMERA_DISPLAY_WIDTH / w_orig, CAMERA_DISPLAY_HEIGHT / h_orig)
        new_w = int(w_orig * ratio)
        new_h = int(h_orig * ratio)
        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(new_w, new_h))
        self._ctk_image = ctk_img
        self.cam_label.configure(image=ctk_img, text="")

    def set_button(self, running: bool):
        self.btn_cam.configure(
            text="TẮT CAMERA" if running else "BẬT CAMERA",
            fg_color="red" if running else "green",
        )

    def set_label(self, text: str):
        self.cam_label.configure(text=text, image=None)
        self._ctk_image = None
