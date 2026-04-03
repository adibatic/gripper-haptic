# src/gripper_control.py
from pyrobotiqgripper import RobotiqGripper
import time

def main():
    print("🤖 Initializing Robotiq 2F-85 Gripper...")
    gripper = RobotiqGripper()

    # The library will try to auto-detect the serial port (e.g. /dev/ttyUSB0), 
    # but you can also specify it manually if needed:
    # gripper = RobotiqGripper(portname="/dev/ttyUSB0")
    
    # Activating the gripper is mandatory before any movement.
    # WARNING: The gripper will open and close fully during this process!
    print("⚠️ Activating... keep hands clear!")
    gripper.activate()
    time.sleep(2)  # Give it a moment to finish calibration
    
    print("✅ Activated! Moving to positions...")
    
    # Open the gripper fully
    gripper.open()
    time.sleep(2)
    
    # Close the gripper fully
    gripper.close()
    time.sleep(2)
    
    # Move to a specific position (range: 0 to 255)
    # 0 = Fully open, 255 = Fully closed
    gripper.move(128, speed=255, force=100)
    print("Moved to half-open position.")

if __name__ == "__main__":
    main()
