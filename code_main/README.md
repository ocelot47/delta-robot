# Delta Robot Project (WIP)

A personal engineering project to design and build a 3-DOF Delta Robot, from
CAD and 3D-printed parts to embedded control, Python desktop control, motion
testing, and gripper experiments.

## Current Status

- Project stage: **Work in Progress**
- Mechanical/CAD design is available
- Prototype integration and ESP32 control are in progress
- Python GUI is available for serial control, testing, and visualization
- MG90S gripper servo control is included in the current firmware/app flow
- Final calibration and production-ready behavior are not finished yet

## What Is Included Right Now

- CAD assembly snapshots
- STL files for 3D printing (`filein3d_STL`)
- Assembly file (`assembly.sldasm`)
- ESP32 firmware (`napcode/code/code.ino`)
- Python desktop app (`napcode/code/main.py`)
- Camera candy detection module (`napcode/code/handlers/candy_detector.py`)
- Calibration measurement template (`napcode/code/calibration_measurements.md`)
- Reference images used for documentation

## Project Gallery

### Complete Assembly View
![Complete assembly CAD view](image/83a0624d-d194-4f59-b114-7ddad7cc7ad6.jpg)
Overall CAD assembly of the Delta Robot frame, motor mounts, and arm linkage.

### Exploded Assembly View
![Exploded assembly CAD view](image/55de9165-3945-4e72-befe-00b2a7845b0c.jpg)
Exploded view showing how structural and moving components fit together.

### Top View Measurement
![Top view CAD measurement](image/top.jpeg)
Top view with geometric spacing measurement used for frame and actuator placement checks.

### Side View Measurement
![Side view CAD measurement](image/side.jpeg)
Side view with height/clearance measurement for workspace and vertical layout validation.

## Repository Highlights

- `image/`: screenshots, measurement views, and CAD references
- `image/filein3d_STL/`: printable STL component set
- `napcode/code/`: Python desktop app and ESP32 firmware
- `napcode/code/code.ino`: ESP32 JSON-over-Serial firmware
- `napcode/code/main.py`: desktop app entry point
- `napcode/code/handlers/candy_detector.py`: YOLO candy detection helper
- `napcode/code/calibration_measurements.md`: robot measurement worksheet

## Desktop App And Firmware

The desktop app is built with Python, CustomTkinter, PySerial, Matplotlib, and
NumPy, OpenCV, Pillow, and Ultralytics. It provides compact controls on the
left, a Matplotlib robot visualization on the right, menu items for plots,
camera support, candy detection, and a log console at the bottom.

The serial protocol is JSON-over-Serial for the current ESP32 firmware.

## Hardware Mapping

| Signal | GPIO |
|---|---:|
| STEP1 / Motor A | 32 |
| DIR1 / Motor A | 33 |
| STEP2 / Motor B | 18 |
| DIR2 / Motor B | 19 |
| STEP3 / Motor C | 25 |
| DIR3 / Motor C | 26 |
| LIMIT_A | 13 |
| LIMIT_B | 14 |
| LIMIT_C | 23 |
| ENABLE_PIN | 27 |
| MG90S gripper servo signal | 17 |

DRV8825 enable is active low: `LOW = enabled`, `HIGH = disabled`.

Limit switches are NC with `INPUT_PULLUP`: `false = normal`, `true = triggered
or wire fault`.

MG90S gripper:

- Servo signal default: `GPIO17`
- Servo power should use a stable external 5V supply; connect servo GND and
  ESP32 GND together.
- Default open angle: `180 deg`
- Default close angle: `50 deg`
- Default boot/start angle: `70 deg`
- Change these in the UI or in `code.ino` if your gripper geometry needs a
  smaller close limit.

## Install

```bash
pip install customtkinter pyserial matplotlib numpy opencv-python pillow ultralytics
```

Arduino libraries:

- `FastAccelStepper`
- `ArduinoJson` v6.x
- `Delta-Kinematics-Library`
- `ESP32Servo`

## Run

1. Upload `napcode/code/code.ino` to the ESP32.
2. Start the desktop app:

