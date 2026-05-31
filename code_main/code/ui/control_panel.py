"""
Dashboard control panel for the ESP32 delta robot GUI.

This file only builds and updates the UI. Motor, serial, camera, limit switch,
and inverse kinematics logic stays in the existing handlers/app callbacks.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import TclError

import customtkinter as ctk

from config import ARM_LENGTH, BASE_TRI, PLATFORM_TRI, ROD_LENGTH, STEPS_PER_DEG


BG = "#F5F6F8"
CARD = "#FFFFFF"
BORDER = "#DADDE2"
PRIMARY = "#2D8ACF"
PRIMARY_HOVER = "#2477B6"
DANGER = "#D71920"
DANGER_HOVER = "#B9151B"
DISABLED = "#6C757D"
TEXT = "#111827"
MUTED = "#5D6673"
SIDEBAR_WIDTH = 340
STATUS_TAB_WIDTH = 280
CAMERA_PREVIEW_WIDTH = 620
CAMERA_PREVIEW_HEIGHT = 349
CAMERA_CARD_WIDTH = CAMERA_PREVIEW_WIDTH + 22
CAMERA_CARD_HEIGHT = CAMERA_PREVIEW_HEIGHT + 112


class ControlPanel:
    def __init__(self, parent, app):
        self.app = app
        self.root = ctk.CTkFrame(parent, fg_color=BG)
        self.root.grid(row=0, column=0, sticky="nsew")
        self.root.grid_columnconfigure(0, weight=0, minsize=SIDEBAR_WIDTH)
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
        self._status_row_counters: dict[int, int] = {}
        self._camera_image = None
        self._latest_camera_frame = None
        self.detect_candy_var = tk.BooleanVar(value=False)

        self._build_top_bar()
        self._build_left_panel()
        self._build_right_panel()

    # Layout builders -----------------------------------------------------

    def _build_top_bar(self):
        bar = ctk.CTkFrame(self.root, fg_color=CARD, border_width=1, border_color=BORDER, corner_radius=8)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 8))
        bar.grid_columnconfigure(11, weight=1)

        self._label(bar, "Serial port").grid(row=0, column=0, padx=(12, 6), pady=10)
        self.port_option = ctk.CTkOptionMenu(bar, values=["No COM"], width=112, fg_color=PRIMARY, button_color="#2477B6")
        self.port_option.grid(row=0, column=1, padx=4, pady=10)

        self.baud_option = ctk.CTkOptionMenu(bar, values=["115200"], width=96, fg_color=PRIMARY, button_color="#2477B6")
        self.baud_option.set("115200")
        self.baud_option.grid(row=0, column=2, padx=4, pady=10)

        self._button(bar, "Refresh", self.app.refresh_ports, width=86).grid(row=0, column=3, padx=4, pady=10)
        self.connect_btn = self._button(bar, "Connect", self.app.connect_serial, width=94)
        self.connect_btn.grid(row=0, column=4, padx=4, pady=10)
        self.disconnect_btn = self._button(bar, "Disconnect", self.app.disconnect_serial, width=106)
        self.disconnect_btn.grid(row=0, column=5, padx=4, pady=10)

        self.connection_var = ctk.StringVar(value="Disconnected")
        self._label(bar, textvariable=self.connection_var, width=210, text_color=MUTED).grid(
            row=0, column=6, padx=(14, 10), pady=10
        )

        self._button(bar, "Enable motors", self.app.enableMotors, width=122).grid(row=0, column=8, padx=4, pady=10)
        self._button(bar, "Disable motors", self.app.disableMotors, width=126, color=DISABLED).grid(
            row=0, column=9, padx=4, pady=10
        )
        self._button(
            bar,
            "Emergency Stop",
            self.app.emergencyStop,
            width=158,
            height=36,
            color=DANGER,
            hover=DANGER_HOVER,
        ).grid(row=0, column=10, padx=(12, 12), pady=10)

    def _build_left_panel(self):
        panel = ctk.CTkScrollableFrame(
            self.root,
            width=SIDEBAR_WIDTH,
            fg_color=BG,
            corner_radius=0,
            scrollbar_button_color="#B8C0CC",
            scrollbar_button_hover_color="#9AA4B2",
        )
        panel.grid(row=1, column=0, sticky="nsew", padx=(12, 8), pady=(0, 12))
        panel.grid_columnconfigure(0, weight=1)

        self._build_motion_section(panel)
        self._build_jog_section(panel)
        self._build_command_section(panel)

        # Existing advanced controls are kept because app.py still reads them.
        self._build_safety_status_section(panel)
        self._build_post_home_section(panel)
        self._build_gripper_section(panel)
        self._build_multi_motor_section(panel)
        self._build_rotate_section(panel)
        self._build_pick_section(panel)
        self._build_ik_section(panel)

    def _build_right_panel(self):
        main = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        main.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=(0, 12))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1, minsize=430)
        main.grid_rowconfigure(1, weight=0)

        workspace = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        workspace.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        workspace.grid_columnconfigure(0, weight=0, minsize=STATUS_TAB_WIDTH)
        workspace.grid_columnconfigure(1, weight=0, minsize=CAMERA_CARD_WIDTH)
        workspace.grid_columnconfigure(2, weight=1)
        workspace.grid_rowconfigure(0, weight=1)

        self._build_telemetry_section(workspace)
        self._build_camera_section(workspace)
        self._build_log_panel(main)

    def _build_motion_section(self, parent):
        frame = self._section(parent, "Position Control")
        frame.grid_columnconfigure((1, 2, 3), weight=1)

        mode = ctk.CTkFrame(frame, fg_color=CARD)
        mode.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=(0, 8))
        self.mode_var = tk.IntVar(value=0)
        self.online_var = tk.IntVar(value=1)
        ctk.CTkRadioButton(mode, text="mm", variable=self.mode_var, value=0, fg_color=PRIMARY).pack(side="left", padx=(0, 14))
        ctk.CTkRadioButton(mode, text="deg", variable=self.mode_var, value=1, fg_color=PRIMARY).pack(side="left", padx=(0, 18))
        ctk.CTkRadioButton(mode, text="Offline", variable=self.online_var, value=0, fg_color=PRIMARY).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(mode, text="Online", variable=self.online_var, value=1, fg_color=PRIMARY).pack(side="left")

        labels = ("X [mm]", "Y [mm]", "Z [mm]")
        defaults = ("0", "0", "-200")
        self.xyz_entries = []
        for col, (label, default) in enumerate(zip(labels, defaults), start=0):
            self._label(frame, label, font_size=12, text_color=MUTED).grid(row=2, column=col, sticky="w", padx=10, pady=(0, 3))
            entry = self._plain_entry(frame, width=78)
            entry.insert(0, default)
            entry.grid(row=3, column=col, sticky="ew", padx=(10 if col == 0 else 4, 4), pady=(0, 8))
            self.xyz_entries.append(entry)
        self.ik_entries["x"], self.ik_entries["y"], self.ik_entries["z"] = self.xyz_entries
        self._button(frame, "Move", self.app.moveXYZ, width=72).grid(row=3, column=3, sticky="ew", padx=(6, 10), pady=(0, 8))

        self.ik_entries["speed"] = self._entry(frame, 4, "Velocity", "2000")
        self.ik_entries["accel"] = self._entry(frame, 5, "Acceleration", "1000")

    def _build_jog_section(self, parent):
        frame = self._section(parent, "JOG / Single Motor")
        self._label(frame, "Motor", text_color=MUTED).grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.single_motor = ctk.CTkOptionMenu(frame, values=["A / 1", "B / 2", "C / 3"], fg_color=PRIMARY, button_color="#2477B6")
        self.single_motor.set("A / 1")
        self.single_motor.grid(row=1, column=1, columnspan=2, sticky="ew", padx=10, pady=5)
        self.single_steps = self._entry(frame, 2, "Steps", "100")
        self.single_speed = self._entry(frame, 3, "Speed", "2000")
        self.single_accel = self._entry(frame, 4, "Accel", "1000")
        self._button(frame, "Motor +", lambda: self.app.moveSingleMotor(1)).grid(row=6, column=0, columnspan=2, sticky="ew", padx=(10, 5), pady=(8, 10))
        self._button(frame, "Motor -", lambda: self.app.moveSingleMotor(-1)).grid(row=6, column=2, sticky="ew", padx=(5, 10), pady=(8, 10))

    def _build_command_section(self, parent):
        frame = self._section(parent, "Commands")
        self._button(frame, "Start", self.app.enableMotors).grid(row=1, column=0, sticky="ew", padx=(10, 5), pady=5)
        self._button(frame, "Stop", self.app.emergencyStop, color=DISABLED).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(5, 10), pady=5)
        self._button(frame, "Enable motors", self.app.enableMotors).grid(row=2, column=0, sticky="ew", padx=(10, 5), pady=5)
        self._button(frame, "Disable motors", self.app.disableMotors, color=DISABLED).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(5, 10), pady=5)
        self._button(frame, "Calibrate", self.app.homeAll).grid(row=3, column=0, sticky="ew", padx=(10, 5), pady=5)
        self._button(frame, "Home", self.app.homeAll).grid(row=3, column=1, columnspan=2, sticky="ew", padx=(5, 10), pady=5)
        for col, motor in enumerate(("A", "B", "C")):
            self._button(frame, f"Home {motor}", lambda m=motor: self.app.homeMotor(m), width=82).grid(
                row=4, column=col, sticky="ew", padx=(10 if col == 0 else 5, 10 if col == 2 else 5), pady=(5, 10)
            )

    def _build_safety_status_section(self, parent):
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
            text_color="#A15C00",
            fg_color=CARD,
            wraplength=260,
            anchor="w",
            font=("Segoe UI", 12),
        )
        self.warning_label.grid(row=7, column=0, columnspan=3, sticky="ew", padx=10, pady=(6, 10))

    def _build_post_home_section(self, parent):
        frame = self._section(parent, "Post-Home Drop")
        self.post_home_enabled = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="Run after Home All", variable=self.post_home_enabled, fg_color=PRIMARY).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=10, pady=5
        )
        self.post_home_a = self._entry(frame, 2, "A steps", "-300")
        self.post_home_b = self._entry(frame, 3, "B steps", "-300")
        self.post_home_c = self._entry(frame, 4, "C steps", "-300")
        self.post_home_speed = self._entry(frame, 5, "Speed", "800")
        self.post_home_accel = self._entry(frame, 6, "Accel", "800")

    def _build_gripper_section(self, parent):
        frame = self._section(parent, "Gripper Servo MG90S")
        self.gripper_open_angle = self._entry(frame, 1, "Open angle", "180")
        self.gripper_close_angle = self._entry(frame, 2, "Close limit", "50")
        self.gripper_angle = self._entry(frame, 3, "Manual angle", "90")
        self._button(frame, "Set Limits", self.app.setGripperLimits).grid(row=5, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        self._button(frame, "Open", self.app.openGripper).grid(row=6, column=0, sticky="ew", padx=(10, 4), pady=(4, 10))
        self._button(frame, "Close", self.app.closeGripper).grid(row=6, column=1, sticky="ew", padx=4, pady=(4, 10))
        self._button(frame, "Set", self.app.setGripperAngle).grid(row=6, column=2, sticky="ew", padx=(4, 10), pady=(4, 10))

    def _build_telemetry_section(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure((0, 1, 2), weight=1, uniform="status_tabs")

        robot = self._card(frame, "Robot Status")
        robot.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        self.status_vars["enabled"] = self._status_row(robot, "enabled", "false")
        self.status_vars["homed"] = self._status_row(robot, "homed", "false")
        self.status_vars["moving"] = self._status_row(robot, "moving", "false")
        self.status_vars["sequence"] = self._status_row(robot, "sequence", "idle")
        self.status_vars["gripper"] = self._status_row(robot, "gripper", "180 deg")
        self.status_vars["xyz"] = ctk.StringVar(value="IK pose: waiting for valid XYZ")
        self._value_label(robot, self.status_vars["xyz"], wraplength=250).grid(row=8, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 10))
        self.status_vars["theta"] = ctk.StringVar(value="-")

        motors = self._card(frame, "Motor Angles / Steps")
        motors.grid(row=1, column=0, sticky="nsew", pady=6)
        for motor in ("A", "B", "C"):
            self.angle_vars[motor] = self._status_row(motors, f"Motor {motor}", "0 step / 0.00 deg")

        limits = self._card(frame, "Limit Switches")
        limits.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        self.limit_vars["LimitA"] = self._status_row(limits, "Limit A", "false")
        self.limit_vars["LimitB"] = self._status_row(limits, "Limit B", "false")
        self.limit_vars["LimitC"] = self._status_row(limits, "Limit C", "false")

    def _build_camera_section(self, parent):
        frame = self._card(parent, "Camera")
        frame.configure(width=CAMERA_CARD_WIDTH, height=CAMERA_CARD_HEIGHT)
        frame.grid(row=0, column=1, sticky="nw")
        frame.grid_propagate(False)
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color=CARD)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)
        self.camera_option = ctk.CTkOptionMenu(
            header,
            values=["Camera 0"],
            command=self.app.change_camera,
            fg_color=PRIMARY,
            button_color="#2477B6",
        )
        self.camera_option.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._button(header, "Scan", self.app.scan_cameras, width=82).grid(row=0, column=1, padx=4)
        self.camera_button = self._button(header, "Start Camera", self.app.toggle_camera, width=128)
        self.camera_button.grid(row=0, column=2, padx=(4, 0))

        self.camera_label = ctk.CTkLabel(
            frame,
            text="Camera not started",
            text_color="#D8DDE6",
            fg_color="#111111",
            font=("Segoe UI", 15),
            corner_radius=6,
            width=CAMERA_PREVIEW_WIDTH,
            height=CAMERA_PREVIEW_HEIGHT,
        )
        self.camera_label.grid(row=1, column=0, padx=10, pady=(0, 10))
        self.camera_label.grid_propagate(False)
        self.camera_label.bind("<Configure>", self._resize_camera_preview)

        detect_controls = ctk.CTkFrame(frame, fg_color=CARD)
        detect_controls.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        detect_controls.grid_columnconfigure(1, weight=1)
        ctk.CTkCheckBox(
            detect_controls,
            text="Detect candy",
            variable=self.detect_candy_var,
            command=self.app.toggleCandyDetection,
            fg_color=PRIMARY,
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.detection_status_var = ctk.StringVar(value="Candy detect off")
        self._value_label(detect_controls, self.detection_status_var).grid(row=0, column=1, sticky="w")
        self._button(detect_controls, "Move to Candy", self.app.moveToDetectedCandy, width=118).grid(
            row=0,
            column=2,
            sticky="e",
            padx=(8, 0),
        )
        self._button(detect_controls, "Log Point", self.app.logCalibrationPoint, width=86).grid(
            row=0,
            column=3,
            sticky="e",
            padx=(8, 0),
        )

    def _build_log_panel(self, parent):
        frame = self._card(parent, "Loaded program / Log console")
        frame.grid(row=2, column=0, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        self._button(frame, "Clear Log", self.clear_log, width=96).grid(row=0, column=1, sticky="e", padx=10, pady=(10, 8))
        self.log_text = ctk.CTkTextbox(
            frame,
            height=96,
            font=("Consolas", 11),
            fg_color="#FBFBFC",
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
        )
        self.log_text.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

    # Advanced controls kept for app.py compatibility --------------------

    def _build_multi_motor_section(self, parent):
        frame = self._section(parent, "Multi Motor Control")
        for col, motor in enumerate(("A", "B", "C")):
            var = tk.BooleanVar(value=True)
            self.multi_enabled_vars[motor] = var
            ctk.CTkCheckBox(frame, text=f"Motor {motor}", variable=var, fg_color=PRIMARY).grid(row=1, column=col, padx=8, pady=5, sticky="w")
        self.multi_step_entries["A"] = self._entry(frame, 1, "Step A", "200")
        self.multi_step_entries["B"] = self._entry(frame, 2, "Step B", "200")
        self.multi_step_entries["C"] = self._entry(frame, 3, "Step C", "200")
        self.multi_speed = self._entry(frame, 4, "Speed", "2000")
        self.multi_accel = self._entry(frame, 5, "Accel", "1000")
        self._button(frame, "Move Selected Motors", self.app.moveSelectedMotors).grid(row=7, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        self._button(frame, "Move All Same Steps", lambda: self.app.moveAllSameSteps(1)).grid(row=8, column=0, columnspan=3, sticky="ew", padx=10, pady=4)
        self._button(frame, "Move All Reverse", lambda: self.app.moveAllSameSteps(-1)).grid(row=9, column=0, columnspan=3, sticky="ew", padx=10, pady=(4, 10))

    def _build_rotate_section(self, parent):
        frame = self._section(parent, "Rotate In Place Test")
        self.rotate_steps = self._entry(frame, 0, "rotateSteps", "500")
        self.rotate_speed = self._entry(frame, 1, "Speed", "2000")
        self.rotate_accel = self._entry(frame, 2, "Accel", "1000")
        self.rotate_repeat = self._entry(frame, 3, "repeatCount", "3")
        self.rotate_delay = self._entry(frame, 4, "delayMs", "700")
        self._button(frame, "Rotate CW", lambda: self.app.rotateInPlace("cw")).grid(row=6, column=0, sticky="ew", padx=(10, 4), pady=(8, 10))
        self._button(frame, "Rotate CCW", lambda: self.app.rotateInPlace("ccw")).grid(row=6, column=1, sticky="ew", padx=4, pady=(8, 10))
        self._button(frame, "Stop", self.app.stopCurrentSequence, color=DISABLED).grid(row=6, column=2, sticky="ew", padx=(4, 10), pady=(8, 10))

    def _build_pick_section(self, parent):
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
        self._button(frame, "Go To Pick A", self.app.goToPickA).grid(row=base, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        self._button(frame, "Go To Place B", self.app.goToPlaceB).grid(row=base + 1, column=0, columnspan=3, sticky="ew", padx=10, pady=4)
        self._button(frame, "Run Pick A -> B", self.app.runPickPlaceSimulation).grid(row=base + 2, column=0, columnspan=3, sticky="ew", padx=10, pady=4)
        self._button(frame, "Stop Sequence", self.app.stopCurrentSequence, color=DISABLED).grid(row=base + 3, column=0, columnspan=3, sticky="ew", padx=10, pady=(4, 10))

    def _build_ik_section(self, parent):
        frame = self._section(parent, "IK Config")
        rows = [
            ("arm", str(ARM_LENGTH)), ("rod", str(ROD_LENGTH)),
            ("base", str(BASE_TRI)), ("platform", str(PLATFORM_TRI)),
            ("stepsPerDeg", str(STEPS_PER_DEG)), ("offsetA", "0"), ("offsetB", "0"),
            ("offsetC", "0"), ("signA", "1"), ("signB", "1"), ("signC", "1"),
        ]
        for row, (label, default) in enumerate(rows):
            self.ik_entries[label] = self._entry(frame, row, label, default)
        self._button(frame, "Send IK Config", self.app.sendIKConfig).grid(row=len(rows) + 1, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 10))

    # Widget helpers ------------------------------------------------------

    def _card(self, parent, title: str):
        frame = ctk.CTkFrame(parent, fg_color=CARD, border_width=1, border_color=BORDER, corner_radius=8)
        frame.grid_columnconfigure(0, weight=1)
        self._label(frame, title, font_size=15, bold=True).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 8))
        return frame

    def _section(self, parent, title: str):
        frame = self._card(parent, title)
        frame.pack(fill="x", padx=0, pady=(0, 10))
        for col in range(3):
            frame.grid_columnconfigure(col, weight=1)
        return frame

    def _label(self, parent, text=None, textvariable=None, width=None, font_size=13, text_color=TEXT, bold=False):
        kwargs = {
            "text": text if text is not None else "",
            "textvariable": textvariable,
            "text_color": text_color,
            "fg_color": "transparent",
            "font": ("Segoe UI", font_size, "bold" if bold else "normal"),
        }
        if width is not None:
            kwargs["width"] = width
        return ctk.CTkLabel(parent, **kwargs)

    def _value_label(self, parent, variable, wraplength=None):
        kwargs = {
            "textvariable": variable,
            "text_color": TEXT,
            "fg_color": "transparent",
            "font": ("Segoe UI", 12),
            "anchor": "w",
            "justify": "left",
        }
        if wraplength is not None:
            kwargs["wraplength"] = wraplength
        return ctk.CTkLabel(parent, **kwargs)

    def _button(self, parent, text, command, width=112, height=32, color=PRIMARY, hover=None):
        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            height=height,
            fg_color=color,
            hover_color=hover or (PRIMARY_HOVER if color == PRIMARY else "#5A6268"),
            font=("Segoe UI", 13),
            command=command,
        )

    def _plain_entry(self, parent, width=96):
        return ctk.CTkEntry(
            parent,
            width=width,
            height=30,
            fg_color="#FFFFFF",
            text_color=TEXT,
            border_color="#AEB6C2",
            font=("Segoe UI", 13),
        )

    def _entry(self, parent, row: int, label: str, default: str):
        self._label(parent, label, text_color=MUTED).grid(row=row + 1, column=0, sticky="w", padx=10, pady=4)
        entry = ctk.CTkEntry(
            parent,
            width=96,
            height=30,
            fg_color="#FFFFFF",
            text_color=TEXT,
            border_color="#AEB6C2",
            font=("Segoe UI", 13),
        )
        entry.insert(0, default)
        entry.grid(row=row + 1, column=1, columnspan=2, sticky="ew", padx=10, pady=4)
        return entry

    def _status_row(self, parent, label: str, default: str):
        key = id(parent)
        row = self._status_row_counters.get(key, 1)
        self._status_row_counters[key] = row + 1
        self._label(parent, label, text_color=MUTED).grid(row=row, column=0, sticky="w", padx=10, pady=3)
        var = ctk.StringVar(value=default)
        self._value_label(parent, var).grid(row=row, column=1, columnspan=2, sticky="e", padx=10, pady=3)
        return var

    # UI updates used by app.py ------------------------------------------

    def update_ports(self, ports: list[str]):
        ports = ports or ["No COM"]
        self.port_option.configure(values=ports)
        self.port_option.set(ports[0])

    def update_cameras(self, cameras: list[dict]):
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
        label = self.camera_option.get()
        for cam in self.camera_list:
            if cam.get("label") == label:
                return int(cam.get("index", 0))
        try:
            return int(label.split("]")[0].replace("[", "").strip())
        except Exception:
            return 0

    def set_camera_running(self, running: bool):
        self.camera_button.configure(text="Stop Camera" if running else "Start Camera")

    def set_camera_opening(self, opening: bool):
        if opening:
            self.camera_button.configure(text="Opening...", state="disabled")
        else:
            self.camera_button.configure(state="normal")

    def set_detection_message(self, text: str):
        self.detection_status_var.set(text)

    def update_detection_summary(self, detections: list[dict]):
        if not detections:
            self.detection_status_var.set("No candy")
            return
        first = detections[0]
        text = f"{len(detections)} candy | x={first['x']} y={first['y']}"
        if first.get("robot_xy_valid"):
            text += f" | X={first['robot_x']:.1f} Y={first['robot_y']:.1f}"
        elif "robot_xy_valid" in first:
            text += " | out of workspace"
        self.detection_status_var.set(text)

    def set_camera_message(self, text: str):
        self._latest_camera_frame = None
        old_image = self._camera_image
        try:
            self.camera_label.configure(text=text, image=None)
        except TclError:
            try:
                self.camera_label._label.configure(image="")
            except Exception:
                pass
            self.camera_label.configure(text=text)
        self._camera_image = None
        del old_image

    def _resize_camera_preview(self, _event=None):
        if self._latest_camera_frame is not None:
            self.update_camera_frame(self._latest_camera_frame, remember=False)

    def update_camera_frame(self, frame, remember: bool = True):
        try:
            import cv2
            from PIL import Image
        except Exception as exc:
            self.set_camera_message(f"Camera display unavailable: {exc}")
            return

        if remember:
            self._latest_camera_frame = frame

        label_w = max(320, self.camera_label.winfo_width())
        label_h = max(180, self.camera_label.winfo_height())
        target_w = label_w
        target_h = min(label_h, int(target_w * 9 / 16))
        if target_h > label_h:
            target_h = label_h
            target_w = int(target_h * 16 / 9)

        h_orig, w_orig = frame.shape[:2]
        ratio = min(target_w / w_orig, target_h / h_orig)
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
        self.connection_var.set(f"Connected to {self.port_option.get()}" if connected else "Disconnected")
        self.connect_btn.configure(state="disabled" if connected else "normal")
        self.disconnect_btn.configure(state="normal" if connected else "disabled")

    def update_status(self, data: dict):
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
                f"IK pose: x={float(data.get('x', 0)):.2f} mm, y={float(data.get('y', 0)):.2f} mm, z={float(data.get('z', 0)):.2f} mm"
            )
            self.status_vars["theta"].set(
                f"phi1: {float(data.get('thetaA', 0)):.2f} deg  phi2: {float(data.get('thetaB', 0)):.2f} deg  phi3: {float(data.get('thetaC', 0)):.2f} deg"
            )
        else:
            self.status_vars["xyz"].set("IK pose: waiting for valid XYZ")
            self.status_vars["theta"].set("-")

        self.limit_vars["LimitA"].set(str(bool(data.get("limitA", False))).lower())
        self.limit_vars["LimitB"].set(str(bool(data.get("limitB", False))).lower())
        self.limit_vars["LimitC"].set(str(bool(data.get("limitC", False))).lower())
        self.warning_label.configure(
            text="" if bool(data.get("homed", False)) else "Robot is not homed. Movement may be unsafe."
        )

    def set_sequence_state(self, text: str):
        self.status_vars["sequence"].set(text)

    def append_log(self, text: str):
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def clear_log(self):
        self.log_text.delete("1.0", "end")
