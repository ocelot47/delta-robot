// Delta Robot - ESP32 motor test + inverse kinematics firmware
//
// Protocol: JSON over Serial at 115200 baud.
// Limit switches are NC: normal = LOW, triggered/wire fault = HIGH.

#include <ArduinoJson.h>
#include <DeltaKinematics.h>
#include <FastAccelStepper.h>
#include <ESP32Servo.h>

// Stepper pins
#define STEP1  32
#define DIR1   33
#define STEP2  18
#define DIR2   19
#define STEP3  25
#define DIR3   26

// NC limit switches: normal = LOW, triggered or wire fault = HIGH.
#define LIMIT_A 13
#define LIMIT_B 14
#define LIMIT_C 23

// DRV8825 common enable: LOW = enabled, HIGH = disabled.
#define ENABLE_PIN 27

// MG90S gripper servo. Change this pin if GPIO17 is already used on your PCB.
#define GRIPPER_SERVO_PIN 17

const uint32_t DEFAULT_SPEED = 2000;
const uint32_t DEFAULT_ACCEL = 1000;

const int GRIPPER_SERVO_MIN_US = 500;
const int GRIPPER_SERVO_MAX_US = 2500;
const int GRIPPER_HARD_MIN_ANGLE = 0;
const int GRIPPER_HARD_MAX_ANGLE = 180;
const int GRIPPER_DEFAULT_START_ANGLE = 70;
const int GRIPPER_DEFAULT_OPEN_ANGLE = 180;
const int GRIPPER_DEFAULT_CLOSED_ANGLE = 50;

// Homing moves "bung ra" in HOME_OUT_SIGN direction until the switch triggers,
// then retracts ("thu lai") in the opposite direction until the switch releases.
const uint32_t HOMING_SPEED = 800;
const uint32_t HOMING_ACCEL = 800;
const int32_t HOME_OUT_SIGN_A = 1;
const int32_t HOME_OUT_SIGN_B = 1;
const int32_t HOME_OUT_SIGN_C = 1;
const int32_t HOMING_SEARCH_CHUNK_STEPS = 300;
const int32_t HOMING_RETRACT_STEPS = 200;
const int32_t HOMING_MAX_RETRACT_STEPS = 6000;
// IK defaults. Tune these for the real robot.
float ikArm = 200.0f;
float ikRod = 320.0f;
float ikBase = 235.0f;
float ikPlatform = 70.0f;
float stepsPerDeg = 8.889f;
int32_t ikOffsetA = 0;
int32_t ikOffsetB = 0;
int32_t ikOffsetC = 0;
int32_t ikSignA = 1;
int32_t ikSignB = 1;
int32_t ikSignC = 1;

FastAccelStepperEngine engine = FastAccelStepperEngine();
FastAccelStepper *motorA = nullptr;
FastAccelStepper *motorB = nullptr;
FastAccelStepper *motorC = nullptr;
Servo gripperServo;

DeltaKinematics DK(200.0f, 320.0f, 235.0f, 70.0f);
StaticJsonDocument<384> doc;

bool driversEnabled = false;
bool homedA = false;
bool homedB = false;
bool homedC = false;
bool movementPending = false;
bool homingActive = false;
bool homingAll = false;
uint8_t homingSearchMask = 0;
uint8_t homingRetractMask = 0;
int32_t homingRetractedA = 0;
int32_t homingRetractedB = 0;
int32_t homingRetractedC = 0;
bool homingRetractStartedA = false;
bool homingRetractStartedB = false;
bool homingRetractStartedC = false;
int32_t activeDirA = 0;
int32_t activeDirB = 0;
int32_t activeDirC = 0;

bool pendingIkMove = false;
bool xyzValid = false;
float lastX = 0.0f;
float lastY = 0.0f;
float lastZ = 0.0f;
float lastThetaA = 0.0f;
float lastThetaB = 0.0f;
float lastThetaC = 0.0f;
float pendingX = 0.0f;
float pendingY = 0.0f;
float pendingZ = 0.0f;
float pendingThetaA = 0.0f;
float pendingThetaB = 0.0f;
float pendingThetaC = 0.0f;

