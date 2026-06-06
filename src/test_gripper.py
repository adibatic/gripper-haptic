from pyrobotiqgripper import RobotiqGripper

gripper = RobotiqGripper()
gripper.activate()
gripper.calibrate(0, 40)

gripper.open()
gripper.goTo(100)
position_in_bit = gripper.getPosition()
print(position_in_bit)
gripper.goTomm(25)
position_in_mm = gripper.getPositionmm()
print(position_in_mm)
gripper.printInfo()
gripper.close()