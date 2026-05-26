"""
handlers/camera.py — Quản lý camera USB.
Chặn VCamDShow / DirectShow spam bằng redirect C-level stderr.
"""

import os
import sys
import contextlib
import multiprocessing as mp
import threading
import cv2


# ── Suppress stderr ──────────────────────────────────────────

def _suppress_fd(fd: int) -> int:
    # Chuyển stdout/stderr cấp thấp sang devnull để chặn log driver camera.
    devnull = os.open(os.devnull, os.O_WRONLY)
    old = os.dup(fd)
    os.dup2(devnull, fd)
    os.close(devnull)
    return old


def _restore_fd(fd: int, old: int):
    # Khôi phục stdout/stderr sau khi thao tác OpenCV xong.
    os.dup2(old, fd)
    os.close(old)


@contextlib.contextmanager
def _quiet_stderr():
    # Context manager dùng quanh OpenCV để hạn chế spam từ driver ảo.
    old_stdout = _suppress_fd(1)
    old_stderr = _suppress_fd(2)
    try:
        yield
    finally:
        _restore_fd(2, old_stderr)
        _restore_fd(1, old_stdout)


def _camera_backends() -> list[int]:
    # Danh sách backend OpenCV sẽ thử khi mở/probe camera.
    if sys.platform == "win32":
        # Prefer MSMF, but keep DirectShow as a fallback because some USB
        # cameras expose only that path. Probing runs in a child process with a
        # timeout, so a bad virtual camera driver cannot freeze the GUI.
        return [cv2.CAP_MSMF, cv2.CAP_DSHOW, cv2.CAP_ANY]
    return [cv2.CAP_ANY]


def _backend_name(backend: int) -> str:
    # Đổi mã backend OpenCV thành tên ngắn để hiện trên UI.
    names = {
        cv2.CAP_MSMF: "MSMF",
        cv2.CAP_DSHOW: "DSHOW",
        cv2.CAP_ANY: "ANY",
    }
    return names.get(backend, str(backend))


def _probe_camera_worker(index: int, backend: int, queue):
    # Process con thử mở camera; nếu backend treo thì app chính vẫn an toàn.
    with _quiet_stderr():
        cap = cv2.VideoCapture(index, backend)
        opened = cap.isOpened()
        readable = False
        width = 0
        height = 0
        if opened:
            readable, frame = cap.read()
            if readable and frame is not None:
                height, width = frame.shape[:2]
            else:
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()
    queue.put((opened, readable, width, height))


def _probe_camera(index: int, backend: int, timeout_s: float = 2.0):
    # Probe camera có timeout, quá thời gian thì terminate process con.
    ctx = mp.get_context("spawn") if sys.platform == "win32" else mp.get_context()
    queue = ctx.Queue()
    process = ctx.Process(target=_probe_camera_worker, args=(index, backend, queue))
    process.daemon = True
    process.start()
    process.join(timeout_s)
    if process.is_alive():
        process.terminate()
        process.join(0.5)
        return None
    if queue.empty():
        return None
    return queue.get()


# ── Lấy tên camera trên Windows ─────────────────────────────

def _get_camera_name_windows(index: int) -> str | None:
    # Lấy tên camera Windows tương ứng với index.
    names = _get_camera_names_windows()
    if index < len(names):
        return names[index]
    return None


def _get_camera_names_windows() -> list[str]:
    # Lấy danh sách tên camera bằng pygrabber hoặc WMI.
    try:
        from pygrabber.dshow_graph import FilterGraph
        devices = list(FilterGraph().get_input_devices())
        if devices:
            return devices
    except Exception:
        pass
    try:
        import win32com.client
        items = win32com.client.GetObject("winmgmts:").InstancesOf("Win32_PnPEntity")
        names = []
        for item in items:
            name = getattr(item, "Name", "") or ""
            pnp_class = (getattr(item, "PNPClass", "") or "").lower()
            lower_name = name.lower()
            if pnp_class in ("camera", "image"):
                names.append(name)
            elif any(k in lower_name for k in ("camera", "webcam", "capture", "video")):
                names.append(name)
        return names
    except Exception:
        pass
    return []


# ── Quét camera ──────────────────────────────────────────────