bool gripperAttached = false;
int gripperServoChannel = -1;
int gripperAngle = GRIPPER_DEFAULT_START_ANGLE;
int gripperOpenAngle = GRIPPER_DEFAULT_OPEN_ANGLE;
int gripperClosedAngle = GRIPPER_DEFAULT_CLOSED_ANGLE;

enum MotorBit {
  MOTOR_A_BIT = 1,
  MOTOR_B_BIT = 2,
  MOTOR_C_BIT = 4,
};

bool limitA() { return digitalRead(LIMIT_A) == HIGH; }
bool limitB() { return digitalRead(LIMIT_B) == HIGH; }
bool limitC() { return digitalRead(LIMIT_C) == HIGH; }

int32_t signOf(int32_t value) {
  // Trả về dấu của số step để biết motor đang đi theo chiều nào.
  if (value > 0) return 1;
  if (value < 0) return -1;
  return 0;
}

int32_t abs32(int32_t value) {
  // Lấy trị tuyệt đối cho số int32_t.
  return value < 0 ? -value : value;
}

int32_t homeOutSign(uint8_t bit) {
  // Trả về chiều đi ra ngoài để tìm công tắc hành trình của từng motor.
  if (bit == MOTOR_A_BIT) return HOME_OUT_SIGN_A;
  if (bit == MOTOR_B_BIT) return HOME_OUT_SIGN_B;
  if (bit == MOTOR_C_BIT) return HOME_OUT_SIGN_C;
  return -1;
}

int32_t pos(FastAccelStepper *stepper) {
  // Đọc vị trí step hiện tại của motor, nếu motor chưa init thì trả 0.
  return stepper ? stepper->getCurrentPosition() : 0;
}

bool isBusy() {
  // Kiểm tra có motor nào đang chạy không.
  return (motorA && motorA->isRunning()) ||
         (motorB && motorB->isRunning()) ||
         (motorC && motorC->isRunning());
}

void sendJson(JsonDocument &out) {
  // Gửi một object JSON ra Serial, kết thúc bằng newline.
  serializeJson(out, Serial);
  Serial.println();
}

void addCommonStatus(JsonDocument &out) {
  // Gắn các field status chung vào mọi response gửi về app.
  out["a"] = pos(motorA);
  out["b"] = pos(motorB);
  out["c"] = pos(motorC);
  out["limitA"] = limitA();
  out["limitB"] = limitB();
  out["limitC"] = limitC();
  out["enabled"] = driversEnabled;
  out["homed"] = homedA && homedB && homedC;
  out["moving"] = isBusy() || homingActive;
  out["gripperAttached"] = gripperAttached;
  out["gripperAngle"] = gripperAngle;
  out["gripperOpenAngle"] = gripperOpenAngle;
  out["gripperClosedAngle"] = gripperClosedAngle;
  out["xyzValid"] = xyzValid;
  if (xyzValid) {
    out["x"] = lastX;
    out["y"] = lastY;
    out["z"] = lastZ;
    out["thetaA"] = lastThetaA;
    out["thetaB"] = lastThetaB;
    out["thetaC"] = lastThetaC;
  }
}

void sendStatus(const char *status = nullptr, const char *motor = nullptr) {
  // Gửi status chuẩn về app, có thể kèm tên motor đang xử lý.
  StaticJsonDocument<512> out;
  out["status"] = status ? status : ((isBusy() || homingActive) ? "moving" : "idle");
  if (motor) out["motor"] = motor;
  addCommonStatus(out);
  sendJson(out);
}

void sendError(const char *msg) {
  // Gửi lỗi về app nhưng vẫn kèm status hiện tại để UI cập nhật được.
  StaticJsonDocument<512> out;
  out["status"] = "error";
  out["msg"] = msg;
  addCommonStatus(out);
  sendJson(out);
}

void setDrivers(bool enabled) {
  // Điều khiển ENABLE chung của 3 DRV8825: LOW bật, HIGH tắt.
  driversEnabled = enabled;
  digitalWrite(ENABLE_PIN, enabled ? LOW : HIGH);
}

