"""
handlers/serial_handler.py - Thin JSON-over-Serial wrapper for ESP32.

The UI owns command sequencing. This class only handles:
  - listing COM ports
  - connecting/disconnecting
  - sending one JSON command line
  - polling and parsing incoming lines
"""

import json
import time
from typing import Callable

import serial
import serial.tools.list_ports

from config import BAUD_RATE, SERIAL_TIMEOUT


class SerialHandler:
    def __init__(self):
        self.ser: serial.Serial | None = None
        self.on_json: Callable[[dict, str], None] | None = None
        self.on_raw: Callable[[str], None] | None = None
        self.on_parse_error: Callable[[str, str], None] | None = None

    def get_ports(self) -> list[str]:
        ports = [p.device for p in serial.tools.list_ports.comports()]
        return ports if ports else ["No COM"]

    def connect(self, port: str, baud_rate: int = BAUD_RATE) -> tuple[bool, str]:
        try:
            self.ser = serial.Serial(port, baud_rate, timeout=SERIAL_TIMEOUT)
            time.sleep(1.5)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            return True, f"Connected to {port} @ {baud_rate}"
        except Exception as exc:
            self.ser = None
            return False, f"Connect failed: {exc}"

    def disconnect(self):
        if self.ser:
            self.ser.close()
            self.ser = None

    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def send_command(self, data: dict) -> bool:
        if not self.is_connected():
            return False
        try:
            line = json.dumps(data, separators=(",", ":")) + "\n"
            self.ser.write(line.encode("utf-8"))
            return True
        except Exception:
            self.disconnect()
            return False

    def poll(self):
        if not self.is_connected():
            return

        while self.ser.in_waiting:
            try:
                raw = self.ser.readline().decode("utf-8", errors="replace").strip()
            except Exception:
                self.disconnect()
                return

            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception as exc:
                if self.on_parse_error:
                    self.on_parse_error(raw, str(exc))
                elif self.on_raw:
                    self.on_raw(raw)
                continue

            if isinstance(data, dict):
                if self.on_json:
                    self.on_json(data, raw)
            elif self.on_raw:
                self.on_raw(raw)
