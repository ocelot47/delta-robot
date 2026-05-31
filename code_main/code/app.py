"""
app.py - Delta robot motor test console.

This version intentionally removes the old camera/IK/XYZ UI. It drives the
ESP32 with motor-step test commands only.
"""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox
from collections.abc import Callable

import customtkinter as ctk

from config import (
    CAMERA_IMAGE_POINTS,
    CAMERA_ROBOT_CALIBRATION_ENABLED,
    CAMERA_ROBOT_POINTS,
    CAMERA_ROBOT_WORKSPACE_RADIUS_MM,
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
    Z_COMPENSATION_ENABLED,
    Z_COMP_OFFSET,
    Z_COMP_ORIGIN_X,
    Z_COMP_ORIGIN_Y,
    Z_COMP_R2,
    Z_COMP_X,
    Z_COMP_X2,
    Z_COMP_XY,
    Z_COMP_Y,
    Z_COMP_Y2,
)
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
        self.camera_opening = False
        self.candy_detector = None
        self.candy_detector_loading = False
        self.candy_detect_enabled = False
        self._detect_busy = False
        self._last_detected_frame = None
        self._last_detections: list[dict] = []
        self._last_detection_log_ms = 0
        self.pixel_robot_mapper = self._build_pixel_robot_mapper()

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
        self._ui_queue = queue.Queue()

        self._build_menu()
        self.ui = ControlPanel(self, self)
        self.refresh_ports()
        self.ui.set_connected(False)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._process_ui_queue()
        self._poll_serial()
        self._status_poll_loop()
        self._camera_loop()

    # Serial connection and command helpers

    def _build_menu(self):
        # Menu kiểu Delta GUI: xem COM và thoát app.
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_command(label="Program", command=self._program_placeholder)
        menubar.add_command(label="Available COMs", command=self._show_available_coms)
        self.config(menu=menubar)

    def _build_pixel_robot_mapper(self):
        if not CAMERA_ROBOT_CALIBRATION_ENABLED:
            return None
        try:
            from handlers.coordinate_mapper import PixelRobotMapper

            return PixelRobotMapper(
                CAMERA_IMAGE_POINTS,
                CAMERA_ROBOT_POINTS,
                CAMERA_ROBOT_WORKSPACE_RADIUS_MM,
            )
        except Exception as exc:
            print(f"Camera calibration disabled: {exc}")
            return None

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
        self.camera.scan_async(lambda cams: self._post_ui(lambda: self.ui.update_cameras(cams)))

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
            self.camera_opening = False
            self.ui.set_camera_running(False)
            self.ui.set_camera_message("Camera stopped")
            return
        if self.camera_opening:
            return

        index = self.ui.get_selected_camera_index()
        self.camera_opening = True
        self.ui.set_camera_opening(True)
        self.ui.set_camera_message("Opening camera...")

        def _on_started(ok: bool):
            self._post_ui(lambda: self._finish_camera_start(index, ok))

        self.camera.start_async(index, _on_started)

    def _finish_camera_start(self, index: int, ok: bool):
        # Nhận kết quả mở camera từ thread nền và cập nhật UI trên Tk thread.
        self.camera_opening = False
        self.ui.set_camera_opening(False)
        if ok:
            self.camera_running = True
            self.ui.set_camera_running(True)
            self.log(f"Camera started: index {index}")
        else:
            self.camera_running = False
            self.ui.set_camera_running(False)
            self.ui.set_camera_message("Cannot open camera")
            self.log(f"Cannot open camera index {index}")

    def toggleCandyDetection(self):
        # Bật/tắt YOLO detect kẹo trên frame camera hiện tại.
        enabled = bool(self.ui.detect_candy_var.get())
        if not enabled:
            self.candy_detect_enabled = False
            self._last_detected_frame = None
            self.ui.set_detection_message("Candy detect off")
            return

        model_path = "best.pt"
        if self.candy_detector is None:
            if self.candy_detector_loading:
                return
            self.candy_detector_loading = True
            self.ui.set_detection_message("Loading best.pt...")
            threading.Thread(
                target=self._load_candy_detector_worker,
                args=(model_path,),
                daemon=True,
            ).start()
            return

        self.candy_detect_enabled = True
        self.ui.set_detection_message("Candy detect on")

    def _load_candy_detector_worker(self, model_path: str):
        # Load YOLO model ngoài Tk thread vì import/model init có thể chậm.
        try:
            from handlers.candy_detector import CandyDetector

            detector = CandyDetector(model_path=model_path, conf=0.5)
            error = None
        except Exception as exc:
            detector, error = None, exc
        self._post_ui(lambda: self._finish_candy_detector_load(model_path, detector, error))

    def _finish_candy_detector_load(self, model_path: str, detector, error):
        # Hoàn tất bật/tắt detect trên Tk thread sau khi worker load model xong.
        self.candy_detector_loading = False
        if error is not None:
            self.candy_detector = None
            self.candy_detect_enabled = False
            self.ui.detect_candy_var.set(False)
            self.ui.set_detection_message("Cannot load best.pt")
            self.log(f"Candy detector error: {error}")
            return
        self.candy_detector = detector
        if not bool(self.ui.detect_candy_var.get()):
            self.candy_detect_enabled = False
            self.ui.set_detection_message("Candy detect off")
            return
        self.candy_detect_enabled = True
        self.ui.set_detection_message("Candy detect on")
        self.log(f"Candy detector loaded: {model_path}")

    def change_camera(self, _label=None):
        # Đổi camera khi dropdown thay đổi trong lúc camera đang chạy.
        if self.camera and self.camera.is_running() and not self.camera_opening:
            index = self.ui.get_selected_camera_index()
            self.camera_opening = True
            self.ui.set_camera_opening(True)
            self.ui.set_camera_message("Switching camera...")

            def _on_switched(ok: bool):
                self._post_ui(lambda: self._finish_camera_switch(index, ok))

            self.camera.switch_async(index, _on_switched)

    def _finish_camera_switch(self, index: int, ok: bool):
        # Nhận kết quả đổi camera từ thread nền và cập nhật UI trên Tk thread.
        self.camera_opening = False
        self.ui.set_camera_opening(False)
        if ok:
            self.camera_running = True
            self.ui.set_camera_running(True)
            self.log(f"Camera switched: index {index}")
        else:
            self.camera_running = False
            self.ui.set_camera_running(False)
            self.ui.set_camera_message("Cannot switch camera")

    def _camera_loop(self):
        # Vòng lặp UI đọc frame camera định kỳ và đưa lên preview.
        if self.camera and self.camera.is_running():
            frame = self.camera.read_frame()
            if frame is not None:
                display_frame = frame
                if self.candy_detect_enabled and self.candy_detector:
                    if self._last_detected_frame is not None:
                        display_frame = self._last_detected_frame
                    if not self._detect_busy:
                        self._detect_busy = True
                        threading.Thread(
                            target=self._detect_frame_worker,
                            args=(frame.copy(),),
                            daemon=True,
                        ).start()
                self.ui.update_camera_frame(display_frame)
        self.after(50, self._camera_loop)

    def _detect_frame_worker(self, frame):
        # Chạy YOLO ngoài Tk thread để preview và các nút không bị đơ.
        try:
            annotated, detections = self.candy_detector.detect(frame)
            error = None
        except Exception as exc:
            annotated, detections, error = None, [], exc
        self._post_ui(lambda: self._finish_frame_detection(annotated, detections, error))

    def _finish_frame_detection(self, annotated, detections: list[dict], error):
        # Cập nhật kết quả detect trên Tk thread.
        self._detect_busy = False
        if not self.candy_detect_enabled:
            return
        if error is not None:
            self.candy_detect_enabled = False
            self._last_detected_frame = None
            self._last_detections = []
            self.ui.detect_candy_var.set(False)
            self.ui.set_detection_message("Detect error")
            self.log(f"Candy detect error: {error}")
            return
        self._last_detected_frame = annotated
        self._add_robot_coordinates(detections)
        self._last_detections = detections
        self.ui.update_detection_summary(detections)
        now = self._now_ms()
        if detections and now - self._last_detection_log_ms > 1000:
            first = detections[0]
            message = (
                "Candy detected: "
                f"x={first['x']}, y={first['y']}, "
                f"conf={first['confidence']:.2f}"
            )
            if first.get("robot_xy_valid"):
                message += f", robotX={first['robot_x']:.1f}, robotY={first['robot_y']:.1f}"
            elif "robot_xy_valid" in first:
                message += ", outside robot workspace"
            self.log(message)
            self._last_detection_log_ms = now

    def _add_robot_coordinates(self, detections: list[dict]):
        if self.pixel_robot_mapper is None:
            return
        for detection in detections:
            robot_x, robot_y = self.pixel_robot_mapper.pixel_to_robot(detection["x"], detection["y"])
            detection["robot_x"] = robot_x
            detection["robot_y"] = robot_y
            detection["robot_xy_valid"] = self.pixel_robot_mapper.is_inside_workspace(robot_x, robot_y)

    def moveToDetectedCandy(self):
        if self.pixel_robot_mapper is None:
            self.log("Move to candy blocked: camera calibration is not enabled")
            return
        if not self._last_detections:
            self.log("Move to candy blocked: no candy detected")
            return

        target = next(
            (item for item in self._last_detections if item.get("robot_xy_valid")),
            None,
        )
        if target is None:
            self.log("Move to candy blocked: detected candy is outside robot workspace")
            return

        try:
            e = self.ui.ik_entries
            z = self._read_float(e["z"], "IK z")
            speed = self._read_int(e["speed"], "IK speed", minimum=1)
            accel = self._read_int(e["accel"], "IK accel", minimum=1)
        except ValueError as exc:
            self.log(str(exc))
            return

        robot_x = target["robot_x"]
        robot_y = target["robot_y"]
        self._set_entry_value(self.ui.ik_entries["x"], f"{robot_x:.2f}")
        self._set_entry_value(self.ui.ik_entries["y"], f"{robot_y:.2f}")

        self._warn_if_unhomed()
        self.sendCommand(self._move_xyz_payload(robot_x, robot_y, z, speed, accel))

    def _set_entry_value(self, entry, value: str):
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def logCalibrationPoint(self):
        if not self._last_detections:
            self.log("Calibration point blocked: no marker/candy detected")
            return
        try:
            e = self.ui.ik_entries
            robot_x = self._read_float(e["x"], "IK x")
            robot_y = self._read_float(e["y"], "IK y")
        except ValueError as exc:
            self.log(str(exc))
            return

        detection = self._last_detections[0]
        self.log(
            "Calibration point: "
            f"image=[{detection['x']}, {detection['y']}], "
            f"robot=[{robot_x:.2f}, {robot_y:.2f}]"
        )

    def _now_ms(self):
        # Lấy thời gian ms tương đối từ Tk để throttle log detect.
        return int(float(self.tk.call("clock", "milliseconds")))

    def _post_ui(self, callback: Callable[[], None]):
        # Thread nền không gọi Tk trực tiếp; chỉ gửi việc về queue cho Tk thread.
        self._ui_queue.put(callback)

    def _process_ui_queue(self):
        # Xử lý các callback từ worker thread trên đúng Tk thread.
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception as exc:
                self.log(f"UI callback error: {exc}")
        self.after(20, self._process_ui_queue)

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
        # Khi robot đang chạy thì poll nhanh hơn để status UI bám theo thời gian thực.
        if self.serial.is_connected():
            self.requestStatus()
        moving = bool(self.latest_status.get("moving", False))
        self.after(150 if moving else 750, self._status_poll_loop)

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
        # Hợp nhất response/status mới vào latest_status rồi cập nhật UI.
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
        self.home_all_drop_running = True
        self.sendCommand({
            "cmd": "move_abc",
            "a": a,
            "b": b,
            "c": c,
            "speed": speed,
            "accel": accel,
        })

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
            x = self._read_float(e["x"], "IK x")
            y = self._read_float(e["y"], "IK y")
            z = self._read_float(e["z"], "IK z")
            speed = self._read_int(e["speed"], "IK speed", minimum=1)
            accel = self._read_int(e["accel"], "IK accel", minimum=1)
        except ValueError as exc:
            self.log(str(exc))
            return

        self._warn_if_unhomed()
        self.sendCommand(self._move_xyz_payload(x, y, z, speed, accel))

    def _move_xyz_payload(self, x: float, y: float, z: float, speed: int, accel: int) -> dict:
        corrected_z = self._compensated_z(x, y, z)
        if Z_COMPENSATION_ENABLED and abs(corrected_z - z) >= 0.01:
            self.log(f"Z compensation: requested={z:.2f}, command={corrected_z:.2f}")
        return {
            "cmd": "move_xyz",
            "x": x,
            "y": y,
            "z": corrected_z,
            "speed": speed,
            "accel": accel,
        }

    def _compensated_z(self, x: float, y: float, z: float) -> float:
        if not Z_COMPENSATION_ENABLED:
            return z
        dx = x - Z_COMP_ORIGIN_X
        dy = y - Z_COMP_ORIGIN_Y
        return (
            z
            + Z_COMP_X * dx
            + Z_COMP_Y * dy
            + Z_COMP_X2 * dx * dx
            + Z_COMP_Y2 * dy * dy
            + Z_COMP_R2 * (dx * dx + dy * dy)
            + Z_COMP_XY * dx * dy
            + Z_COMP_OFFSET
        )

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
            self.camera.stop(wait=True)
        self.serial.disconnect()
        self.destroy()