int constrainGripperAngle(int angle) {
  // Giới hạn góc servo kẹp trong khoảng open/close đã cấu hình.
  int lo = min(gripperOpenAngle, gripperClosedAngle);
  int hi = max(gripperOpenAngle, gripperClosedAngle);
  return constrain(angle, lo, hi);
}

void writeGripperAngle(int angle) {
  // Ghi góc servo kẹp và lưu lại gripperAngle để trả status.
  gripperAngle = constrainGripperAngle(angle);
  if (gripperAttached) {
    gripperServo.write(gripperAngle);
  }
}

void setGripperLimits(int openAngle, int closedAngle) {
  // Cập nhật giới hạn mở/kẹp của servo từ app.
  gripperOpenAngle = constrain(openAngle, GRIPPER_HARD_MIN_ANGLE, GRIPPER_HARD_MAX_ANGLE);
  gripperClosedAngle = constrain(closedAngle, GRIPPER_HARD_MIN_ANGLE, GRIPPER_HARD_MAX_ANGLE);
  writeGripperAngle(gripperAngle);
}

void applyConfig(uint32_t speed, uint32_t accel) {
  // Áp tốc độ/gia tốc cho cả 3 stepper.
  speed = max((uint32_t)1, speed);
  accel = max((uint32_t)1, accel);
  if (motorA) { motorA->setSpeedInHz(speed); motorA->setAcceleration(accel); }
  if (motorB) { motorB->setSpeedInHz(speed); motorB->setAcceleration(accel); }
  if (motorC) { motorC->setSpeedInHz(speed); motorC->setAcceleration(accel); }
}

void clearActiveDirs() {
  // Xóa chiều chạy hiện tại, dùng sau khi dừng hoặc move xong.
  activeDirA = 0;
  activeDirB = 0;
  activeDirC = 0;
}

void cancelPendingIk() {
  // Hủy move_xyz đang chờ commit nếu move bị stop/lỗi.
  pendingIkMove = false;
}

void stopAllMotors() {
  // Dừng khẩn cấp toàn bộ motor và reset các state homing/move.
  if (motorA) motorA->forceStop();
  if (motorB) motorB->forceStop();
  if (motorC) motorC->forceStop();
  movementPending = false;
  homingActive = false;
  homingSearchMask = 0;
  homingRetractMask = 0;
  homingAll = false;
  homingRetractStartedA = false;
  homingRetractStartedB = false;
  homingRetractStartedC = false;
  clearActiveDirs();
  cancelPendingIk();
}

uint8_t bitForMotor(const char *motor) {
  // Chuyển tên motor A/B/C hoặc 1/2/3 thành bit mask nội bộ.
  if (!motor) return 0;
  if (strcmp(motor, "A") == 0 || strcmp(motor, "1") == 0) return MOTOR_A_BIT;
  if (strcmp(motor, "B") == 0 || strcmp(motor, "2") == 0) return MOTOR_B_BIT;
  if (strcmp(motor, "C") == 0 || strcmp(motor, "3") == 0) return MOTOR_C_BIT;
  return 0;
}

const char *nameForBit(uint8_t bit) {
  // Chuyển bit mask motor thành tên A/B/C để trả status.
  if (bit == MOTOR_A_BIT) return "A";
  if (bit == MOTOR_B_BIT) return "B";
  if (bit == MOTOR_C_BIT) return "C";
  return "?";
}

bool limitForBit(uint8_t bit) {
  // Đọc limit switch tương ứng với motor bit.
  if (bit == MOTOR_A_BIT) return limitA();
  if (bit == MOTOR_B_BIT) return limitB();
  if (bit == MOTOR_C_BIT) return limitC();
  return true;
}

FastAccelStepper *stepperForBit(uint8_t bit) {
  // Lấy pointer stepper tương ứng với motor bit.
  if (bit == MOTOR_A_BIT) return motorA;
  if (bit == MOTOR_B_BIT) return motorB;
  if (bit == MOTOR_C_BIT) return motorC;
  return nullptr;
}

void markHomed(uint8_t bit) {
  // Đánh dấu motor đã homed.
  if (bit == MOTOR_A_BIT) homedA = true;
  if (bit == MOTOR_B_BIT) homedB = true;
  if (bit == MOTOR_C_BIT) homedC = true;
}

