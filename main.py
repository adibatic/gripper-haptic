from machine import Pin, PWM
import time
import random  # for synthetic test data

# Define pins for 5 motors (replace with your actual GPIO pins)
motor_pins = [18, 19, 21, 22, 23]

# Frequency and PWM resolution setup
freq = 5000  # 5 kHz PWM frequency

# Initialize PWM objects for each motor pin
motors = []
for pin_num in motor_pins:
    pwm = PWM(Pin(pin_num))
    pwm.freq(freq)
    motors.append(pwm)

def constrain(value, min_val=0.0, max_val=1.0):
    return max(min_val, min(value, max_val))

try:
    while True:
        # Replace this block with real sensor/serial input code:
        input_vals = [random.uniform(0, 1) for _ in range(5)]  # simulate 5 float values between 0 and 1

        for i in range(5):
            value = constrain(input_vals[i])
            duty = int(value * 65535)  # MicroPython PWM duty_u16 range is 0-65535
            motors[i].duty_u16(duty)
            print(f"Motor {i} - Duty: {duty} ({value:.2f})")

        time.sleep(1)

except KeyboardInterrupt:
    print("Stopping motors and cleaning up")
    for pwm in motors:
        pwm.duty_u16(0)
    # Optionally, deinit PWM channels:
    for pwm in motors:
        pwm.deinit()
