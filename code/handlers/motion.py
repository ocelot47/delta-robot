"""
handlers/motion.py — Motion Planner chạy trên PC.
Tính toán chuỗi waypoint XYZ (mm); giao tiếp thực tế do SerialHandler đảm nhận.
"""

import math
from config import XY_MAX, Z_HOME, Z_MIN, Z_MAX


# ── Workspace clamp ───────────────────────────────────────────

def clamp_xyz(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Giới hạn tọa độ vào workspace hình trụ."""
    r = math.sqrt(x ** 2 + y ** 2)
    if r > XY_MAX:
        scale = XY_MAX / r
        x, y = x * scale, y * scale
    # Z_MAX âm hơn Z_MIN → dùng max/min đúng chiều
    z = max(Z_MAX, min(Z_MIN, z))
    return round(x, 2), round(y, 2), round(z, 2)


# ── MotionPlanner ─────────────────────────────────────────────

class MotionPlanner:
    """
    Lên lịch các chuỗi chuyển động XYZ:
      - Quỹ đạo tròn liên tục (circle)
      - Pick & Place đơn (build_pp_seq)
      - Pick & Place lặp lại (advanced)
    """

    def __init__(self):
        self.circle_running = False
        self._phase: float = 0.0

        self._pp_seq:  list[tuple[float, float, float, str]] = []
        self._pp_idx:  int = 0
        self._adv_cfg: dict = {}

    # ── Quỹ đạo tròn ─────────────────────────────────────────

    def start_circle(self, angle_deg: float = 0.0):
        self._phase = math.radians(angle_deg)
        self.circle_running = True

    def stop_circle(self):
        self.circle_running = False

    def is_circle_running(self) -> bool:
        return self.circle_running

    def next_circle_point(self, radius: float, z: float,
                           speed_deg: float) -> tuple[float, float, float] | None:
        """
        Trả về điểm XYZ tiếp theo trên vòng tròn tại độ cao z.
        Tự clamp vào workspace.
        """
        if not self.circle_running:
            return None
        x = radius * math.cos(self._phase)
        y = radius * math.sin(self._phase)
        self._phase = (self._phase + math.radians(speed_deg)) % (2 * math.pi)
        return clamp_xyz(x, y, z)

    # ── Pick & Place (simple) ─────────────────────────────────

    def build_pp_seq(self,
                     pick: tuple[float, float, float],
                     place: tuple[float, float, float],
                     travel_z: float):
        """
        Xây chuỗi 8 waypoint Pick & Place:
          ① Nâng an toàn   → (0, 0, travel_z)
          ② Dịch tới GẮP  → (pick_x, pick_y, travel_z)
          ③ Hạ xuống gắp  → (pick_x, pick_y, pick_z)
          ④ Nâng mang vật  → (pick_x, pick_y, travel_z)
          ⑤ Dịch tới THẢ  → (place_x, place_y, travel_z)
          ⑥ Hạ xuống thả  → (place_x, place_y, place_z)
          ⑦ Nâng lên       → (place_x, place_y, travel_z)
          ⑧ Về HOME        → (0, 0, Z_HOME)
        """
        px, py, pz = clamp_xyz(*pick)
        lx, ly, lz = clamp_xyz(*place)
        tz = max(Z_MAX, min(Z_MIN, travel_z))

        self._pp_seq = [
            (0.0, 0.0,  tz,     "① Nâng lên (an toàn)"),
            (px,  py,   tz,     "② Di chuyển tới điểm GẮP"),
            (px,  py,   pz,     "③ Hạ xuống — kẹp/hút vật"),
            (px,  py,   tz,     "④ Nâng lên — mang vật"),
            (lx,  ly,   tz,     "⑤ Di chuyển tới điểm THẢ"),
            (lx,  ly,   lz,     "⑥ Hạ xuống — thả vật"),
            (lx,  ly,   tz,     "⑦ Nâng lên"),
            (0.0, 0.0,  Z_HOME, "⑧ Về HOME"),
        ]
        self._pp_idx = 0

    def next_pp_step(self) -> tuple[float, float, float, str] | None:
        """Trả về waypoint tiếp theo hoặc None nếu chuỗi hết."""
        if self._pp_idx >= len(self._pp_seq):
            return None
        step = self._pp_seq[self._pp_idx]
        self._pp_idx += 1
        return step

    # ── Pick & Place (advanced / repeat) ─────────────────────

    def setup_advanced(self,
                       pick: tuple, place: tuple,
                       travel_z: float, delay: int, repeat: int):
        self._adv_cfg = {
            "pick":     pick,
            "place":    place,
            "travel_z": travel_z,
            "delay":    max(100, delay),
            "repeat":   max(1, repeat),
            "current":  0,
        }

    def adv_cfg(self) -> dict:
        return self._adv_cfg

    def advance(self):
        self._adv_cfg["current"] = self._adv_cfg.get("current", 0) + 1
