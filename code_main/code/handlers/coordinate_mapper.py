"""
Convert camera pixel coordinates to robot XY coordinates.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


class PixelRobotMapper:
    def __init__(
        self,
        image_points,
        robot_points,
        workspace_radius_mm: float | None = None,
    ):
        if len(image_points) < 4 or len(robot_points) < 4:
            raise ValueError("Need at least 4 calibration points")
        if len(image_points) != len(robot_points):
            raise ValueError("image_points and robot_points must have the same length")

        self.workspace_radius_mm = workspace_radius_mm
        src = np.float32(image_points)
        dst = np.float32(robot_points)
        matrix, _ = cv2.findHomography(src, dst)
        if matrix is None:
            raise ValueError("Cannot compute camera-to-robot homography")
        self.matrix = matrix

    def pixel_to_robot(self, u: float, v: float) -> tuple[float, float]:
        point = np.float32([[[u, v]]])
        mapped = cv2.perspectiveTransform(point, self.matrix)[0][0]
        return float(mapped[0]), float(mapped[1])

    def is_inside_workspace(self, x: float, y: float) -> bool:
        if self.workspace_radius_mm is None:
            return True
        return math.hypot(x, y) <= self.workspace_radius_mm
