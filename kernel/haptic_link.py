"""
haptic_link.py

Host side of the haptic link: sends one "{left:.4f},{right:.4f}\n" line per
tick to the ESP32 over serial. The board-side receiver is firmware/stream.py,
which maps left -> thumb (M1) and right -> index (M2).
"""

import serial


class HapticLink:
    """Owns the ESP32 serial port. Failures are non-fatal: if the port won't
    open, haptics are disabled and the experiment still runs."""

    def __init__(self, port: str, baud: int):
        self.port = port
        self.ser = None
        self._warned_write_failure = False
        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
        except Exception as e:
            print(f"\n[Haptic] WARNING: could not open {port} ({e}). "
                  f"Haptic feedback disabled.")

    @property
    def is_connected(self) -> bool:
        return self.ser is not None

    def send(self, left_intensity: float, right_intensity: float):
        """Writes one line. Write errors are reported once, then suppressed."""
        if self.ser is None:
            return
        try:
            self.ser.write(f"{left_intensity:.4f},{right_intensity:.4f}\n".encode("utf-8"))
        except Exception as e:
            if not self._warned_write_failure:
                print(f"\n[Haptic][ERROR] serial write failed: {e} "
                      f"(further write errors suppressed)")
                self._warned_write_failure = True

    def close(self):
        """Sends a zero pair so the motors stop promptly, then closes."""
        if self.ser is None:
            return
        try:
            self.ser.write(b"0.0000,0.0000\n")
        except Exception:
            pass
        self.ser.close()
