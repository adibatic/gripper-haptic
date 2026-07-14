"""
haptic_link.py

Host side of the haptic link: sends one "{left:.4f},{right:.4f}\n" line per
tick to the ESP32 over serial. The board-side receiver is firmware/stream.py,
which maps left -> thumb (M1) and right -> index (M2).
"""

import threading

import serial


class HapticLink:
    """Owns the ESP32 serial port. Failures are non-fatal: if the port won't
    open, haptics are disabled and the experiment still runs.

    reconnect() releases and reopens the port, for the mid-session firmware
    swap that a condition change can require (kernel/tracking.py's 'c' key
    handling) — mpremote/esptool need exclusive access to flash the board."""

    def __init__(self, port: str, baud: int):
        self.port = port
        self._baud = baud
        self._lock = threading.Lock()
        self.ser = None
        self._warned_write_failure = False
        self._open()

    def _open(self):
        """Caller holds self._lock (or, at __init__, no other thread exists yet)."""
        try:
            self.ser = serial.Serial(self.port, self._baud, timeout=0.1)
            self._warned_write_failure = False
        except Exception as e:
            print(f"\n[Haptic] WARNING: could not open {self.port} ({e}). "
                  f"Haptic feedback disabled.")

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self.ser is not None

    def send(self, left_intensity: float, right_intensity: float):
        """Writes one line. Write errors are reported once, then suppressed."""
        with self._lock:
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
        """Sends a zero pair so the motors stop promptly, then closes and
        releases the port. self.ser is set to None so is_connected reflects
        reality and a later reconnect()/send() behaves correctly."""
        with self._lock:
            if self.ser is None:
                return
            try:
                self.ser.write(b"0.0000,0.0000\n")
            except Exception:
                pass
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def reconnect(self):
        """Closes the port if open, then reopens it. Used after an external
        reflash (mpremote/esptool) that needed exclusive access to the port."""
        self.close()
        with self._lock:
            self._open()
