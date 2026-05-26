# Delta GUI for ESP32 Delta Robot

Python desktop app + ESP32 firmware for testing a 3-motor delta robot. The UI
is styled after `grzesiek2201/Delta-Robot`: compact controls on the left,
Matplotlib robot visualization on the right, menu items for plots, and a log
console at the bottom.

The serial protocol remains JSON-over-Serial for the current ESP32 firmware.

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
pip install customtkinter pyserial matplotlib numpy
```

Arduino libraries:

- `FastAccelStepper`
- `ArduinoJson` v6.x
- `Delta-Kinematics-Library`
- `ESP32Servo`

## Run

1. Upload `code.ino` to the ESP32.
2. Start the desktop app:

```bash
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
   sequence now closes the gripper at Position A and opens it at Position B.
9. Use `Position` + `Move` only after IK config is correct for the real robot.

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