void clearHomed(uint8_t bit) {
  // Xóa trạng thái homed của motor khi bắt đầu homing lại hoặc lỗi.
  if (bit == MOTOR_A_BIT) homedA = false;
  if (bit == MOTOR_B_BIT) homedB = false;
  if (bit == MOTOR_C_BIT) homedC = false;
}

int32_t &homingRetractedForBit(uint8_t bit) {
  // Tham chiếu tới biến đếm step đã lùi sau khi chạm limit.
  if (bit == MOTOR_A_BIT) return homingRetractedA;
  if (bit == MOTOR_B_BIT) return homingRetractedB;
  return homingRetractedC;
}

bool &homingRetractStartedForBit(uint8_t bit) {
  // Tham chiếu tới cờ motor đã bắt đầu lùi khỏi limit hay chưa.
  if (bit == MOTOR_A_BIT) return homingRetractStartedA;
  if (bit == MOTOR_B_BIT) return homingRetractStartedB;
  return homingRetractStartedC;
}

void moveHomingSearchChunk(uint8_t bit) {
  // Cho một motor đi từng đoạn nhỏ theo chiều tìm limit.
  FastAccelStepper *stepper = stepperForBit(bit);
  if (stepper && !stepper->isRunning()) {
    stepper->move(homeOutSign(bit) * HOMING_SEARCH_CHUNK_STEPS);
  }
}

void moveHomingRetractChunk(uint8_t bit) {
  // Cho motor đã chạm limit lùi đúng HOMING_RETRACT_STEPS rồi dừng.
  FastAccelStepper *stepper = stepperForBit(bit);
  if (!stepper || stepper->isRunning()) return;
  int32_t steps = -homeOutSign(bit) * HOMING_RETRACT_STEPS;
  stepper->move(steps);
  homingRetractedForBit(bit) += abs32(steps);
  homingRetractStartedForBit(bit) = true;
}

bool limitBlocksDelta(uint8_t bit, int32_t delta) {
  // Chặn move nếu limit đang triggered và lệnh còn đi tiếp vào limit.
  if (!limitForBit(bit)) return false;
  int32_t dir = signOf(delta);
  if (dir == 0) return true;
  return dir == homeOutSign(bit);
}

bool movingIntoLimit() {
  // Kiểm tra motor đang chạy có đâm vào limit hay không.
  return (limitA() && activeDirA == HOME_OUT_SIGN_A) ||
         (limitB() && activeDirB == HOME_OUT_SIGN_B) ||
         (limitC() && activeDirC == HOME_OUT_SIGN_C);
}

bool canStartMotion(int32_t a, int32_t b, int32_t c) {
  // Kiểm tra điều kiện trước khi bắt đầu move_abc/move_motor.
  if (!driversEnabled) {
    sendError("motors_disabled");
    return false;
  }
  if (homingActive || isBusy()) {
    sendError("busy");
    return false;
  }
  if (limitBlocksDelta(MOTOR_A_BIT, a) ||
      limitBlocksDelta(MOTOR_B_BIT, b) ||
      limitBlocksDelta(MOTOR_C_BIT, c)) {
    sendError("limit_triggered_reverse_allowed_only");
    return false;
  }
  return true;
}

bool startMoveABC(int32_t a, int32_t b, int32_t c, uint32_t speed,
                  uint32_t accel, bool fromIk = false) {
  // Bắt đầu chạy tương đối 3 motor theo số step A/B/C.
  if (!canStartMotion(a, b, c)) return false;
  applyConfig(speed, accel);

  activeDirA = signOf(a);
  activeDirB = signOf(b);
  activeDirC = signOf(c);

  if (a != 0 && motorA) motorA->move(a);
  if (b != 0 && motorB) motorB->move(b);
  if (c != 0 && motorC) motorC->move(c);

  if (a == 0 && b == 0 && c == 0) {
    clearActiveDirs();
    sendStatus("done");
    return true;
  }

  movementPending = true;
  pendingIkMove = fromIk;
  if (!fromIk) {
    xyzValid = false;
  }
  sendStatus("moving");
  return true;
}

