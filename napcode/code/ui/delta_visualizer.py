"""
Matplotlib views used by the desktop Delta GUI.

The 3D model is a lightweight live visualizer for testing. It is inspired by
the reference Delta-Robot project UI, but it is intentionally decoupled from
the ESP32 protocol used by this project.
"""

from __future__ import annotations

import datetime as dt
import math
import tkinter as tk
from collections import deque

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from config import ARM_LENGTH, BASE_TRI, PLATFORM_TRI, STEPS_PER_DEG


# Default pose for the 3D viewer when firmware has no valid XYZ/IK status.
# It is only a visual home estimate; real geometry must be calibrated before
# using the 3D model as a physical pose reference.
VIEW_HOME_THETA_DEG = 62.0
VIEW_HOME_TCP_Z = -360.0
VIEW_HOME_BASE_THETA_DEG = 55.0
VIEW_HOME_BASE_TCP_Z = -330.0


class DeltaVisualizer:
    def __init__(self, master):
        # Tạo Figure Matplotlib nhúng vào Tkinter để vẽ mô hình 3D.
        self.master = master
        self.fig = plt.Figure(figsize=(6.8, 5.7), dpi=100)
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.canvas = FigureCanvasTkAgg(self.fig, master=master)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.trajectory_enabled = tk.BooleanVar(value=False)
        self.trajectory = deque(maxlen=80)
        self.latest_status = {}
        self.angle_history = deque(maxlen=120)
        self.view_home_theta_deg = VIEW_HOME_THETA_DEG
        self.view_home_tcp_z = VIEW_HOME_TCP_Z

        self.plot_window = None
        self.plot_fig = None
        self.plot_ax = None
        self.plot_canvas = None

        self.draw_robot({})

    def set_post_home_drop_estimate(
        self,
        a_steps: int,
        b_steps: int,
        c_steps: int,
        *,
        record: bool = False,
    ):
        # Ước lượng pose home 3D dựa trên lượng step hạ sau homing trong app.
        avg_steps = (abs(a_steps) + abs(b_steps) + abs(c_steps)) / 3.0
        scale = max(0.0, min(2.0, avg_steps / 800.0))
        self.view_home_theta_deg = VIEW_HOME_BASE_THETA_DEG + 7.0 * scale
        self.view_home_tcp_z = VIEW_HOME_BASE_TCP_Z - 30.0 * scale
        if record:
            now = dt.datetime.now().strftime("%M:%S:%f")[:-3]
            self.angle_history.append((
                now,
                (self.view_home_theta_deg, self.view_home_theta_deg, self.view_home_theta_deg),
            ))
            if self.plot_window and self.plot_window.winfo_exists():
                self._redraw_angle_plot()
        self.draw_robot(self.latest_status)

    def draw_robot(self, status: dict):
        # Vẽ lại toàn bộ robot 3D từ status hiện tại hoặc pose home ước lượng.
        self.latest_status = dict(status)
        self.ax.clear()
        self._setup_axes()

        theta = self._angles_from_status(status)
        tcp = self._tcp_from_status(status, theta)
        base = self._triangle(BASE_TRI, z=0.0)
        eff = self._triangle(PLATFORM_TRI, z=tcp[2], center=(tcp[0], tcp[1]))
        elbows = self._elbows(theta, base)

        self.ax.plot(base[:, 0], base[:, 1], base[:, 2], color="slategrey", linewidth=2)
        self.ax.plot(eff[:, 0], eff[:, 1], eff[:, 2], color="black", linewidth=2)
        self.ax.scatter([tcp[0]], [tcp[1]], [tcp[2]], color="red", s=38)

        for i in range(3):
            b = base[i]
            e = elbows[i]
            p = eff[i]
            self.ax.plot([b[0], e[0]], [b[1], e[1]], [b[2], e[2]], color="black", linewidth=2)
            self.ax.plot([e[0], p[0]], [e[1], p[1]], [e[2], p[2]], color="black", linewidth=1.7)

        self._draw_frame_posts(base)

        if self.trajectory_enabled.get():
            self.trajectory.append(tcp)
            if len(self.trajectory) > 1:
                xs, ys, zs = zip(*self.trajectory)
                self.ax.plot(xs, ys, zs, color="#1f77b4", linewidth=1.2)

        self.canvas.draw_idle()

    def record_status(self, status: dict):
        # Ghi lịch sử góc để cửa sổ Joints plot có dữ liệu vẽ.
        theta = self._angles_from_status(status)
        now = dt.datetime.now().strftime("%M:%S:%f")[:-3]
        self.angle_history.append((now, theta))
        if self.plot_window and self.plot_window.winfo_exists():
            self._redraw_angle_plot()

    def open_joint_plot(self):
        # Mở cửa sổ plot góc 3 motor theo thời gian.
        if self.plot_window and self.plot_window.winfo_exists():
            self.plot_window.lift()
            return

        self.plot_window = tk.Toplevel(self.master)
        self.plot_window.title("Joints angles")
        self.plot_window.geometry("720x760")
        self.plot_fig = plt.Figure(figsize=(6.2, 5.4), dpi=100)
        self.plot_ax = self.plot_fig.add_subplot(111)
        self.plot_canvas = FigureCanvasTkAgg(self.plot_fig, master=self.plot_window)
        self.plot_canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(self.plot_canvas, self.plot_window)
        toolbar.update()
        self._redraw_angle_plot()

    def open_workspace_plot(self):
        # Mở cửa sổ workspace lý thuyết, không phụ thuộc pose hiện tại.
        win = tk.Toplevel(self.master)
        win.title("Workspace")
        win.geometry("730x720")
        fig = plt.Figure(figsize=(6.4, 6.2), dpi=100)
        ax = fig.add_subplot(111, projection="3d")
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._draw_workspace(ax)
        canvas.draw_idle()

    def clear_trajectory(self):
        # Xóa đường trajectory đang vẽ trên mô hình 3D.
        self.trajectory.clear()
        self.draw_robot(self.latest_status)

    def _redraw_angle_plot(self):
        # Vẽ lại biểu đồ góc motor trong cửa sổ Joints plot.
        if not self.plot_ax or not self.plot_canvas:
            return
        self.plot_ax.clear()
        xs = [item[0] for item in self.angle_history]
        a = [item[1][0] for item in self.angle_history]
        b = [item[1][1] for item in self.angle_history]
        c = [item[1][2] for item in self.angle_history]
        self.plot_ax.plot(xs, a, "g", label="Joint 1")
        self.plot_ax.plot(xs, b, "r", label="Joint 2")
        self.plot_ax.plot(xs, c, "b", label="Joint 3")
        self.plot_ax.set_xlabel("time")
        self.plot_ax.set_ylabel("angle [deg]")
        self.plot_ax.grid(True)
        self.plot_ax.legend(loc="upper left")
        self.plot_ax.xaxis.set_major_locator(plt.MaxNLocator(5))
        self.plot_fig.tight_layout()
        self.plot_canvas.draw_idle()

    def _setup_axes(self):
        # Cấu hình trục X/Y/Z và góc nhìn cho mô hình 3D.
        self.ax.set_xlim(-300, 300)
        self.ax.set_ylim(-300, 300)
        self.ax.set_zlim(-600, 100)
        self.ax.set_xlabel("X [mm]")
        self.ax.set_ylabel("Y [mm]")
        self.ax.set_zlabel("Z [mm]")
        self.ax.view_init(elev=25, azim=-60)
        self.ax.grid(True)

    def _draw_workspace(self, ax):
        # Vẽ workspace minh họa bằng point cloud đơn giản.
        xs, ys, zs = [], [], []
        for z in range(-470, -70, 18):
            radius = max(30, 230 - abs(z + 260) * 0.55)
            for deg in range(0, 360, 5):
                rad = math.radians(deg)
                xs.append(radius * math.cos(rad))
                ys.append(radius * math.sin(rad))
                zs.append(z)
        ax.scatter(xs, ys, zs, s=2, color="#1f77b4")
        ax.set_xlim(-260, 260)
        ax.set_ylim(-260, 260)
        ax.set_zlim(-500, -40)
        ax.set_xlabel("X [mm]")
        ax.set_ylabel("Y [mm]")
        ax.set_zlabel("Z [mm]")
        ax.view_init(elev=23, azim=-55)
        ax.grid(True)

    def _draw_frame_posts(self, base):
        # Vẽ ba cột khung đứng để dễ hình dung robot trong không gian.
        for p in base[:3]:
            x, y = p[0], p[1]
            self.ax.plot([x, x], [y, y], [0, -520], color="lightslategrey", linewidth=1.2)

    def _angles_from_status(self, status: dict) -> tuple[float, float, float]:
        # Lấy góc motor từ IK nếu có; nếu chưa có thì dùng pose home ước lượng.
        if status.get("xyzValid"):
            return (
                float(status.get("thetaA", 0.0)),
                float(status.get("thetaB", 0.0)),
                float(status.get("thetaC", 0.0)),
            )
        if status.get("homed"):
            return (
                self.view_home_theta_deg,
                self.view_home_theta_deg,
                self.view_home_theta_deg,
            )
        return (
            self.view_home_theta_deg,
            self.view_home_theta_deg,
            self.view_home_theta_deg,
        )

    def _tcp_from_status(self, status: dict, theta: tuple[float, float, float]):
        # Lấy vị trí TCP từ IK nếu có; nếu chưa có thì dùng Z home ước lượng.
        if status.get("xyzValid"):
            return (
                float(status.get("x", 0.0)),
                float(status.get("y", 0.0)),
                float(status.get("z", -260.0)),
            )
        return (0.0, 0.0, self.view_home_tcp_z)

    def _triangle(self, side: float, z: float, center=(0.0, 0.0)):
        # Tạo tọa độ tam giác base/platform để vẽ.
        r = side / math.sqrt(3)
        points = []
        for deg in (90, 210, 330, 90):
            rad = math.radians(deg)
            points.append((center[0] + r * math.cos(rad), center[1] + r * math.sin(rad), z))
        try:
            import numpy as np

            return np.array(points, dtype=float)
        except Exception:
            return points

    def _elbows(self, theta: tuple[float, float, float], base):
        # Ước lượng tọa độ khuỷu tay của 3 nhánh từ góc motor.
        elbows = []
        for i, angle in enumerate(theta):
            rad = math.radians(angle)
            b = base[i]
            direction = math.atan2(-b[1], -b[0])
            x = b[0] + ARM_LENGTH * math.cos(rad) * math.cos(direction)
            y = b[1] + ARM_LENGTH * math.cos(rad) * math.sin(direction)
            z = -ARM_LENGTH * math.sin(rad)
            elbows.append((x, y, z))
        try:
            import numpy as np

            return np.array(elbows, dtype=float)
        except Exception:
            return elbows
