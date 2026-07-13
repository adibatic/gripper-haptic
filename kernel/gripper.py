"""
gripper.py

Robotiq 2F-85 control: a thread-safe wrapper over pyRobotiqGripper v3.2.7.

The lock matters — status_loop, motion_loop and log_loop all hit the same
serial port, and the library is not thread-safe.
"""

import threading

from pyrobotiqgripper import RobotiqGripper

# Mechanical limits / move defaults (0-255). Port and rates live in experiment.py.
MAX_POS = 225                   # Fully-closed position in bits (0 = open)
SPEED   = 200
FORCE   = 100


class GripperController:
    """Owns the Robotiq connection and the lock serializing access to it."""

    def __init__(self, port: str):
        self.device = RobotiqGripper(port)
        self.device.connect()
        self._lock = threading.Lock()

    def is_activated(self) -> bool:
        with self._lock:
            return bool(self.device.isActivated())

    def start(self):
        """Sets the GTO bit; required before move() or it raises. Unlike
        activate(), this does not move the gripper."""
        with self._lock:
            self.device.start()

    def read_position(self) -> int:
        """Current position in bits (0-255), or -1 if unavailable."""
        with self._lock:
            try:
                return int(self.device.position())
            except Exception:
                return -1

    def move(self, position: int, speed: int = SPEED, force: int = FORCE):
        """Non-blocking move, clamped to [0, MAX_POS].

        wait=False is essential: move() blocks until the motion completes by
        default, which would stall motion_loop's tick.
        """
        position = max(0, min(MAX_POS, position))
        with self._lock:
            self.device.move(position, speed=speed, force=force,
                             wait=False, readStatus=False, refreshStatus=False)

    def close(self):
        with self._lock:
            try:
                self.device.disconnect()
            except Exception:
                pass
