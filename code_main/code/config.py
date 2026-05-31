import customtkinter as ctk

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ════════════════════════════════════════════════════════════
#  THÔNG SỐ CƠ HỌC ROBOT DELTA  (đơn vị: mm)
#  Đo trực tiếp trên robot của bạn rồi điền vào đây.
#  Xem hình minh hoạ trong README.md.
# ════════════════════════════════════════════════════════════
ARM_LENGTH      = 200.0   # Chiều dài cánh tay trên (upper arm / bicep), mm
ROD_LENGTH      = 320.0   # Chiều dài thanh nối   (forearm / rod),       mm
BASE_TRI        = 235.0   # Cạnh tam giác đế      (base triangle side),  mm
PLATFORM_TRI    = 70.0    # Cạnh tam giác động    (end-effector side),   mm

# ════════════════════════════════════════════════════════════
#  THÔNG SỐ TRUYỀN ĐỘNG (stepper)
# ════════════════════════════════════════════════════════════
STEPS_PER_DEG   = 8.889   # steps / 1° góc motor
                           # Ví dụ: 200 step/rev × 16 microstep / 360° = 8.889
DEFAULT_MAX_SPEED = 3000.0 # steps/s
DEFAULT_ACCEL     = 1500.0 # steps/s²

# ════════════════════════════════════════════════════════════
#  GIỚI HẠN KHÔNG GIAN LÀM VIỆC  (đơn vị: mm)
#  Robot chỉ hoạt động trong hình trụ bán kính XY_MAX,
#  độ sâu từ Z_MIN (cao nhất) đến Z_MAX (thấp nhất).
#  Z luôn âm (đầu robot ở phía dưới đế).
# ════════════════════════════════════════════════════════════
XY_MAX =  80.0    # bán kính tối đa trên mặt phẳng XY, mm
Z_HOME = -200.0   # vị trí HOME (an toàn, giữa), mm
Z_MIN  = -150.0   # giới hạn trên (gần đế nhất),  mm  — Z âm nên MIN nhỏ hơn HOME
Z_MAX  = -280.0   # giới hạn dưới (xa đế nhất),   mm

# ════════════════════════════════════════════════════════════
#  SERIAL
# ════════════════════════════════════════════════════════════
BAUD_RATE        = 115200
SERIAL_TIMEOUT   = 0.05
SEND_INTERVAL_MS = 30     # tần suất gửi lệnh tối đa (ms)

# ════════════════════════════════════════════════════════════
#  CAMERA
# ════════════════════════════════════════════════════════════
CAMERA_WIDTH          = 1280
CAMERA_HEIGHT         = 720
CAMERA_DISPLAY_WIDTH  = 480   # nhỏ hơn để layout gọn
CAMERA_DISPLAY_HEIGHT = 340
CAMERA_UPDATE_MS      = 50    # 20fps — đủ mượt, nhẹ CPU hơn 33ms

# Camera pixel -> robot XY calibration.
# Replace these sample points with your measured points, then set
# CAMERA_ROBOT_CALIBRATION_ENABLED = True.
# Use reachable robot workspace points, not the full camera view.
CAMERA_ROBOT_CALIBRATION_ENABLED = True
CAMERA_IMAGE_POINTS = [
    [443, 442],  # bottom-left reachable point in camera
    [801, 433],  # bottom-right reachable point in camera
    [786, 159],  # top-right reachable point in camera
    [432, 174],  # top-left reachable point in camera
]
CAMERA_ROBOT_POINTS = [
    [ 65.0, -30.0],  # robot X/Y mm for bottom-left point, measured Z=-170
    [ 55.0,  60.0],  # robot X/Y mm for bottom-right point, measured Z=-160
    [-15.0,  67.0],  # robot X/Y mm for top-right point, measured Z=-170
    [-20.0, -40.0],  # robot X/Y mm for top-left point, measured Z=-180
]
CAMERA_ROBOT_WORKSPACE_RADIUS_MM = XY_MAX

# Z compensation by XY position.
# Firmware IK still receives move_xyz, but the app can slightly adjust the
# commanded Z to counter real-world height drift when X/Y changes.
#
# Formula:
#   dx = x - Z_COMP_ORIGIN_X
#   dy = y - Z_COMP_ORIGIN_Y
#   z_command = z_user
#       + Z_COMP_X*dx + Z_COMP_Y*dy
#       + Z_COMP_X2*dx*dx + Z_COMP_Y2*dy*dy
#       + Z_COMP_R2*(dx*dx + dy*dy) + Z_COMP_XY*dx*dy
#       + Z_COMP_OFFSET
#
# Tune the sign from real robot behavior. On this robot, a positive R2
# correction compensates the observed height rise when moving away from center.
Z_COMPENSATION_ENABLED = True
Z_COMP_ORIGIN_X = 0.0
Z_COMP_ORIGIN_Y = 0.0
Z_COMP_X = 0.0        # mm Z correction per 1 mm X
Z_COMP_Y = 0.0        # mm Z correction per 1 mm Y
Z_COMP_X2 = 0.0       # mm Z correction per 1 mm^2 X
Z_COMP_Y2 = 0.0       # mm Z correction per 1 mm^2 Y
Z_COMP_R2 = 0.00050   # mm Z correction per 1 mm^2 radius
Z_COMP_XY = 0.0       # mm Z correction per 1 mm^2 XY product
Z_COMP_OFFSET = 0.0  # constant Z correction, mm

# ════════════════════════════════════════════════════════════
#  QUỸ ĐẠO TRÒN  (đơn vị: mm, ms)
# ════════════════════════════════════════════════════════════
CIRCLE_DEFAULT_RADIUS  = 40.0   # bán kính vòng tròn XY, mm
CIRCLE_DEFAULT_Z       = -230.0 # độ cao cố định khi xoay, mm
CIRCLE_DEFAULT_SPEED   = 6.0    # °/tick
CIRCLE_DEFAULT_TICK    = 50     # ms mỗi tick

# ════════════════════════════════════════════════════════════
#  PICK & PLACE  (đơn vị: mm, ms)
#  Toàn bộ theo toạ độ XYZ thực trong không gian làm việc.
# ════════════════════════════════════════════════════════════
PP_DEFAULT_PICK_X   =  30.0
PP_DEFAULT_PICK_Y   =   0.0
PP_DEFAULT_PICK_Z   = -250.0   # độ sâu tại điểm gắp (hạ xuống)

PP_DEFAULT_PLACE_X  = -30.0
PP_DEFAULT_PLACE_Y  =   0.0
PP_DEFAULT_PLACE_Z  = -250.0   # độ sâu tại điểm thả

PP_DEFAULT_TRAVEL_Z = -200.0   # độ cao di chuyển an toàn (nâng lên)
PP_DEFAULT_DELAY    = 1200      # ms dừng tại mỗi vị trí
PP_DEFAULT_REPEAT   = 1

# ════════════════════════════════════════════════════════════
#  WINDOW
# ════════════════════════════════════════════════════════════
WINDOW_WIDTH    = 1280
WINDOW_HEIGHT   = 800
WINDOW_MIN_WIDTH  = 1100
WINDOW_MIN_HEIGHT = 720