```bash
cd napcode/code
python main.py
```

3. Select the COM port, keep baudrate `115200`, then press `Connect`.

## Test Flow

1. Press `Enable motors`.
2. Check status and limit switches. All limits should be `false` when not pressed.
3. Use `Home A`, `Home B`, `Home C`, or `Home`.
4. Use `JOG / Single Motor` to move one motor.
5. Use `Multi Motor Control` to send `move_abc`.
6. Use `Rotate In Place Test` for the temporary motor-step pattern.
7. Use `Gripper Servo MG90S` to test open/close before running pick/place.
8. Use `Pick From A To B Simulation` for a step-position demo sequence. The
   sequence closes the gripper at Position A and opens it at Position B.
9. Use `Position` + `Move` only after IK config is correct for the real robot.

Candy detection:

- Put `best.pt` in the app folder, next to `main.py`.
- Start the app, scan/select camera, then press `Start Camera`.
- Tick `Detect candy` in the Camera panel.
- The preview draws bounding boxes and red center points. The panel shows the
  first candy center as image pixel coordinates `x/y`.
- Current detection is camera-only. It does not automatically move the robot
  until camera-to-robot calibration is added.

`Emergency Stop` stops app sequences and sends `{"cmd":"stop"}`. It does not
disable the drivers.

Home All behavior:

- Each motor moves toward its NC limit switch until triggered.
- Each motor retracts `HOMING_RETRACT_STEPS` from the just-triggered switch
  position. Default is `200` steps away from the switch.
- Firmware then reports `{"status":"homed","motor":"all"}`.
- The desktop app can optionally run a flexible `Post-Home Drop` move after
  `Home All`. Adjust A/B/C steps, speed, and accel in the app UI; no firmware
  upload is needed for later tuning.
- `Post-Home Drop` is disabled by default because firmware already retracts
  200 steps during homing.
- If the robot moves upward instead of downward, change the signs of A/B/C
  steps in the `Post-Home Drop` section.

## Supported Commands

```json
{"cmd":"enable"}
{"cmd":"disable"}
{"cmd":"stop"}
{"cmd":"status"}
{"cmd":"home"}
{"cmd":"home_motor","motor":"A"}
{"cmd":"move_motor","motor":"A","steps":1000,"speed":2000,"accel":1000}
{"cmd":"jog","motor":"A","dir":1,"steps":100}
{"cmd":"move_abc","a":1000,"b":0,"c":1000,"speed":2000,"accel":1000}
{"cmd":"set_ik_config","arm":100,"rod":250,"base":150,"platform":60,"stepsPerDeg":8.889,"offsetA":0,"offsetB":0,"offsetC":0,"signA":1,"signB":1,"signC":1}
{"cmd":"move_xyz","x":0,"y":0,"z":-200,"speed":2000,"accel":1000}
{"cmd":"gripper_open"}
{"cmd":"gripper_close"}
{"cmd":"gripper_close","angle":50}
{"cmd":"set_gripper","angle":90}
{"cmd":"set_gripper_limits","openAngle":180,"closedAngle":50}
```

Gripper status fields are included in normal status responses:

```json
{"gripperAttached":true,"gripperAngle":180,"gripperOpenAngle":180,"gripperClosedAngle":50}
```

The Program menu from the reference app is present as a placeholder only. The
original repo uses a different command protocol, so program upload was not
copied into this ESP32 JSON app.

## Next Milestones

- Finish mechanical assembly validation
- Refine control firmware and motion sequencing
- Add kinematics and trajectory testing
- Complete calibration measurements
- Tune repeatability and accuracy
- Publish final demo and full build guide

## Tools and Stack

- CAD / 3D design workflow
- 3D-printed mechanical parts (STL)
- Embedded control (Arduino/ESP-style `.ino` workflow)
- ESP32, DRV8825, limit switches, MG90S servo
- Python desktop GUI with serial communication and robot visualization
- OpenCV and Ultralytics YOLO for camera-based candy detection

## Note

This repository is actively updated while the robot is being developed.