void commitPendingIk() {
  // Khi move_xyz hoàn tất, commit x/y/z/theta cuối cùng vào status.
  if (!pendingIkMove) return;
  lastX = pendingX;
  lastY = pendingY;
  lastZ = pendingZ;
  lastThetaA = pendingThetaA;
  lastThetaB = pendingThetaB;
  lastThetaC = pendingThetaC;
  xyzValid = true;
  pendingIkMove = false;
}

int32_t thetaToSteps(float theta, int32_t signValue, int32_t offset) {
  // Đổi góc IK sang target step theo sign/offset từng motor.
  return offset + (int32_t)(theta * stepsPerDeg * (float)signValue);
}

void startMoveXYZ(float x, float y, float z, uint32_t speed, uint32_t accel) {
  // Tính IK cho XYZ rồi chuyển thành move_abc tương đối.
  if (DK.inverse(x, y, z) != 1) {
    sendError("ik_fail");
    return;
  }

  int32_t targetA = thetaToSteps(DK.a, ikSignA, ikOffsetA);
  int32_t targetB = thetaToSteps(DK.b, ikSignB, ikOffsetB);
  int32_t targetC = thetaToSteps(DK.c, ikSignC, ikOffsetC);
  int32_t deltaA = targetA - pos(motorA);
  int32_t deltaB = targetB - pos(motorB);
  int32_t deltaC = targetC - pos(motorC);

  pendingX = x;
  pendingY = y;
  pendingZ = z;
  pendingThetaA = DK.a;
  pendingThetaB = DK.b;
  pendingThetaC = DK.c;

  if (deltaA == 0 && deltaB == 0 && deltaC == 0) {
    pendingIkMove = true;
    commitPendingIk();
    sendStatus("done");
    return;
  }

  if (!startMoveABC(deltaA, deltaB, deltaC, speed, accel, true)) {
    cancelPendingIk();
  }
}

void startHomeMask(uint8_t mask, bool all) {
  // Khởi động homing cho một motor hoặc cả 3 motor.
  if (!driversEnabled) {
    sendError("motors_disabled");
    return;
  }
  if (homingActive || isBusy()) {
    sendError("busy");
    return;
  }

  homingSearchMask = mask;
  homingRetractMask = 0;
  homingAll = all;
  homingActive = homingSearchMask != 0;
  homingRetractedA = 0;
  homingRetractedB = 0;
  homingRetractedC = 0;
  homingRetractStartedA = false;
  homingRetractStartedB = false;
  homingRetractStartedC = false;
  applyConfig(HOMING_SPEED, HOMING_ACCEL);

  if (homingSearchMask & MOTOR_A_BIT) clearHomed(MOTOR_A_BIT);
  if (homingSearchMask & MOTOR_B_BIT) clearHomed(MOTOR_B_BIT);
  if (homingSearchMask & MOTOR_C_BIT) clearHomed(MOTOR_C_BIT);
  xyzValid = false;
  cancelPendingIk();

  sendStatus("homing", all ? "all" : nameForBit(mask));
}

void processHoming() {
  // State machine homing: motor nào chạm trước thì lùi, motor khác tiếp tục tìm limit.
  if (!homingActive) return;

  uint8_t bits[] = {MOTOR_A_BIT, MOTOR_B_BIT, MOTOR_C_BIT};
  for (uint8_t i = 0; i < 3; i++) {
    uint8_t bit = bits[i];
    FastAccelStepper *stepper = stepperForBit(bit);
    if (!stepper) continue;

    if (homingSearchMask & bit) {
      if (limitForBit(bit)) {
        stepper->forceStop();
        stepper->setCurrentPosition(0);
        homingSearchMask &= ~bit;
        homingRetractMask |= bit;
        homingRetractedForBit(bit) = 0;
        homingRetractStartedForBit(bit) = false;
        sendStatus("homing_retract", nameForBit(bit));
        moveHomingRetractChunk(bit);
      } else {
        moveHomingSearchChunk(bit);
      }
      continue;
    }

    if (homingRetractMask & bit) {
      if (!homingRetractStartedForBit(bit)) {
        moveHomingRetractChunk(bit);
        continue;
      }

      if (stepper->isRunning()) continue;

      if (!limitForBit(bit)) {
        stepper->setCurrentPosition(0);
        markHomed(bit);
        homingRetractMask &= ~bit;
        sendStatus("homed", nameForBit(bit));
      } else {
        clearHomed(bit);
        homingRetractMask &= ~bit;
        sendError("home_retract_200_steps_limit_still_triggered");
        return;
      }
    }
  }

  if (homingSearchMask == 0 && homingRetractMask == 0) {
    homingActive = false;
    if (homingAll) {
      sendStatus("homed", "all");
    }
    homingAll = false;
  }
}

