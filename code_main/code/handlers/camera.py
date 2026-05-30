"""
handlers/camera.py — Quản lý camera USB.
Chặn VCamDShow / DirectShow spam bằng redirect C-level stderr.
"""

import os
import sys
import contextlib
import multiprocessing as mp
import threading
import time
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
        # DirectShow thường mở nhanh và khớp với danh sách thiết bị lấy từ
        # pygrabber trên Windows; MSMF giữ lại làm fallback.
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF]
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


def _probe_camera(index: int, backend: int, timeout_s: float = 0.7):
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
            elif _looks_like_camera_name(lower_name):
                names.append(name)
        return names
    except Exception:
        pass
    return []


def _looks_like_camera_name(name: str) -> bool:
    # Lọc các thiết bị audio có tên dính chữ camera như "Microphone (USB Camera)".
    lower_name = (name or "").lower()
    if any(k in lower_name for k in ("microphone", "audio", "speaker", "sound")):
        return False
    return any(k in lower_name for k in ("camera", "webcam", "capture", "video"))


# ── Quét camera ──────────────────────────────────────────────

def scan_cameras(max_index: int = 8) -> list[dict]:
    """
    Quét index 0..max_index-1.
    Trả về list[{"index": int, "name": str, "label": str}].
    """
    # Trên Windows, lấy tên thiết bị trước để scan gần như tức thì. Mở thử
    # camera dễ bị chậm với driver ảo, nên để bước đó cho Start Camera async.
    results = []
    windows_names = _get_camera_names_windows() if sys.platform == "win32" else []
    if windows_names:
        for i, name in enumerate(windows_names):
            if not _looks_like_camera_name(name):
                continue
            label = f"[{i}] {name} (DSHOW)"
            results.append({
                "index": i,
                "name": name,
                "label": label,
                "backend": cv2.CAP_DSHOW,
                "backend_name": "DSHOW",
                "readable": False,
                "width": 0,
                "height": 0,
            })
        existing = {int(item["index"]) for item in results}
        for i in range(max_index):
            if i in existing:
                continue
            results.append({
                "index": i,
                "name": f"Camera {i}",
                "label": f"[{i}] Camera {i} (Auto)",
                "backend": None,
                "backend_name": "Auto",
                "readable": False,
                "width": 0,
                "height": 0,
            })
        return results

    # Fallback khi không lấy được danh sách hệ điều hành: probe ít index hơn,
    # timeout ngắn, và chỉ dùng backend ưu tiên. Backend khác sẽ thử lúc Start.
    for i in range(max_index):
        found = None
        backend = _camera_backends()[0]
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
        if found:
            name = f"Camera {i}"
            label = f"[{i}] {name} ({found['backend_name']})"
            results.append({"index": i, "name": name, "label": label, **found})
    return results


# ── CameraHandler ────────────────────────────────────────────

class CameraHandler:
    def __init__(self):
        # Trạng thái camera OpenCV đang được app quản lý.
        self.cap = None
        self.camera_running = False
        self._backend = None
        self._camera_list: list[dict] = []
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._stop_event = threading.Event()
        self._capture_thread = None
        self._session_id = 0
        self._open_deadline_s = 1.5

    def scan_async(self, on_done, max_index: int = 8):
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

    def _open_capture(self, index: int):
        # Mở camera theo index, chỉ trả thành công khi đã đọc được frame thật.
        from config import CAMERA_WIDTH, CAMERA_HEIGHT

        preferred = [
            c.get("backend")
            for c in self._camera_list
            if int(c.get("index", -1)) == int(index) and c.get("backend") is not None
        ]
        backends = preferred + [b for b in _camera_backends() if b not in preferred]

        for backend in backends:
            with _quiet_stderr():
                cap = self._create_capture(index, backend)
                opened = cap.isOpened()
            if not opened:
                cap.release()
                continue

            with _quiet_stderr():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            frame = self._read_first_frame(cap)
            if frame is not None:
                return cap, backend, frame
            cap.release()

        return None, None, None

    def _read_first_frame(self, cap, timeout_s: float = 1.2):
        # Một số camera mở được nhưng vài frame đầu rỗng/đen; đợi ngắn rồi fail.
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            with _quiet_stderr():
                ret, frame = cap.read()
            if ret and frame is not None:
                if frame.size and frame.max() > 0:
                    return frame
            time.sleep(0.03)
        return None

    def _create_capture(self, index: int, backend: int):
        # Một số backend bỏ qua timeout, nhưng nơi hỗ trợ thì giúp fail nhanh hơn.
        params = []
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            params.extend([cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(self._open_deadline_s * 1000)])
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            params.extend([cv2.CAP_PROP_READ_TIMEOUT_MSEC, 500])
        if params:
            try:
                return cv2.VideoCapture(index, backend, params)
            except Exception:
                pass
        return cv2.VideoCapture(index, backend)

    def start_async(self, index: int, on_done):
        # Mở và đọc camera trong thread nền để không khóa Tk UI.
        self.stop(wait=False)
        self._stop_event.clear()
        self._session_id += 1
        session_id = self._session_id

        def _worker():
            cap, backend, first_frame = self._open_capture(index)
            if self._stop_event.is_set() or session_id != self._session_id:
                if cap is not None:
                    cap.release()
                return
            if cap is None:
                on_done(False)
                return

            self.cap = cap
            self._backend = backend
            self.camera_running = True
            with self._frame_lock:
                self._latest_frame = first_frame
            on_done(True)

            while not self._stop_event.is_set() and session_id == self._session_id:
                with _quiet_stderr():
                    ret, frame = cap.read()
                if ret and frame is not None:
                    with self._frame_lock:
                        self._latest_frame = frame
                else:
                    time.sleep(0.03)

            self.camera_running = False
            with self._frame_lock:
                self._latest_frame = None
            cap.release()
            if self.cap is cap:
                self.cap = None

        self._capture_thread = threading.Thread(target=_worker, daemon=True)
        self._capture_thread.start()

    def start(self, index: int) -> bool:
        # Mở camera đồng bộ, giữ lại cho các caller cũ.
        cap, backend, first_frame = self._open_capture(index)
        if cap is None:
            return False
        self.stop(wait=False)
        self.cap = cap
        self._backend = backend
        self.camera_running = True
        with self._frame_lock:
            self._latest_frame = first_frame
        return True

    def stop(self, wait: bool = False):
        # Dừng camera và giải phóng thiết bị.
        self._session_id += 1
        self._stop_event.set()
        self.camera_running = False
        thread = self._capture_thread
        if wait and thread and thread.is_alive():
            thread.join(timeout=0.5)
        if not thread or not thread.is_alive():
            self._capture_thread = None
        if wait and self.cap:
            self.cap.release()
            self.cap = None
        with self._frame_lock:
            self._latest_frame = None

    def switch(self, index: int) -> bool:
        # Đổi camera đang mở sang index khác.
        self.stop(wait=False)
        return self.start(index)

    def switch_async(self, index: int, on_done):
        # Đổi camera trong thread nền.
        self.start_async(index, on_done)

    def is_running(self) -> bool:
        # Kiểm tra camera đang chạy hay không.
        return self.camera_running

    def read_frame(self):
        # Lấy frame mới nhất do thread nền đọc sẵn.
        if not self.camera_running:
            return None
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

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
