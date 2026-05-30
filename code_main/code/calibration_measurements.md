# Delta Robot Calibration Measurements

File nay dung de do va ghi thong so robot delta. Sau khi dien xong, gui lai
file nay de tinh:

- `stepsPerDeg`
- `offsetA/B/C`
- `signA/B/C`
- goc home thuc te
- gioi han goc tung motor
- thong so IK `arm/rod/base/platform`
- workspace X/Y/Z cua dau gap
- thong so hien thi 3D trong app

## 1. Thong Tin Chung

Ngay do:

Nguoi do:

Ghi chu robot:

```text

```

Microstep DRV8825 dang dung:

- [ ] Full step
- [ ] 1/2
- [ ] 1/4
- [ ] 1/8
- [ ] 1/16
- [ ] 1/32

Motor step angle:

- [ ] 1.8 deg/step
- [ ] 0.9 deg/step
- [ ] Khac:

Ti so truyen neu co:

```text
Motor truc tiep / pulley / gear:
Gear ratio:
Ghi chu:
```

## 2. Huong Dan Do Goc

Can chon mot moc do goc co dinh va dung nhat quan cho ca 3 motor.

Khuyen nghi:

- Dung mat phang ngang cua tam base lam moc `0 deg`.
- Do goc cua canh tay tren tu truc motor den khop noi voi 2 thanh song song.
- Ghi ro quy uoc:
  - goc duong la tay co len hay ha xuong
  - +step tren app lam tay di len hay di xuong

Moc do goc ban dang dung:

```text

```

Quy uoc goc duong:

```text

```

## 3. Hinh Hoc Robot Delta

Do bang mm. Neu kho do, chup anh va ghi mo ta.

### 3.1 Base Triangle

Tam giac co dinh phia tren, noi 3 truc motor.

| Thong so | Gia tri mm | Cach do / ghi chu |
|---|---:|---|
| Base side: khoang cach truc motor A-B |  |  |
| Base side: khoang cach truc motor B-C |  |  |
| Base side: khoang cach truc motor C-A |  |  |
| Base side trung binh se dung tinh IK |  |  |

Neu truc motor khong nam dung tren dinh tam giac, ghi offset:

```text

```

### 3.2 Platform Triangle

Tam giac nho o dau gap, noi 3 cap thanh song song.

| Thong so | Gia tri mm | Cach do / ghi chu |
|---|---:|---|
| Platform side: khop A-B |  |  |
| Platform side: khop B-C |  |  |
| Platform side: khop C-A |  |  |
| Platform side trung binh se dung tinh IK |  |  |

Offset tu tam platform den dau kep gap:

```text
X offset:
Y offset:
Z offset:
```

### 3.3 Upper Arm

Canh tay tren: tu truc motor den khop noi voi 2 thanh song song.

| Motor | Chieu dai upper arm mm | Ghi chu |
|---|---:|---|
| A |  |  |
| B |  |  |
| C |  |  |
| Trung binh dung tinh IK |  |  |

### 3.4 Forearm Rods

Moi canh co 2 thanh song song tu upper arm xuong platform.

| Canh | Rod 1 mm | Rod 2 mm | Trung binh | Ghi chu |
|---|---:|---:|---:|---|
| A |  |  |  |  |
| B |  |  |  |  |
| C |  |  |  |  |
| Trung binh dung tinh IK |  |  |  |  |

Khoang cach giua 2 rod song song cua moi canh:

| Canh | Khoang cach giua 2 rod mm | Ghi chu |
|---|---:|---|
| A |  |  |
| B |  |  |
| C |  |  |

## 4. Kiem Tra Limit Switch

Truoc khi do goc, kiem tra limit NC:

1. Chay app.
2. Connect ESP32.
3. Khi chua cham, limit phai la `false`.
4. Bam tay tung cong tac, limit tuong ung phai la `true`.

| Limit | Chua cham | Bam tay | Ghi chu |
|---|---|---|---|
| A | false / true | false / true |  |
| B | false / true | false / true |  |
| C | false / true | false / true |  |

## 5. Home All Va Goc Home

Sau khi bam `Home`:

- Motor nao cham limit truoc thi motor do lui `HOMING_RETRACT_STEPS`.
- Motor con lai tiep tuc home.
- Sau khi tat ca homed, app status `homed=true`.

Thu tu cham limit:

```text
1:
2:
3:
```

`HOMING_RETRACT_STEPS` dang dung trong firmware:

```text
200
```

Goc sau Home All:

| Motor | Step status sau Home All | Goc upper arm sau Home All | +step lam tay len/xuong | Ghi chu |
|---|---:|---:|---|---|
| A | 0 |  |  |  |
| B | 0 |  |  |  |
| C | 0 |  |  |  |

