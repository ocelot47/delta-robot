"""
Classic desktop control panel for the ESP32 delta robot test GUI.

The layout follows the Delta-Robot reference app: compact controls on the left,
large live robot visualization on the right, and a log console at the bottom.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import TclError

import customtkinter as ctk

from ui.delta_visualizer import DeltaVisualizer
from config import STEPS_PER_DEG


class ControlPanel:
    def __init__(self, parent, app):
        # Lưu tham chiếu tới app chính để các nút có thể gọi hàm gửi lệnh.
        self.app = app
        self.root = ctk.CTkFrame(parent, fg_color="white")
        self.root.grid(row=0, column=0, sticky="nsew")
        self.root.grid_columnconfigure(0, weight=0)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        self.status_vars: dict[str, ctk.StringVar] = {}
        self.limit_vars: dict[str, ctk.StringVar] = {}
        self.angle_vars: dict[str, ctk.StringVar] = {}
        self.multi_enabled_vars: dict[str, tk.BooleanVar] = {}
        self.multi_step_entries: dict[str, ctk.CTkEntry] = {}
        self.pick_entries: dict[str, ctk.CTkEntry] = {}
        self.ik_entries: dict[str, ctk.CTkEntry] = {}
        self.camera_list: list[dict] = []
        self._camera_image = None
        self._latest_camera_frame = None
        self.detect_candy_var = tk.BooleanVar(value=False)

        self._build_top_bar()
        self._build_left_panel()
        self._build_visualizer_panel()
        self._build_log_panel()

    def _build_top_bar(self):
        # Thanh trên cùng: chọn COM, kết nối serial và nút an toàn nhanh.
        bar = ctk.CTkFrame(self.root, fg_color="white", corner_radius=0)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(14, 6))
        bar.grid_columnconfigure(14, weight=1)

        self._label(bar, "Serial port").grid(row=0, column=0, padx=(0, 6))
        self.port_option = ctk.CTkOptionMenu(bar, values=["No COM"], width=105)
        self.port_option.grid(row=0, column=1, padx=4)
        self.baud_option = ctk.CTkOptionMenu(bar, values=["115200"], width=92)
        self.baud_option.set("115200")
        self.baud_option.grid(row=0, column=2, padx=4)
        ctk.CTkButton(bar, text="Refresh", width=78, command=self.app.refresh_ports).grid(row=0, column=3, padx=4)
        self.connect_btn = ctk.CTkButton(bar, text="Connect", width=88, command=self.app.connect_serial)
        self.connect_btn.grid(row=0, column=4, padx=4)
        self.disconnect_btn = ctk.CTkButton(bar, text="Disconnect", width=96, command=self.app.disconnect_serial)
        self.disconnect_btn.grid(row=0, column=5, padx=4)

        self.connection_var = ctk.StringVar(value="Disconnected")
        self._label(bar, textvariable=self.connection_var, width=170).grid(row=0, column=6, padx=(14, 18))

        ctk.CTkButton(bar, text="Enable motors", width=118, command=self.app.enableMotors).grid(row=0, column=7, padx=4)
        ctk.CTkButton(bar, text="Disable motors", width=122, fg_color="#6c757d", command=self.app.disableMotors).grid(row=0, column=8, padx=4)
        ctk.CTkButton(
            bar,
            text="Emergency Stop",
            width=150,
            height=34,
            fg_color="#c1121f",
            hover_color="#9b0d18",
            command=self.app.emergencyStop,
        ).grid(row=0, column=9, padx=(16, 0))

    def _build_left_panel(self):
        # Panel trái chứa toàn bộ form điều khiển robot.
        panel = ctk.CTkScrollableFrame(self.root, width=430, fg_color="white", corner_radius=0)
        panel.grid(row=1, column=0, sticky="nsew", padx=(18, 8), pady=4)
        panel.grid_columnconfigure(0, weight=1)

        self._build_motion_section(panel)
        self._build_jog_section(panel)
        self._build_command_section(panel)
        self._build_post_home_section(panel)
        self._build_safety_status_section(panel)
        self._build_gripper_section(panel)
        self._build_multi_motor_section(panel)
        self._build_rotate_section(panel)
        self._build_pick_section(panel)
        self._build_ik_section(panel)

    def _build_visualizer_panel(self):
        # Panel phải chứa status rút gọn, camera và mô hình 3D.
        frame = ctk.CTkFrame(self.root, fg_color="white", corner_radius=0)
        frame.grid(row=1, column=1, sticky="nsew", padx=(8, 18), pady=4)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=2)
        frame.grid_columnconfigure(1, weight=1)

        self._build_telemetry_section(frame)
        self._build_camera_section(frame)

        plot_frame = tk.Frame(frame, bg="white")
        plot_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.visualizer = DeltaVisualizer(plot_frame)

        controls = ctk.CTkFrame(frame, fg_color="white")
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.trajectory_check = ctk.CTkCheckBox(
            controls,
            text="Trajectory plot",
            variable=self.visualizer.trajectory_enabled,
        )
        self.trajectory_check.pack(side="left", padx=(0, 10))
        ctk.CTkButton(controls, text="Clear trajectory", width=125, command=self.visualizer.clear_trajectory).pack(side="left")
        ctk.CTkButton(controls, text="Joints plot", width=100, command=self.visualizer.open_joint_plot).pack(side="left", padx=8)
        ctk.CTkButton(controls, text="Workspace", width=100, command=self.visualizer.open_workspace_plot).pack(side="left")

    def _build_motion_section(self, parent):
        # Nhập tọa độ XYZ và thông số tốc độ/gia tốc cho lệnh move_xyz.
        frame = self._section(parent, "Position")
        mode = ctk.CTkFrame(frame, fg_color="white")
        mode.grid(row=1, column=0, columnspan=5, sticky="w")
        self.mode_var = tk.IntVar(value=0)
        self.online_var = tk.IntVar(value=1)
        ctk.CTkRadioButton(mode, text="mm", variable=self.mode_var, value=0).pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(mode, text="deg", variable=self.mode_var, value=1).pack(side="left", padx=(0, 24))
        ctk.CTkRadioButton(mode, text="Offline", variable=self.online_var, value=0).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(mode, text="Online", variable=self.online_var, value=1).pack(side="left")

        labels = ("X [mm]", "Y [mm]", "Z [mm]")
        defaults = ("0", "0", "-200")
        self.xyz_entries = []
        for col, (label, default) in enumerate(zip(labels, defaults), start=1):
            self._label(frame, label, font_size=12).grid(row=2, column=col, padx=3, pady=(6, 2))
            entry = ctk.CTkEntry(frame, width=64)
            entry.insert(0, default)
            entry.grid(row=3, column=col, padx=3)
            self.xyz_entries.append(entry)
        self.ik_entries["x"], self.ik_entries["y"], self.ik_entries["z"] = self.xyz_entries
        ctk.CTkButton(frame, text="Move", width=70, command=self.app.moveXYZ).grid(row=3, column=4, padx=(8, 0))

        self.ik_entries["speed"] = self._entry(frame, 4, "Velocity", "2000")
        self.ik_entries["accel"] = self._entry(frame, 5, "Acceleration", "1000")

    def _build_jog_section(self, parent):
        # Điều khiển riêng từng motor A/B/C theo số step tương đối.
        frame = self._section(parent, "JOG / Single Motor")
        self.single_motor = ctk.CTkOptionMenu(frame, values=["A / 1", "B / 2", "C / 3"], width=95)
        self.single_motor.set("A / 1")
        self.single_motor.grid(row=1, column=1, columnspan=2, sticky="w", padx=4, pady=4)
        self.single_steps = self._entry(frame, 2, "steps", "100")
        self.single_speed = self._entry(frame, 3, "speed", "2000")
        self.single_accel = self._entry(frame, 4, "accel", "1000")
        ctk.CTkButton(frame, text="Motor +", width=92, command=lambda: self.app.moveSingleMotor(1)).grid(row=6, column=1, padx=4, pady=5)
        ctk.CTkButton(frame, text="Motor -", width=92, command=lambda: self.app.moveSingleMotor(-1)).grid(row=6, column=2, padx=4, pady=5)

    def _build_command_section(self, parent):
        # Các lệnh thường dùng: enable/stop/home từng motor và home all.
        frame = self._section(parent, "Commands")
        ctk.CTkButton(frame, text="Start", width=88, command=self.app.enableMotors).grid(row=1, column=0, padx=4, pady=4)
        ctk.CTkButton(frame, text="Stop", width=88, command=self.app.emergencyStop).grid(row=2, column=0, padx=4, pady=4)
        ctk.CTkButton(frame, text="Calibrate", width=88, command=self.app.homeAll).grid(row=3, column=0, padx=4, pady=4)
        ctk.CTkButton(frame, text="Home", width=88, command=self.app.homeAll).grid(row=4, column=0, padx=4, pady=4)
        ctk.CTkButton(frame, text="Enable motors", width=130, command=self.app.enableMotors).grid(row=1, column=1, padx=12, pady=4)
        ctk.CTkButton(frame, text="Disable motors", width=130, command=self.app.disableMotors).grid(row=2, column=1, padx=12, pady=4)
        for col, motor in enumerate(("A", "B", "C"), start=0):
            ctk.CTkButton(frame, text=f"Home {motor}", width=82, command=lambda m=motor: self.app.homeMotor(m)).grid(row=5, column=col, padx=4, pady=(8, 4))

    def _build_post_home_section(self, parent):
        # Cấu hình tùy chọn: app gửi thêm move_abc sau khi firmware báo Home All xong.
        frame = self._section(parent, "Post-Home Drop")
        self.post_home_enabled = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            frame,
            text="Run after Home All",
            variable=self.post_home_enabled,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=4)
        self.post_home_a = self._entry(frame, 2, "A steps", "-300")
        self.post_home_b = self._entry(frame, 3, "B steps", "-300")
        self.post_home_c = self._entry(frame, 4, "C steps", "-300")
        self.post_home_speed = self._entry(frame, 5, "speed", "800")
        self.post_home_accel = self._entry(frame, 6, "accel", "800")
        for entry in (
            self.post_home_a,
            self.post_home_b,
            self.post_home_c,
            self.post_home_speed,
            self.post_home_accel,
        ):
            entry.bind("<KeyRelease>", self.app.schedulePostHomePreview)
            entry.bind("<Return>", self.app.previewPostHomeDrop)
            entry.bind("<FocusOut>", self.app.previewPostHomeDrop)
        ctk.CTkButton(
            frame,
            text="Preview 3D",
            command=self.app.previewPostHomeDrop,
        ).grid(row=8, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 3))
        ctk.CTkLabel(
            frame,
            text="Adjust signs if the robot moves upward instead of downward.",
            text_color="#555555",
            fg_color="white",
            wraplength=360,
            anchor="w",
        ).grid(row=9, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 0))

    def _build_safety_status_section(self, parent):
        # Hiển thị trạng thái an toàn tổng quát lấy từ gói status ESP32.
        frame = self._section(parent, "Connection / Safety")
        for label, default in (
            ("enabled", "false"),
            ("homed", "false"),
            ("moving", "false"),
            ("sequence", "idle"),
            ("gripper", "180 deg"),
        ):
            self._status_row(frame, label, default)
        self.warning_label = ctk.CTkLabel(
            frame,
            text="",
            text_color="#a15c00",
            fg_color="white",
            wraplength=360,
            anchor="w",
        )
        self.warning_label.grid(row=7, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 0))

    def _build_gripper_section(self, parent):
        # Điều khiển servo MG90S: mở, kẹp, set góc thủ công và giới hạn góc.
        frame = self._section(parent, "Gripper Servo MG90S")
        self.gripper_open_angle = self._entry(frame, 1, "open angle", "180")
        self.gripper_close_angle = self._entry(frame, 2, "close limit angle", "50")
        self.gripper_angle = self._entry(frame, 3, "manual angle", "90")
        ctk.CTkButton(
            frame, text="Set Limits", command=self.app.setGripperLimits
        ).grid(row=5, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 3))
        ctk.CTkButton(
            frame, text="Open Gripper", command=self.app.openGripper
        ).grid(row=6, column=0, sticky="ew", padx=4, pady=3)
        ctk.CTkButton(
            frame, text="Close Gripper", command=self.app.closeGripper
        ).grid(row=6, column=1, sticky="ew", padx=4, pady=3)
        ctk.CTkButton(
            frame, text="Set Angle", command=self.app.setGripperAngle
        ).grid(row=6, column=2, sticky="ew", padx=4, pady=3)

    def _build_telemetry_section(self, parent):
        # Khung telemetry nhỏ: góc/step 3 motor và trạng thái 3 limit switch.
        frame = ctk.CTkFrame(parent, fg_color="#f7f7f7", border_width=1, border_color="#d0d0d0", corner_radius=4)
        frame.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 6))
        for col in range(6):
            frame.grid_columnconfigure(col, weight=1)
        self._label(frame, "Robot Status", font_size=15).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 3))
        self._label(frame, "Motor Angles / Steps", font_size=15).grid(row=0, column=2, sticky="w", padx=8, pady=(6, 3))
        for label in ("A", "B", "C"):
            self.angle_vars[label] = self._telemetry_pair(frame, f"Motor {label}", "0 step / 0.00 deg", start_col=2)

        self._label(frame, "Limit Switches", font_size=15).grid(row=0, column=4, sticky="w", padx=8, pady=(6, 3))
        self.limit_vars["LimitA"] = self._telemetry_pair(frame, "Limit A", "false", start_col=4)
        self.limit_vars["LimitB"] = self._telemetry_pair(frame, "Limit B", "false", start_col=4)
        self.limit_vars["LimitC"] = self._telemetry_pair(frame, "Limit C", "false", start_col=4)

        self.status_vars["xyz"] = ctk.StringVar(value="3D pose: waiting for valid IK/XYZ")
        self._label(frame, textvariable=self.status_vars["xyz"], font_size=13).grid(row=4, column=0, columnspan=6, sticky="w", padx=8, pady=(4, 6))
        self.status_vars["theta"] = ctk.StringVar(value="-")

    def _build_camera_section(self, parent):
        # Khung camera USB: scan thiết bị, chọn camera và hiển thị preview.
        frame = ctk.CTkFrame(parent, fg_color="#f7f7f7", border_width=1, border_color="#d0d0d0", corner_radius=4)
        frame.grid(row=0, column=1, rowspan=2, sticky="nsew", pady=(0, 6))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(frame, fg_color="#f7f7f7")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        self._label(header, "Camera", font_size=15).pack(side="left")
        ctk.CTkButton(header, text="Scan", width=62, command=self.app.scan_cameras).pack(side="right", padx=(6, 0))

        self.camera_label = ctk.CTkLabel(
            frame,
            text="Camera preview",
            text_color="#d8d8d8",
            fg_color="#111111",
            height=180,
        )
        self.camera_label.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.camera_label.bind("<Configure>", self._resize_camera_preview)

        controls = ctk.CTkFrame(frame, fg_color="#f7f7f7")
        controls.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        controls.grid_columnconfigure(0, weight=1)
        self.camera_option = ctk.CTkOptionMenu(
            controls,
            values=["Camera 0"],
            width=150,
            command=self.app.change_camera,
        )
        self.camera_option.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.camera_button = ctk.CTkButton(controls, text="Start Camera", width=120, command=self.app.toggle_camera)
        self.camera_button.grid(row=0, column=1)

        detect_controls = ctk.CTkFrame(frame, fg_color="#f7f7f7")
        detect_controls.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
        detect_controls.grid_columnconfigure(1, weight=1)
        ctk.CTkCheckBox(
            detect_controls,
            text="Detect candy",
            variable=self.detect_candy_var,
            command=self.app.toggleCandyDetection,
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.detection_status_var = ctk.StringVar(value="Candy detect off")
        self._label(
            detect_controls,
            textvariable=self.detection_status_var,
            font_size=13,
        ).grid(row=0, column=1, sticky="w")

    def _build_multi_motor_section(self, parent):
        # Điều khiển nhiều motor cùng lúc bằng lệnh move_abc.
        frame = self._section(parent, "Multi Motor Control")
        for col, motor in enumerate(("A", "B", "C")):
            var = tk.BooleanVar(value=True)
            self.multi_enabled_vars[motor] = var
            ctk.CTkCheckBox(frame, text=f"Motor {motor}", variable=var).grid(row=1, column=col, padx=3, pady=4, sticky="w")
        self.multi_step_entries["A"] = self._entry(frame, 1, "Step A", "200")
        self.multi_step_entries["B"] = self._entry(frame, 2, "Step B", "200")
        self.multi_step_entries["C"] = self._entry(frame, 3, "Step C", "200")
        self.multi_speed = self._entry(frame, 4, "speed", "2000")
        self.multi_accel = self._entry(frame, 5, "accel", "1000")
        ctk.CTkButton(frame, text="Move Selected Motors", command=self.app.moveSelectedMotors).grid(row=7, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 3))
        ctk.CTkButton(frame, text="Move All Same Steps", command=lambda: self.app.moveAllSameSteps(1)).grid(row=8, column=0, columnspan=3, sticky="ew", padx=4, pady=3)
        ctk.CTkButton(frame, text="Move All Reverse", command=lambda: self.app.moveAllSameSteps(-1)).grid(row=9, column=0, columnspan=3, sticky="ew", padx=4, pady=3)

    def _build_rotate_section(self, parent):
        # Pattern test quay tại chỗ, không phải inverse kinematics thật.
        frame = self._section(parent, "Rotate In Place Test")
        self.rotate_steps = self._entry(frame, 0, "rotateSteps", "500")
        self.rotate_speed = self._entry(frame, 1, "speed", "2000")
        self.rotate_accel = self._entry(frame, 2, "accel", "1000")
        self.rotate_repeat = self._entry(frame, 3, "repeatCount", "3")
        self.rotate_delay = self._entry(frame, 4, "delayBetweenMovesMs", "700")
        ctk.CTkButton(frame, text="Rotate CW", command=lambda: self.app.rotateInPlace("cw")).grid(row=6, column=0, padx=3, pady=5, sticky="ew")
        ctk.CTkButton(frame, text="Rotate CCW", command=lambda: self.app.rotateInPlace("ccw")).grid(row=6, column=1, padx=3, pady=5, sticky="ew")
        ctk.CTkButton(frame, text="Stop", fg_color="#8a5a00", command=self.app.stopCurrentSequence).grid(row=6, column=2, padx=3, pady=5, sticky="ew")

    def _build_pick_section(self, parent):
        # Sequence demo pick A -> B bằng các vị trí step giả lập.
        frame = self._section(parent, "Pick From A To B Simulation")
        rows = [
            ("A1", "0"), ("B1", "0"), ("C1", "-800"),
            ("A2", "1200"), ("B2", "1200"), ("C2", "-800"),
            ("safeA", "0"), ("safeB", "0"), ("safeC", "0"),
            ("speed", "2000"), ("accel", "1000"),
            ("gripDelayMs", "800"), ("moveDelayMs", "400"),
        ]
        for row, (label, default) in enumerate(rows):
            self.pick_entries[label] = self._entry(frame, row, label, default)
        base = len(rows) + 1
        ctk.CTkButton(frame, text="Go To Pick A", command=self.app.goToPickA).grid(row=base, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 3))
        ctk.CTkButton(frame, text="Go To Place B", command=self.app.goToPlaceB).grid(row=base + 1, column=0, columnspan=3, sticky="ew", padx=4, pady=3)
        ctk.CTkButton(frame, text="Run Pick A -> B Simulation", command=self.app.runPickPlaceSimulation).grid(row=base + 2, column=0, columnspan=3, sticky="ew", padx=4, pady=3)
        ctk.CTkButton(frame, text="Stop Sequence", fg_color="#8a5a00", command=self.app.stopCurrentSequence).grid(row=base + 3, column=0, columnspan=3, sticky="ew", padx=4, pady=3)

    def _build_ik_section(self, parent):
        # Thông số hình học IK gửi xuống firmware để move_xyz.
        frame = self._section(parent, "IK Config")
        rows = [
            ("arm", "100"), ("rod", "250"), ("base", "150"), ("platform", "60"),
            ("stepsPerDeg", "8.889"), ("offsetA", "0"), ("offsetB", "0"),
            ("offsetC", "0"), ("signA", "1"), ("signB", "1"), ("signC", "1"),
        ]
        for row, (label, default) in enumerate(rows):
            self.ik_entries[label] = self._entry(frame, row, label, default)
        ctk.CTkButton(frame, text="Send IK Config", command=self.app.sendIKConfig).grid(row=len(rows) + 1, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 3))

    def _build_log_panel(self):
        # Console log: hiển thị command gửi đi, response nhận về và lỗi parse.
        frame = ctk.CTkFrame(self.root, fg_color="white", corner_radius=0)
        frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(4, 12))
        frame.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(frame, fg_color="white")
        header.grid(row=0, column=0, sticky="ew")
        self._label(header, "Loaded program / Log console").pack(side="left")
        ctk.CTkButton(header, text="Clear Log", width=90, command=self.clear_log).pack(side="right")
        self.log_text = ctk.CTkTextbox(frame, height=118, font=("Consolas", 11), fg_color="#f7f7f7", text_color="black")
        self.log_text.grid(row=1, column=0, sticky="ew", pady=(4, 0))

    def _section(self, parent, title: str):
        # Helper tạo một section có tiêu đề và 3 cột co giãn.
        frame = ctk.CTkFrame(parent, fg_color="white", border_width=0, corner_radius=0)
        frame.pack(fill="x", padx=2, pady=6)
        for col in range(3):
            frame.grid_columnconfigure(col, weight=1)
        self._label(frame, title, font_size=15).grid(row=0, column=0, columnspan=3, sticky="w", padx=4, pady=(2, 5))
        return frame

    def _label(self, parent, text=None, textvariable=None, width=None, font_size=14):
        # Helper tạo label đồng bộ style cho toàn bộ giao diện.
        kwargs = {
            "text": text if text is not None else "",
            "textvariable": textvariable,
            "text_color": "black",
            "fg_color": "white",
            "font": ("Times New Roman", font_size),
        }
        if width is not None:
            kwargs["width"] = width
        return ctk.CTkLabel(parent, **kwargs)

    def _entry(self, parent, row: int, label: str, default: str):
        # Helper tạo cặp label + ô nhập số, giá trị default nằm ở tham số cuối.
        self._label(parent, label).grid(row=row + 1, column=0, sticky="w", padx=4, pady=3)
        entry = ctk.CTkEntry(parent, width=96, fg_color="white", text_color="black")
        entry.insert(0, default)
        entry.grid(row=row + 1, column=1, columnspan=2, sticky="ew", padx=4, pady=3)
        return entry

    def _status_row(self, parent, label: str, default: str):
        # Helper tạo một dòng status dạng label + biến StringVar.
        row = len(self.status_vars) + 1
        self._label(parent, label).grid(row=row, column=0, sticky="w", padx=4, pady=2)
        var = ctk.StringVar(value=default)
        self.status_vars[label] = var
        self._label(parent, textvariable=var, font_size=13).grid(row=row, column=1, columnspan=2, sticky="e", padx=4, pady=2)
        return var

    def _telemetry_pair(self, parent, label: str, default: str, start_col: int = 0):
        # Helper tạo một cặp telemetry trong khung status nhỏ phía trên.
        key = f"_telemetry_row_{start_col}"
        row = getattr(self, key, 1)
        setattr(self, key, row + 1)
        self._label(parent, label, font_size=13).grid(
            row=row, column=start_col, sticky="w", padx=8, pady=2
        )
        var = ctk.StringVar(value=default)
        self.status_vars[label] = var
        self._label(parent, textvariable=var, font_size=13).grid(
            row=row, column=start_col + 1, sticky="w", padx=8, pady=2
        )
        return var

    def update_ports(self, ports: list[str]):
        # Cập nhật dropdown COM khi người dùng bấm Refresh hoặc app khởi động.
        ports = ports or ["No COM"]
        self.port_option.configure(values=ports)
        self.port_option.set(ports[0])

    def update_cameras(self, cameras: list[dict]):
        # Cập nhật danh sách camera sau khi scan xong.
        self.camera_list = cameras
        if not cameras:
            self.camera_option.configure(values=["Camera 0"])
            self.camera_option.set("Camera 0")
            self.set_camera_message("No camera found. Try Start Camera with Camera 0.")
            return
        labels = [cam["label"] for cam in cameras]
        self.camera_option.configure(values=labels)
        self.camera_option.set(labels[0])
        self.set_camera_message(f"Found {len(cameras)} camera(s)")

    def get_selected_camera_index(self) -> int:
        # Lấy index camera từ lựa chọn hiện tại trong dropdown.
        label = self.camera_option.get()
        for cam in self.camera_list:
            if cam.get("label") == label:
                return int(cam.get("index", 0))
        try:
            return int(label.split("]")[0].replace("[", "").strip())
        except Exception:
            return 0

    def set_camera_running(self, running: bool):
        # Đổi text nút Start/Stop camera theo trạng thái đang chạy.
        self.camera_button.configure(text="Stop Camera" if running else "Start Camera")

    def set_detection_message(self, text: str):
        # Cập nhật dòng trạng thái YOLO detect kẹo.
        self.detection_status_var.set(text)

    def update_detection_summary(self, detections: list[dict]):
        # Hiển thị nhanh số kẹo detect được và tọa độ tâm kẹo đầu tiên.
        if not detections:
            self.detection_status_var.set("No candy")
            return
        first = detections[0]
        self.detection_status_var.set(
            f"{len(detections)} candy | x={first['x']} y={first['y']}"
        )

    def set_camera_message(self, text: str):
        # Hiển thị thông báo trong khung preview khi chưa có frame camera.
        self._latest_camera_frame = None
        old_image = self._camera_image
        try:
            self.camera_label.configure(text=text, image=None)
        except TclError:
            # Khi Tk image cũ đã bị hủy, CTkLabel có thể vẫn còn giữ tên pyimage.
            # Xóa image trực tiếp ở label nội bộ rồi mới set text.
            try:
                self.camera_label._label.configure(image="")
            except Exception:
                pass
            self.camera_label.configure(text=text)
        self._camera_image = None
        del old_image

    def _resize_camera_preview(self, _event=None):
        # Khi khung camera đổi kích thước, resize lại frame cuối cùng.
        if self._latest_camera_frame is not None:
            self.update_camera_frame(self._latest_camera_frame, remember=False)

    def update_camera_frame(self, frame, remember: bool = True):
        # Chuyển frame OpenCV sang CTkImage và fit vào khung preview.
        try:
            import cv2
            from PIL import Image
        except Exception as exc:
            self.set_camera_message(f"Camera display unavailable: {exc}")
            return

        if remember:
            self._latest_camera_frame = frame
        height = max(180, self.camera_label.winfo_height())
        width = max(260, self.camera_label.winfo_width())
        h_orig, w_orig = frame.shape[:2]
        ratio = min(width / w_orig, height / h_orig)
        new_w = max(1, int(w_orig * ratio))
        new_h = max(1, int(h_orig * ratio))
        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(new_w, new_h))
        old_image = self._camera_image
        self._camera_image = ctk_image
        try:
            self.camera_label.configure(image=ctk_image, text="")
        except TclError:
            try:
                self.camera_label._label.configure(image="")
            except Exception:
                pass
            self.camera_label.configure(image=ctk_image, text="")
        del old_image

    def set_connected(self, connected: bool):
        # Cập nhật trạng thái nút Connect/Disconnect và label kết nối.
        self.connection_var.set(f"Connected to {self.port_option.get()}" if connected else "Disconnected")
        self.connect_btn.configure(state="disabled" if connected else "normal")
        self.disconnect_btn.configure(state="normal" if connected else "disabled")

    def update_status(self, data: dict):
        # Nhận gói status từ app và đổ dữ liệu lên các biến hiển thị.
        status = data.get("status", "")
        moving = bool(data.get("moving", status in ("moving", "homing", "homing_retract")))
        self.status_vars["enabled"].set(str(bool(data.get("enabled", False))).lower())
        self.status_vars["homed"].set(str(bool(data.get("homed", False))).lower())
        self.status_vars["moving"].set(str(moving).lower())
        self.status_vars["gripper"].set(f"{int(data.get('gripperAngle', 0))} deg")
        step_values = {
            "A": int(data.get("a", 0)),
            "B": int(data.get("b", 0)),
            "C": int(data.get("c", 0)),
        }
        theta_values = {
            "A": data.get("thetaA"),
            "B": data.get("thetaB"),
            "C": data.get("thetaC"),
        }
        for motor in ("A", "B", "C"):
            step = step_values[motor]
            if data.get("xyzValid") and theta_values[motor] is not None:
                deg = float(theta_values[motor])
                self.angle_vars[motor].set(f"{step} step / {deg:.2f} deg")
            else:
                deg = step / STEPS_PER_DEG
                self.angle_vars[motor].set(f"{step} step / {deg:.2f} deg*")
        if data.get("xyzValid"):
            self.status_vars["xyz"].set(
                f"3D pose from IK: x={float(data.get('x', 0)):.2f} mm, y={float(data.get('y', 0)):.2f} mm, z={float(data.get('z', 0)):.2f} mm"
            )
            self.status_vars["theta"].set(
                f"phi1: {float(data.get('thetaA', 0)):.2f} deg  phi2: {float(data.get('thetaB', 0)):.2f} deg  phi3: {float(data.get('thetaC', 0)):.2f} deg"
            )
        else:
            self.status_vars["xyz"].set("3D pose: fixed visual home estimate until firmware returns valid IK/XYZ")
            self.status_vars["theta"].set("-")

        self.limit_vars["LimitA"].set(str(bool(data.get("limitA", False))).lower())
        self.limit_vars["LimitB"].set(str(bool(data.get("limitB", False))).lower())
        self.limit_vars["LimitC"].set(str(bool(data.get("limitC", False))).lower())
        self.warning_label.configure(
            text="" if bool(data.get("homed", False)) else "Robot is not homed. Movement may be unsafe."
        )

    def set_sequence_state(self, text: str):
        # Cập nhật trạng thái sequence hiện tại trong khung safety.
        self.status_vars["sequence"].set(text)

    def append_log(self, text: str):
        # Ghi một dòng log xuống console.
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def clear_log(self):
        # Xóa toàn bộ log console.
        self.log_text.delete("1.0", "end")