void handleCommand(const String &line) {
  // Parse JSON command từ app và dispatch tới chức năng tương ứng.
  doc.clear();
  DeserializationError err = deserializeJson(doc, line);
  if (err) {
    sendError("json_parse");
    return;
  }

  const char *cmd = doc["cmd"] | "";

  if (strcmp(cmd, "status") == 0) {
    sendStatus();
    return;
  }

  if (strcmp(cmd, "enable") == 0) {
    setDrivers(true);
    sendStatus("ok");
    return;
  }

  if (strcmp(cmd, "disable") == 0) {
    stopAllMotors();
    setDrivers(false);
    sendStatus("ok");
    return;
  }

  if (strcmp(cmd, "stop") == 0) {
    stopAllMotors();
    sendStatus("idle");
    return;
  }

  if (strcmp(cmd, "gripper_open") == 0) {
    writeGripperAngle(gripperOpenAngle);
    sendStatus("ok");
    return;
  }

  if (strcmp(cmd, "gripper_close") == 0) {
    int angle = doc["angle"] | gripperClosedAngle;
    writeGripperAngle(angle);
    sendStatus("ok");
    return;
  }

  if (strcmp(cmd, "set_gripper") == 0) {
    int angle = doc["angle"] | gripperAngle;
    writeGripperAngle(angle);
    sendStatus("ok");
    return;
  }

  if (strcmp(cmd, "set_gripper_limits") == 0) {
    int openAngle = doc["openAngle"] | gripperOpenAngle;
    int closedAngle = doc["closedAngle"] | gripperClosedAngle;
    setGripperLimits(openAngle, closedAngle);
    sendStatus("ok");
    return;
  }

  if (strcmp(cmd, "home") == 0) {
    startHomeMask(MOTOR_A_BIT | MOTOR_B_BIT | MOTOR_C_BIT, true);
    return;
  }

  if (strcmp(cmd, "home_motor") == 0) {
    const char *motor = doc["motor"] | "";
    uint8_t bit = bitForMotor(motor);
    if (bit == 0) {
      sendError("invalid_motor");
      return;
    }
    startHomeMask(bit, false);
    return;
  }

  if (strcmp(cmd, "jog") == 0) {
    const char *motor = doc["motor"] | "";
    uint8_t bit = bitForMotor(motor);
    if (bit == 0) {
      sendError("invalid_motor");
      return;
    }
    int dir = doc["dir"] | 1;
    int32_t steps = doc["steps"] | 100;
    uint32_t speed = doc["speed"] | DEFAULT_SPEED;
    uint32_t accel = doc["accel"] | DEFAULT_ACCEL;
    int32_t signedSteps = abs32(steps) * (dir >= 0 ? 1 : -1);
    int32_t a = 0, b = 0, c = 0;
    if (bit == MOTOR_A_BIT) a = signedSteps;
    if (bit == MOTOR_B_BIT) b = signedSteps;
    if (bit == MOTOR_C_BIT) c = signedSteps;
    startMoveABC(a, b, c, speed, accel);
    return;
  }

  if (strcmp(cmd, "move_motor") == 0) {
    const char *motor = doc["motor"] | "";
    uint8_t bit = bitForMotor(motor);
    if (bit == 0) {
      sendError("invalid_motor");
      return;
    }
    int32_t steps = doc["steps"] | 0;
    uint32_t speed = doc["speed"] | DEFAULT_SPEED;
    uint32_t accel = doc["accel"] | DEFAULT_ACCEL;
    int32_t a = 0, b = 0, c = 0;
    if (bit == MOTOR_A_BIT) a = steps;
    if (bit == MOTOR_B_BIT) b = steps;
    if (bit == MOTOR_C_BIT) c = steps;
    startMoveABC(a, b, c, speed, accel);
    return;
  }

  if (strcmp(cmd, "move_abc") == 0) {
    int32_t a = doc["a"] | 0;
    int32_t b = doc["b"] | 0;
    int32_t c = doc["c"] | 0;
    uint32_t speed = doc["speed"] | DEFAULT_SPEED;
    uint32_t accel = doc["accel"] | DEFAULT_ACCEL;
    startMoveABC(a, b, c, speed, accel);
    return;
  }

  if (strcmp(cmd, "move_xyz") == 0) {
    float x = doc["x"] | 0.0f;
    float y = doc["y"] | 0.0f;
    float z = doc["z"] | -200.0f;
    uint32_t speed = doc["speed"] | DEFAULT_SPEED;
    uint32_t accel = doc["accel"] | DEFAULT_ACCEL;
    startMoveXYZ(x, y, z, speed, accel);
    return;
  }

  if (strcmp(cmd, "set_ik_config") == 0) {
    ikArm = doc["arm"] | ikArm;
    ikRod = doc["rod"] | ikRod;
    ikBase = doc["base"] | ikBase;
    ikPlatform = doc["platform"] | ikPlatform;
    stepsPerDeg = doc["stepsPerDeg"] | stepsPerDeg;
    ikOffsetA = doc["offsetA"] | ikOffsetA;
    ikOffsetB = doc["offsetB"] | ikOffsetB;
    ikOffsetC = doc["offsetC"] | ikOffsetC;
    ikSignA = doc["signA"] | ikSignA;
    ikSignB = doc["signB"] | ikSignB;
    ikSignC = doc["signC"] | ikSignC;
    ikSignA = ikSignA >= 0 ? 1 : -1;
    ikSignB = ikSignB >= 0 ? 1 : -1;
    ikSignC = ikSignC >= 0 ? 1 : -1;
    DK = DeltaKinematics(ikArm, ikRod, ikBase, ikPlatform);
    sendStatus("ok");
    return;
  }

  sendError("unknown_cmd");
}