def scan_cameras(max_index: int = 10) -> list[dict]:
    """
    Quét index 0..max_index-1.
    Trả về list[{"index": int, "name": str, "label": str}].
    """
    # Quét nhiều index/backend và trả dữ liệu để UI chọn đúng camera.
    results = []
    windows_names = _get_camera_names_windows() if sys.platform == "win32" else []
    for i in range(max_index):
        found = None
        for backend in _camera_backends():
            result = _probe_camera(i, backend)
            if result:
                opened, readable, width, height = result
            else:
                opened, readable, width, height = False, False, 0, 0
            if opened or readable:
                found = {
                    "backend": backend,
                    "backend_name": _backend_name(backend),
                    "readable": readable,
                    "width": width,
                    "height": height,
                }
                break
        if found:
            name = _get_camera_name_windows(i) if sys.platform == "win32" else None
            name = name or f"Camera {i}"
            label = f"[{i}] {name} ({found['backend_name']})"
            results.append({"index": i, "name": name, "label": label, **found})

    detected_indices = {item["index"] for item in results}
    for i, name in enumerate(windows_names[:max_index]):
        if i in detected_indices:
            continue
        label = f"[{i}] {name} (Windows device)"
        results.append({
            "index": i,
            "name": name,
            "label": label,
            "backend": None,
            "backend_name": "Windows device",
            "readable": False,
            "width": 0,
            "height": 0,
        })
    return results


# ── CameraHandler ────────────────────────────────────────────

class CameraHandler:
    def __init__(self):
        # Trạng thái camera OpenCV đang được app quản lý.
        self.cap = None
        self.camera_running = False
        self._backend = None
        self._camera_list: list[dict] = []

    def scan_async(self, on_done, max_index: int = 10):
        # Chạy scan trong thread nền để giao diện không bị đứng.
        """Quét trong thread riêng; gọi on_done(list) khi xong."""
        def _w():
            cams = scan_cameras(max_index)
            self._camera_list = cams
            on_done(cams)
        threading.Thread(target=_w, daemon=True).start()

    def label_to_index(self, label: str) -> int:
        # Đổi label dropdown thành camera index.
        for c in self._camera_list:
            if c["label"] == label:
                return c["index"]
        try:
            return int(label.split("]")[0].replace("[", "").strip())
        except Exception:
            return 0

    def start(self, index: int) -> bool:
        # Mở camera theo index, ưu tiên backend đã probe thành công.
        from config import CAMERA_WIDTH, CAMERA_HEIGHT

        preferred = [
            c.get("backend")
            for c in self._camera_list
            if int(c.get("index", -1)) == int(index) and c.get("backend") is not None
        ]
        backends = preferred + [b for b in _camera_backends() if b not in preferred]

        for backend in backends:
            with _quiet_stderr():
                cap = cv2.VideoCapture(index, backend)
                opened = cap.isOpened()
            if opened:
                self._backend = backend
                break
            cap.release()
        else:
            return False

        with _quiet_stderr():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        self.camera_running = True
        return True

    def stop(self):
        # Dừng camera và giải phóng thiết bị.
        self.camera_running = False
        if self.cap:
            self.cap.release()
            self.cap = None

    def switch(self, index: int) -> bool:
        # Đổi camera đang mở sang index khác.
        self.stop()
        return self.start(index)

    def is_running(self) -> bool:
        # Kiểm tra camera đang chạy hay không.
        return self.camera_running

    def read_frame(self):
        # Đọc một frame camera; trả None nếu camera chưa mở hoặc đọc lỗi.
        if not self.camera_running or not self.cap:
            return None
        with _quiet_stderr():
            ret, frame = self.cap.read()
        return frame if ret else None

    def detect_circles(self, frame):
        # Detect hình tròn đơn giản bằng HoughCircles, chưa dùng YOLO/AI.
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (9, 9), 2)
        return cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT,
            dp=1.2, minDist=80, param1=80, param2=30,
            minRadius=10, maxRadius=160,
        )

    def draw_circles(self, frame, circles):
        # Vẽ kết quả detect circle lên frame camera.
        if circles is not None:
            for x, y, r in circles[0, :3].astype(int):
                cv2.circle(frame, (x, y), r, (0, 255, 0), 2)
                cv2.circle(frame, (x, y), 3, (0, 0, 255), -1)
                cv2.putText(frame, f"({x},{y}) r={r}", (x + 8, y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return frame
