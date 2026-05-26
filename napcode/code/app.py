"""
app.py - Delta robot motor test console.

This version intentionally removes the old camera/IK/XYZ UI. It drives the
ESP32 with motor-step test commands only.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox
from collections.abc import Callable

import customtkinter as ctk

from config import WINDOW_HEIGHT, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH, WINDOW_WIDTH
from handlers.serial_handler import SerialHandler
from ui.control_panel import ControlPanel


# Temporary test pattern, not real delta robot kinematics.
# A/B/C are phase-shifted so the arms cycle around instead of all opening or
# closing together. Change these tuples if the mechanics need a different order.
ROTATE_PATTERNS = {
    "cw": (
        (1, -1, 0),
        (0, 1, -1),
        (-1, 0, 1),
    ),
    "ccw": (
        (-1, 1, 0),
        (0, -1, 1),
        (1, 0, -1),
    ),
}


class DeltaControlApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Cấu hình cửa sổ chính và layout gốc.
        self.title("Delta GUI")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.serial = SerialHandler()
        # Callback serial: SerialHandler chỉ đọc/parse, app quyết định xử lý dữ liệu.
        self.serial.on_json = self._on_serial_json
        self.serial.on_parse_error = self._on_parse_error
        self.serial.on_raw = self._on_raw_line
        self.camera = None
        self.camera_running = False

        self.latest_status = {
            # Trạng thái mới nhất nhận từ ESP32, dùng để cập nhật UI và tính delta.
            "enabled": False,
            "homed": False,
            "moving": False,
            "a": 0,
            "b": 0,
            "c": 0,
            "limitA": False,
            "limitB": False,
            "limitC": False,
            "gripperAngle": 180,
            "gripperOpenAngle": 180,
            "gripperClosedAngle": 50,
            "xyzValid": False,
        }

        self.sequence_running = False
        # Các biến quản lý sequence app-side như rotate/pick/post-home.
        self.sequence_name = "idle"
        self.sequence_id = 0
        self.waiting_for_done = False
        self.pending_after_done: Callable[[], None] | None = None
        self.pending_home_all_drop = False
        self.home_all_drop_running = False
        self._post_home_preview_after = None

        self._build_menu()
        self.ui = ControlPanel(self, self)
        self.refresh_ports()
        self.ui.set_connected(False)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_serial()
        self._status_poll_loop()
        self._camera_loop()

    # Serial connection and command helpers

    def _build_menu(self):
        # Menu kiểu Delta GUI: mở plot, xem COM và thoát app.
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_command(label="Program", command=self._program_placeholder)
        plot_menu = tk.Menu(menubar, tearoff=0)
        plot_menu.add_command(label="Joints", command=lambda: self.ui.visualizer.open_joint_plot())
        plot_menu.add_command(label="Workspace", command=lambda: self.ui.visualizer.open_workspace_plot())
        menubar.add_cascade(label="Plots", menu=plot_menu)
        menubar.add_command(label="Available COMs", command=self._show_available_coms)
        self.config(menu=menubar)

    def _program_placeholder(self):
        # Placeholder vì program creator của repo tham khảo dùng protocol khác.
        messagebox.showinfo(
            "Program",
            "Program creator from the reference project is not enabled here. "
            "This app keeps the ESP32 JSON motor-test protocol.",
        )

    def _show_available_coms(self):
        # Popup hiển thị danh sách COM port hiện có.
        messagebox.showinfo("Available COMs", "\n".join(self.serial.get_ports()))

    # Camera helpers

    def scan_cameras(self):
        # Scan camera USB trong thread riêng qua CameraHandler.
        try:
            from handlers.camera import CameraHandler
        except Exception as exc:
            self.log(f"Camera unavailable: {exc}")
            self.ui.set_camera_message("OpenCV is not available")
            return
        if self.camera is None:
            self.camera = CameraHandler()
        self.ui.set_camera_message("Scanning cameras...")
        self.camera.scan_async(lambda cams: self.after(0, lambda: self.ui.update_cameras(cams)))

    def toggle_camera(self):
        # Bật/tắt camera preview, không liên quan tới firmware ESP32.
        try:
            from handlers.camera import CameraHandler
        except Exception as exc:
            self.log(f"Camera unavailable: {exc}")
            self.ui.set_camera_message("OpenCV is not available")
            return
        if self.camera is None:
            self.camera = CameraHandler()

        if self.camera.is_running():
            self.camera.stop()
            self.camera_running = False
            self.ui.set_camera_running(False)
            self.ui.set_camera_message("Camera stopped")
            return

        index = self.ui.get_selected_camera_index()
        if self.camera.start(index):
            self.camera_running = True
            self.ui.set_camera_running(True)
            self.log(f"Camera started: index {index}")
        else:
            self.ui.set_camera_message("Cannot open camera")
            self.log(f"Cannot open camera index {index}")

    def change_camera(self, _label=None):
        # Đổi camera khi dropdown thay đổi trong lúc camera đang chạy.
        if self.camera and self.camera.is_running():
            index = self.ui.get_selected_camera_index()
            if self.camera.switch(index):
                self.log(f"Camera switched: index {index}")
            else:
                self.ui.set_camera_message("Cannot switch camera")

    def _camera_loop(self):
        # Vòng lặp UI đọc frame camera định kỳ và đưa lên preview.
        if self.camera and self.camera.is_running():
            frame = self.camera.read_frame()
            if frame is not None:
                self.ui.update_camera_frame(frame)
        self.after(50, self._camera_loop)

    def refresh_ports(self):
        # Cập nhật dropdown COM port.
        self.ui.update_ports(self.serial.get_ports())

    def connect_serial(self):
        # Mở serial tới ESP32 và request status đầu tiên.
        port = self.ui.port_option.get()
        if port in ("No COM", "Không có"):
            self.log("No COM port found")
            return
        try:
            baud_rate = int(self.ui.baud_option.get())
        except ValueError:
            baud_rate = 115200

        ok, msg = self.serial.connect(port, baud_rate)
        self.log(msg)
        self.ui.set_connected(ok)
        if ok:
            self.requestStatus()

    def disconnect_serial(self):
        # Ngắt serial và dừng sequence app-side nếu có.
        self.stopCurrentSequence(send_stop=False)
        self.serial.disconnect()
        self.ui.set_connected(False)
        self.latest_status["moving"] = False
        self.log("Disconnected")

    def sendCommand(self, obj: dict, *, log_command: bool = True) -> bool:
        # Hàm gửi JSON xuống ESP32; mọi button handler nên đi qua hàm này.
        if not self.serial.is_connected():
            self.log("Cannot send command: ESP32 is not connected")
            return False
        if log_command:
            self.log(">> " + json.dumps(obj, separators=(",", ":")))
        ok = self.serial.send_command(obj)
        if not ok:
            self.ui.set_connected(False)
            self.log("Serial write failed")
        return ok

    def requestStatus(self):
        # Poll status ESP32; gọi định kỳ khi đã kết nối.
        self.sendCommand({"cmd": "status"}, log_command=False)

    def _poll_serial(self):
        # Đọc serial non-blocking liên tục bằng after().
        if self.serial.is_connected():
            self.serial.poll()
        self.after(20, self._poll_serial)

    def _status_poll_loop(self):
        # Gửi {"cmd":"status"} mỗi 750ms, tránh spam serial quá nhanh.
        if self.serial.is_connected():
            self.requestStatus()
        self.after(750, self._status_poll_loop)

    def _on_serial_json(self, data: dict, raw: str):
        # ESP32 trả JSON hợp lệ.
        self.log("<< " + raw)
        self.handleStatusResponse(data)

    def _on_raw_line(self, raw: str):
        # Dòng serial không phải JSON nhưng vẫn muốn hiện log.
        self.log("<< " + raw)

    def _on_parse_error(self, raw: str, error: str):
        # Báo lỗi khi ESP32 trả dữ liệu không parse được JSON.
        self.log(f"JSON parse error: {error} | raw={raw}")

    # Status handling

    def handleStatusResponse(self, data: dict):
        # Hợp nhất response/status mới vào latest_status rồi cập nhật UI/plot.
        status = data.get("status")

        if "boot" in data:
            self.log(str(data["boot"]))

        if "moving" not in data:
            if status in ("moving", "homing", "homing_retract"):
                data["moving"] = True
            elif status in ("idle", "done", "homed", "ok", "error"):
                data["moving"] = False

        for key in (
            "enabled",
            "homed",
            "moving",
            "a",
            "b",
            "c",
            "limitA",
            "limitB",
            "limitC",
            "gripperAngle",
            "gripperOpenAngle",
            "gripperClosedAngle",
            "xyzValid",
            "x",
            "y",
            "z",
            "thetaA",
            "thetaB",
            "thetaC",
        ):
            if key in data:
                self.latest_status[key] = data[key]

        self.ui.update_status(self.latest_status)
        self.ui.visualizer.record_status(self.latest_status)
        self.ui.visualizer.draw_robot(self.latest_status)

        if (
            # Sau Home All, nếu app được cấu hình post-home thì gửi move_abc từ app.
            status == "homed"
            and data.get("motor") == "all"
            and self.pending_home_all_drop
        ):
            self.pending_home_all_drop = False
            self._runPostHomeDropFromApp()
            return

        if status == "done" and self.home_all_drop_running:
            self.home_all_drop_running = False
            self.log("Post-home drop done")

        if status == "error":
            self.log("ESP32 error: " + str(data.get("msg", "")))
            self.pending_home_all_drop = False
            self.home_all_drop_running = False
            if self.sequence_running:
                self.stopCurrentSequence(send_stop=False)
            return

        if status == "done" and self.waiting_for_done:
            callback = self.pending_after_done
            self.waiting_for_done = False
            self.pending_after_done = None
            if callback:
                callback()

    # Safety commands

    def emergencyStop(self):
        # Dừng sequence app-side và gửi stop xuống ESP32, không disable driver.
        self.sequence_id += 1
        self.sequence_running = False
        self.sequence_name = "idle"
        self.waiting_for_done = False
        self.pending_home_all_drop = False
        self.home_all_drop_running = False
        self.pending_after_done = None
        self.ui.set_sequence_state("idle")
        self.sendCommand({"cmd": "stop"})
        self.log("Emergency stop requested")

    def enableMotors(self):
        # ENABLE_PIN LOW trên firmware, driver giữ lực.
        self.sendCommand({"cmd": "enable"})

    def disableMotors(self):
        # Tắt driver khi người dùng yêu cầu rõ ràng.
        self.stopCurrentSequence(send_stop=False)
        self.sendCommand({"cmd": "disable"})

    def openGripper(self):
        # Mở kẹp về gripperOpenAngle trong firmware.
        self.sendCommand({"cmd": "gripper_open"})

    def closeGripper(self):
        # Kẹp về góc close limit nhập trên UI.
        try:
            angle = self._read_int(self.ui.gripper_close_angle, "gripper close angle")
        except ValueError as exc:
            self.log(str(exc))
            return
        self.sendCommand({"cmd": "gripper_close", "angle": angle})

    def setGripperAngle(self):
        # Set servo kẹp tới góc thủ công.
        try:
            angle = self._read_int(self.ui.gripper_angle, "gripper angle")
        except ValueError as exc:
            self.log(str(exc))
            return
        self.sendCommand({"cmd": "set_gripper", "angle": angle})

    def setGripperLimits(self):
        # Cập nhật giới hạn mở/kẹp trong firmware.
        try:
            open_angle = self._read_int(self.ui.gripper_open_angle, "gripper open angle")
            close_angle = self._read_int(self.ui.gripper_close_angle, "gripper close angle")
        except ValueError as exc:
            self.log(str(exc))
            return
        self.sendCommand({
            "cmd": "set_gripper_limits",
            "openAngle": open_angle,
            "closedAngle": close_angle,
        })

    def stopCurrentSequence(self, send_stop: bool = True):
        # Dừng rotate/pick/post-home đang chạy ở app.
        self.sequence_id += 1
        was_running = self.sequence_running
        self.sequence_running = False
        self.sequence_name = "idle"
        self.waiting_for_done = False
        self.pending_after_done = None
        self.ui.set_sequence_state("idle")
        if send_stop:
            self.sendCommand({"cmd": "stop"})
        if was_running:
            self.log("Sequence stopped")

    # Homing

    def homeMotor(self, motor: str):
        # Home riêng một motor A/B/C.
        self.sendCommand({"cmd": "home_motor", "motor": motor})

    def homeAll(self):
        # Home All; nếu checkbox Post-Home Drop bật thì app sẽ gửi move_abc sau homed all.
        self.pending_home_all_drop = True
        self.sendCommand({"cmd": "home"})

    def _runPostHomeDropFromApp(self):
        # Đọc thông số Post-Home Drop trên UI và gửi move_abc sau khi Home All xong.
        try:
            enabled = bool(self.ui.post_home_enabled.get())
            a = self._read_int(self.ui.post_home_a, "post-home A")
            b = self._read_int(self.ui.post_home_b, "post-home B")
            c = self._read_int(self.ui.post_home_c, "post-home C")
            speed = self._read_int(self.ui.post_home_speed, "post-home speed", minimum=1)
            accel = self._read_int(self.ui.post_home_accel, "post-home accel", minimum=1)
        except ValueError as exc:
            self.log(str(exc))
            return

        if not enabled:
            self.log("Post-home drop skipped")
            return
        if a == 0 and b == 0 and c == 0:
            self.log("Post-home drop skipped: A/B/C are all 0")
            return

        self.log(f"Post-home drop from app: A={a}, B={b}, C={c}")
        self.ui.visualizer.set_post_home_drop_estimate(a, b, c)
        self.home_all_drop_running = True
        self.sendCommand({
            "cmd": "move_abc",
            "a": a,
            "b": b,
            "c": c,
            "speed": speed,
            "accel": accel,
        })

    def schedulePostHomePreview(self, _event=None):
        # Debounce preview để không redraw 3D quá nhiều trong lúc đang gõ.
        if self._post_home_preview_after:
            self.after_cancel(self._post_home_preview_after)
        self._post_home_preview_after = self.after(250, self.previewPostHomeDrop)

    def previewPostHomeDrop(self):
        # Preview pose 3D theo thông số Post-Home Drop, không gửi lệnh xuống ESP32.
        self._post_home_preview_after = None
        try:
            a = self._read_int(self.ui.post_home_a, "post-home A")
            b = self._read_int(self.ui.post_home_b, "post-home B")
            c = self._read_int(self.ui.post_home_c, "post-home C")
        except ValueError:
            return
        self.ui.visualizer.set_post_home_drop_estimate(a, b, c, record=True)

    # Motor movement commands

    def moveSingleMotor(self, direction: int = 1):
        # Gửi move_motor cho một motor, direction = 1 hoặc -1.
        try:
            motor = self.ui.single_motor.get()[0]
            steps = abs(self._read_int(self.ui.single_steps, "single steps")) * direction
            speed = self._read_int(self.ui.single_speed, "single speed", minimum=1)
            accel = self._read_int(self.ui.single_accel, "single accel", minimum=1)
        except ValueError as exc:
            self.log(str(exc))
            return

        self._warn_if_unhomed()
        self.sendCommand({
            "cmd": "move_motor",
            "motor": motor,
            "steps": steps,
            "speed": speed,
            "accel": accel,
        })

    def moveSelectedMotors(self):
        # Gửi move_abc, motor không được tick sẽ gửi step = 0.
        try:
            speed = self._read_int(self.ui.multi_speed, "multi speed", minimum=1)
            accel = self._read_int(self.ui.multi_accel, "multi accel", minimum=1)
            steps = {
                motor: self._read_int(entry, f"Step {motor}")
                for motor, entry in self.ui.multi_step_entries.items()
            }
        except ValueError as exc:
            self.log(str(exc))
            return

        payload = {
            "cmd": "move_abc",
            "a": steps["A"] if self.ui.multi_enabled_vars["A"].get() else 0,
            "b": steps["B"] if self.ui.multi_enabled_vars["B"].get() else 0,
            "c": steps["C"] if self.ui.multi_enabled_vars["C"].get() else 0,
            "speed": speed,
            "accel": accel,
        }
        self._warn_if_unhomed()
        self.sendCommand(payload)

    def moveAllSameSteps(self, direction: int):
        # Gửi cùng số step cho cả 3 motor, có thể đảo chiều.
        try:
            base_steps = abs(self._read_int(self.ui.multi_step_entries["A"], "Step A"))
            speed = self._read_int(self.ui.multi_speed, "multi speed", minimum=1)
            accel = self._read_int(self.ui.multi_accel, "multi accel", minimum=1)
        except ValueError as exc:
            self.log(str(exc))
            return

        steps = base_steps * direction
        self._warn_if_unhomed()
        self.sendCommand({
            "cmd": "move_abc",
            "a": steps,
            "b": steps,
            "c": steps,
            "speed": speed,
            "accel": accel,
        })

    # Inverse kinematics XYZ commands

    def sendIKConfig(self):
        # Gửi thông số hình học delta/offset/sign xuống firmware.
        try:
            e = self.ui.ik_entries
            payload = {
                "cmd": "set_ik_config",
                "arm": self._read_float(e["arm"], "IK arm", minimum=0.001),
                "rod": self._read_float(e["rod"], "IK rod", minimum=0.001),
                "base": self._read_float(e["base"], "IK base", minimum=0.001),
                "platform": self._read_float(e["platform"], "IK platform", minimum=0.001),
                "stepsPerDeg": self._read_float(
                    e["stepsPerDeg"], "IK stepsPerDeg", minimum=0.001
                ),
                "offsetA": self._read_int(e["offsetA"], "IK offsetA"),
                "offsetB": self._read_int(e["offsetB"], "IK offsetB"),
                "offsetC": self._read_int(e["offsetC"], "IK offsetC"),
                "signA": self._read_sign(e["signA"], "IK signA"),
                "signB": self._read_sign(e["signB"], "IK signB"),
                "signC": self._read_sign(e["signC"], "IK signC"),
            }
        except ValueError as exc:
            self.log(str(exc))
            return
        self.sendCommand(payload)

    def moveXYZ(self):
        # Gửi move_xyz; firmware tính IK và đổi sang step motor.
        try:
            e = self.ui.ik_entries
            payload = {
                "cmd": "move_xyz",
                "x": self._read_float(e["x"], "IK x"),
                "y": self._read_float(e["y"], "IK y"),
                "z": self._read_float(e["z"], "IK z"),
                "speed": self._read_int(e["speed"], "IK speed", minimum=1),
                "accel": self._read_int(e["accel"], "IK accel", minimum=1),
            }
        except ValueError as exc:
            self.log(str(exc))
            return

        self._warn_if_unhomed()
        self.sendCommand(payload)

    # Rotate test

    def rotateInPlace(self, direction: str):
        # Demo xoay tại chỗ bằng pattern step tạm, không phải IK thật.
        if not self._require_connected("Rotate In Place Test"):
            return
        try:
            rotate_steps = abs(self._read_int(self.ui.rotate_steps, "rotateSteps"))
            speed = self._read_int(self.ui.rotate_speed, "rotate speed", minimum=1)
            accel = self._read_int(self.ui.rotate_accel, "rotate accel", minimum=1)
            repeat_count = max(1, self._read_int(self.ui.rotate_repeat, "repeatCount"))
            delay_ms = max(0, self._read_int(self.ui.rotate_delay, "delayBetweenMovesMs"))
        except ValueError as exc:
            self.log(str(exc))
            return

        pattern = ROTATE_PATTERNS[direction]
        self._warn_if_unhomed()
        self.sequence_id += 1
        active_id = self.sequence_id
        self.sequence_running = True
        self.sequence_name = "rotate"
        self.ui.set_sequence_state(f"rotate {direction}")

        def run_step(index: int):
            if not self._sequence_is_active(active_id):
                return
            total_moves = repeat_count * len(pattern)
            if index >= total_moves:
                self.sequence_running = False
                self.ui.set_sequence_state("idle")
                self.log("Rotate test done")
                return

            phase = pattern[index % len(pattern)]
            cycle = index // len(pattern) + 1
            phase_index = index % len(pattern) + 1
            self.log(
                f"Rotate {direction.upper()} cycle {cycle}/{repeat_count}, "
                f"phase {phase_index}/{len(pattern)}"
            )
            self._move_relative_abc(
                phase[0] * rotate_steps,
                phase[1] * rotate_steps,
                phase[2] * rotate_steps,
                speed,
                accel,
                on_done=lambda: self.after(delay_ms, lambda: run_step(index + 1)),
            )

        run_step(0)

    # Pick A -> B simulation

    def goToPickA(self):
        # Đi tới vị trí pick A theo target step tuyệt đối trên UI.
        config = self._read_pick_config()
        if not config:
            return
        self._warn_if_unhomed()
        self._move_to_absolute_steps(config["pick"], config["speed"], config["accel"])

    def goToPlaceB(self):
        # Đi tới vị trí place B theo target step tuyệt đối trên UI.
        config = self._read_pick_config()
        if not config:
            return
        self._warn_if_unhomed()
        self._move_to_absolute_steps(config["place"], config["speed"], config["accel"])

    def runPickPlaceSimulation(self):
        # Chạy sequence pick/place: enable, safe, pick, close gripper, place, open gripper.
        if not self._require_connected("Pick A -> B Simulation"):
            return
        config = self._read_pick_config()
        if not config:
            return

        self._warn_if_unhomed()
        self.sequence_id += 1
        active_id = self.sequence_id
        self.sequence_running = True
        self.sequence_name = "pick"
        self.ui.set_sequence_state("pick A->B")

        steps = [
            ("command", {"cmd": "enable"}, "Enable motors"),
            ("move", config["safe"], "Move to Safe position"),
            ("move", config["pick"], "Move to Position A"),
            ("delay", config["grip_delay"], "Wait before gripper close"),
            ("command", {"cmd": "gripper_close"}, "Close gripper"),
            ("move", config["safe"], "Move to Safe position"),
            ("move", config["place"], "Move to Position B"),
            ("delay", config["grip_delay"], "Wait before gripper open"),
            ("command", {"cmd": "gripper_open"}, "Open gripper"),
            ("move", config["safe"], "Move to Safe position"),
            ("log", "Pick A -> B Simulation done", ""),
        ]

        def run_step(index: int):
            if not self._sequence_is_active(active_id):
                return
            if index >= len(steps):
                self.sequence_running = False
                self.ui.set_sequence_state("idle")
                return

            kind, value, label = steps[index]
            if label:
                self.log(label)

            if kind == "command":
                self.sendCommand(value)
                self.after(150, lambda: run_step(index + 1))
            elif kind == "move":
                self._move_to_absolute_steps(
                    value,
                    config["speed"],
                    config["accel"],
                    on_done=lambda: self.after(
                        config["move_delay"], lambda: run_step(index + 1)
                    ),
                )
            elif kind == "delay":
                self.after(value, lambda: run_step(index + 1))
            elif kind == "log":
                self.log(value)
                self.after(100, lambda: run_step(index + 1))

        run_step(0)

    # Internal movement helpers

    def _move_relative_abc(
        # Gửi move_abc tương đối và optional callback khi nhận status done.
        self,
        a_steps: int,
        b_steps: int,
        c_steps: int,
        speed: int,
        accel: int,
        on_done: Callable[[], None] | None = None,
    ):
        payload = {
            "cmd": "move_abc",
            "a": int(a_steps),
            "b": int(b_steps),
            "c": int(c_steps),
            "speed": int(speed),
            "accel": int(accel),
        }
        if a_steps == 0 and b_steps == 0 and c_steps == 0:
            self.log("No motor step delta to send")
            if on_done:
                self.after(50, on_done)
            return
        if self.sendCommand(payload):
            self.waiting_for_done = True
            self.pending_after_done = on_done

    def _move_to_absolute_steps(
        # UI pick/safe là target tuyệt đối; firmware move_abc là tương đối nên cần tính delta.
        self,
        target: tuple[int, int, int],
        speed: int,
        accel: int,
        on_done: Callable[[], None] | None = None,
    ):
        # Firmware move_abc is relative. UI pick/safe positions are absolute
        # motor-step targets, so calculate deltas from the last status packet.
        current = (
            int(self.latest_status.get("a", 0)),
            int(self.latest_status.get("b", 0)),
            int(self.latest_status.get("c", 0)),
        )
        delta = (
            target[0] - current[0],
            target[1] - current[1],
            target[2] - current[2],
        )
        self.log(f"Absolute target {target}; relative delta {delta}")
        self._move_relative_abc(delta[0], delta[1], delta[2], speed, accel, on_done)

    # Parsing and state helpers

    def _read_pick_config(self) -> dict | None:
        # Đọc toàn bộ cấu hình Pick A -> B từ các ô nhập.
        try:
            e = self.ui.pick_entries
            return {
                "pick": (
                    self._read_int(e["A1"], "A1"),
                    self._read_int(e["B1"], "B1"),
                    self._read_int(e["C1"], "C1"),
                ),
                "place": (
                    self._read_int(e["A2"], "A2"),
                    self._read_int(e["B2"], "B2"),
                    self._read_int(e["C2"], "C2"),
                ),
                "safe": (
                    self._read_int(e["safeA"], "safeA"),
                    self._read_int(e["safeB"], "safeB"),
                    self._read_int(e["safeC"], "safeC"),
                ),
                "speed": self._read_int(e["speed"], "pick speed", minimum=1),
                "accel": self._read_int(e["accel"], "pick accel", minimum=1),
                "grip_delay": max(0, self._read_int(e["gripDelayMs"], "gripDelayMs")),
                "move_delay": max(0, self._read_int(e["moveDelayMs"], "moveDelayMs")),
            }
        except ValueError as exc:
            self.log(str(exc))
            return None

    def _read_int(self, entry, label: str, minimum: int | None = None) -> int:
        # Parse số nguyên từ entry, cho phép người dùng nhập dạng 1000 hoặc 1000.0.
        raw = entry.get().strip()
        try:
            value = int(float(raw))
        except ValueError as exc:
            raise ValueError(f"{label} must be a number") from exc
        if minimum is not None and value < minimum:
            raise ValueError(f"{label} must be >= {minimum}")
        return value

    def _read_float(self, entry, label: str, minimum: float | None = None) -> float:
        # Parse số thực từ entry.
        raw = entry.get().strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{label} must be a number") from exc
        if minimum is not None and value < minimum:
            raise ValueError(f"{label} must be >= {minimum}")
        return value

    def _read_sign(self, entry, label: str) -> int:
        # Parse sign motor IK, chỉ cho phép -1 hoặc 1.
        value = self._read_int(entry, label)
        if value not in (-1, 1):
            raise ValueError(f"{label} must be -1 or 1")
        return value

    def _require_connected(self, action: str) -> bool:
        # Chặn các action cần ESP32 nếu serial chưa kết nối.
        if self.serial.is_connected():
            return True
        self.log(f"{action} blocked: ESP32 is not connected")
        return False

    def _warn_if_unhomed(self):
        # Cảnh báo nhưng vẫn cho test motor khi chưa homed.
        if not bool(self.latest_status.get("homed", False)):
            self.log("WARNING: Robot is not homed. Movement may be unsafe.")

    def _sequence_is_active(self, active_id: int) -> bool:
        # Kiểm tra sequence hiện tại còn hợp lệ hay đã bị stop/sequence mới thay thế.
        return self.sequence_running and self.sequence_id == active_id

    def log(self, text: str):
        # Ghi log lên UI.
        self.ui.append_log(text)

    def _on_close(self):
        # Dọn tài nguyên trước khi đóng app.
        self.stopCurrentSequence(send_stop=False)
        if self.camera:
            self.camera.stop()
        self.serial.disconnect()
        self.destroy()