void setup() {
  // Khởi tạo Serial, GPIO, servo, stepper và gửi boot status.
  Serial.begin(115200);

  pinMode(LIMIT_A, INPUT_PULLUP);
  pinMode(LIMIT_B, INPUT_PULLUP);
  pinMode(LIMIT_C, INPUT_PULLUP);
  pinMode(ENABLE_PIN, OUTPUT);
  setDrivers(false);

  gripperServo.setPeriodHertz(50);
  gripperServoChannel = gripperServo.attach(
    GRIPPER_SERVO_PIN,
    GRIPPER_SERVO_MIN_US,
    GRIPPER_SERVO_MAX_US
  );
  gripperAttached = gripperServoChannel >= 0;
  writeGripperAngle(GRIPPER_DEFAULT_START_ANGLE);

  engine.init();

  motorA = engine.stepperConnectToPin(STEP1);
  motorB = engine.stepperConnectToPin(STEP2);
  motorC = engine.stepperConnectToPin(STEP3);

  if (motorA) { motorA->setDirectionPin(DIR1); motorA->setCurrentPosition(0); }
  if (motorB) { motorB->setDirectionPin(DIR2); motorB->setCurrentPosition(0); }
  if (motorC) { motorC->setDirectionPin(DIR3); motorC->setCurrentPosition(0); }
  applyConfig(DEFAULT_SPEED, DEFAULT_ACCEL);

  StaticJsonDocument<512> out;
  out["boot"] = "delta_motor_test_ik_ready";
  out["status"] = "idle";
  addCommonStatus(out);
  sendJson(out);
}

void loop() {
  // Vòng lặp chính: đọc command, xử lý homing, giám sát limit và báo done.
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      handleCommand(line);
    }
  }

  processHoming();

  if (!homingActive && movementPending && movingIntoLimit()) {
    stopAllMotors();
    xyzValid = false;
    sendError("limit_triggered");
    return;
  }

  if (!homingActive && movementPending && !isBusy()) {
    movementPending = false;
    clearActiveDirs();
    commitPendingIk();
    sendStatus("done");
  }
}