## 6. Tim Steps Per Degree

Lam tung motor rieng le. Khuyen nghi speed/accel thap.

Trong app:

```text
JOG / Single Motor
steps = 200
speed = 500
accel = 500
```

Sau moi lan chay, do lai goc upper arm.

### Motor A

| Lan do | Lenh | Step status tren app | Goc do duoc | Ghi chu |
|---|---:|---:|---:|---|
| Home | 0 | 0 |  |  |
| A +200 | +200 |  |  |  |
| A +400 | +400 |  |  |  |
| A -200 | -200 |  |  |  |

### Motor B

| Lan do | Lenh | Step status tren app | Goc do duoc | Ghi chu |
|---|---:|---:|---:|---|
| Home | 0 | 0 |  |  |
| B +200 | +200 |  |  |  |
| B +400 | +400 |  |  |  |
| B -200 | -200 |  |  |  |

### Motor C

| Lan do | Lenh | Step status tren app | Goc do duoc | Ghi chu |
|---|---:|---:|---:|---|
| Home | 0 | 0 |  |  |
| C +200 | +200 |  |  |  |
| C +400 | +400 |  |  |  |
| C -200 | -200 |  |  |  |

## 7. Gioi Han Goc Tung Canh

Muc tieu: tim goc cao nhat co the co len va goc thap nhat co the ha xuong
ma khong cham khung, khong cang rod, khong gay ket co khi.

Di chuyen rat cham:

```text
steps = 50 hoac 100
speed = 300 den 500
accel = 300 den 500
```

### Motor A

| Gioi han | Step status | Goc upper arm | Mo ta co khi |
|---|---:|---:|---|
| Cao nhat / co len toi da |  |  |  |
| Thap nhat / ha xuong toi da |  |  |  |

### Motor B

| Gioi han | Step status | Goc upper arm | Mo ta co khi |
|---|---:|---:|---|
| Cao nhat / co len toi da |  |  |  |
| Thap nhat / ha xuong toi da |  |  |  |

### Motor C

| Gioi han | Step status | Goc upper arm | Mo ta co khi |
|---|---:|---:|---|
| Cao nhat / co len toi da |  |  |  |
| Thap nhat / ha xuong toi da |  |  |  |

## 8. Workspace Dau Gap

Phan nay do gioi han thuc te cua diem dau gap/kep.

Chon truc toa do:

```text
X duong huong ve:
Y duong huong ve:
Z duong huong ve:
Goc toa do dat tai:
```

### 8.1 Tam Workspace

Vi tri dau gap sau Home All:

```text
X =
Y =
Z =
```

### 8.2 Gioi Han Len/Xuong

Tai tam XY, di chuyen Z len/xuong cham nhat co the.

| Gioi han | X | Y | Z | Step A | Step B | Step C | Ghi chu |
|---|---:|---:|---:|---:|---:|---:|---|
| Z cao nhat |  |  |  |  |  |  |  |
| Z thap nhat |  |  |  |  |  |  |  |

### 8.3 Gioi Han Trai/Phai/Truoc/Sau

O mot do cao Z an toan, tim gioi han X/Y.

Do cao Z khi test:

```text
Z =
```

| Huong | X | Y | Z | Step A | Step B | Step C | Ghi chu |
|---|---:|---:|---:|---:|---:|---:|---|
| Tien truoc toi da |  |  |  |  |  |  |  |
| Lui sau toi da |  |  |  |  |  |  |  |
| Trai toi da |  |  |  |  |  |  |  |
| Phai toi da |  |  |  |  |  |  |  |

### 8.4 Diem Test IK Neu Co

Neu app/firmware da move_xyz duoc, ghi diem command va diem thuc te.

| Diem | X lenh | Y lenh | Z lenh | X thuc | Y thuc | Z thuc | Ghi chu |
|---|---:|---:|---:|---:|---:|---:|---|
| P1 | 0 | 0 |  |  |  |  |  |
| P2 |  |  |  |  |  |  |  |
| P3 |  |  |  |  |  |  |  |
| P4 |  |  |  |  |  |  |  |

## 9. Gripper Servo MG90S

Goc start firmware hien tai:

```text
70 deg
```

| Trang thai | Goc command | Trang thai thuc te | Ghi chu |
|---|---:|---|---|
| Start | 70 |  |  |
| Open | 180 |  |  |
| Close | 50 |  |  |
| Close nho nhat an toan |  |  |  |

## 10. Loi / Bat Thuong Khi Do

```text

```
